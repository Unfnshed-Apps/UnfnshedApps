"""Shared query helpers and business logic for nesting job/sheet operations."""

from fastapi import HTTPException

from ..models import (
    NestingJob, NestingSheet, SheetPart, SheetPartPlacement,
)


# ---------------------------------------------------------------------------
# Query helpers (extracted from repeated inline patterns)
# ---------------------------------------------------------------------------

def _get_sheet_row(cur, job_id: int, sheet_id: int) -> dict | None:
    """Fetch a nesting sheet joined with its job, verifying the sheet belongs to the job."""
    cur.execute(
        """
        SELECT ns.id, ns.status, ns.claimed_by, nj.id as job_id, nj.prototype
        FROM nesting_sheets ns
        JOIN nesting_jobs nj ON ns.job_id = nj.id
        WHERE ns.id = %s AND nj.id = %s
        """,
        (sheet_id, job_id)
    )
    return cur.fetchone()


def _ensure_inventory_row(cur, component_id: int):
    """Ensure a component_inventory record exists (insert if missing)."""
    cur.execute(
        """
        INSERT INTO component_inventory (component_id, quantity_on_hand, quantity_reserved)
        VALUES (%s, 0, 0)
        ON CONFLICT (component_id) DO NOTHING
        """,
        (component_id,)
    )


def _get_sheet_parts_grouped(cur, sheet_id: int) -> list[dict]:
    """Get all parts on a sheet, grouped by component_id with summed quantities."""
    cur.execute(
        """
        SELECT component_id, SUM(quantity) as total_qty
        FROM sheet_parts
        WHERE sheet_id = %s
        GROUP BY component_id
        """,
        (sheet_id,)
    )
    return cur.fetchall()


def _fetch_sheet_for_response(cur, sheet_id: int) -> dict:
    """Fetch a sheet row suitable for building a NestingSheet response."""
    cur.execute(
        """
        SELECT id, job_id, sheet_number, dxf_filename, gcode_filename,
               status, cut_at, claimed_by, claimed_at
        FROM nesting_sheets
        WHERE id = %s
        """,
        (sheet_id,)
    )
    return cur.fetchone()


def _fetch_parts_for_response(cur, sheet_id: int) -> list[SheetPart]:
    """Fetch sheet parts with component names for building a response."""
    cur.execute(
        """
        SELECT sp.id, sp.sheet_id, sp.component_id, sp.quantity,
               sp.product_sku, sp.assembled_qty,
               cd.name as component_name
        FROM sheet_parts sp
        JOIN component_definitions cd ON sp.component_id = cd.id
        WHERE sp.sheet_id = %s
        """,
        (sheet_id,)
    )
    return [
        SheetPart(
            id=p["id"],
            sheet_id=p["sheet_id"],
            component_id=p["component_id"],
            quantity=p["quantity"],
            component_name=p["component_name"],
            product_sku=p["product_sku"],
            assembled_qty=p["assembled_qty"],
        )
        for p in cur.fetchall()
    ]


def _fetch_order_ids_for_sheet(cur, sheet_id: int) -> list[int]:
    """Fetch order IDs linked to a sheet."""
    cur.execute(
        "SELECT order_id FROM nesting_sheet_orders WHERE sheet_id = %s",
        (sheet_id,)
    )
    return [r["order_id"] for r in cur.fetchall()]


def _build_sheet_response(cur, sheet_id: int, order_ids: list[int] | None = None) -> NestingSheet:
    """Build a full NestingSheet response object for a given sheet_id."""
    sheet_row = _fetch_sheet_for_response(cur, sheet_id)
    parts = _fetch_parts_for_response(cur, sheet_id)
    if order_ids is None:
        order_ids = _fetch_order_ids_for_sheet(cur, sheet_id)
    return NestingSheet(
        id=sheet_row["id"],
        job_id=sheet_row["job_id"],
        sheet_number=sheet_row["sheet_number"],
        dxf_filename=sheet_row["dxf_filename"],
        gcode_filename=sheet_row["gcode_filename"],
        status=sheet_row["status"],
        cut_at=sheet_row["cut_at"],
        claimed_by=sheet_row.get("claimed_by"),
        claimed_at=sheet_row.get("claimed_at"),
        parts=parts,
        order_ids=order_ids,
    )


