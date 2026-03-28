"""Inventory management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    ComponentInventory, InventoryAdjustment, InventoryTransaction,
    ProductsAvailableResponse, ProductAvailability, ComponentAvailability,
    ComponentSummary, BuildPlanRequest, BuildPlanResponse, ComponentNeed,
    ProductInventory
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _ensure_component_inventory(conn, component_id: int) -> None:
    """Ensure a component_inventory record exists for the given component."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO component_inventory (component_id, quantity_on_hand, quantity_reserved)
            VALUES (%s, 0, 0)
            ON CONFLICT (component_id) DO NOTHING
            """,
            (component_id,)
        )


def _get_component_inventory(conn, component_id: int) -> ComponentInventory | None:
    """Helper to fetch a component's inventory with details."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ci.id, ci.component_id, ci.quantity_on_hand, ci.quantity_reserved,
                   ci.last_updated, cd.name as component_name, cd.dxf_filename
            FROM component_inventory ci
            JOIN component_definitions cd ON ci.component_id = cd.id
            WHERE ci.component_id = %s
            """,
            (component_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        return ComponentInventory(
            id=row["id"],
            component_id=row["component_id"],
            quantity_on_hand=row["quantity_on_hand"],
            quantity_reserved=row["quantity_reserved"],
            last_updated=row["last_updated"],
            component_name=row["component_name"],
            dxf_filename=row["dxf_filename"]
        )


@router.get("/components", response_model=list[ComponentInventory])
def list_component_inventory(_: str = Depends(verify_api_key)):
    """
    Get all component inventory levels.

    Returns inventory for all components that have inventory records.
    Components without records will have implicit 0 quantity.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all components with their inventory (LEFT JOIN to include all)
            cur.execute(
                """
                SELECT cd.id as component_id, cd.name as component_name, cd.dxf_filename,
                       COALESCE(ci.id, 0) as id,
                       COALESCE(ci.quantity_on_hand, 0) as quantity_on_hand,
                       COALESCE(ci.quantity_reserved, 0) as quantity_reserved,
                       ci.last_updated
                FROM component_definitions cd
                LEFT JOIN component_inventory ci ON cd.id = ci.component_id
                ORDER BY cd.name
                """
            )
            rows = cur.fetchall()

        return [
            ComponentInventory(
                id=row["id"],
                component_id=row["component_id"],
                quantity_on_hand=row["quantity_on_hand"],
                quantity_reserved=row["quantity_reserved"],
                last_updated=row["last_updated"],
                component_name=row["component_name"],
                dxf_filename=row["dxf_filename"]
            )
            for row in rows
        ]


@router.get("/components/{component_id}", response_model=ComponentInventory)
def get_component_inventory(component_id: int, _: str = Depends(verify_api_key)):
    """Get a single component's inventory with transaction history available via separate endpoint."""
    with get_db() as conn:
        # Ensure record exists
        _ensure_component_inventory(conn, component_id)

        inventory = _get_component_inventory(conn, component_id)
        if not inventory:
            raise HTTPException(status_code=404, detail="Component not found")
        return inventory


@router.get("/components/{component_id}/transactions", response_model=list[InventoryTransaction])
def get_component_transactions(
    component_id: int,
    limit: int = Query(50, ge=1, le=500),
    _: str = Depends(verify_api_key)
):
    """Get transaction history for a component."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, component_id, transaction_type, quantity,
                       reference_type, reference_id, notes, created_at, created_by
                FROM inventory_transactions
                WHERE component_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (component_id, limit)
            )
            rows = cur.fetchall()

        return [
            InventoryTransaction(
                id=row["id"],
                component_id=row["component_id"],
                transaction_type=row["transaction_type"],
                quantity=row["quantity"],
                reference_type=row["reference_type"],
                reference_id=row["reference_id"],
                notes=row["notes"],
                created_at=row["created_at"],
                created_by=row["created_by"]
            )
            for row in rows
        ]


@router.post("/components/{component_id}/adjust", response_model=ComponentInventory)
def adjust_component_inventory(
    component_id: int,
    adjustment: InventoryAdjustment,
    request: Request,
    _: str = Depends(verify_api_key)
):
    """
    Manually adjust component inventory.

    Use positive quantity to add, negative to remove.
    """
    device_name = request.headers.get("X-Device-Name", "unknown")

    with get_db() as conn:
        # Ensure record exists
        _ensure_component_inventory(conn, component_id)

        with conn.cursor() as cur:
            # Verify component exists
            cur.execute("SELECT id FROM component_definitions WHERE id = %s", (component_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Component not found")

            # Check that adjustment won't make quantity_on_hand negative
            if adjustment.quantity < 0:
                cur.execute(
                    "SELECT quantity_on_hand FROM component_inventory WHERE component_id = %s",
                    (component_id,)
                )
                inv_row = cur.fetchone()
                current_qty = inv_row["quantity_on_hand"] if inv_row else 0
                if current_qty + adjustment.quantity < 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Adjustment would result in negative inventory "
                               f"(current: {current_qty}, adjustment: {adjustment.quantity})"
                    )

            # Update inventory
            cur.execute(
                """
                UPDATE component_inventory
                SET quantity_on_hand = quantity_on_hand + %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE component_id = %s
                """,
                (adjustment.quantity, component_id)
            )

            # Create transaction record
            cur.execute(
                """
                INSERT INTO inventory_transactions
                (component_id, transaction_type, quantity, reference_type, notes, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (component_id, adjustment.reason, adjustment.quantity,
                 "manual", adjustment.notes, device_name)
            )

        return _get_component_inventory(conn, component_id)


