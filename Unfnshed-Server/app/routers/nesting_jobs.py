"""Nesting jobs API endpoints — job CRUD and queue summary."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    NestingJob, NestingJobCreate,
    QueueSummary, QueueJobSummary,
)
from .nesting_helpers import _get_job_with_sheets

router = APIRouter(prefix="/nesting-jobs", tags=["nesting-jobs"])


@router.get("", response_model=list[NestingJob])
def list_nesting_jobs(
    status: Optional[str] = Query(None, description="Filter by status: pending, cutting, completed"),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(verify_api_key)
):
    """List all nesting jobs with their sheets and parts."""
    with get_db() as conn:
        with conn.cursor() as cur:
            query = "SELECT id FROM nesting_jobs"
            params = []

            if status:
                query += " WHERE status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            job_ids = [row["id"] for row in cur.fetchall()]

        return [_get_job_with_sheets(conn, job_id) for job_id in job_ids]


@router.get("/queue", response_model=QueueSummary)
def get_queue_summary(_: str = Depends(verify_api_key)):
    """Get queue summary for CNC operators."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Production counts (non-prototype)
            cur.execute(
                """SELECT COUNT(*) as cnt FROM nesting_sheets ns
                   JOIN nesting_jobs nj ON ns.job_id = nj.id
                   WHERE ns.status = 'pending' AND nj.prototype = FALSE"""
            )
            pending_sheets = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT COUNT(*) as cnt FROM nesting_sheets ns
                   JOIN nesting_jobs nj ON ns.job_id = nj.id
                   WHERE ns.status = 'cutting' AND nj.prototype = FALSE"""
            )
            cutting_sheets = cur.fetchone()["cnt"]

            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM nesting_sheets ns
                JOIN nesting_jobs nj ON ns.job_id = nj.id
                WHERE ns.status = 'cut'
                  AND ns.cut_at >= CURRENT_DATE
                  AND nj.prototype = FALSE
                """
            )
            completed_today = cur.fetchone()["cnt"]

            # Prototype counts
            cur.execute(
                """SELECT COUNT(*) as cnt FROM nesting_sheets ns
                   JOIN nesting_jobs nj ON ns.job_id = nj.id
                   WHERE ns.status = 'pending' AND nj.prototype = TRUE"""
            )
            prototype_pending = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT COUNT(*) as cnt FROM nesting_sheets ns
                   JOIN nesting_jobs nj ON ns.job_id = nj.id
                   WHERE ns.status = 'cutting' AND nj.prototype = TRUE"""
            )
            prototype_cutting = cur.fetchone()["cnt"]

            # Jobs list: production only
            cur.execute(
                """
                SELECT id, name, status, total_sheets, completed_sheets
                FROM nesting_jobs
                WHERE status IN ('pending', 'cutting')
                  AND prototype = FALSE
                ORDER BY created_at ASC
                """
            )
            jobs = [
                QueueJobSummary(
                    id=r["id"],
                    name=r["name"],
                    status=r["status"],
                    total_sheets=r["total_sheets"],
                    completed_sheets=r["completed_sheets"]
                )
                for r in cur.fetchall()
            ]

    return QueueSummary(
        pending_sheets=pending_sheets,
        cutting_sheets=cutting_sheets,
        completed_today=completed_today,
        prototype_pending_sheets=prototype_pending,
        prototype_cutting_sheets=prototype_cutting,
        jobs=jobs,
    )


@router.get("/{job_id}", response_model=NestingJob)
def get_nesting_job(job_id: int, _: str = Depends(verify_api_key)):
    """Get a nesting job by ID with all its sheets and parts."""
    with get_db() as conn:
        job = _get_job_with_sheets(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Nesting job not found")
        return job


@router.post("", response_model=NestingJob, status_code=status.HTTP_201_CREATED)
def create_nesting_job(
    job: NestingJobCreate,
    request: Request,
    _: str = Depends(verify_api_key)
):
    """
    Create a new nesting job with sheets and parts.

    This is typically called by Unfnest after generating G-code files.
    The job starts with 'pending' status and sheets can be marked as cut later.
    """
    # --- Input validation ---
    if not job.sheets:
        raise HTTPException(status_code=400, detail="Job must contain at least one sheet")

    for idx, sheet in enumerate(job.sheets):
        comp_ids = [p.component_id for p in sheet.parts]
        if len(comp_ids) != len(set(comp_ids)):
            raise HTTPException(
                status_code=400,
                detail=f"Sheet {idx + 1} contains duplicate component_ids in its parts list"
            )

    device_name = request.headers.get("X-Device-Name", job.created_by or "unknown")

    with get_db() as conn:
        with conn.cursor() as cur:
            # Create the job
            cur.execute(
                """
                INSERT INTO nesting_jobs (name, status, total_sheets, completed_sheets, created_by, prototype)
                VALUES (%s, 'pending', %s, 0, %s, %s)
                RETURNING id
                """,
                (job.name, len(job.sheets), device_name, job.prototype)
            )
            job_id = cur.fetchone()["id"]

            # Create sheets and parts
            all_order_ids = set()
            for sheet in job.sheets:
                cur.execute(
                    """
                    INSERT INTO nesting_sheets
                    (job_id, sheet_number, dxf_filename, gcode_filename, status,
                     has_variable_pockets)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                    RETURNING id
                    """,
                    (job_id, sheet.sheet_number, sheet.dxf_filename, sheet.gcode_filename,
                     sheet.has_variable_pockets)
                )
                sheet_id = cur.fetchone()["id"]

                # Add parts for this sheet
                for part in sheet.parts:
                    cur.execute(
                        """
                        INSERT INTO sheet_parts (sheet_id, component_id, quantity)
                        VALUES (%s, %s, %s)
                        """,
                        (sheet_id, part.component_id, part.quantity)
                    )

                # Add per-instance placements for this sheet
                for placement in sheet.placements:
                    cur.execute(
                        """
                        INSERT INTO sheet_part_placements
                        (sheet_id, component_id, order_id, instance_index, x, y, rotation, source_dxf)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (sheet_id, placement.component_id, placement.order_id,
                         placement.instance_index, placement.x, placement.y,
                         placement.rotation, placement.source_dxf)
                    )

                # Link orders to this sheet
                for order_id in sheet.order_ids:
                    cur.execute(
                        """
                        INSERT INTO nesting_sheet_orders (sheet_id, order_id)
                        VALUES (%s, %s)
                        ON CONFLICT (sheet_id, order_id) DO NOTHING
                        """,
                        (sheet_id, order_id)
                    )
                    all_order_ids.add(order_id)

            # Also include job-level order_ids (union of all sheets)
            all_order_ids.update(job.order_ids)

            # Mark all linked orders as nested (skip for prototype jobs)
            if not job.prototype:
                for order_id in all_order_ids:
                    cur.execute(
                        """
                        UPDATE shopify_orders
                        SET nested_at = CURRENT_TIMESTAMP,
                            production_status = 'nested'
                        WHERE id = %s AND nested_at IS NULL
                        """,
                        (order_id,)
                    )

        return _get_job_with_sheets(conn, job_id)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_nesting_job(job_id: int, _: str = Depends(verify_api_key)):
    """
    Delete a nesting job and all its sheets/parts.

    Note: This does NOT reverse any inventory transactions that were created
    when sheets were marked as cut. Use inventory adjustments for corrections.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nesting_jobs WHERE id = %s", (job_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Nesting job not found")
