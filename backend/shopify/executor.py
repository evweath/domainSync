"""
Transaction executor: applies approved transactions to the destination store
via the Shopify Admin API.  Reports per-transaction results.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from .client import ShopifyClient, ShopifyError

logger = logging.getLogger(__name__)


async def execute_transactions(
    dest_store_url: str,
    dest_access_token: str,
    transactions: List[Dict],
    progress_cb: Optional[Callable[[Dict], None]] = None,
) -> List[Dict]:
    """
    Execute a list of approved transactions against the destination store.

    Only transactions with approved=True are executed.
    Returns a list of result dicts: {id, status, error}.
    """
    approved = [t for t in transactions if t.get("approved") is True]
    results = []
    # Multiple product transactions can reference the same new collection name;
    # create each distinct collection only once per run.
    created_collections: set = set()

    async with ShopifyClient(dest_store_url, dest_access_token) as client:
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
                    elif title.lower() in created_collections:
                        pass  # already created this collection earlier in the run
                    else:
                        await client.create_custom_collection(title)
                        created_collections.add(title.lower())

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
                progress_cb({**result, "transaction": txn})

    return results


def _strip_ids(obj: Any) -> Any:
    """Recursively remove Shopify id fields so we don't copy IDs across stores."""
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items()
                if k not in ("id", "admin_graphql_api_id")}
    if isinstance(obj, list):
        return [_strip_ids(i) for i in obj]
    return obj
