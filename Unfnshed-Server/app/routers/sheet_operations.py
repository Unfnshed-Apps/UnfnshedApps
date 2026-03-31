"""Sheet lifecycle endpoints — claim, cut, release, and related operations."""

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    NestingJob, NestingSheet, ClaimSheetRequest, MarkCutWithDamagesRequest,
    ClaimedSheetInfo, UpdateGcodeFilename, PocketTarget, SetSheetThicknessRequest,
)
from .nesting_helpers import (
    _get_sheet_row,
    _get_sheet_parts_grouped,
    _build_sheet_response,
    _validate_and_lock_sheet,
    _update_inventory_for_cut,
    _mark_sheet_cut_status,
    _check_completions,
    _find_and_lock_next_sheet,
    _setup_bundle_claim,
    _auto_assemble_products,
    _get_job_with_sheets,
)

router = APIRouter(tags=["sheet-operations"])


@router.post("/nesting-jobs/claim-next-sheet", response_model=NestingJob)
def claim_next_sheet(
    body: ClaimSheetRequest,
    _: str = Depends(verify_api_key)
):
    """
    Atomically claim the next pending sheet for a CNC machine.

    Uses SELECT ... FOR UPDATE SKIP LOCKED to prevent two machines
    from claiming the same sheet.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            row = _find_and_lock_next_sheet(cur, body.machine_id, body.prototype)
            if not row:
                raise HTTPException(status_code=404, detail="No pending sheets")

            sheet_id = row["id"]
            job_id = row["job_id"]
            bundle_id = row["bundle_id"]

            # Bundle claim flow
            _setup_bundle_claim(cur, bundle_id, body.machine_id)

            # Claim the sheet
            cur.execute(
                """
                UPDATE nesting_sheets
                SET status = 'cutting',
                    claimed_by = %s,
                    claimed_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (body.machine_id, sheet_id)
            )

            # Move job to cutting if still pending
            cur.execute(
                """
                UPDATE nesting_jobs
                SET status = 'cutting'
                WHERE id = %s AND status = 'pending'
                """,
                (job_id,)
            )

        return _get_job_with_sheets(conn, job_id)


@router.get("/nesting-jobs/claimed-sheets", response_model=list[ClaimedSheetInfo])
def get_claimed_sheets(
    machine_id: str = Query(..., description="Machine identifier to check"),
    _: str = Depends(verify_api_key)
):
    """Get sheets currently claimed by a specific machine (for crash recovery)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ns.id as sheet_id, ns.job_id, ns.sheet_number,
                       nj.name as job_name
                FROM nesting_sheets ns
                JOIN nesting_jobs nj ON ns.job_id = nj.id
                WHERE ns.status = 'cutting' AND ns.claimed_by = %s
                ORDER BY ns.claimed_at ASC
                """,
                (machine_id,)
            )
            rows = cur.fetchall()

    return [
        ClaimedSheetInfo(
            job_id=r["job_id"],
            sheet_id=r["sheet_id"],
            sheet_number=r["sheet_number"],
            job_name=r["job_name"],
        )
        for r in rows
    ]


@router.post("/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-cut", response_model=NestingSheet)
def mark_sheet_cut(
    job_id: int,
    sheet_id: int,
    request: Request,
    _: str = Depends(verify_api_key)
):
    """
    Mark a sheet as cut and update component inventory.

    This is the KEY endpoint that connects cutting to inventory:
    1. Gets all parts on the sheet (grouped by component_id)
    2. For each component: increments component_inventory.quantity_on_hand
    3. Creates inventory_transaction records (type='cut')
    4. Updates sheet.status = 'cut', sheet.cut_at = now()
    5. Updates job.completed_sheets count
    """
    device_name = request.headers.get("X-Device-Name", "unknown")

    with get_db() as conn:
        with conn.cursor() as cur:
            sheet_row = _validate_and_lock_sheet(cur, job_id, sheet_id)
            is_prototype = sheet_row["prototype"]

            parts = _get_sheet_parts_grouped(cur, sheet_id)

            if not is_prototype:
                _update_inventory_for_cut(cur, sheet_id, parts, device_name)
                _auto_assemble_products(cur, [p["component_id"] for p in parts], sheet_id, device_name)

            _mark_sheet_cut_status(cur, job_id, sheet_id)
            sheet_order_ids = _check_completions(cur, job_id, sheet_id, is_prototype)

            return _build_sheet_response(cur, sheet_id, order_ids=sheet_order_ids)


