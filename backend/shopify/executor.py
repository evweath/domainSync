"""
Transaction executor: applies approved transactions to the destination store
via the Shopify Admin API.  Reports per-transaction results.
"""
import inspect
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .client import ShopifyClient, ShopifyError

logger = logging.getLogger(__name__)


async def execute_transactions(
    dest_store_url: str,
    dest_access_token: str,
    transactions: List[Dict],
    progress_cb: Optional[Callable[[Dict], Any]] = None,
) -> List[Dict]:
    """
    Execute a list of approved transactions against the destination store.

    Only transactions with approved=True are executed.
    Returns a list of result dicts: {id, status, error}.

    ``progress_cb`` (sync or async) is invoked once per processed transaction
    with ``{**result, "transaction": txn, "index": i, "total": n}``.
    """
    approved = [t for t in transactions if t.get("approved") is True]
    total = len(approved)
    results = []
    # Per-run collection resolution. Many product transactions can target the
    # same new collection; we resolve each collection title to a single live
    # collection id ONCE (create-or-reuse) and remember which products already
    # belong to it, so we never create a duplicate collection and never re-add a
    # product. Titles map case-insensitively to a resolved collection id;
    # members maps a collection id to the set of product ids already in it.
    resolved_collections: Dict[str, Optional[int]] = {}
    collection_members: Dict[int, set] = {}

    async with ShopifyClient(dest_store_url, dest_access_token) as client:
        # If any collection associations are pending, fetch the destination
        # catalog ONCE (fresh, at execute time) and build a handle→id index —
        # instead of a per-product GET, which for large batches saturates the
        # Shopify rate limit. Still "fresh": it reflects the store right now.
        handle_to_id: Dict[str, int] = {}
        if any(t.get("action") == "CREATE" and t.get("resource_type") == "collection" for t in approved):
            async for prod in client.iter_products():
                h = prod.get("handle")
                if h:
                    handle_to_id[h] = prod.get("id")

        for txn in approved:
            result = {"id": txn["id"], "status": "ok", "error": None}
            try:
                action = txn["action"]
                rtype = txn["resource_type"]
                meta = txn.get("meta", {})
                pid = txn.get("product_id")

                if action == "CREATE" and rtype == "product":
                    src = meta.get("source_product", {})
                    await client.create_product(_strip_ids(src))

                elif action == "CREATE" and rtype == "collection":
                    # Collection name is editable in the UI — write whatever the
                    # transaction now carries (meta.collection_title / new_value).
                    title = (meta.get("collection_title") or txn.get("new_value") or "").strip()
                    if not title:
                        result["status"] = "skipped"
                        result["error"] = "No collection title"
                    else:
                        cid = await _resolve_collection(
                            client, title, resolved_collections, collection_members
                        )
                        if cid is None:
                            result["status"] = "error"
                            result["error"] = f"Could not create or find collection '{title}'"
                        else:
                            # Resolve the tagged product's id from the freshly
                            # fetched destination index (falls back to the
                            # transaction's snapshot id if the handle isn't found).
                            target_pid = handle_to_id.get(txn.get("handle"))
                            if target_pid is None:
                                target_pid = pid
                            if target_pid is None:
                                result["status"] = "skipped"
                                result["error"] = "Product not found on destination"
                            elif target_pid in collection_members.get(cid, set()):
                                pass  # already a member — nothing to do
                            else:
                                await client.add_to_collection(cid, target_pid)
                                collection_members.setdefault(cid, set()).add(target_pid)

                elif action == "CREATE" and rtype == "variant":
                    if pid:
                        product = await client.get_product(pid)
                        variants = product.get("variants", [])
                        variants.append(_strip_ids(meta.get("variant", {})))
                        await client.update_product(pid, {"variants": variants})

                elif action == "CREATE" and rtype == "image":
                    if pid:
                        img = meta.get("image", {})
                        product = await client.get_product(pid)
                        images = product.get("images", [])
                        images.append({"src": img.get("src", ""), "alt": img.get("alt", "")})
                        await client.update_product(pid, {"images": images})

                elif action in ("UPDATE", "MERGE") and rtype == "product_field":
                    if pid:
                        field_key = meta.get("field_key")
                        await client.update_product(pid, {field_key: txn["new_value"]})

                elif action in ("UPDATE", "MERGE") and rtype == "tags":
                    if pid:
                        product = await client.get_product(pid)
                        current_tags = {t.strip() for t in (product.get("tags") or "").split(",") if t.strip()}
                        adds = set(meta.get("tags_to_add", []))
                        removes = set(meta.get("tags_to_remove", []))
                        new_tags = (current_tags | adds) - removes
                        await client.update_product(pid, {"tags": ", ".join(sorted(new_tags))})

                elif action == "UPDATE" and rtype == "variant_field":
                    if pid:
                        variant_id = meta.get("variant_id")
                        field_key = meta.get("field_key")
                        if variant_id and field_key:
                            product = await client.get_product(pid)
                            variants = product.get("variants", [])
                            for v in variants:
                                if v["id"] == variant_id:
                                    v[field_key] = txn["new_value"]
                            await client.update_product(pid, {"variants": variants})

                elif action == "UPDATE" and rtype == "collections":
                    # Add/remove a product's custom-collection memberships in one
                    # transaction. Adds create-or-reuse the collection; removes
                    # delete the collect for this product (custom collections only
                    # — smart collections are rule-based and can't be edited here).
                    if pid:
                        for title in meta.get("add", []):
                            if not title:
                                continue
                            cid = await _resolve_collection(
                                client, title, resolved_collections, collection_members)
                            if cid is not None and pid not in collection_members.get(cid, set()):
                                await client.add_to_collection(cid, pid)
                                collection_members.setdefault(cid, set()).add(pid)
                        for title in meta.get("remove", []):
                            if not title:
                                continue
                            existing = await client.find_custom_collection_by_title(title)
                            if not existing or existing.get("id") is None:
                                continue
                            for col in await client.get_collects(existing["id"]):
                                if col.get("product_id") == pid and col.get("id") is not None:
                                    await client.remove_from_collection(col["id"])
                                    break

                elif action == "ASSOCIATE" and rtype == "collection_membership":
                    if pid:
                        cid = meta.get("collection_id")
                        if cid:
                            await client.add_to_collection(cid, pid)

                elif action == "DELETE" and rtype == "image":
                    if pid:
                        img_id = meta.get("image_id")
                        if img_id:
                            await client._delete(f"/products/{pid}/images/{img_id}.json")

                elif action == "DELETE" and rtype == "product":
                    if pid:
                        await client._delete(f"/products/{pid}.json")

                else:
                    result["status"] = "skipped"
                    result["error"] = f"No executor for {action}/{rtype}"

            except ShopifyError as exc:
                result["status"] = "error"
                result["error"] = f"Shopify API {exc.status}: {exc.body[:200]}"
                logger.warning("execute_transactions: %s/%s failed: %s",
                               txn["action"], txn["resource_type"], exc)
            except Exception as exc:
                result["status"] = "error"
                result["error"] = str(exc)
                logger.exception("execute_transactions: unexpected error on %s", txn["id"])

            results.append(result)
            if progress_cb:
                out = progress_cb({**result, "transaction": txn,
                                   "index": len(results), "total": total})
                if inspect.isawaitable(out):
                    await out

    return results


