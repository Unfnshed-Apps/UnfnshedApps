"""Shipping queue + Shippo rate shopping + label purchase + fulfillment."""

import json
import logging

import requests
from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    ShippingQueueItem, ShippingLineItem,
    GetRatesRequest, ShippingRate, RatesResponse, ShippingStatusResponse,
    PurchaseLabelRequest, PurchaseLabelResponse,
    FulfillOrderRequest, FulfillOrderResponse,
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
    """Load Shippo keys + toggle and ship-from address from the settings table.

    Returns a dict with both stored keys, the use_live toggle, and ship-from
    fields. Use ``_active_shippo_key()`` to pick the active key based on the
    toggle.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COALESCE(shippo_test_key, '') as shippo_test_key,
                    COALESCE(shippo_live_key, '') as shippo_live_key,
                    COALESCE(shippo_use_live, FALSE) as shippo_use_live,
                    COALESCE(ship_from_name, '') as ship_from_name,
                    COALESCE(ship_from_street1, '') as ship_from_street1,
                    COALESCE(ship_from_street2, '') as ship_from_street2,
                    COALESCE(ship_from_city, '') as ship_from_city,
                    COALESCE(ship_from_state, '') as ship_from_state,
                    COALESCE(ship_from_zip, '') as ship_from_zip,
                    COALESCE(ship_from_country, 'US') as ship_from_country,
                    COALESCE(ship_from_phone, '') as ship_from_phone,
                    COALESCE(ship_from_email, '') as ship_from_email
                FROM shopify_settings WHERE id = 1
            """)
            return cur.fetchone()


def _is_test_mode(settings) -> bool:
    """Return True when the toggle says use the test key.

    The toggle is the single source of truth for test vs live mode. Key
    prefixes are only used for inline UI validation in the Admin app, never
    for runtime mode detection.
    """
    if settings is None:
        return True
    return not settings["shippo_use_live"]


def _active_shippo_key(settings) -> tuple[str | None, bool]:
    """Return ``(active_key, test_mode)`` from the settings dict.

    The active key is whichever of test_key/live_key matches the toggle. If
    the requested mode's key is empty, returns ``(None, test_mode)`` and the
    caller is expected to raise a clear 400 error rather than silently
    falling back to the other key.
    """
    test_mode = _is_test_mode(settings)
    if settings is None:
        return None, test_mode
    if test_mode:
        key = settings["shippo_test_key"]
    else:
        key = settings["shippo_live_key"]
    return (key or None), test_mode


def _format_address_for_shippo(addr_dict, fallback_phone=""):
    """Convert a Shopify address dict to Shippo's address format.

    Shippo requires a valid phone on the destination address for label
    purchase (transactions), even though it's optional for rate quotes.
    If the customer has no phone, ``fallback_phone`` (typically the
    ship-from phone) is used instead.
    """
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

    phone = addr_dict.get("phone", "") or ""
    if not phone:
        phone = fallback_phone

    return {
        "name": name or "Customer",
        "street1": addr_dict.get("address1", ""),
        "street2": addr_dict.get("address2", "") or "",
        "city": addr_dict.get("city", ""),
        "state": addr_dict.get("province_code") or addr_dict.get("province", ""),
        "zip": addr_dict.get("zip", ""),
        "country": addr_dict.get("country_code") or addr_dict.get("country", "US"),
        "phone": phone,
    }


@router.post("/rates", response_model=RatesResponse)
def get_rates(body: GetRatesRequest, _: str = Depends(verify_api_key)):
    """Fetch shipping rates from Shippo for an order's destination."""
    settings = _load_shipping_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="Shipping settings not configured")

    shippo_key, test_mode = _active_shippo_key(settings)
    if not shippo_key:
        mode_label = "Test" if test_mode else "Live"
        raise HTTPException(
            status_code=400,
            detail=(
                f"{mode_label} Shippo key not configured. "
                f"Save one in Admin or toggle modes."
            ),
        )

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

    address_to = _format_address_for_shippo(
        order["shipping_address"],
        fallback_phone=settings["ship_from_phone"],
    )
    if not address_to or not address_to.get("street1"):
        raise HTTPException(
            status_code=400,
            detail="Order has no shipping address",
        )

    ship_from_email = settings["ship_from_email"] or ""

    address_from = {
        "name": settings["ship_from_name"] or "Shipper",
        "street1": settings["ship_from_street1"],
        "street2": settings["ship_from_street2"],
        "city": settings["ship_from_city"],
        "state": settings["ship_from_state"],
        "zip": settings["ship_from_zip"],
        "country": settings["ship_from_country"],
        "phone": settings["ship_from_phone"],
        "email": ship_from_email,
    }

    # Add email to destination address too — Shippo may require it
    if ship_from_email and not address_to.get("email"):
        address_to["email"] = ship_from_email

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
    return RatesResponse(
        rates=[r for _, r in rates],
        test_mode=test_mode,
    )