@router.post("/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-cut-with-damages", response_model=NestingSheet)
def mark_sheet_cut_with_damages(
    job_id: int,
    sheet_id: int,
    body: MarkCutWithDamagesRequest,
    request: Request,
    _: str = Depends(verify_api_key)
):
    """
    Mark a sheet as cut, crediting only good parts to inventory.

    If damaged_parts is empty, behaves identically to mark-cut.
    Damaged parts are recorded in the damaged_parts table for re-nesting.
    """
    device_name = request.headers.get("X-Device-Name", "unknown")

    # Build a lookup of damaged quantities by component_id
    damage_map: dict[int, int] = {}
    for dp in body.damaged_parts:
        damage_map[dp.component_id] = damage_map.get(dp.component_id, 0) + dp.quantity

    with get_db() as conn:
        with conn.cursor() as cur:
            sheet_row = _validate_and_lock_sheet(cur, job_id, sheet_id)
            is_prototype = sheet_row["prototype"]

            parts = _get_sheet_parts_grouped(cur, sheet_id)

            if not is_prototype:
                reported_by = sheet_row["claimed_by"] or device_name
                _update_inventory_for_cut(cur, sheet_id, parts, device_name, damage_map,
                                          machine_id=reported_by)
                _auto_assemble_products(cur, [p["component_id"] for p in parts], sheet_id, device_name)

            _mark_sheet_cut_status(cur, job_id, sheet_id)
            sheet_order_ids = _check_completions(cur, job_id, sheet_id, is_prototype)

            return _build_sheet_response(cur, sheet_id, order_ids=sheet_order_ids)


@router.post("/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-failed", response_model=NestingSheet)
def mark_sheet_failed(
    job_id: int,
    sheet_id: int,
    _: str = Depends(verify_api_key)
):
    """Mark a sheet as failed (no inventory update)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            row = _get_sheet_row(cur, job_id, sheet_id)
            if not row:
                raise HTTPException(status_code=404, detail="Sheet not found in this job")

            if row["status"] == "cut":
                raise HTTPException(status_code=400, detail="Cannot mark a cut sheet as failed")

            cur.execute(
                """
                UPDATE nesting_sheets
                SET status = 'failed'
                WHERE id = %s
                """,
                (sheet_id,)
            )

            return _build_sheet_response(cur, sheet_id)


@router.post("/nesting-jobs/{job_id}/sheets/{sheet_id}/release", response_model=NestingSheet)
def release_sheet(
    job_id: int,
    sheet_id: int,
    _: str = Depends(verify_api_key)
):
    """Release a claimed sheet back to pending status."""
    with get_db() as conn:
        with conn.cursor() as cur:
            row = _get_sheet_row(cur, job_id, sheet_id)
            if not row:
                raise HTTPException(status_code=404, detail="Sheet not found in this job")

            if row["status"] != "cutting":
                raise HTTPException(status_code=400, detail="Sheet is not in cutting status")

            cur.execute(
                """
                UPDATE nesting_sheets
                SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                WHERE id = %s
                """,
                (sheet_id,)
            )

            return _build_sheet_response(cur, sheet_id)


@router.patch("/nesting-jobs/{job_id}/sheets/{sheet_id}/gcode-filename")
def update_sheet_gcode_filename(
    job_id: int,
    sheet_id: int,
    body: UpdateGcodeFilename,
    _: str = Depends(verify_api_key)
):
    """Update a sheet's gcode_filename after local G-code generation."""
    with get_db() as conn:
        with conn.cursor() as cur:
            row = _get_sheet_row(cur, job_id, sheet_id)
            if not row:
                raise HTTPException(status_code=404, detail="Sheet not found in this job")

            if row["status"] != "cutting":
                raise HTTPException(
                    status_code=400,
                    detail="Sheet must be in cutting status to update gcode filename"
                )

            cur.execute(
                """
                UPDATE nesting_sheets
                SET gcode_filename = %s
                WHERE id = %s
                """,
                (body.gcode_filename, sheet_id)
            )

        return {"sheet_id": sheet_id, "gcode_filename": body.gcode_filename}


