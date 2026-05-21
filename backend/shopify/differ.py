"""
Diff engine: compares two store snapshots and produces an ordered
transaction queue.  Every transaction carries explicit warnings and a
risk level so the UI can surface them to the user before any writes.

Risk levels
-----------
LOW      Adding something new (new product, new tag, new collection membership)
MEDIUM   Updating a field value — destination had something, it will change
HIGH     Replacing a multi-value field (tags, collections) — existing values
         will be REMOVED if they are not in the source
CRITICAL Deleting a product or removing a product from a collection it belongs
         to (downstream impact: collection page may lose items, URLs break)
"""
import uuid
from typing import Any, Dict, List, Optional


# Fields compared for UPDATE detection, in display order
_PRODUCT_FIELDS = [
    ("title",        "Title"),
    ("body_html",    "Description (HTML)"),
    ("vendor",       "Vendor"),
    ("product_type", "Product Type"),
    ("status",       "Status"),
    ("tags",         "Tags"),         # treated specially — comma-separated
]

_VARIANT_FIELDS = [
    ("price",                "Price"),
    ("compare_at_price",     "Compare-At Price"),
    ("sku",                  "SKU"),
    ("barcode",              "Barcode"),
    ("weight",               "Weight"),
    ("weight_unit",          "Weight Unit"),
    ("inventory_policy",     "Inventory Policy"),
    ("fulfillment_service",  "Fulfillment Service"),
    ("taxable",              "Taxable"),
    ("requires_shipping",    "Requires Shipping"),
]


def _txn(
    action: str,
    resource_type: str,
    handle: str,
    title: str,
    field: str,
    old_value: Any,
    new_value: Any,
    risk_level: str,
    warnings: List[str],
    affected_relationships: Optional[List[Dict]] = None,
    product_id: Optional[int] = None,
    meta: Optional[Dict] = None,
) -> Dict:
    return {
        "id": str(uuid.uuid4()),
        "action": action,
        "resource_type": resource_type,
        "handle": handle,
        "title": title,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "risk_level": risk_level,
        "warnings": warnings,
        "affected_relationships": affected_relationships or [],
        "product_id": product_id,
        "approved": None,  # None=pending, True=approved, False=rejected
        "meta": meta or {},
    }


def _tag_set(tags_str: str) -> set:
    return {t.strip() for t in (tags_str or "").split(",") if t.strip()}


def _short(value: Any, max_len: int = 80) -> str:
    s = str(value or "")
    return s[:max_len] + ("…" if len(s) > max_len else "")


