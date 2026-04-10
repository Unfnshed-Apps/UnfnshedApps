"""Shipping queue + Shippo rate shopping endpoints."""

import json
import logging

import requests
from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    ShippingQueueItem, ShippingLineItem,
    GetRatesRequest, ShippingRate,
)

logger = logging.getLogger(__name__)

SHIPPO_API_URL = "https://api.goshippo.com"

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


# ==================== Shippo Rate Shopping ====================

def _load_shipping_settings():
    """Load Shippo API key and ship-from address from the settings table."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(shippo_api_key, '') as shippo_api_key,
                    COALESCE(ship_from_name, '') as ship_from_name,
                    COALESCE(ship_from_street1, '') as ship_from_street1,
                    COALESCE(ship_from_street2, '') as ship_from_street2,
                    COALESCE(ship_from_city, '') as ship_from_city,
                    COALESCE(ship_from_state, '') as ship_from_state,
                    COALESCE(ship_from_zip, '') as ship_from_zip,
                    COALESCE(ship_from_country, 'US') as ship_from_country,
                    COALESCE(ship_from_phone, '') as ship_from_phone
                FROM shopify_settings WHERE id = 1
            """)
            return cur.fetchone()


def _format_address_for_shippo(addr_dict):
    """Convert a Shopify address dict to Shippo's address format."""
    if not addr_dict:
        return None
    if isinstance(addr_dict, str):
        try:
            addr_dict = json.loads(addr_dict)
        except Exception:
            return None

    name = addr_dict.get("name", "")
    if not name:
        first = addr_dict.get("first_name", "")
        last = addr_dict.get("last_name", "")
        name = f"{first} {last}".strip()

    return {
        "name": name or "Customer",
        "street1": addr_dict.get("address1", ""),
        "street2": addr_dict.get("address2", "") or "",
        "city": addr_dict.get("city", ""),
        "state": addr_dict.get("province_code") or addr_dict.get("province", ""),
        "zip": addr_dict.get("zip", ""),
        "country": addr_dict.get("country_code") or addr_dict.get("country", "US"),
        "phone": addr_dict.get("phone", "") or "",
    }


@router.post("/rates", response_model=list[ShippingRate])
def get_rates(body: GetRatesRequest, _: str = Depends(verify_api_key)):
    """Fetch shipping rates from Shippo for an order's destination."""
    settings = _load_shipping_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="Shipping settings not configured")

    shippo_key = settings["shippo_api_key"]
    if not shippo_key:
        raise HTTPException(status_code=400, detail="Shippo API key not configured")

    # Validate ship-from
    required_from = ["ship_from_street1", "ship_from_city", "ship_from_state",
                     "ship_from_zip", "ship_from_country"]
    for field in required_from:
        if not settings[field]:
            raise HTTPException(
                status_code=400,
                detail=f"Ship-from address incomplete: {field} is required",
            )

    # Load order shipping address
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shipping_address FROM shopify_orders WHERE id = %s",
                (body.order_id,),
            )
            order = cur.fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    address_to = _format_address_for_shippo(order["shipping_address"])
    if not address_to or not address_to.get("street1"):
        raise HTTPException(
            status_code=400,
            detail="Order has no shipping address",
        )

    address_from = {
        "name": settings["ship_from_name"] or "Shipper",
        "street1": settings["ship_from_street1"],
        "street2": settings["ship_from_street2"],
        "city": settings["ship_from_city"],
        "state": settings["ship_from_state"],
        "zip": settings["ship_from_zip"],
        "country": settings["ship_from_country"],
        "phone": settings["ship_from_phone"],
    }

    parcel = {
        "length": str(body.length_in),
        "width": str(body.width_in),
        "height": str(body.height_in),
        "distance_unit": "in",
        "weight": str(body.weight_lbs),
        "mass_unit": "lb",
    }

    # Call Shippo
    payload = {
        "address_from": address_from,
        "address_to": address_to,
        "parcels": [parcel],
        "async": False,
    }
    headers = {
        "Authorization": f"ShippoToken {shippo_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{SHIPPO_API_URL}/shipments/",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        logger.exception("Shippo request failed")
        raise HTTPException(status_code=502, detail=f"Shippo request failed: {e}")

    if resp.status_code >= 400:
        logger.error("Shippo error %s: %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=502,
            detail=f"Shippo error: {resp.text[:500]}",
        )

    data = resp.json()
    raw_rates = data.get("rates", [])

    # Convert + sort by amount ascending
    rates = []
    for r in raw_rates:
        try:
            amount_float = float(r.get("amount", "0"))
        except (ValueError, TypeError):
            amount_float = 0.0
        rates.append((amount_float, ShippingRate(
            rate_id=r.get("object_id", ""),
            carrier=r.get("provider", ""),
            service=r.get("servicelevel", {}).get("name", ""),
            amount=str(r.get("amount", "0")),
            currency=r.get("currency", "USD"),
            days=r.get("estimated_days"),
            attributes=r.get("attributes", []) or [],
        )))

    rates.sort(key=lambda x: x[0])
    return [r for _, r in rates]
