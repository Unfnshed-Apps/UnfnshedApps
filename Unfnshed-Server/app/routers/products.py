"""Products API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from psycopg.errors import ForeignKeyViolation

from ..models import (
    Product, ProductCreate, ProductUpdate, ProductComponent,
    ProductMatingPair, ProductUnit,
)

router = APIRouter(prefix="/products", tags=["products"])


def _validate_and_insert_units(cur, bundle_sku: str, units) -> None:
    """Validate and insert product_units rows for a bundle."""
    for unit in units:
        # Source product must exist
        cur.execute("SELECT sku FROM products WHERE sku = %s", (unit.source_product_sku,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Source product '{unit.source_product_sku}' not found"
            )
        # Source product must not be a bundle itself (no nested bundles)
        cur.execute(
            "SELECT 1 FROM product_units WHERE bundle_sku = %s LIMIT 1",
            (unit.source_product_sku,)
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail=f"Source product '{unit.source_product_sku}' is itself a bundle — nested bundles are not allowed"
            )
        # Cannot reference self
        if unit.source_product_sku == bundle_sku:
            raise HTTPException(
                status_code=400,
                detail="A bundle cannot reference itself as a unit"
            )
        cur.execute(
            """
            INSERT INTO product_units (bundle_sku, source_product_sku, unit_index)
            VALUES (%s, %s, %s)
            """,
            (bundle_sku, unit.source_product_sku, unit.unit_index)
        )


def _get_product_with_components(conn, sku: str) -> Product | None:
    """Helper to fetch a product with all its components."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sku, name, description, outsourced FROM products WHERE sku = %s",
            (sku,)
        )
        product_row = cur.fetchone()
        if not product_row:
            return None

        cur.execute(
            """
            SELECT pc.id, pc.product_sku, pc.component_id, pc.quantity,
                   cd.name as component_name, cd.dxf_filename
            FROM product_components pc
            JOIN component_definitions cd ON pc.component_id = cd.id
            WHERE pc.product_sku = %s
            """,
            (sku,)
        )
        component_rows = cur.fetchall()

        components = [ProductComponent(**row) for row in component_rows]

        cur.execute(
            """
            SELECT id, pocket_component_id, mating_component_id,
                   pocket_index, clearance_inches
            FROM component_mating_pairs
            WHERE product_sku = %s
            ORDER BY id
            """,
            (sku,)
        )
        mating_rows = cur.fetchall()
        mating_pairs = [ProductMatingPair(**row) for row in mating_rows]

        cur.execute(
            """
            SELECT pu.id, pu.source_product_sku, pu.unit_index,
                   p.name as source_product_name
            FROM product_units pu
            JOIN products p ON pu.source_product_sku = p.sku
            WHERE pu.bundle_sku = %s
            ORDER BY pu.unit_index
            """,
            (sku,)
        )
        unit_rows = cur.fetchall()
        units = [ProductUnit(**row) for row in unit_rows]

        return Product(
            sku=product_row["sku"],
            name=product_row["name"],
            description=product_row["description"] or "",
            outsourced=product_row["outsourced"] or False,
            components=components,
            mating_pairs=mating_pairs,
            units=units,
        )


@router.get("", response_model=list[Product])
def list_products(_: str = Depends(verify_api_key)):
    """Get all products with their components."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT sku, name, description, outsourced FROM products ORDER BY sku")
            product_rows = cur.fetchall()

            if not product_rows:
                return []

            # Fetch all components in one query
            cur.execute(
                """
                SELECT pc.id, pc.product_sku, pc.component_id, pc.quantity,
                       cd.name as component_name, cd.dxf_filename
                FROM product_components pc
                JOIN component_definitions cd ON pc.component_id = cd.id
                ORDER BY pc.product_sku, pc.id
                """
            )
            comp_rows = cur.fetchall()

            # Fetch all mating pairs in one query
            cur.execute(
                """
                SELECT id, product_sku, pocket_component_id, mating_component_id,
                       pocket_index, clearance_inches
                FROM component_mating_pairs
                ORDER BY product_sku, id
                """
            )
            mp_rows = cur.fetchall()

            # Fetch all bundle units in one query
            cur.execute(
                """
                SELECT pu.id, pu.bundle_sku, pu.source_product_sku, pu.unit_index,
                       p.name as source_product_name
                FROM product_units pu
                JOIN products p ON pu.source_product_sku = p.sku
                ORDER BY pu.bundle_sku, pu.unit_index
                """
            )
            unit_rows = cur.fetchall()

        # Group components by product SKU
        comp_by_sku: dict[str, list] = {}
        for row in comp_rows:
            comp_by_sku.setdefault(row["product_sku"], []).append(
                ProductComponent(**row)
            )

        # Group mating pairs by product SKU
        mp_by_sku: dict[str, list] = {}
        for row in mp_rows:
            mp_by_sku.setdefault(row["product_sku"], []).append(
                ProductMatingPair(
                    id=row["id"],
                    pocket_component_id=row["pocket_component_id"],
                    mating_component_id=row["mating_component_id"],
                    pocket_index=row["pocket_index"],
                    clearance_inches=row["clearance_inches"],
                )
            )

        # Group units by bundle SKU
        units_by_sku: dict[str, list] = {}
        for row in unit_rows:
            units_by_sku.setdefault(row["bundle_sku"], []).append(
                ProductUnit(
                    id=row["id"],
                    source_product_sku=row["source_product_sku"],
                    unit_index=row["unit_index"],
                    source_product_name=row["source_product_name"],
                )
            )

        return [
            Product(
                sku=p["sku"],
                name=p["name"],
                description=p["description"] or "",
                outsourced=p["outsourced"] or False,
                components=comp_by_sku.get(p["sku"], []),
                mating_pairs=mp_by_sku.get(p["sku"], []),
                units=units_by_sku.get(p["sku"], []),
            )
            for p in product_rows
        ]


@router.get("/{sku}", response_model=Product)
def get_product(sku: str, _: str = Depends(verify_api_key)):
    """Get a product by SKU with all its components."""
    with get_db() as conn:
        product = _get_product_with_components(conn, sku)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product


@router.post("", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(product: ProductCreate, _: str = Depends(verify_api_key)):
    """Create a new product with components, or a bundle with units."""
    # Validate: bundle products must not have components or mating pairs
    if product.units and (product.components or product.mating_pairs):
        raise HTTPException(
            status_code=400,
            detail="A bundle product cannot have its own components or mating pairs"
        )

    with get_db() as conn:
        with conn.cursor() as cur:
            # Insert product
            cur.execute(
                """
                INSERT INTO products (sku, name, description, outsourced)
                VALUES (%s, %s, %s, %s)
                """,
                (product.sku, product.name, product.description, product.outsourced)
            )

            if product.units:
                # Bundle product — insert unit references
                _validate_and_insert_units(cur, product.sku, product.units)
            else:
                # Base product — insert components and mating pairs
                for comp in product.components:
                    cur.execute(
                        """
                        INSERT INTO product_components (product_sku, component_id, quantity)
                        VALUES (%s, %s, %s)
                        """,
                        (product.sku, comp.component_id, comp.quantity)
                    )

                component_ids = {c.component_id for c in product.components}
                for mp in product.mating_pairs:
                    if mp.pocket_component_id not in component_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Mating pair pocket component {mp.pocket_component_id} is not in this product's BOM"
                        )
                    if mp.mating_component_id not in component_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Mating pair tab component {mp.mating_component_id} is not in this product's BOM"
                        )
                    cur.execute(
                        """
                        INSERT INTO component_mating_pairs
                            (product_sku, pocket_component_id, mating_component_id, pocket_index, clearance_inches)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (product.sku, mp.pocket_component_id, mp.mating_component_id,
                         mp.pocket_index, mp.clearance_inches)
                    )

        return _get_product_with_components(conn, product.sku)


