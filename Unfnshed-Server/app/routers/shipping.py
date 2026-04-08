"""Shipping queue endpoints: unfulfilled orders with stock availability."""

from fastapi import APIRouter, Depends

from ..auth import verify_api_key
from ..database import get_db
from ..models import ShippingQueueItem, ShippingLineItem

router = APIRouter(prefix="/shipping", tags=["shipping"])


@router.get("/queue", response_model=list[ShippingQueueItem])
def get_shipping_queue(_: str = Depends(verify_api_key)):
    """Get unfulfilled orders with per-item stock availability."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Fetch unfulfilled, paid, uncancelled orders
            cur.execute("""
                SELECT
                    so.id as order_id,
                    so.order_number,
                    so.name,
                    so.customer_name,
                    so.email,
                    so.shipping_address,
                    so.created_at,
                    so.note,
                    so.total_price,
                    so.fulfillment_status
                FROM shopify_orders so
                WHERE so.financial_status IN ('paid', 'partially_refunded')
                  AND so.cancelled_at IS NULL
                  AND (so.fulfillment_status IS NULL
                       OR so.fulfillment_status NOT IN ('fulfilled'))
                ORDER BY so.created_at ASC
            """)
            orders = cur.fetchall()

            if not orders:
                return []

            # Fetch all line items for these orders
            order_ids = [o["order_id"] for o in orders]
            placeholders = ",".join(["%s"] * len(order_ids))
            cur.execute(
                f"""
                SELECT
                    soi.order_id,
                    soi.sku,
                    soi.title,
                    soi.variant_title,
                    soi.quantity,
                    soi.fulfillment_status,
                    soi.requires_shipping
                FROM shopify_order_items soi
                WHERE soi.order_id IN ({placeholders})
                  AND soi.requires_shipping = TRUE
                ORDER BY soi.order_id, soi.id
                """,
                order_ids,
            )
            all_items = cur.fetchall()

            # Fetch product inventory for stock checks
            cur.execute("""
                SELECT product_sku, quantity_on_hand
                FROM product_inventory
            """)
            stock_map = {r["product_sku"]: r["quantity_on_hand"] for r in cur.fetchall()}

            # Fetch bundle derived stock
            cur.execute("""
                SELECT pu.bundle_sku, pu.source_product_sku,
                       COALESCE(pi.quantity_on_hand, 0) as source_stock
                FROM product_units pu
                LEFT JOIN product_inventory pi ON pu.source_product_sku = pi.product_sku
            """)
            bundle_rows = cur.fetchall()

            bundle_sources = {}
            for row in bundle_rows:
                bsku = row["bundle_sku"]
                ssku = row["source_product_sku"]
                if bsku not in bundle_sources:
                    bundle_sources[bsku] = {}
                if ssku not in bundle_sources[bsku]:
                    bundle_sources[bsku][ssku] = {"count": 0, "stock": row["source_stock"]}
                bundle_sources[bsku][ssku]["count"] += 1

            bundle_stock = {}
            for bsku, sources in bundle_sources.items():
                bundle_stock[bsku] = min(
                    s["stock"] // s["count"] for s in sources.values()
                ) if sources else 0

            bundle_skus = set(bundle_sources.keys())

            # Group items by order
            items_by_order = {}
            for item in all_items:
                items_by_order.setdefault(item["order_id"], []).append(item)

            # Build response
            results = []
            for order in orders:
                oid = order["order_id"]
                line_items = []
                ready = True

                for item in items_by_order.get(oid, []):
                    sku = item["sku"]
                    is_bundle = sku in bundle_skus if sku else False

                    if sku and is_bundle:
                        stock = bundle_stock.get(sku, 0)
                    elif sku:
                        stock = stock_map.get(sku, 0)
                    else:
                        stock = 0

                    qty = item["quantity"] or 1
                    in_stock = stock >= qty

                    if not in_stock:
                        ready = False

                    line_items.append(ShippingLineItem(
                        sku=sku or "",
                        title=item["title"] or "",
                        variant_title=item["variant_title"] or "",
                        quantity=qty,
                        stock=stock,
                        in_stock=in_stock,
                        is_bundle=is_bundle,
                    ))

                results.append(ShippingQueueItem(
                    order_id=oid,
                    order_number=order["order_number"] or "",
                    name=order["name"] or "",
                    customer_name=order["customer_name"] or "",
                    email=order["email"] or "",
                    shipping_address=order["shipping_address"],
                    created_at=order["created_at"],
                    note=order["note"] or "",
                    total_price=order["total_price"] or "0.00",
                    items=line_items,
                    ready_to_ship=ready,
                ))

            return results
