"""Component definitions API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import ComponentDefinition, ComponentDefinitionCreate, ComponentDefinitionUpdate

router = APIRouter(prefix="/components", tags=["components"])


@router.get("", response_model=list[ComponentDefinition])
def list_components(_: str = Depends(verify_api_key)):
    """Get all component definitions."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, dxf_filename, variable_pockets, mating_role FROM component_definitions ORDER BY name")
            rows = cur.fetchall()
            return [ComponentDefinition(**row) for row in rows]


@router.get("/{component_id}", response_model=ComponentDefinition)
def get_component(component_id: int, _: str = Depends(verify_api_key)):
    """Get a component definition by ID."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, dxf_filename, variable_pockets, mating_role FROM component_definitions WHERE id = %s",
                (component_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Component not found")
            return ComponentDefinition(**row)


@router.post("", response_model=ComponentDefinition, status_code=status.HTTP_201_CREATED)
def create_component(component: ComponentDefinitionCreate, _: str = Depends(verify_api_key)):
    """Create a new component definition."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO component_definitions (name, dxf_filename, variable_pockets, mating_role)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, dxf_filename, variable_pockets, mating_role
                """,
                (component.name, component.dxf_filename, component.variable_pockets, component.mating_role)
            )
            row = cur.fetchone()
            return ComponentDefinition(**row)


@router.put("/{component_id}", response_model=ComponentDefinition)
def update_component(
    component_id: int,
    component: ComponentDefinitionUpdate,
    _: str = Depends(verify_api_key)
):
    """Update a component definition."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if exists
            cur.execute("SELECT id FROM component_definitions WHERE id = %s", (component_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Component not found")

            # Build update query dynamically
            updates = []
            values = []
            if component.name is not None:
                updates.append("name = %s")
                values.append(component.name)
            if component.dxf_filename is not None:
                updates.append("dxf_filename = %s")
                values.append(component.dxf_filename)
            if component.variable_pockets is not None:
                updates.append("variable_pockets = %s")
                values.append(component.variable_pockets)
            if component.mating_role is not None:
                updates.append("mating_role = %s")
                values.append(component.mating_role)

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            values.append(component_id)
            cur.execute(
                f"UPDATE component_definitions SET {', '.join(updates)} WHERE id = %s RETURNING id, name, dxf_filename, variable_pockets, mating_role",
                values
            )
            row = cur.fetchone()
            return ComponentDefinition(**row)


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_component(component_id: int, _: str = Depends(verify_api_key)):
    """Delete a component definition. Fails if component is used in products."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Check if used in any products — return their SKUs if so
            cur.execute(
                "SELECT p.sku, p.name FROM products p "
                "JOIN product_components pc ON pc.product_sku = p.sku "
                "WHERE pc.component_id = %s",
                (component_id,)
            )
            rows = cur.fetchall()
            if rows:
                product_list = ", ".join(f"{r['name']} ({r['sku']})" for r in rows)
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete component - used in: {product_list}"
                )

            try:
                cur.execute("DELETE FROM component_definitions WHERE id = %s", (component_id,))
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot delete component - it is referenced by other data (inventory, nesting jobs, or mating pairs)"
                )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Component not found")