async def _resolve_collection(
    client: ShopifyClient,
    title: str,
    resolved: Dict[str, Optional[int]],
    members: Dict[int, set],
) -> Optional[int]:
    """Return the destination collection id for ``title``, creating it if needed.

    Resolution is cached per run by lower-cased title so a collection shared by
    many products is looked up / created only once. A live query decides whether
    the collection already exists (never creating a duplicate); the collection's
    current membership is fetched once so products aren't re-added.
    """
    key = title.strip().lower()
    if key in resolved:
        return resolved[key]

    # Fresh, live check on the target store — do not rely on any cached snapshot.
    existing = await client.find_custom_collection_by_title(title)
    if existing and existing.get("id") is not None:
        cid = existing["id"]
    else:
        created = await client.create_custom_collection(title)
        cid = created.get("id")

    resolved[key] = cid
    if cid is not None and cid not in members:
        try:
            collects = await client.get_collects(cid)
            members[cid] = {c.get("product_id") for c in collects if c.get("product_id") is not None}
        except Exception:
            members[cid] = set()
    return cid


def _strip_ids(obj: Any) -> Any:
    """Recursively remove Shopify id fields so we don't copy IDs across stores."""
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items()
                if k not in ("id", "admin_graphql_api_id")}
    if isinstance(obj, list):
        return [_strip_ids(i) for i in obj]
    return obj