@router.get("/status", response_model=ShippingStatusResponse)
def get_shipping_status(_: str = Depends(verify_api_key)):
    """Report active Shippo mode and whether the active key is configured.

    The client uses this to render the TEST MODE banner and to enable or
    disable mutation buttons (Print Label, Mark Fulfilled). Always reflects
    the current state of the toggle, never cached.
    """
    settings = _load_shipping_settings()
    if settings is None:
        return ShippingStatusResponse(
            test_mode=True,
            active_key_present=False,
            test_key_stored=False,
            live_key_stored=False,
        )
    test_mode = _is_test_mode(settings)
    active_key, _ = _active_shippo_key(settings)
    return ShippingStatusResponse(
        test_mode=test_mode,
        active_key_present=bool(active_key),
        test_key_stored=bool(settings["shippo_test_key"]),
        live_key_stored=bool(settings["shippo_live_key"]),
    )


# ==================== Label Purchase ====================

@router.post("/purchase-label", response_model=PurchaseLabelResponse)
def purchase_label(body: PurchaseLabelRequest, _: str = Depends(verify_api_key)):
    """Purchase a shipping label by committing to a quoted rate.

    Calls Shippo POST /transactions/ which charges the account (live mode)
    or creates a mock label (test mode).  The result is persisted in
    ``shipping_labels`` for audit and later fulfillment.
    """
    settings = _load_shipping_settings()
    if not settings:
        raise HTTPException(status_code=400, detail="Shipping settings not configured")

    shippo_key, test_mode = _active_shippo_key(settings)
    if not shippo_key:
        mode_label = "Test" if test_mode else "Live"
        raise HTTPException(
            status_code=400,
            detail=f"{mode_label} Shippo key not configured.",
        )

    # Call Shippo to purchase the label
    headers = {
        "Authorization": f"ShippoToken {shippo_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "rate": body.rate_id,
        "label_file_type": "PDF",
        "async": False,
    }

    try:
        resp = requests.post(
            f"{SHIPPO_API_URL}/transactions/",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        logger.exception("Shippo transaction request failed")
        raise HTTPException(status_code=502, detail=f"Shippo request failed: {e}")

    if resp.status_code >= 400:
        logger.error("Shippo transaction error %s: %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=502,
            detail=f"Shippo error: {resp.text[:500]}",
        )

    data = resp.json()

    # Shippo returns status "SUCCESS" or "ERROR"
    if data.get("status") == "ERROR":
        messages = data.get("messages", [])
        detail = "; ".join(m.get("text", "") for m in messages) if messages else "Label purchase failed"
        logger.error("Shippo transaction failed: %s", detail)
        raise HTTPException(status_code=502, detail=detail)

    transaction_id = data.get("object_id", "")
    tracking_number = data.get("tracking_number", "")
    label_url = data.get("label_url", "")
    carrier = data.get("rate", {}).get("provider", "") if isinstance(data.get("rate"), dict) else ""
    service = data.get("rate", {}).get("servicelevel", {}).get("name", "") if isinstance(data.get("rate"), dict) else ""
    amount = data.get("rate", {}).get("amount") if isinstance(data.get("rate"), dict) else None

    # Persist in shipping_labels
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shipping_labels
                    (order_id, rate_id, transaction_id, tracking_number,
                     carrier, service, label_url, amount, test_mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (body.order_id, body.rate_id, transaction_id, tracking_number,
                 carrier, service, label_url, amount, test_mode),
            )

    return PurchaseLabelResponse(
        label_url=label_url,
        tracking_number=tracking_number,
        carrier=carrier,
        service=service,
        transaction_id=transaction_id,
        test_mode=test_mode,
    )


# ==================== Order Fulfillment ====================

def _deduct_product_inventory(cur, sku: str, qty: int) -> dict:
    """Deduct qty from product_inventory for a single SKU.

    Returns a dict describing what was deducted, for the response payload.
    Raises HTTPException if insufficient stock.
    """
    cur.execute(
        "SELECT quantity_on_hand FROM product_inventory WHERE product_sku = %s",
        (sku,),
    )
    row = cur.fetchone()
    on_hand = row["quantity_on_hand"] if row else 0

    if on_hand < qty:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient stock for {sku}: need {qty}, have {on_hand}",
        )

    cur.execute(
        """
        UPDATE product_inventory
        SET quantity_on_hand = quantity_on_hand - %s,
            last_updated = CURRENT_TIMESTAMP
        WHERE product_sku = %s
        """,
        (qty, sku),
    )
    return {"sku": sku, "quantity": qty, "remaining": on_hand - qty}


