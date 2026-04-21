"""Manual nest endpoints: hand-built sheet layouts usable as auto-nest overrides.

A manual nest is one or more sheets, each with parts placed by hand at a fixed
(x, y, rotation). When override_enabled is true, the nesting pipeline will
consult the nest during planning: if a job's product demand matches the nest's
contents, the pre-built layout is used verbatim instead of auto-nesting.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    ManualNest, ManualNestCreate, ManualNestPartItem,
    ManualNestSheetItem, ManualNestUpdate,
)

logger = logging.getLogger("nesting-api")

router = APIRouter(prefix="/manual-nests", tags=["manual_nests"])


# ------------------------------------------------------------------ helpers

def _get_nest_with_sheets(cur, nest_id: int) -> ManualNest | None:
    """Load a manual nest with its sheets and parts."""
    cur.execute("""
        SELECT id, name, override_enabled, created_at, updated_at
        FROM manual_nests
        WHERE id = %s
    """, (nest_id,))
    row = cur.fetchone()
    if not row:
        return None

    cur.execute("""
        SELECT id, sheet_index, width, height, part_spacing, edge_margin,
               material, thickness
        FROM manual_nest_sheets
        WHERE nest_id = %s
        ORDER BY sheet_index
    """, (nest_id,))
    sheet_rows = cur.fetchall()

    sheets: list[ManualNestSheetItem] = []
    for sr in sheet_rows:
        cur.execute("""
            SELECT id, component_id, product_sku, product_unit, instance_index,
                   x, y, rotation_deg
            FROM manual_nest_parts
            WHERE sheet_id = %s
            ORDER BY id
        """, (sr["id"],))
        parts = [ManualNestPartItem(**p) for p in cur.fetchall()]
        sheets.append(ManualNestSheetItem(**sr, parts=parts))

    return ManualNest(
        id=row["id"],
        name=row["name"],
        override_enabled=row["override_enabled"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        sheets=sheets,
    )


def _write_sheets(cur, nest_id: int, sheets: list[ManualNestSheetItem]) -> None:
    """Replace all sheets (and their parts) for a nest."""
    cur.execute("DELETE FROM manual_nest_sheets WHERE nest_id = %s", (nest_id,))
    for sheet in sheets:
        cur.execute("""
            INSERT INTO manual_nest_sheets
                (nest_id, sheet_index, width, height, part_spacing,
                 edge_margin, material, thickness)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            nest_id, sheet.sheet_index, sheet.width, sheet.height,
            sheet.part_spacing, sheet.edge_margin, sheet.material, sheet.thickness,
        ))
        sheet_id = cur.fetchone()["id"]
        for part in sheet.parts:
            cur.execute("""
                INSERT INTO manual_nest_parts
                    (sheet_id, component_id, product_sku, product_unit,
                     instance_index, x, y, rotation_deg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                sheet_id, part.component_id, part.product_sku, part.product_unit,
                part.instance_index, part.x, part.y, part.rotation_deg,
            ))


# ------------------------------------------------------------------ endpoints

@router.post("", response_model=ManualNest, status_code=status.HTTP_201_CREATED)
def create_manual_nest(body: ManualNestCreate, _: str = Depends(verify_api_key)):
    """Create a manual nest, optionally with initial sheets and parts."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO manual_nests (name, override_enabled)
                VALUES (%s, %s)
                RETURNING id
            """, (body.name, body.override_enabled))
            nest_id = cur.fetchone()["id"]

            if body.sheets:
                _write_sheets(cur, nest_id, body.sheets)

            return _get_nest_with_sheets(cur, nest_id)


@router.get("", response_model=list[ManualNest])
def list_manual_nests(_: str = Depends(verify_api_key)):
    """List all manual nests with full sheet/part detail."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM manual_nests
                ORDER BY updated_at DESC, id DESC
            """)
            ids = [r["id"] for r in cur.fetchall()]
            return [_get_nest_with_sheets(cur, nid) for nid in ids]


@router.get("/{nest_id}", response_model=ManualNest)
def get_manual_nest(nest_id: int, _: str = Depends(verify_api_key)):
    """Fetch a single manual nest with full detail."""
    with get_db() as conn:
        with conn.cursor() as cur:
            nest = _get_nest_with_sheets(cur, nest_id)
            if not nest:
                raise HTTPException(status_code=404, detail="Manual nest not found")
            return nest


@router.put("/{nest_id}", response_model=ManualNest)
def update_manual_nest(
    nest_id: int,
    body: ManualNestUpdate,
    _: str = Depends(verify_api_key),
):
    """Partial update. If `sheets` is provided, it REPLACES all existing sheets."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM manual_nests WHERE id = %s", (nest_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Manual nest not found")

            # Update scalar fields that were provided
            sets = []
            params: list = []
            if body.name is not None:
                if not body.name.strip():
                    raise HTTPException(status_code=400, detail="Name cannot be empty")
                sets.append("name = %s")
                params.append(body.name)
            if body.override_enabled is not None:
                sets.append("override_enabled = %s")
                params.append(body.override_enabled)

            if sets:
                sets.append("updated_at = CURRENT_TIMESTAMP")
                params.append(nest_id)
                cur.execute(
                    f"UPDATE manual_nests SET {', '.join(sets)} WHERE id = %s",
                    params,
                )

            if body.sheets is not None:
                _write_sheets(cur, nest_id, body.sheets)
                cur.execute(
                    "UPDATE manual_nests SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (nest_id,),
                )

            return _get_nest_with_sheets(cur, nest_id)


@router.delete("/{nest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_manual_nest(nest_id: int, _: str = Depends(verify_api_key)):
    """Delete a manual nest. Cascades to its sheets and parts."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM manual_nests WHERE id = %s RETURNING id",
                (nest_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Manual nest not found")
