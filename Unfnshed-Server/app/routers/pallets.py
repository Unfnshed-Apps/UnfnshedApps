"""Pallet tracking and machine assignment API endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    Pallet, PalletCreate, SetActivePalletRequest, MachineActivePallet
)

router = APIRouter(tags=["pallets"])


@router.post("/pallets", response_model=Pallet, status_code=status.HTTP_201_CREATED)
def create_pallet(body: PalletCreate, _: str = Depends(verify_api_key)):
    """Create a pallet with 3 thickness measurements. Average is computed automatically."""
    avg = (body.measurement_1 + body.measurement_2 + body.measurement_3) / 3.0

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pallets
                (measurement_1, measurement_2, measurement_3,
                 avg_thickness_inches, sheets_remaining)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, measurement_1, measurement_2, measurement_3,
                          avg_thickness_inches, sheets_remaining, created_at, depleted_at
                """,
                (body.measurement_1, body.measurement_2,
                 body.measurement_3, avg, body.sheets_remaining)
            )
            row = cur.fetchone()
            return Pallet(**row)


@router.get("/pallets", response_model=list[Pallet])
def list_pallets(
    active: Optional[bool] = Query(None, description="If true, only non-depleted pallets"),
    _: str = Depends(verify_api_key)
):
    """List pallets, optionally filtering to active (non-depleted) only."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if active:
                cur.execute(
                    """
                    SELECT id, measurement_1, measurement_2, measurement_3,
                           avg_thickness_inches, sheets_remaining, created_at, depleted_at
                    FROM pallets
                    WHERE depleted_at IS NULL
                    ORDER BY created_at DESC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, measurement_1, measurement_2, measurement_3,
                           avg_thickness_inches, sheets_remaining, created_at, depleted_at
                    FROM pallets
                    ORDER BY created_at DESC
                    """
                )
            rows = cur.fetchall()
            return [Pallet(**r) for r in rows]


@router.get("/pallets/{pallet_id}", response_model=Pallet)
def get_pallet(pallet_id: int, _: str = Depends(verify_api_key)):
    """Get a single pallet by ID."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, measurement_1, measurement_2, measurement_3,
                       avg_thickness_inches, sheets_remaining, created_at, depleted_at
                FROM pallets WHERE id = %s
                """,
                (pallet_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pallet not found")
            return Pallet(**row)


@router.post("/pallets/{pallet_id}/deplete", response_model=Pallet)
def deplete_pallet(pallet_id: int, _: str = Depends(verify_api_key)):
    """Mark a pallet as depleted."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, depleted_at FROM pallets WHERE id = %s",
                (pallet_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pallet not found")
            if row["depleted_at"] is not None:
                raise HTTPException(status_code=400, detail="Pallet already depleted")

            cur.execute(
                """
                UPDATE pallets SET depleted_at = CURRENT_TIMESTAMP WHERE id = %s
                RETURNING id, measurement_1, measurement_2, measurement_3,
                          avg_thickness_inches, sheets_remaining, created_at, depleted_at
                """,
                (pallet_id,)
            )
            row = cur.fetchone()
            return Pallet(**row)


@router.post("/pallets/{pallet_id}/decrement-sheet", response_model=Pallet)
def decrement_pallet_sheet(pallet_id: int, _: str = Depends(verify_api_key)):
    """Decrement sheets_remaining by 1 after cutting a sheet."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sheets_remaining, depleted_at FROM pallets WHERE id = %s",
                (pallet_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pallet not found")
            if row["depleted_at"] is not None:
                raise HTTPException(status_code=400, detail="Pallet already depleted")

            new_remaining = max(0, row["sheets_remaining"] - 1)
            cur.execute(
                """
                UPDATE pallets SET sheets_remaining = %s WHERE id = %s
                RETURNING id, measurement_1, measurement_2, measurement_3,
                          avg_thickness_inches, sheets_remaining, created_at, depleted_at
                """,
                (new_remaining, pallet_id)
            )
            row = cur.fetchone()
            return Pallet(**row)


@router.post("/machines/{letter}/active-pallet", response_model=MachineActivePallet)
def set_active_pallet(
    letter: str,
    body: SetActivePalletRequest,
    _: str = Depends(verify_api_key)
):
    """Assign a pallet to a CNC machine. Replaces any existing assignment."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify pallet exists and is not depleted
            cur.execute(
                "SELECT id FROM pallets WHERE id = %s AND depleted_at IS NULL",
                (body.pallet_id,)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Pallet not found or already depleted")

            cur.execute(
                """
                INSERT INTO machine_active_pallets (machine_letter, pallet_id, assigned_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (machine_letter) DO UPDATE
                SET pallet_id = EXCLUDED.pallet_id,
                    assigned_at = CURRENT_TIMESTAMP
                RETURNING machine_letter, pallet_id, assigned_at
                """,
                (letter.upper(), body.pallet_id)
            )
            row = cur.fetchone()

            # Get pallet details
            cur.execute(
                "SELECT avg_thickness_inches, sheets_remaining FROM pallets WHERE id = %s",
                (body.pallet_id,)
            )
            pallet_row = cur.fetchone()

            return MachineActivePallet(
                machine_letter=row["machine_letter"],
                pallet_id=row["pallet_id"],
                assigned_at=row["assigned_at"],
                avg_thickness_inches=pallet_row["avg_thickness_inches"],
                sheets_remaining=pallet_row["sheets_remaining"],
            )


@router.get("/machines/{letter}/active-pallet", response_model=MachineActivePallet)
def get_active_pallet(letter: str, _: str = Depends(verify_api_key)):
    """Get the currently active pallet for a CNC machine."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT map.machine_letter, map.pallet_id, map.assigned_at,
                       p.avg_thickness_inches, p.sheets_remaining
                FROM machine_active_pallets map
                JOIN pallets p ON map.pallet_id = p.id
                WHERE map.machine_letter = %s
                """,
                (letter.upper(),)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="No active pallet for this machine")
            return MachineActivePallet(**row)
