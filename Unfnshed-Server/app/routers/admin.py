"""Admin API endpoints — Shopify settings, sync control, and order management."""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..auth import verify_api_key
from ..database import get_db
from ..shopify_client import ShopifyAPI, ShopifyConfig
from ..shopify_sync import run_shopify_sync

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Pydantic models ─────────────────────────────────────────────────

class ShopifySettingsResponse(BaseModel):
    store_url: str
    client_id: str
    client_secret_masked: str
    api_version: str
    auto_sync: bool
    sync_interval_minutes: int
    last_sync: Optional[str]
    shippo_api_key_masked: str = ""


class ShopifySettingsUpdate(BaseModel):
    store_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_version: str = "2026-01"
    shippo_api_key: Optional[str] = None


class ShopifyTestRequest(BaseModel):
    store_url: str
    client_id: str
    client_secret: str
    api_version: str = "2026-01"


class SyncSettingsResponse(BaseModel):
    auto_sync: bool
    sync_interval_minutes: int
    last_sync: Optional[str]


class SyncSettingsUpdate(BaseModel):
    auto_sync: bool
    sync_interval_minutes: int


# ── Helpers ──────────────────────────────────────────────────────────

def _mask_secret(secret: str) -> str:
    """Show only last 4 chars of a secret."""
    if not secret or len(secret) <= 4:
        return "****"
    return "*" * (len(secret) - 4) + secret[-4:]


