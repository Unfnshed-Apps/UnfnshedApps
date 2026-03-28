"""Products API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import Product, ProductCreate, ProductUpdate, ProductComponent

router = APIRouter(prefix="/products", tags=["products"])


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

        return Product(
            sku=product_row["sku"],
            name=product_row["name"],
            description=product_row["description"] or "",
            outsourced=product_row["outsourced"] or False,
            components=components
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

        # Group components by product SKU
        comp_by_sku: dict[str, list] = {}
        for row in comp_rows:
            comp_by_sku.setdefault(row["product_sku"], []).append(
                ProductComponent(**row)
            )

        return [
            Product(
                sku=p["sku"],
                name=p["name"],
                description=p["description"] or "",
                outsourced=p["outsourced"] or False,
                components=comp_by_sku.get(p["sku"], []),
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
    """Create a new product with components."""
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

            # Insert components
            for comp in product.components:
                cur.execute(
                    """
                    INSERT INTO product_components (product_sku, component_id, quantity)
                    VALUES (%s, %s, %s)
                    """,
                    (product.sku, comp.component_id, comp.quantity)
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

            # Replace components if provided
            if product.components is not None:
                cur.execute("DELETE FROM product_components WHERE product_sku = %s", (sku,))
                for comp in product.components:
                    cur.execute(
                        """
                        INSERT INTO product_components (product_sku, component_id, quantity)
                        VALUES (%s, %s, %s)
                        """,
                        (sku, comp.component_id, comp.quantity)
                    )

        return _get_product_with_components(conn, sku)


@router.delete("/{sku}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(sku: str, _: str = Depends(verify_api_key)):
    """Delete a product and its component relationships."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE sku = %s", (sku,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Product not found")
