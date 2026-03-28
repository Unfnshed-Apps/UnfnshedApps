"""
Shopify API client for server-side integration.

Handles authentication and data sync with Shopify stores.
Uses the Shopify Admin API with Client Credentials Grant (OAuth 2.0).

This module is adapted from the desktop app's shopify_api.py for server use.
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


# User-Agent to avoid Cloudflare blocking
USER_AGENT = "UnfnshedServer/1.0 (Shopify Integration)"


@dataclass
class ShopifyConfig:
    """Shopify connection configuration."""
    store_url: str  # e.g., "your-store.myshopify.com"
    client_id: str  # From Dev Dashboard
    client_secret: str  # From Dev Dashboard
    api_version: str = "2026-01"  # Shopify API version
    # These are managed internally after token exchange
    access_token: str = ""
    token_expires_at: Optional[datetime] = None


@dataclass
class ShopifyLineItem:
    """Represents a line item in a Shopify order."""
    id: int
    product_id: Optional[int]
    variant_id: Optional[int]
    title: str
    variant_title: str
    sku: str
    vendor: str
    quantity: int
    price: str
    total_discount: str
    fulfillable_quantity: int
    fulfillment_status: Optional[str]
    requires_shipping: bool
    taxable: bool
    gift_card: bool
    properties: list
    tax_lines: list
    discount_allocations: list
    grams: int


@dataclass
class ShopifyFulfillment:
    """Represents a fulfillment (shipment) for an order."""
    id: int
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    tracking_company: Optional[str]
    tracking_number: Optional[str]
    tracking_numbers: list
    tracking_url: Optional[str]
    tracking_urls: list
    shipment_status: Optional[str]
    service: Optional[str]
    location_id: Optional[int]
    line_items: list


@dataclass
class ShopifyOrder:
    """Represents a Shopify order with comprehensive data."""
    id: int
    order_number: str
    name: str
    created_at: datetime
    processed_at: Optional[datetime]
    closed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    # Customer info
    customer_name: str
    email: str
    phone: Optional[str]
    # Addresses
    shipping_address: dict
    billing_address: dict
    # Pricing
    total_price: str
    subtotal_price: str
    total_tax: str
    total_discounts: str
    total_shipping: str
    currency: str
    # Status
    financial_status: str
    fulfillment_status: Optional[str]
    # Metadata
    note: Optional[str]
    tags: str
    source_name: Optional[str]
    landing_site: Optional[str]
    referring_site: Optional[str]
    discount_codes: list
    shipping_lines: list
    payment_gateway_names: list
    # Related data
    line_items: list[ShopifyLineItem]
    fulfillments: list[ShopifyFulfillment]


class ShopifyAPIError(Exception):
    """Custom exception for Shopify API errors."""
    pass


class ShopifyAPI:
    """
    Client for Shopify Admin API using Client Credentials Grant.

    This is the OAuth 2.0 flow for Dev Dashboard apps where you exchange
    Client ID + Client Secret for a temporary access token (valid 24 hours).
    """

    def __init__(self, config: ShopifyConfig):
        self.config = config
        self._base_url = f"https://{config.store_url}/admin/api/{config.api_version}"

    def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token, refreshing if needed."""
        # Check if token exists and is still valid (with 5 min buffer)
        if self.config.access_token and self.config.token_expires_at:
            if datetime.now() < self.config.token_expires_at - timedelta(minutes=5):
                return  # Token is still valid

        # Need to get a new token via OAuth
        self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        """
        Get a new access token using Client Credentials Grant.

        POST https://{shop}.myshopify.com/admin/oauth/access_token
        Content-Type: application/x-www-form-urlencoded

        grant_type=client_credentials&client_id={id}&client_secret={secret}
        """
        url = f"https://{self.config.store_url}/admin/oauth/access_token"

        # Prepare form data
        form_data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }).encode('utf-8')

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

        req = urllib.request.Request(url, data=form_data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

                self.config.access_token = result.get("access_token", "")
                expires_in = result.get("expires_in", 86399)  # Default ~24 hours

                # Set expiration time
                self.config.token_expires_at = datetime.now() + timedelta(seconds=expires_in)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""

            # Check if it's a Cloudflare challenge page
            if "Just a moment" in error_body or "cloudflare" in error_body.lower():
                raise ShopifyAPIError(
                    f"Request blocked by Cloudflare. This can happen if:\n"
                    f"1. The store URL is incorrect\n"
                    f"2. The app isn't installed on the store\n"
                    f"3. Client credentials are for a different store\n\n"
                    f"Store URL: {self.config.store_url}"
                )

            raise ShopifyAPIError(f"Token exchange failed - HTTP {e.code}: {e.reason}\n{error_body[:500]}")
        except urllib.error.URLError as e:
            raise ShopifyAPIError(f"Connection error: {e.reason}")

    def _make_request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        """Make an authenticated request to the Shopify API."""
        # Ensure we have a valid token before making the request
        self._ensure_valid_token()

        url = f"{self._base_url}/{endpoint}"

        headers = {
            "X-Shopify-Access-Token": self.config.access_token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

        request_data = None
        if data:
            request_data = json.dumps(data).encode('utf-8')

        req = urllib.request.Request(url, data=request_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""
            raise ShopifyAPIError(f"HTTP {e.code}: {e.reason} - {error_body[:500]}")
        except urllib.error.URLError as e:
            raise ShopifyAPIError(f"Connection error: {e.reason}")

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the Shopify connection.

        Returns:
            Tuple of (success: bool, message_or_shop_name: str)
        """
        try:
            # Try to fetch shop info as a connection test
            result = self._make_request("shop.json")
            shop_name = result.get("shop", {}).get("name", "Unknown")
            return True, shop_name
        except ShopifyAPIError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def get_orders(
        self,
        status: str = "any",
        fulfillment_status: str = "unfulfilled",
        limit: int = 50,
        since_id: int = None
    ) -> list[ShopifyOrder]:
        """
        Fetch orders from Shopify.

        Args:
            status: Order financial status filter ("any", "paid", "pending", etc.)
            fulfillment_status: "fulfilled", "unfulfilled", "partial", or "any"
            limit: Maximum number of orders to fetch (max 250)
            since_id: Only return orders after this ID (for pagination)

        Returns:
            List of ShopifyOrder objects
        """
        params = [
            f"status={status}",
            f"fulfillment_status={fulfillment_status}",
            f"limit={min(limit, 250)}",
        ]

        if since_id:
            params.append(f"since_id={since_id}")

        endpoint = f"orders.json?{'&'.join(params)}"
        result = self._make_request(endpoint)

        orders = []
        for order_data in result.get("orders", []):
            if order_data is not None:
                orders.append(self._parse_order(order_data))

        return orders

    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse ISO 8601 datetime string from Shopify."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def _parse_order(self, data: dict) -> ShopifyOrder:
        """Parse order data from Shopify API response."""
        # Parse customer name - handle None customer
        customer = data.get("customer") or {}
        customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        if not customer_name:
            customer_name = data.get("email", "Unknown")

        # Parse line items
        line_items = []
        for item in data.get("line_items", []):
            line_items.append(ShopifyLineItem(
                id=item["id"],
                product_id=item.get("product_id"),
                variant_id=item.get("variant_id"),
                title=item.get("title", ""),
                variant_title=item.get("variant_title", ""),
                sku=item.get("sku", ""),
                vendor=item.get("vendor", ""),
                quantity=item.get("quantity", 0),
                price=item.get("price", "0.00"),
                total_discount=item.get("total_discount", "0.00"),
                fulfillable_quantity=item.get("fulfillable_quantity", 0),
                fulfillment_status=item.get("fulfillment_status"),
                requires_shipping=item.get("requires_shipping", True),
                taxable=item.get("taxable", True),
                gift_card=item.get("gift_card", False),
                properties=item.get("properties", []),
                tax_lines=item.get("tax_lines", []),
                discount_allocations=item.get("discount_allocations", []),
                grams=item.get("grams", 0),
            ))

        # Parse fulfillments
        fulfillments = []
        for f in data.get("fulfillments", []):
            fulfillments.append(ShopifyFulfillment(
                id=f["id"],
                status=f.get("status", ""),
                created_at=self._parse_datetime(f.get("created_at")),
                updated_at=self._parse_datetime(f.get("updated_at")),
                tracking_company=f.get("tracking_company"),
                tracking_number=f.get("tracking_number"),
                tracking_numbers=f.get("tracking_numbers", []),
                tracking_url=f.get("tracking_url"),
                tracking_urls=f.get("tracking_urls", []),
                shipment_status=f.get("shipment_status"),
                service=f.get("service"),
                location_id=f.get("location_id"),
                line_items=f.get("line_items", []),
            ))

        # Calculate total shipping from shipping_lines
        shipping_lines = data.get("shipping_lines", [])
        total_shipping = "0.00"
        if shipping_lines:
            total_shipping = sum(float(s.get("price", "0")) for s in shipping_lines)
            total_shipping = f"{total_shipping:.2f}"

        # Parse created_at timestamp
        created_at = self._parse_datetime(data.get("created_at")) or datetime.now()

        return ShopifyOrder(
            id=data["id"],
            order_number=str(data.get("order_number", data["id"])),
            name=data.get("name", f"#{data.get('order_number', data['id'])}"),
            created_at=created_at,
            processed_at=self._parse_datetime(data.get("processed_at")),
            closed_at=self._parse_datetime(data.get("closed_at")),
            cancelled_at=self._parse_datetime(data.get("cancelled_at")),
            cancel_reason=data.get("cancel_reason"),
            # Customer info
            customer_name=customer_name,
            email=data.get("email", ""),
            phone=data.get("phone") or (customer.get("phone") if customer else None),
            # Addresses
            shipping_address=data.get("shipping_address") or {},
            billing_address=data.get("billing_address") or {},
            # Pricing
            total_price=data.get("total_price", "0.00"),
            subtotal_price=data.get("subtotal_price", "0.00"),
            total_tax=data.get("total_tax", "0.00"),
            total_discounts=data.get("total_discounts", "0.00"),
            total_shipping=total_shipping,
            currency=data.get("currency", "USD"),
            # Status
            financial_status=data.get("financial_status", "unknown"),
            fulfillment_status=data.get("fulfillment_status"),
            # Metadata
            note=data.get("note"),
            tags=data.get("tags", ""),
            source_name=data.get("source_name"),
            landing_site=data.get("landing_site"),
            referring_site=data.get("referring_site"),
            discount_codes=data.get("discount_codes", []),
            shipping_lines=shipping_lines,
            payment_gateway_names=data.get("payment_gateway_names", []),
            # Related data
            line_items=line_items,
            fulfillments=fulfillments,
        )