@router.put("/{sku}", response_model=Product)
def update_product(sku: str, product: ProductUpdate, _: str = Depends(verify_api_key)):
    """Update a product. If components are provided, replaces all existing components."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if exists
            cur.execute("SELECT sku FROM products WHERE sku = %s", (sku,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Product not found")

            # Build update query
            updates = []
            values = []
            if product.name is not None:
                updates.append("name = %s")
                values.append(product.name)
            if product.description is not None:
                updates.append("description = %s")
                values.append(product.description)
            if product.outsourced is not None:
                updates.append("outsourced = %s")
                values.append(product.outsourced)

            if updates:
                values.append(sku)
                cur.execute(
                    f"UPDATE products SET {', '.join(updates)} WHERE sku = %s",
                    values
                )

            # Replace units if provided
            if product.units is not None:
                # Setting units makes this a bundle — clear components and mating pairs
                if product.units:
                    cur.execute("DELETE FROM component_mating_pairs WHERE product_sku = %s", (sku,))
                    cur.execute("DELETE FROM product_components WHERE product_sku = %s", (sku,))
                cur.execute("DELETE FROM product_units WHERE bundle_sku = %s", (sku,))
                if product.units:
                    _validate_and_insert_units(cur, sku, product.units)

            # Replace components if provided (only valid for base products)
            if product.components is not None:
                # Replacing components invalidates mating pairs — clear them
                cur.execute("DELETE FROM component_mating_pairs WHERE product_sku = %s", (sku,))
                cur.execute("DELETE FROM product_components WHERE product_sku = %s", (sku,))
                # Clear units — setting components makes this a base product
                cur.execute("DELETE FROM product_units WHERE bundle_sku = %s", (sku,))
                for comp in product.components:
                    cur.execute(
                        """
                        INSERT INTO product_components (product_sku, component_id, quantity)
                        VALUES (%s, %s, %s)
                        """,
                        (sku, comp.component_id, comp.quantity)
                    )

            # Replace mating pairs if provided
            if product.mating_pairs is not None:
                cur.execute("DELETE FROM component_mating_pairs WHERE product_sku = %s", (sku,))
                # Get current component IDs for validation
                cur.execute(
                    "SELECT component_id FROM product_components WHERE product_sku = %s",
                    (sku,)
                )
                component_ids = {row["component_id"] for row in cur.fetchall()}
                for mp in product.mating_pairs:
                    if mp.pocket_component_id not in component_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Mating pair pocket component {mp.pocket_component_id} is not in this product's BOM"
                        )
                    if mp.mating_component_id not in component_ids:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Mating pair tab component {mp.mating_component_id} is not in this product's BOM"
                        )
                    cur.execute(
                        """
                        INSERT INTO component_mating_pairs
                            (product_sku, pocket_component_id, mating_component_id, pocket_index, clearance_inches)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (sku, mp.pocket_component_id, mp.mating_component_id,
                         mp.pocket_index, mp.clearance_inches)
                    )

        return _get_product_with_components(conn, sku)


@router.delete("/{sku}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(sku: str, _: str = Depends(verify_api_key)):
    """Delete a product and its component relationships."""
    with get_db() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("DELETE FROM products WHERE sku = %s", (sku,))
            except ForeignKeyViolation:
                # Product is referenced as a unit in a bundle
                cur.execute(
                    "SELECT bundle_sku FROM product_units WHERE source_product_sku = %s LIMIT 1",
                    (sku,)
                )
                row = cur.fetchone()
                bundle = row["bundle_sku"] if row else "unknown"
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete — this product is used as a unit in bundle '{bundle}'"
                )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Product not found")