@router.post("/nesting-jobs/sheets/{sheet_id}/set-thickness")
def set_sheet_thickness(
    sheet_id: int,
    body: SetSheetThicknessRequest,
    _: str = Depends(verify_api_key)
):
    """Set the actual measured thickness for a sheet (from the machine's active pallet)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE nesting_sheets
                SET actual_thickness_inches = %s
                WHERE id = %s
                """,
                (body.actual_thickness_inches, sheet_id)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Sheet not found")

        return {"sheet_id": sheet_id, "actual_thickness_inches": body.actual_thickness_inches}


@router.get("/nesting-jobs/sheets/{sheet_id}/pocket-targets", response_model=list[PocketTarget])
def get_pocket_targets(sheet_id: int, _: str = Depends(verify_api_key)):
    """
    Resolve pocket target thicknesses for a sheet with variable pockets.

    For each variable-pocket component on this sheet, finds the mating tab component,
    locates which sheet that tab was placed on (for the same order), and returns
    that sheet's actual_thickness_inches as the pocket target.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Find all placements on this sheet that have variable pockets
            # and their mating pairs
            cur.execute(
                """
                SELECT DISTINCT
                    spp.component_id,
                    cmp.pocket_index,
                    cmp.mating_component_id,
                    cmp.clearance_inches,
                    cmp.product_sku,
                    spp.order_id
                FROM sheet_part_placements spp
                JOIN component_definitions cd ON spp.component_id = cd.id
                JOIN product_components pc ON pc.component_id = spp.component_id
                JOIN component_mating_pairs cmp
                    ON spp.component_id = cmp.pocket_component_id
                    AND cmp.product_sku = pc.product_sku
                WHERE spp.sheet_id = %s
                  AND cd.variable_pockets = TRUE
                """,
                (sheet_id,)
            )
            mating_info = cur.fetchall()

            targets = []

            # Check if this sheet has a pallet assigned (bundled sheets share a pallet)
            cur.execute("""
                SELECT p.avg_thickness_inches
                FROM nesting_sheets ns
                JOIN pallets p ON ns.pallet_id = p.id
                WHERE ns.id = %s
            """, (sheet_id,))
            pallet_row = cur.fetchone()

            if pallet_row and pallet_row["avg_thickness_inches"] is not None:
                # All mating pairs share pallet thickness
                for info in mating_info:
                    targets.append(PocketTarget(
                        component_id=info["component_id"],
                        pocket_index=info["pocket_index"],
                        mating_thickness_inches=pallet_row["avg_thickness_inches"],
                        clearance_inches=info["clearance_inches"],
                    ))
                return targets

            # Fallback: order_id-based matching
            for info in mating_info:
                # Find the mating tab's sheet and its actual thickness
                cur.execute(
                    """
                    SELECT ns.actual_thickness_inches
                    FROM sheet_part_placements tab_spp
                    JOIN nesting_sheets ns ON tab_spp.sheet_id = ns.id
                    WHERE tab_spp.component_id = %s
                      AND tab_spp.order_id = %s
                      AND ns.actual_thickness_inches IS NOT NULL
                    LIMIT 1
                    """,
                    (info["mating_component_id"], info["order_id"])
                )
                thickness_row = cur.fetchone()

                if thickness_row and thickness_row["actual_thickness_inches"] is not None:
                    targets.append(PocketTarget(
                        component_id=info["component_id"],
                        pocket_index=info["pocket_index"],
                        mating_thickness_inches=thickness_row["actual_thickness_inches"],
                        clearance_inches=info["clearance_inches"],
                    ))

            return targets
