"""Sheet bundle endpoints: group mating sheets for machine affinity."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import BundleCreate, SheetBundle, SheetBundleSheet

logger = logging.getLogger("nesting-api")

router = APIRouter(prefix="/bundles", tags=["bundles"])


def _get_bundle_with_sheets(cur, bundle_id: int) -> SheetBundle | None:
    """Load a bundle with its sheet details."""
    cur.execute("""
        SELECT id, status, sheet_count, claimed_by, created_at, completed_at
        FROM sheet_bundles
        WHERE id = %s
    """, (bundle_id,))
    row = cur.fetchone()
    if not row:
        return None

    cur.execute("""
        SELECT ns.id, ns.sheet_number, ns.job_id, nj.name as job_name,
               ns.status, ns.dxf_filename
        FROM nesting_sheets ns
        JOIN nesting_jobs nj ON ns.job_id = nj.id
        WHERE ns.bundle_id = %s
        ORDER BY ns.sheet_number
    """, (bundle_id,))
    sheets = [SheetBundleSheet(**s) for s in cur.fetchall()]

    return SheetBundle(
        id=row["id"],
        status=row["status"],
        sheet_count=row["sheet_count"],
        claimed_by=row["claimed_by"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        sheets=sheets,
    )


@router.post("", response_model=SheetBundle, status_code=status.HTTP_201_CREATED)
def create_bundle(body: BundleCreate, _: str = Depends(verify_api_key)):
    """Create a bundle from 2-4 sheet IDs."""
    sheet_ids = body.sheet_ids
    if len(sheet_ids) < 2 or len(sheet_ids) > 20:
        raise HTTPException(status_code=400, detail="Bundle must contain 2-20 sheets")

    if len(set(sheet_ids)) != len(sheet_ids):
        raise HTTPException(status_code=400, detail="Duplicate sheet IDs")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify all sheets exist and aren't already bundled
            placeholders = ",".join(["%s"] * len(sheet_ids))
            cur.execute(f"""
                SELECT id, bundle_id, status
                FROM nesting_sheets
                WHERE id IN ({placeholders})
            """, sheet_ids)
            rows = cur.fetchall()

            if len(rows) != len(sheet_ids):
                found_ids = {r["id"] for r in rows}
                missing = set(sheet_ids) - found_ids
                raise HTTPException(
                    status_code=404,
                    detail=f"Sheets not found: {sorted(missing)}"
                )

            for r in rows:
                if r["bundle_id"] is not None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Sheet {r['id']} is already in a bundle"
                    )

            # Create bundle
            cur.execute("""
                INSERT INTO sheet_bundles (status, sheet_count)
                VALUES ('pending', %s)
                RETURNING id
            """, (len(sheet_ids),))
            bundle_id = cur.fetchone()["id"]

            # Assign sheets to bundle
            cur.execute(f"""
                UPDATE nesting_sheets
                SET bundle_id = %s
                WHERE id IN ({placeholders})
            """, [bundle_id] + sheet_ids)

            return _get_bundle_with_sheets(cur, bundle_id)


@router.get("", response_model=list[SheetBundle])
def list_bundles(_: str = Depends(verify_api_key)):
    """List all bundles."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM sheet_bundles
                ORDER BY created_at DESC
                LIMIT 100
            """)
            bundle_ids = [r["id"] for r in cur.fetchall()]
            return [_get_bundle_with_sheets(cur, bid) for bid in bundle_ids]


@router.get("/{bundle_id}", response_model=SheetBundle)
def get_bundle(bundle_id: int, _: str = Depends(verify_api_key)):
    """Get a bundle with sheet details."""
    with get_db() as conn:
        with conn.cursor() as cur:
            bundle = _get_bundle_with_sheets(cur, bundle_id)
            if not bundle:
                raise HTTPException(status_code=404, detail="Bundle not found")
            return bundle


@router.delete("/{bundle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bundle(bundle_id: int, _: str = Depends(verify_api_key)):
    """Delete a pending bundle (unlinks sheets)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status FROM sheet_bundles WHERE id = %s
            """, (bundle_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Bundle not found")

            if row["status"] != "pending":
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete bundle in '{row['status']}' status"
                )

            # Unlink sheets
            cur.execute("""
                UPDATE nesting_sheets SET bundle_id = NULL WHERE bundle_id = %s
            """, (bundle_id,))

            # Delete bundle
            cur.execute("DELETE FROM sheet_bundles WHERE id = %s", (bundle_id,))