# ---------------------------------------------------------------------------
# Shared mark-cut helpers (used by both mark_sheet_cut and
# mark_sheet_cut_with_damages)
# ---------------------------------------------------------------------------

def _validate_and_lock_sheet(cur, job_id: int, sheet_id: int) -> dict:
    """Validate the sheet exists in the job and is not already cut.

    Returns the sheet row dict (with status, prototype, etc.).
    Raises HTTPException on validation failure.
    """
    row = _get_sheet_row(cur, job_id, sheet_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sheet not found in this job")
    if row["status"] == "cut":
        raise HTTPException(status_code=400, detail="Sheet already marked as cut")
    return row


def _update_inventory_for_cut(cur, sheet_id: int, parts: list[dict],
                               device_name: str,
                               damage_map: dict[int, int] | None = None,
                               machine_id: str | None = None):
    """Credit good parts to inventory and record damages.

    *parts* comes from _get_sheet_parts_grouped.  *damage_map* maps
    component_id -> damaged quantity (may be None or empty for the simple
    mark-cut path).  *machine_id* is used for the damaged_parts.reported_by
    field (defaults to device_name).
    """
    if damage_map is None:
        damage_map = {}

    if machine_id is None:
        machine_id = device_name

    for part in parts:
        component_id = part["component_id"]
        total_qty = part["total_qty"]
        damaged_qty = damage_map.get(component_id, 0)
        good_qty = total_qty - damaged_qty

        _ensure_inventory_row(cur, component_id)

        if good_qty > 0:
            cur.execute(
                """
                UPDATE component_inventory
                SET quantity_on_hand = quantity_on_hand + %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE component_id = %s
                """,
                (good_qty, component_id)
            )
            cur.execute(
                """
                INSERT INTO inventory_transactions
                (component_id, transaction_type, quantity, reference_type, reference_id, created_by)
                VALUES (%s, 'cut', %s, 'nesting_sheet', %s, %s)
                """,
                (component_id, good_qty, sheet_id, device_name)
            )

        if damaged_qty > 0:
            cur.execute(
                """
                INSERT INTO damaged_parts (sheet_id, component_id, quantity, reported_by)
                VALUES (%s, %s, %s, %s)
                """,
                (sheet_id, component_id, damaged_qty, machine_id)
            )
            cur.execute(
                """
                INSERT INTO inventory_transactions
                (component_id, transaction_type, quantity, reference_type, reference_id,
                 notes, created_by)
                VALUES (%s, 'damaged', %s, 'nesting_sheet', %s, %s, %s)
                """,
                (component_id, -damaged_qty, sheet_id,
                 f"Damaged during cutting on machine {machine_id}", device_name)
            )


def _mark_sheet_cut_status(cur, job_id: int, sheet_id: int):
    """Update the sheet to 'cut' and bump the job's completed_sheets counter."""
    cur.execute(
        """
        UPDATE nesting_sheets
        SET status = 'cut', cut_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (sheet_id,)
    )
    cur.execute(
        """
        UPDATE nesting_jobs
        SET completed_sheets = completed_sheets + 1,
            status = CASE
                WHEN completed_sheets + 1 >= total_sheets THEN 'completed'
                ELSE 'cutting'
            END
        WHERE id = %s
        """,
        (job_id,)
    )


def _check_completions(cur, job_id: int, sheet_id: int, is_prototype: bool):
    """Check and update order completion and bundle completion."""
    sheet_order_ids = _fetch_order_ids_for_sheet(cur, sheet_id)

    # Order completion
    if not is_prototype and sheet_order_ids:
        order_placeholders = ",".join(["%s"] * len(sheet_order_ids))
        cur.execute(
            f"""
            SELECT nso.order_id, COUNT(*) FILTER (WHERE ns.status != 'cut') as uncut
            FROM nesting_sheet_orders nso
            JOIN nesting_sheets ns ON ns.id = nso.sheet_id
            WHERE nso.order_id IN ({order_placeholders}) AND ns.job_id = %s
            GROUP BY nso.order_id
            """,
            list(sheet_order_ids) + [job_id]
        )
        for row in cur.fetchall():
            if row["uncut"] == 0:
                cur.execute(
                    """
                    UPDATE shopify_orders
                    SET cut_at = CURRENT_TIMESTAMP,
                        production_status = 'cut'
                    WHERE id = %s AND cut_at IS NULL
                    """,
                    (row["order_id"],)
                )

    # Bundle completion
    cur.execute(
        "SELECT bundle_id FROM nesting_sheets WHERE id = %s",
        (sheet_id,)
    )
    bundle_check = cur.fetchone()
    if bundle_check and bundle_check["bundle_id"]:
        bid = bundle_check["bundle_id"]
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE status != 'cut') as uncut
            FROM nesting_sheets
            WHERE bundle_id = %s
        """, (bid,))
        uncut_in_bundle = cur.fetchone()["uncut"]
        if uncut_in_bundle == 0:
            cur.execute("""
                UPDATE sheet_bundles
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (bid,))

    return sheet_order_ids


# ---------------------------------------------------------------------------
# Claim-next-sheet helpers
# ---------------------------------------------------------------------------

def _find_and_lock_next_sheet(cur, machine_id: str, prototype: bool) -> dict | None:
    """SELECT FOR UPDATE SKIP LOCKED the next pending sheet for a machine."""
    cur.execute(
        """
        SELECT ns.id, ns.job_id, ns.bundle_id
        FROM nesting_sheets ns
        JOIN nesting_jobs nj ON ns.job_id = nj.id
        LEFT JOIN sheet_bundles sb ON ns.bundle_id = sb.id
        WHERE ns.status = 'pending'
          AND nj.prototype = %(prototype)s
          AND (
            ns.bundle_id IS NULL
            OR sb.claimed_by IS NULL
            OR sb.claimed_by = %(machine_id)s
          )
        ORDER BY nj.created_at ASC, ns.sheet_number ASC
        LIMIT 1
        FOR UPDATE OF ns SKIP LOCKED
        """,
        {"prototype": prototype, "machine_id": machine_id}
    )
    return cur.fetchone()


def _setup_bundle_claim(cur, bundle_id: int, machine_id: str) -> dict | None:
    """Handle bundle claiming logic for the first sheet from an unclaimed bundle.

    Returns bundle_info dict or None if no bundle.
    """
    if bundle_id is None:
        return None

    cur.execute(
        "SELECT id, claimed_by, sheet_count FROM sheet_bundles WHERE id = %s",
        (bundle_id,)
    )
    bundle_row = cur.fetchone()
    if not bundle_row:
        return None

    if bundle_row["claimed_by"] is None:
        # First claim on this bundle
        cur.execute("""
            UPDATE sheet_bundles
            SET claimed_by = %s, status = 'cutting'
            WHERE id = %s
        """, (machine_id, bundle_id))

    return {
        "bundle_id": bundle_id,
        "sheet_count": bundle_row["sheet_count"],
        "claimed_by": machine_id,
    }


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

def _intent_aware_assemble(cur, sheet_id: int, device_name: str):
    """Assemble products from intent-tagged sheet_parts.

    Only assembles products using components specifically tagged for that
    product. Components spanning multiple sheets are handled by querying
    ALL cut sheets with unassembled parts for the same product_sku.

    Parts without a product_sku (component-only nesting) are skipped —
    they go to component_inventory only.
    """
    # Find distinct product_skus on this sheet (exclude NULL)
    cur.execute(
        """
        SELECT DISTINCT product_sku
        FROM sheet_parts
        WHERE sheet_id = %s AND product_sku IS NOT NULL
        """,
        (sheet_id,),
    )
    skus = [r["product_sku"] for r in cur.fetchall()]
    if not skus:
        return

    for sku in skus:
        # Count unassembled components across ALL cut sheets for this product
        cur.execute(
            """
            SELECT sp.component_id, SUM(sp.quantity - sp.assembled_qty) as available
            FROM sheet_parts sp
            JOIN nesting_sheets ns ON sp.sheet_id = ns.id
            WHERE sp.product_sku = %s
              AND ns.status = 'cut'
              AND sp.quantity > sp.assembled_qty
            GROUP BY sp.component_id
            """,
            (sku,),
        )
        available_map = {r["component_id"]: r["available"] for r in cur.fetchall()}
        if not available_map:
            continue

        # Look up product BOM
        cur.execute(
            """
            SELECT component_id, quantity
            FROM product_components
            WHERE product_sku = %s
            """,
            (sku,),
        )
        bom = cur.fetchall()
        if not bom:
            continue

        # Calculate max assemblable units (bottleneck component)
        max_units = None
        for row in bom:
            avail = available_map.get(row["component_id"], 0)
            possible = avail // row["quantity"]
            if max_units is None or possible < max_units:
                max_units = possible

        if not max_units or max_units <= 0:
            continue

        # Deduct from component_inventory and mark sheet_parts as assembled
        for row in bom:
            deduct = max_units * row["quantity"]

            # Deduct from physical component inventory
            cur.execute(
                """
                UPDATE component_inventory
                SET quantity_on_hand = quantity_on_hand - %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE component_id = %s
                """,
                (deduct, row["component_id"]),
            )
            cur.execute(
                """
                INSERT INTO inventory_transactions
                (component_id, transaction_type, quantity, reference_type, reference_id,
                 notes, created_by)
                VALUES (%s, 'assembled', %s, 'nesting_sheet', %s, %s, %s)
                """,
                (row["component_id"], -deduct, sheet_id,
                 f"Assembled {max_units}x {sku}", device_name),
            )

            # Update assembled_qty on sheet_parts rows (FIFO: oldest first)
            remaining = deduct
            cur.execute(
                """
                SELECT sp.id, sp.quantity - sp.assembled_qty as unassembled
                FROM sheet_parts sp
                JOIN nesting_sheets ns ON sp.sheet_id = ns.id
                WHERE sp.product_sku = %s
                  AND sp.component_id = %s
                  AND ns.status = 'cut'
                  AND sp.quantity > sp.assembled_qty
                ORDER BY ns.cut_at ASC, sp.id ASC
                """,
                (sku, row["component_id"]),
            )
            for sp_row in cur.fetchall():
                if remaining <= 0:
                    break
                consume = min(remaining, sp_row["unassembled"])
                cur.execute(
                    "UPDATE sheet_parts SET assembled_qty = assembled_qty + %s WHERE id = %s",
                    (consume, sp_row["id"]),
                )
                remaining -= consume

        # Credit product inventory
        cur.execute(
            """
            INSERT INTO product_inventory (product_sku, quantity_on_hand, quantity_reserved)
            VALUES (%s, 0, 0)
            ON CONFLICT (product_sku) DO NOTHING
            """,
            (sku,),
        )
        cur.execute(
            """
            UPDATE product_inventory
            SET quantity_on_hand = quantity_on_hand + %s,
                last_updated = CURRENT_TIMESTAMP
            WHERE product_sku = %s
            """,
            (max_units, sku),
        )


def _get_job_with_sheets(conn, job_id: int) -> NestingJob | None:
    """Helper to fetch a nesting job with all its sheets and parts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, status, total_sheets, completed_sheets,
                   created_at, created_by, prototype
            FROM nesting_jobs
            WHERE id = %s
            """,
            (job_id,)
        )
        job_row = cur.fetchone()
        if not job_row:
            return None

        # Get all sheets for this job
        cur.execute(
            """
            SELECT id, job_id, sheet_number, dxf_filename, gcode_filename,
                   status, cut_at, claimed_by, claimed_at,
                   has_variable_pockets,
                   actual_thickness_inches
            FROM nesting_sheets
            WHERE job_id = %s
            ORDER BY sheet_number
            """,
            (job_id,)
        )
        sheet_rows = cur.fetchall()

        sheets = []
        all_order_ids = set()
        for sheet_row in sheet_rows:
            # Get parts for this sheet
            cur.execute(
                """
                SELECT sp.id, sp.sheet_id, sp.component_id, sp.quantity,
                       sp.product_sku, sp.assembled_qty,
                       cd.name as component_name
                FROM sheet_parts sp
                JOIN component_definitions cd ON sp.component_id = cd.id
                WHERE sp.sheet_id = %s
                """,
                (sheet_row["id"],)
            )
            part_rows = cur.fetchall()

            parts = [
                SheetPart(
                    id=p["id"],
                    sheet_id=p["sheet_id"],
                    component_id=p["component_id"],
                    quantity=p["quantity"],
                    component_name=p["component_name"],
                    product_sku=p["product_sku"],
                    assembled_qty=p["assembled_qty"],
                )
                for p in part_rows
            ]

            # Get placements for this sheet
            cur.execute(
                """
                SELECT spp.id, spp.sheet_id, spp.component_id, spp.order_id,
                       spp.instance_index, spp.x, spp.y, spp.rotation, spp.source_dxf,
                       cd.name as component_name
                FROM sheet_part_placements spp
                JOIN component_definitions cd ON spp.component_id = cd.id
                WHERE spp.sheet_id = %s
                ORDER BY spp.instance_index
                """,
                (sheet_row["id"],)
            )
            placement_rows = cur.fetchall()
            placements = [
                SheetPartPlacement(
                    id=pl["id"],
                    sheet_id=pl["sheet_id"],
                    component_id=pl["component_id"],
                    order_id=pl["order_id"],
                    instance_index=pl["instance_index"],
                    x=pl["x"],
                    y=pl["y"],
                    rotation=pl["rotation"],
                    source_dxf=pl["source_dxf"],
                    component_name=pl["component_name"],
                )
                for pl in placement_rows
            ]

            # Get order IDs for this sheet
            cur.execute(
                "SELECT order_id FROM nesting_sheet_orders WHERE sheet_id = %s",
                (sheet_row["id"],)
            )
            sheet_order_ids = [r["order_id"] for r in cur.fetchall()]
            all_order_ids.update(sheet_order_ids)

            sheets.append(NestingSheet(
                id=sheet_row["id"],
                job_id=sheet_row["job_id"],
                sheet_number=sheet_row["sheet_number"],
                dxf_filename=sheet_row["dxf_filename"],
                gcode_filename=sheet_row["gcode_filename"],
                status=sheet_row["status"],
                cut_at=sheet_row["cut_at"],
                claimed_by=sheet_row["claimed_by"],
                claimed_at=sheet_row["claimed_at"],
                has_variable_pockets=sheet_row.get("has_variable_pockets", False),
                actual_thickness_inches=sheet_row.get("actual_thickness_inches"),
                parts=parts,
                placements=placements,
                order_ids=sheet_order_ids
            ))

        return NestingJob(
            id=job_row["id"],
            name=job_row["name"],
            status=job_row["status"],
            total_sheets=job_row["total_sheets"],
            completed_sheets=job_row["completed_sheets"],
            created_at=job_row["created_at"],
            created_by=job_row["created_by"],
            prototype=job_row["prototype"],
            sheets=sheets,
            order_ids=sorted(all_order_ids)
        )