def diff_stores(
    source: Dict,
    dest: Dict,
    selected_fields: Optional[List[str]] = None,
    include_deletes: bool = False,
    include_new: bool = True,
) -> List[Dict]:
    """
    Compare source and dest snapshots.  Returns a list of Transaction dicts
    ordered: NEW products → field UPDATEs → collection changes → DELETEs.

    selected_fields: if provided, only diff these product fields.
    include_deletes: if True, include CRITICAL delete transactions for products
                     in dest but not in source.
    include_new: if True, include LOW transactions for new products.
    """
    transactions: List[Dict] = []
    allowed = set(selected_fields) if selected_fields else None

    src_products: Dict[str, Dict] = source.get("products", {})
    dst_products: Dict[str, Dict] = dest.get("products", {})
    dst_collections: Dict[int, Dict] = dest.get("collections", {})

    # Map dest product handle → shopify id for relationship lookups
    dst_handle_to_id: Dict[str, int] = {
        h: p["id"] for h, p in dst_products.items()
    }

    # -----------------------------------------------------------------------
    # NEW products (in source, not in dest)
    # -----------------------------------------------------------------------
    if include_new:
        for handle, src_p in src_products.items():
            if handle not in dst_products:
                transactions.append(_txn(
                    action="CREATE",
                    resource_type="product",
                    handle=handle,
                    title=src_p.get("title", handle),
                    field="*",
                    old_value=None,
                    new_value=src_p.get("title", handle),
                    risk_level="LOW",
                    warnings=[
                        f"New product '{src_p.get('title', handle)}' will be created in the destination store."
                    ],
                    meta={"source_product": src_p},
                ))

    # -----------------------------------------------------------------------
    # MODIFIED products (in both source and dest)
    # -----------------------------------------------------------------------
    for handle, src_p in src_products.items():
        if handle not in dst_products:
            continue
        dst_p = dst_products[handle]
        dst_pid = dst_p["id"]
        p_title = dst_p.get("title", handle)

        # --- Scalar product fields ---
        for field_key, field_label in _PRODUCT_FIELDS:
            if allowed and field_key not in allowed:
                continue
            if field_key == "tags":
                continue  # handled separately below
            src_val = (src_p.get(field_key) or "").strip()
            dst_val = (dst_p.get(field_key) or "").strip()
            if src_val == dst_val:
                continue
            transactions.append(_txn(
                action="UPDATE",
                resource_type="product_field",
                handle=handle,
                title=p_title,
                field=field_label,
                old_value=_short(dst_val),
                new_value=_short(src_val),
                risk_level="MEDIUM",
                warnings=[
                    f"'{field_label}' will change on product '{p_title}'.",
                    f"  Current: {_short(dst_val, 120)}",
                    f"  → New:   {_short(src_val, 120)}",
                ],
                product_id=dst_pid,
                meta={"field_key": field_key},
            ))

        # --- Tags (set diff) ---
        if not allowed or "tags" in allowed:
            src_tags = _tag_set(src_p.get("tags", ""))
            dst_tags = _tag_set(dst_p.get("tags", ""))
            tags_to_add = src_tags - dst_tags
            tags_to_remove = dst_tags - src_tags

            if tags_to_add:
                transactions.append(_txn(
                    action="MERGE",
                    resource_type="tags",
                    handle=handle,
                    title=p_title,
                    field="Tags (add)",
                    old_value=", ".join(sorted(dst_tags)) or "(none)",
                    new_value=", ".join(sorted(src_tags)),
                    risk_level="LOW",
                    warnings=[
                        f"Will ADD {len(tags_to_add)} tag(s) to '{p_title}': {', '.join(sorted(tags_to_add))}"
                    ],
                    product_id=dst_pid,
                    meta={"tags_to_add": list(tags_to_add), "tags_to_remove": []},
                ))

            if tags_to_remove:
                transactions.append(_txn(
                    action="UPDATE",
                    resource_type="tags",
                    handle=handle,
                    title=p_title,
                    field="Tags (remove)",
                    old_value=", ".join(sorted(dst_tags)),
                    new_value=", ".join(sorted(src_tags)) or "(none)",
                    risk_level="HIGH",
                    warnings=[
                        f"Will REMOVE {len(tags_to_remove)} tag(s) from '{p_title}'.",
                        f"Tags to remove: {', '.join(sorted(tags_to_remove))}",
                        "These tags may be used by smart collections or discount rules — removing them could affect collection membership.",
                    ],
                    affected_relationships=[
                        {"type": "smart_collection", "name": col.get("title", str(cid)),
                         "action": "may lose this product if it filters on removed tags"}
                        for cid, col in dst_collections.items()
                        if col.get("_type") == "smart"
                    ][:5],
                    product_id=dst_pid,
                    meta={"tags_to_add": [], "tags_to_remove": list(tags_to_remove)},
                ))

        # --- Variants ---
        if not allowed or "variants" in allowed:
            src_variants = {v.get("sku", v.get("id")): v for v in src_p.get("variants", [])}
            dst_variants = {v.get("sku", v.get("id")): v for v in dst_p.get("variants", [])}

            for vkey, src_v in src_variants.items():
                if vkey not in dst_variants:
                    transactions.append(_txn(
                        action="CREATE",
                        resource_type="variant",
                        handle=handle,
                        title=p_title,
                        field=f"Variant '{src_v.get('title', vkey)}'",
                        old_value=None,
                        new_value=src_v.get("price"),
                        risk_level="LOW",
                        warnings=[
                            f"New variant '{src_v.get('title', vkey)}' (SKU: {src_v.get('sku', '—')}) will be added to '{p_title}'."
                        ],
                        product_id=dst_pid,
                        meta={"variant": src_v},
                    ))
                else:
                    dst_v = dst_variants[vkey]
                    for vf_key, vf_label in _VARIANT_FIELDS:
                        sv = str(src_v.get(vf_key) or "").strip()
                        dv = str(dst_v.get(vf_key) or "").strip()
                        if sv == dv:
                            continue
                        risk = "HIGH" if vf_key == "price" else "MEDIUM"
                        warn = [f"Variant '{src_v.get('title', vkey)}' — {vf_label} will change on '{p_title}'."]
                        if vf_key == "price":
                            warn.append(f"  Price: ${dv} → ${sv}")
                            warn.append("Changing the price will immediately affect the storefront and any active discounts referencing this variant.")
                        transactions.append(_txn(
                            action="UPDATE",
                            resource_type="variant_field",
                            handle=handle,
                            title=p_title,
                            field=f"Variant '{src_v.get('title', vkey)}' — {vf_label}",
                            old_value=dv,
                            new_value=sv,
                            risk_level=risk,
                            warnings=warn,
                            product_id=dst_pid,
                            meta={"variant_id": dst_v.get("id"), "field_key": vf_key, "variant": dst_v},
                        ))

        # --- Images ---
        if not allowed or "images" in allowed:
            src_imgs = {i.get("src", ""): i for i in src_p.get("images", [])}
            dst_imgs = {i.get("src", ""): i for i in dst_p.get("images", [])}
            new_imgs = set(src_imgs) - set(dst_imgs)
            removed_imgs = set(dst_imgs) - set(src_imgs)
            for src_img_url in new_imgs:
                transactions.append(_txn(
                    action="CREATE",
                    resource_type="image",
                    handle=handle,
                    title=p_title,
                    field="Image",
                    old_value=None,
                    new_value=src_img_url,
                    risk_level="LOW",
                    warnings=[f"New image will be added to '{p_title}'."],
                    product_id=dst_pid,
                    meta={"image": src_imgs[src_img_url]},
                ))
            for dst_img_url in removed_imgs:
                transactions.append(_txn(
                    action="DELETE",
                    resource_type="image",
                    handle=handle,
                    title=p_title,
                    field="Image",
                    old_value=dst_img_url,
                    new_value=None,
                    risk_level="HIGH",
                    warnings=[
                        f"Image will be REMOVED from '{p_title}'.",
                        "Any external references or CDN links to this image URL will break.",
                    ],
                    product_id=dst_pid,
                    meta={"image_id": dst_imgs[dst_img_url].get("id")},
                ))

        # --- Collection membership ---
        if not allowed or "collections" in allowed:
            dst_col_ids = set(dest.get("product_collections", {}).get(dst_pid, []))
            src_pid = src_p.get("id")
            src_col_ids_raw = set(source.get("product_collections", {}).get(src_pid, []))

            # Map source collection titles to dest collection titles by title match
            src_col_titles = {
                source["collections"].get(cid, {}).get("title", "").lower()
                for cid in src_col_ids_raw
            }
            dst_col_by_title = {
                col.get("title", "").lower(): cid
                for cid, col in dst_collections.items()
            }

            for src_col_title in src_col_titles:
                dst_cid = dst_col_by_title.get(src_col_title)
                if dst_cid is None:
                    transactions.append(_txn(
                        action="CREATE",
                        resource_type="collection",
                        handle=handle,
                        title=p_title,
                        field="Collection",
                        old_value=None,
                        new_value=src_col_title,
                        risk_level="MEDIUM",
                        warnings=[
                            f"Collection '{src_col_title}' does not exist in the destination store.",
                            "The collection will need to be created before this product can be added to it.",
                        ],
                        product_id=dst_pid,
                        meta={"collection_title": src_col_title},
                    ))
                elif dst_cid not in dst_col_ids:
                    col_name = dst_collections[dst_cid].get("title", str(dst_cid))
                    transactions.append(_txn(
                        action="ASSOCIATE",
                        resource_type="collection_membership",
                        handle=handle,
                        title=p_title,
                        field="Collection",
                        old_value="(not a member)",
                        new_value=col_name,
                        risk_level="LOW",
                        warnings=[f"'{p_title}' will be ADDED to collection '{col_name}'."],
                        product_id=dst_pid,
                        meta={"collection_id": dst_cid, "collection_name": col_name},
                    ))

    # -----------------------------------------------------------------------
    # DELETED products (in dest, not in source) — only if requested
    # -----------------------------------------------------------------------
    if include_deletes:
        for handle, dst_p in dst_products.items():
            if handle in src_products:
                continue
            dst_pid = dst_p["id"]
            col_names = [
                dst_collections.get(cid, {}).get("title", str(cid))
                for cid in dest.get("product_collections", {}).get(dst_pid, [])
            ]
            warnings = [
                f"⚠️ Product '{dst_p.get('title', handle)}' exists in the destination but NOT in the source.",
                "Deleting this product is PERMANENT and cannot be undone via this tool.",
            ]
            if col_names:
                warnings.append(
                    f"It is a member of {len(col_names)} collection(s): {', '.join(col_names[:5])}."
                    " These collection pages will lose this product."
                )
            transactions.append(_txn(
                action="DELETE",
                resource_type="product",
                handle=handle,
                title=dst_p.get("title", handle),
                field="*",
                old_value=dst_p.get("title", handle),
                new_value=None,
                risk_level="CRITICAL",
                warnings=warnings,
                affected_relationships=[
                    {"type": "collection", "name": n, "action": "will lose this product"}
                    for n in col_names
                ],
                product_id=dst_pid,
            ))

    # Sort: LOW → MEDIUM → HIGH → CRITICAL, then by handle
    _order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    transactions.sort(key=lambda t: (_order.get(t["risk_level"], 9), t["handle"]))
    return transactions