def _fmt_ts(val) -> str:
    """Format a timestamp to ISO string or empty."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)


def _fmt_price(val, currency="USD") -> str:
    if not val:
        return ""
    if currency == "USD":
        return f"${val}"
    return f"{val} {currency}"


def _fmt_address(addr) -> str:
    if not addr:
        return ""
    if isinstance(addr, str):
        try:
            addr = json.loads(addr)
        except (json.JSONDecodeError, TypeError):
            return str(addr)
    if not isinstance(addr, dict):
        return str(addr)
    parts = []
    city = addr.get("city", "")
    province = addr.get("province_code") or addr.get("province", "")
    zip_code = addr.get("zip", "")
    country = addr.get("country_code") or addr.get("country", "")
    if city:
        parts.append(city)
    if province or zip_code:
        parts.append(f"{province} {zip_code}".strip())
    if country:
        parts.append(country)
    return ", ".join(parts) if parts else ""


# ── Shopify Settings CRUD ───────────────────────────────────────────

@router.get("/shopify-settings", response_model=ShopifySettingsResponse)
def get_shopify_settings(_: str = Depends(verify_api_key)):
    """Return current Shopify settings with masked client_secret."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT store_url, client_id, client_secret, api_version,
                       auto_sync, sync_interval_minutes, last_sync,
                       COALESCE(shippo_api_key, '') as shippo_api_key
                FROM shopify_settings WHERE id = 1
            """)
            row = cur.fetchone()

    if not row:
        return ShopifySettingsResponse(
            store_url="",
            client_id="",
            client_secret_masked="",
            api_version="2026-01",
            auto_sync=False,
            sync_interval_minutes=60,
            last_sync=None,
            shippo_api_key_masked="",
        )

    return ShopifySettingsResponse(
        store_url=row["store_url"] or "",
        client_id=row["client_id"] or "",
        client_secret_masked=_mask_secret(row["client_secret"] or ""),
        api_version=row["api_version"] or "2026-01",
        auto_sync=row["auto_sync"] or False,
        sync_interval_minutes=row["sync_interval_minutes"] or 60,
        last_sync=_fmt_ts(row["last_sync"]) or None,
        shippo_api_key_masked=_mask_secret(row["shippo_api_key"] or ""),
    )


@router.put("/shopify-settings")
def update_shopify_settings(body: ShopifySettingsUpdate, _: str = Depends(verify_api_key)):
    """Update API credentials. Only fields provided in the request are updated."""
    # Build a list of (column, value) for fields that were actually sent
    updates = []
    if body.store_url is not None:
        updates.append(("store_url", body.store_url))
    if body.client_id is not None:
        updates.append(("client_id", body.client_id))
    if body.client_secret is not None:
        updates.append(("client_secret", body.client_secret))
    if body.api_version is not None:
        updates.append(("api_version", body.api_version))
    if body.shippo_api_key is not None:
        updates.append(("shippo_api_key", body.shippo_api_key))

    if not updates:
        return {"status": "ok"}

    with get_db() as conn:
        with conn.cursor() as cur:
            # Ensure row exists
            cur.execute("""
                INSERT INTO shopify_settings (id) VALUES (1)
                ON CONFLICT (id) DO NOTHING
            """)
            # Update only the provided fields
            set_clauses = ", ".join(f"{col} = %s" for col, _ in updates)
            values = [val for _, val in updates]
            cur.execute(
                f"UPDATE shopify_settings SET {set_clauses} WHERE id = 1",
                values,
            )

    return {"status": "ok"}


@router.delete("/shopify-settings")
def clear_shopify_settings(_: str = Depends(verify_api_key)):
    """Clear Shopify credentials and disable auto-sync."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE shopify_settings
                SET store_url = '', client_id = '', client_secret = '', auto_sync = FALSE
                WHERE id = 1
            """)

    return {"status": "ok"}


@router.post("/shopify-settings/test")
def test_shopify_connection(body: ShopifyTestRequest, _: str = Depends(verify_api_key)):
    """Test Shopify connection with the provided credentials."""
    config = ShopifyConfig(
        store_url=body.store_url,
        client_id=body.client_id,
        client_secret=body.client_secret,
        api_version=body.api_version,
    )
    api = ShopifyAPI(config)
    success, message = api.test_connection()
    return {"success": success, "message": message}


# ── Sync Control ─────────────────────────────────────────────────────

@router.post("/sync")
def trigger_sync(_: str = Depends(verify_api_key)):
    """Trigger an immediate Shopify order sync (runs synchronously)."""
    with get_db() as conn:
        try:
            synced, errors = run_shopify_sync(conn)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {"synced": synced, "errors": errors}


@router.get("/sync-settings", response_model=SyncSettingsResponse)
def get_sync_settings(_: str = Depends(verify_api_key)):
    """Return auto-sync settings."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT auto_sync, sync_interval_minutes, last_sync
                FROM shopify_settings WHERE id = 1
            """)
            row = cur.fetchone()

    if not row:
        return SyncSettingsResponse(auto_sync=False, sync_interval_minutes=60, last_sync=None)

    return SyncSettingsResponse(
        auto_sync=row["auto_sync"] or False,
        sync_interval_minutes=row["sync_interval_minutes"] or 60,
        last_sync=_fmt_ts(row["last_sync"]) or None,
    )


@router.put("/sync-settings")
def update_sync_settings(body: SyncSettingsUpdate, _: str = Depends(verify_api_key)):
    """Update auto-sync settings and reconfigure the scheduler."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE shopify_settings
                SET auto_sync = %s, sync_interval_minutes = %s
                WHERE id = 1
            """, (body.auto_sync, body.sync_interval_minutes))

    # Reconfigure the background scheduler
    from ..scheduler import configure_shopify_sync
    configure_shopify_sync(body.auto_sync, body.sync_interval_minutes)

    return {"status": "ok"}


# ── Orders ───────────────────────────────────────────────────────────

def _order_where_clause(filter_val: str) -> str:
    """Map a filter string to a SQL WHERE clause."""
    if filter_val == "pending":
        return " WHERE o.production_status = 'pending'"
    elif filter_val == "nested":
        return " WHERE o.production_status = 'nested'"
    elif filter_val == "cut":
        return " WHERE o.production_status = 'cut'"
    elif filter_val == "shipped":
        return " WHERE o.production_status = 'shipped'"
    elif filter_val == "unfulfilled":
        return " WHERE o.fulfillment_status IS NULL OR o.fulfillment_status != 'fulfilled'"
    return ""


def _get_order_skus(conn, order_id: int) -> str:
    """Get a comma-separated SKU summary for an order."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT sku, title, quantity
            FROM shopify_order_items WHERE order_id = %s
        """, (order_id,))
        items = cur.fetchall()
    if not items:
        return "(no items)"
    parts = []
    for item in items:
        sku = item["sku"] or item["title"][:20]
        if item["quantity"] > 1:
            parts.append(f"{sku} x{item['quantity']}")
        else:
            parts.append(sku)
    return ", ".join(parts)


@router.get("/orders")
def list_orders(
    filter: str = Query("all", description="Filter: all, pending, nested, cut, shipped, unfulfilled"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    _: str = Depends(verify_api_key),
):
    """List orders with pagination and filtering."""
    where = _order_where_clause(filter)

    with get_db() as conn:
        # Get total count
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM shopify_orders o" + where)
            total_count = cur.fetchone()["cnt"]

        # Get page
        query = """
            SELECT o.id, o.order_number, o.customer_name, o.total_price,
                   o.currency, o.fulfillment_status, o.production_status,
                   o.created_at, o.email, o.phone, o.subtotal_price,
                   o.total_tax, o.total_discounts, o.total_shipping,
                   o.financial_status, o.note, o.tags, o.source_name,
                   o.shopify_order_id, o.name as display_name,
                   o.nested_at, o.cut_at, o.packed_at, o.synced_at,
                   o.processed_at, o.cancelled_at, o.cancel_reason,
                   o.closed_at, o.shipping_address, o.billing_address,
                   o.discount_codes, o.shipping_lines,
                   o.payment_gateway_names, o.landing_site,
                   o.referring_site
            FROM shopify_orders o
        """
        query += where
        query += " ORDER BY o.created_at DESC LIMIT %s OFFSET %s"

        with conn.cursor() as cur:
            cur.execute(query, (limit, offset))
            rows = cur.fetchall()

        orders = []
        for row in rows:
            skus = _get_order_skus(conn, row["id"])
            currency = row["currency"] or "USD"
            fulfillment = row["fulfillment_status"] or "unfulfilled"
            production = row["production_status"] or "pending"

            orders.append({
                "orderNumber": f"#{row['order_number']}",
                "customerName": row["customer_name"] or "",
                "skus": skus,
                "total": _fmt_price(row["total_price"], currency),
                "shopifyStatus": fulfillment.title(),
                "productionStatus": production.replace("_", " ").title(),
                "createdAt": _fmt_ts(row["created_at"]),
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "subtotalPrice": _fmt_price(row["subtotal_price"], currency),
                "totalTax": _fmt_price(row["total_tax"], currency),
                "totalDiscounts": _fmt_price(row["total_discounts"], currency),
                "totalShipping": _fmt_price(row["total_shipping"], currency),
                "financialStatus": (row["financial_status"] or "").replace("_", " ").title(),
                "note": row["note"] or "",
                "tags": row["tags"] or "",
                "sourceName": row["source_name"] or "",
                "shopifyOrderId": row["shopify_order_id"] or "",
                "displayName": row["display_name"] or "",
                "nestedAt": _fmt_ts(row["nested_at"]),
                "cutAt": _fmt_ts(row["cut_at"]),
                "packedAt": _fmt_ts(row["packed_at"]),
                "syncedAt": _fmt_ts(row["synced_at"]),
                "processedAt": _fmt_ts(row["processed_at"]),
                "cancelledAt": _fmt_ts(row["cancelled_at"]),
                "cancelReason": row["cancel_reason"] or "",
                "closedAt": _fmt_ts(row["closed_at"]),
                "shippingAddress": _fmt_address(row["shipping_address"]),
                "billingAddress": _fmt_address(row["billing_address"]),
            })

    return {"orders": orders, "total_count": total_count}


@router.get("/orders/count")
def get_order_count(
    filter: str = Query("all", description="Filter: all, pending, nested, cut, shipped, unfulfilled"),
    _: str = Depends(verify_api_key),
):
    """Return the count of orders matching the given filter."""
    where = _order_where_clause(filter)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM shopify_orders o" + where)
            count = cur.fetchone()["cnt"]

    return {"count": count}