@router.post("/fulfill", response_model=FulfillOrderResponse)
def fulfill_order(body: FulfillOrderRequest, _: str = Depends(verify_api_key)):
    """Mark an order as fulfilled: deduct product inventory and optionally
    push tracking info to Shopify.

    Inventory deduction resolves bundles to their source products via
    ``product_units`` — shipping a 2-pack deducts 2x the single unit.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify order exists and is not already fulfilled
            cur.execute(
                """
                SELECT id, fulfillment_status, shopify_order_id
                FROM shopify_orders WHERE id = %s
                """,
                (body.order_id,),
            )
            order = cur.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            if order["fulfillment_status"] == "fulfilled":
                raise HTTPException(status_code=409, detail="Order is already fulfilled")

            # Get shippable line items
            cur.execute(
                """
                SELECT sku, quantity
                FROM shopify_order_items
                WHERE order_id = %s AND requires_shipping = TRUE
                """,
                (body.order_id,),
            )
            items = cur.fetchall()

            # Load bundle mappings (bundle_sku -> list of source_product_sku)
            cur.execute(
                "SELECT bundle_sku, source_product_sku FROM product_units"
            )
            bundle_map = {}
            for row in cur.fetchall():
                bundle_map.setdefault(row["bundle_sku"], []).append(
                    row["source_product_sku"]
                )

            # Deduct inventory for each line item
            deductions = []
            for item in items:
                sku = item["sku"]
                qty = item["quantity"] or 1
                if not sku:
                    continue

                if sku in bundle_map:
                    # Bundle: deduct each source product
                    for source_sku in bundle_map[sku]:
                        d = _deduct_product_inventory(cur, source_sku, qty)
                        deductions.append(d)
                else:
                    d = _deduct_product_inventory(cur, sku, qty)
                    deductions.append(d)

            # Mark order fulfilled
            cur.execute(
                """
                UPDATE shopify_orders
                SET fulfillment_status = 'fulfilled'
                WHERE id = %s
                """,
                (body.order_id,),
            )

            # Update shipping_labels status
            if body.tracking_number:
                cur.execute(
                    """
                    UPDATE shipping_labels
                    SET status = 'fulfilled'
                    WHERE order_id = %s AND tracking_number = %s
                    """,
                    (body.order_id, body.tracking_number),
                )

            # Optionally push to Shopify
            shopify_pushed = False
            cur.execute(
                """
                SELECT store_url, client_id, client_secret, api_version,
                       COALESCE(push_fulfillments_to_shopify, FALSE) as push_enabled
                FROM shopify_settings WHERE id = 1
                """
            )
            settings = cur.fetchone()

            if (settings and settings["push_enabled"]
                    and settings["store_url"] and settings["client_id"]
                    and settings["client_secret"] and body.tracking_number):
                try:
                    from ..shopify_client import ShopifyAPI, ShopifyConfig
                    config = ShopifyConfig(
                        store_url=settings["store_url"],
                        client_id=settings["client_id"],
                        client_secret=settings["client_secret"],
                        api_version=settings["api_version"] or "2026-01",
                    )
                    api = ShopifyAPI(config)
                    api.create_fulfillment(
                        shopify_order_id=order["shopify_order_id"],
                        tracking_number=body.tracking_number,
                        tracking_company=body.carrier,
                    )
                    shopify_pushed = True
                except Exception:
                    logger.exception(
                        "Failed to push fulfillment to Shopify for order %s",
                        body.order_id,
                    )

    return FulfillOrderResponse(
        status="fulfilled",
        inventory_deducted=True,
        shopify_pushed=shopify_pushed,
        deductions=deductions,
    )