@router.get("/products-available", response_model=ProductsAvailableResponse)
def get_products_available(_: str = Depends(verify_api_key)):
    """
    Calculate how many of each product can be assembled from current component inventory.

    Handles shared components correctly:
    - Shows individual product maximums (how many of EACH could be made if only making that product)
    - Indicates when components are shared across products

    Note: The max_individual values cannot simply be summed because products may share components.
    Use the validate-build-plan endpoint to check if a specific combination is feasible.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all component inventory with details
            cur.execute(
                """
                SELECT cd.id, cd.name,
                       COALESCE(ci.quantity_on_hand, 0) - COALESCE(ci.quantity_reserved, 0) as available
                FROM component_definitions cd
                LEFT JOIN component_inventory ci ON cd.id = ci.component_id
                """
            )
            component_inventory = {row["id"]: {"name": row["name"], "available": row["available"]}
                                   for row in cur.fetchall()}

            # Get all products with their components (non-outsourced only)
            cur.execute(
                """
                SELECT p.sku, p.name, pc.component_id, pc.quantity
                FROM products p
                JOIN product_components pc ON p.sku = pc.product_sku
                WHERE p.outsourced = FALSE
                ORDER BY p.sku
                """
            )
            product_rows = cur.fetchall()

        # Build product -> components mapping
        products_components = {}
        for row in product_rows:
            sku = row["sku"]
            if sku not in products_components:
                products_components[sku] = {"name": row["name"], "components": []}
            products_components[sku]["components"].append({
                "component_id": row["component_id"],
                "quantity": row["quantity"]
            })

        # Find which components are shared (used by multiple products)
        component_usage = {}  # component_id -> list of SKUs
        for sku, data in products_components.items():
            for comp in data["components"]:
                comp_id = comp["component_id"]
                if comp_id not in component_usage:
                    component_usage[comp_id] = []
                component_usage[comp_id].append(sku)

        shared_components = {comp_id for comp_id, skus in component_usage.items() if len(skus) > 1}

        # Build components summary
        components_summary = []
        for comp_id, skus in component_usage.items():
            comp_info = component_inventory.get(comp_id, {"name": "Unknown", "available": 0})
            components_summary.append(ComponentSummary(
                id=comp_id,
                name=comp_info["name"],
                available=comp_info["available"],
                used_by=skus
            ))

        # Calculate availability for each product
        products_available = []
        for sku, data in products_components.items():
            component_details = []
            min_possible = float('inf')
            limiting_component = None

            for comp in data["components"]:
                comp_id = comp["component_id"]
                required = comp["quantity"]
                comp_info = component_inventory.get(comp_id, {"name": "Unknown", "available": 0})
                available = comp_info["available"]

                # How many products could be made based on this component alone
                possible = available // required if required > 0 else float('inf')

                if possible < min_possible:
                    min_possible = possible
                    limiting_component = comp_info["name"]

                component_details.append(ComponentAvailability(
                    component_id=comp_id,
                    name=comp_info["name"],
                    required=required,
                    available=available,
                    shared=comp_id in shared_components
                ))

            has_shared = any(comp["component_id"] in shared_components for comp in data["components"])

            products_available.append(ProductAvailability(
                sku=sku,
                name=data["name"],
                max_individual=int(min_possible) if min_possible != float('inf') else 0,
                limiting_component=limiting_component,
                has_shared_components=has_shared,
                components=component_details
            ))

        return ProductsAvailableResponse(
            components_summary=components_summary,
            products=products_available
        )


@router.post("/validate-build-plan", response_model=BuildPlanResponse)
def validate_build_plan(
    plan: BuildPlanRequest,
    _: str = Depends(verify_api_key)
):
    """
    Validate if a specific build plan is feasible with current inventory.

    This properly handles shared components - it sums up all the component
    requirements across the entire build plan and checks if inventory can fulfill them.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get component inventory
            cur.execute(
                """
                SELECT cd.id, cd.name,
                       COALESCE(ci.quantity_on_hand, 0) - COALESCE(ci.quantity_reserved, 0) as available
                FROM component_definitions cd
                LEFT JOIN component_inventory ci ON cd.id = ci.component_id
                """
            )
            component_inventory = {row["id"]: {"name": row["name"], "available": row["available"]}
                                   for row in cur.fetchall()}

            # Calculate total component requirements
            component_needs = {}  # component_id -> total needed

            for item in plan.items:
                # Get components for this product
                cur.execute(
                    """
                    SELECT component_id, quantity
                    FROM product_components
                    WHERE product_sku = %s
                    """,
                    (item.sku,)
                )
                product_components = cur.fetchall()

                if not product_components:
                    return BuildPlanResponse(
                        valid=False,
                        components_needed=[],
                        message=f"Product {item.sku} not found or has no components"
                    )

                for pc in product_components:
                    comp_id = pc["component_id"]
                    needed = pc["quantity"] * item.qty
                    if comp_id not in component_needs:
                        component_needs[comp_id] = 0
                    component_needs[comp_id] += needed

        # Check if all needs can be met
        components_result = []
        all_ok = True

        for comp_id, need in component_needs.items():
            comp_info = component_inventory.get(comp_id, {"name": "Unknown", "available": 0})
            have = comp_info["available"]
            ok = have >= need

            if not ok:
                all_ok = False

            components_result.append(ComponentNeed(
                component_id=comp_id,
                name=comp_info["name"],
                need=need,
                have=have,
                ok=ok
            ))

        return BuildPlanResponse(
            valid=all_ok,
            components_needed=components_result,
            message=None if all_ok else "Insufficient components for this build plan"
        )


