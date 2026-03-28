"""
Reusable Shopify sync logic.

Extracted from admin/bridge/sync_controller.py and admin/scheduler.py
so both the FastAPI admin router and the background scheduler can share it.
"""

import json
import logging

from .shopify_client import ShopifyAPI, ShopifyConfig

logger = logging.getLogger("nesting-api")


def save_shopify_order(conn, order) -> int:
    """
    Upsert a single ShopifyOrder into the database.

    Args:
        conn: psycopg connection (caller is responsible for commit)
        order: ShopifyOrder dataclass instance

    Returns:
        The database row id of the upserted order.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO shopify_orders (
                shopify_order_id, order_number, name, created_at, processed_at,
                closed_at, cancelled_at, cancel_reason, customer_name, email,
                phone, shipping_address, billing_address, total_price,
                subtotal_price, total_tax, total_discounts, total_shipping,
                currency, financial_status, fulfillment_status, note, tags,
                source_name, landing_site, referring_site, discount_codes,
                shipping_lines, payment_gateway_names, synced_at
            ) VALUES (
                %(shopify_order_id)s, %(order_number)s, %(name)s, %(created_at)s,
                %(processed_at)s, %(closed_at)s, %(cancelled_at)s, %(cancel_reason)s,
                %(customer_name)s, %(email)s, %(phone)s, %(shipping_address)s,
                %(billing_address)s, %(total_price)s, %(subtotal_price)s,
                %(total_tax)s, %(total_discounts)s, %(total_shipping)s,
                %(currency)s, %(financial_status)s, %(fulfillment_status)s,
                %(note)s, %(tags)s, %(source_name)s, %(landing_site)s,
                %(referring_site)s, %(discount_codes)s, %(shipping_lines)s,
                %(payment_gateway_names)s, NOW()
            )
            ON CONFLICT (shopify_order_id) DO UPDATE SET
                order_number = EXCLUDED.order_number,
                name = EXCLUDED.name,
                processed_at = EXCLUDED.processed_at,
                closed_at = EXCLUDED.closed_at,
                cancelled_at = EXCLUDED.cancelled_at,
                cancel_reason = EXCLUDED.cancel_reason,
                customer_name = EXCLUDED.customer_name,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                shipping_address = EXCLUDED.shipping_address,
                billing_address = EXCLUDED.billing_address,
                total_price = EXCLUDED.total_price,
                subtotal_price = EXCLUDED.subtotal_price,
                total_tax = EXCLUDED.total_tax,
                total_discounts = EXCLUDED.total_discounts,
                total_shipping = EXCLUDED.total_shipping,
                currency = EXCLUDED.currency,
                financial_status = EXCLUDED.financial_status,
                fulfillment_status = EXCLUDED.fulfillment_status,
                note = EXCLUDED.note,
                tags = EXCLUDED.tags,
                source_name = EXCLUDED.source_name,
                landing_site = EXCLUDED.landing_site,
                referring_site = EXCLUDED.referring_site,
                discount_codes = EXCLUDED.discount_codes,
                shipping_lines = EXCLUDED.shipping_lines,
                payment_gateway_names = EXCLUDED.payment_gateway_names,
                synced_at = NOW()
            RETURNING id
        """, {
            "shopify_order_id": str(order.id),
            "order_number": order.order_number,
            "name": order.name,
            "created_at": order.created_at,
            "processed_at": order.processed_at,
            "closed_at": order.closed_at,
            "cancelled_at": order.cancelled_at,
            "cancel_reason": order.cancel_reason,
            "customer_name": order.customer_name,
            "email": order.email,
            "phone": order.phone,
            "shipping_address": json.dumps(order.shipping_address) if order.shipping_address else None,
            "billing_address": json.dumps(order.billing_address) if order.billing_address else None,
            "total_price": order.total_price,
            "subtotal_price": order.subtotal_price,
            "total_tax": order.total_tax,
            "total_discounts": order.total_discounts,
            "total_shipping": order.total_shipping,
            "currency": order.currency,
            "financial_status": order.financial_status,
            "fulfillment_status": order.fulfillment_status,
            "note": order.note,
            "tags": order.tags,
            "source_name": order.source_name,
            "landing_site": order.landing_site,
            "referring_site": order.referring_site,
            "discount_codes": json.dumps(order.discount_codes) if order.discount_codes else None,
            "shipping_lines": json.dumps(order.shipping_lines) if order.shipping_lines else None,
            "payment_gateway_names": json.dumps(order.payment_gateway_names) if order.payment_gateway_names else None,
        })
        order_id = cur.fetchone()["id"]

        # Delete existing line items and re-insert
        cur.execute("DELETE FROM shopify_order_items WHERE order_id = %s", (order_id,))

        for item in order.line_items:
            cur.execute("""
                INSERT INTO shopify_order_items (
                    order_id, shopify_line_item_id, sku, title, quantity, price
                ) VALUES (
                    %(order_id)s, %(line_item_id)s, %(sku)s, %(title)s, %(quantity)s, %(price)s
                )
            """, {
                "order_id": order_id,
                "line_item_id": item.id,
                "sku": item.sku,
                "title": item.title,
                "quantity": item.quantity,
                "price": item.price,
            })

    conn.commit()
    return order_id


def run_shopify_sync(conn) -> tuple[int, int]:
    """
    Run a full Shopify order sync.

    Reads credentials from shopify_settings, fetches all orders from
    Shopify, and upserts them into the database.

    Args:
        conn: psycopg connection

    Returns:
        Tuple of (synced_count, error_count).

    Raises:
        ValueError: If Shopify credentials are not configured.
    """
    # Load credentials
    with conn.cursor() as cur:
        cur.execute("""
            SELECT store_url, client_id, client_secret, api_version
            FROM shopify_settings WHERE id = 1
        """)
        row = cur.fetchone()

    if not row or not row["store_url"] or not row["client_id"] or not row["client_secret"]:
        raise ValueError("Shopify not configured. Please set up credentials first.")

    config = ShopifyConfig(
        store_url=row["store_url"],
        client_id=row["client_id"],
        client_secret=row["client_secret"],
        api_version=row["api_version"] or "2026-01",
    )
    api = ShopifyAPI(config)

    synced_count = 0
    error_count = 0
    since_id = 1  # Use since_id=1 to force ascending ID order from the start

    while True:
        orders = api.get_orders(
            status="any", fulfillment_status="any",
            limit=250, since_id=since_id,
        )

        if not orders:
            break

        for order in orders:
            try:
                save_shopify_order(conn, order)
                synced_count += 1
            except Exception:
                logger.exception(f"Error saving order #{order.order_number}")
                error_count += 1

        if len(orders) < 250:
            break

        # since_id returns ascending order -- max ID is always last
        since_id = max(o.id for o in orders)

    # Update last_sync timestamp
    with conn.cursor() as cur:
        cur.execute("UPDATE shopify_settings SET last_sync = NOW() WHERE id = 1")
    conn.commit()

    logger.info(f"Shopify sync complete: {synced_count} synced, {error_count} errors")
    return synced_count, error_count