@router.get("/products", response_model=list[ProductInventory])
def list_product_inventory(_: str = Depends(verify_api_key)):
    """Get all finished product inventory levels."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.sku as product_sku, p.name as product_name,
                       COALESCE(pi.id, 0) as id,
                       COALESCE(pi.quantity_on_hand, 0) as quantity_on_hand,
                       COALESCE(pi.quantity_reserved, 0) as quantity_reserved,
                       pi.last_updated
                FROM products p
                LEFT JOIN product_inventory pi ON p.sku = pi.product_sku
                ORDER BY p.sku
                """
            )
            rows = cur.fetchall()

        return [
            ProductInventory(
                id=row["id"],
                product_sku=row["product_sku"],
                quantity_on_hand=row["quantity_on_hand"],
                quantity_reserved=row["quantity_reserved"],
                product_name=row["product_name"],
                last_updated=row["last_updated"]
            )
            for row in rows
        ]


@router.post("/products/{sku}/adjust", response_model=ProductInventory)
def adjust_product_inventory(
    sku: str,
    adjustment: InventoryAdjustment,
    _: str = Depends(verify_api_key)
):
    """Manually adjust finished product inventory."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify product exists
            cur.execute("SELECT sku, name FROM products WHERE sku = %s", (sku,))
            product = cur.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")

            # Ensure inventory record exists
            cur.execute(
                """
                INSERT INTO product_inventory (product_sku, quantity_on_hand, quantity_reserved)
                VALUES (%s, 0, 0)
                ON CONFLICT (product_sku) DO NOTHING
                """,
                (sku,)
            )

            # Check that adjustment won't make quantity_on_hand negative
            if adjustment.quantity < 0:
                cur.execute(
                    "SELECT quantity_on_hand FROM product_inventory WHERE product_sku = %s",
                    (sku,)
                )
                inv_row = cur.fetchone()
                current_qty = inv_row["quantity_on_hand"] if inv_row else 0
                if current_qty + adjustment.quantity < 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Adjustment would result in negative inventory "
                               f"(current: {current_qty}, adjustment: {adjustment.quantity})"
                    )

            # Update inventory
            cur.execute(
                """
                UPDATE product_inventory
                SET quantity_on_hand = quantity_on_hand + %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE product_sku = %s
                RETURNING id, product_sku, quantity_on_hand, quantity_reserved, last_updated
                """,
                (adjustment.quantity, sku)
            )
            row = cur.fetchone()

        return ProductInventory(
            id=row["id"],
            product_sku=row["product_sku"],
            quantity_on_hand=row["quantity_on_hand"],
            quantity_reserved=row["quantity_reserved"],
            product_name=product["name"],
            last_updated=row["last_updated"]
        )
