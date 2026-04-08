"""Replenishment system endpoints: forecasting, stock targets, and queue generation."""

import json
import math
import logging
from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_api_key
from ..database import get_db
from ..models import (
    ReplenishmentConfig, ReplenishmentConfigUpdate,
    ComponentForecast, ReplenishmentNeed, ReplenishmentSnapshot,
    ReplenishmentStatus, ProductReplenishmentStatus,
    ReplenishmentQueueResponse,
)

logger = logging.getLogger("nesting-api")

router = APIRouter(prefix="/replenishment", tags=["replenishment"])

# Whitelist of columns allowed in replenishment config updates.
# Must match the fields defined in ReplenishmentConfigUpdate.
REPLENISHMENT_CONFIG_COLUMNS = {
    "minimum_stock",
    "ses_alpha",
    "review_period_days",
    "lead_time_days",
    "service_z",
    "trend_clamp_low",
    "trend_clamp_high",
}


# ==================== Config ====================

@router.get("/config", response_model=ReplenishmentConfig)
def get_config(_: str = Depends(verify_api_key)):
    """Get the current replenishment configuration."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM replenishment_config WHERE id = 1")
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Config row missing")
            return ReplenishmentConfig(**row)


@router.put("/config", response_model=ReplenishmentConfig)
def update_config(
    body: ReplenishmentConfigUpdate,
    _: str = Depends(verify_api_key),
):
    """Update replenishment configuration (partial update)."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    invalid_keys = set(updates.keys()) - REPLENISHMENT_CONFIG_COLUMNS
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"Invalid fields: {invalid_keys}")

    with get_db() as conn:
        with conn.cursor() as cur:
            set_clauses = [f"{k} = %({k})s" for k in updates]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE replenishment_config SET {', '.join(set_clauses)} WHERE id = 1"
            cur.execute(sql, updates)

            cur.execute("SELECT * FROM replenishment_config WHERE id = 1")
            return ReplenishmentConfig(**cur.fetchone())


# ==================== Status ====================

@router.get("/status", response_model=list[ReplenishmentStatus])
def get_status(_: str = Depends(verify_api_key)):
    """Live stock positions for all components (current vs precomputed target vs pipeline)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get all components with inventory, forecast, and precomputed targets
            cur.execute("""
                SELECT
                    cd.id as component_id,
                    cd.name as component_name,
                    cd.dxf_filename,
                    COALESCE(ci.quantity_on_hand, 0) as current_stock,
                    COALESCE(ci.quantity_reserved, 0) as reserved,
                    COALESCE(cf.velocity, 0) as velocity,
                    COALESCE(cf.target_stock, 0) as target_stock,
                FROM component_definitions cd
                LEFT JOIN component_inventory ci ON cd.id = ci.component_id
                LEFT JOIN component_forecast cf ON cd.id = cf.component_id
            """)
            components = cur.fetchall()

            # Determine which components are outsourced-only
            # (every product using them has outsourced=TRUE, or they have no products)
            cur.execute("""
                SELECT pc.component_id
                FROM product_components pc
                JOIN products p ON pc.product_sku = p.sku
                GROUP BY pc.component_id
                HAVING BOOL_AND(p.outsourced) = TRUE
            """)
            outsourced_ids = {r["component_id"] for r in cur.fetchall()}

            # Calculate pipeline (parts in pending/cutting sheets)
            cur.execute("""
                SELECT sp.component_id, COALESCE(SUM(sp.quantity), 0) as pipeline
                FROM sheet_parts sp
                JOIN nesting_sheets ns ON sp.sheet_id = ns.id
                JOIN nesting_jobs nj ON ns.job_id = nj.id
                WHERE ns.status IN ('pending', 'cutting')
                  AND nj.prototype = FALSE
                GROUP BY sp.component_id
            """)
            pipeline_map = {r["component_id"]: r["pipeline"] for r in cur.fetchall()}

            results = []
            for comp in components:
                cid = comp["component_id"]
                pipeline = pipeline_map.get(cid, 0)
                effective = comp["current_stock"] - comp["reserved"] + pipeline
                target = comp["target_stock"]
                status = "below_target" if effective < target else "adequate"

                results.append(ReplenishmentStatus(
                    component_id=cid,
                    component_name=comp["component_name"],
                    dxf_filename=comp["dxf_filename"],
                    current_stock=comp["current_stock"],
                    reserved=comp["reserved"],
                    pipeline=pipeline,
                    effective_stock=effective,
                    target_stock=target,
                    velocity=comp["velocity"],
                    outsourced=cid in outsourced_ids,
                    status=status,
                ))

            return results


# ==================== Product Status ====================

@router.get("/product-status", response_model=list[ProductReplenishmentStatus])
def get_product_status(_: str = Depends(verify_api_key)):
    """Live stock positions for all non-outsourced products."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM replenishment_config LIMIT 1")
            cfg = cur.fetchone()
            min_stock = cfg["minimum_stock"]

            cur.execute("""
                SELECT
                    p.sku as product_sku,
                    p.name as product_name,
                    COALESCE(pi.quantity_on_hand, 0) as current_stock,
                    COALESCE(pi.quantity_reserved, 0) as reserved,
                    COALESCE(pf.velocity, 0) as velocity,
                    COALESCE(pf.target_units, 0) as target_stock
                FROM products p
                LEFT JOIN product_inventory pi ON p.sku = pi.product_sku
                LEFT JOIN product_forecast pf ON p.sku = pf.product_sku
                WHERE p.outsourced = FALSE
            """)
            products = cur.fetchall()

            # Build bundle derived stock from source product inventory
            cur.execute("""
                SELECT pu.bundle_sku, pu.source_product_sku,
                       COALESCE(pi.quantity_on_hand, 0) as source_stock
                FROM product_units pu
                LEFT JOIN product_inventory pi ON pu.source_product_sku = pi.product_sku
            """)
            bundle_unit_rows = cur.fetchall()

            bundle_sources_raw = {}
            for row in bundle_unit_rows:
                bsku = row["bundle_sku"]
                ssku = row["source_product_sku"]
                if bsku not in bundle_sources_raw:
                    bundle_sources_raw[bsku] = {}
                if ssku not in bundle_sources_raw[bsku]:
                    bundle_sources_raw[bsku][ssku] = {"count": 0, "stock": row["source_stock"]}
                bundle_sources_raw[bsku][ssku]["count"] += 1

            bundle_derived_stock = {}
            for bsku, sources in bundle_sources_raw.items():
                if not sources:
                    bundle_derived_stock[bsku] = 0
                else:
                    bundle_derived_stock[bsku] = min(
                        s["stock"] // s["count"] for s in sources.values()
                    )

            bundle_skus = set(bundle_sources_raw.keys())

            results = []
            for prod in products:
                sku = prod["product_sku"]
                velocity = prod["velocity"]
                is_bundle = sku in bundle_skus

                if is_bundle:
                    current = bundle_derived_stock.get(sku, 0)
                    reserved = 0
                else:
                    current = prod["current_stock"]
                    reserved = prod["reserved"]

                target = max(prod["target_stock"], min_stock)
                deficit = max(0, target - current)
                status = "below_target" if current < target else "adequate"

                results.append(ProductReplenishmentStatus(
                    product_sku=sku,
                    product_name=prod["product_name"],
                    current_stock=current,
                    reserved=reserved,
                    target_stock=target,
                    velocity=velocity,
                    deficit=deficit,
                    status=status,
                    is_derived=is_bundle,
                ))

            return results


# ==================== Queue ====================

@router.get("/queue", response_model=ReplenishmentQueueResponse)
def get_queue(_: str = Depends(verify_api_key)):
    """Get the latest replenishment snapshot: mandatory parts + scored fill candidates."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Get latest snapshot
            cur.execute("""
                SELECT id, calculated_at, total_mandatory, total_fill
                FROM replenishment_snapshots
                ORDER BY calculated_at DESC
                LIMIT 1
            """)
            snapshot_row = cur.fetchone()
            if not snapshot_row:
                return ReplenishmentQueueResponse()

            snapshot_id = snapshot_row["id"]

            # Get needs with component info
            cur.execute("""
                SELECT rn.component_id, rn.velocity, rn.current_stock, rn.reserved,
                       rn.pipeline, rn.effective_stock, rn.target_stock, rn.deficit,
                       cd.name as component_name, cd.dxf_filename
                FROM replenishment_needs rn
                JOIN component_definitions cd ON rn.component_id = cd.id
                WHERE rn.snapshot_id = %s
                ORDER BY rn.deficit DESC
            """, (snapshot_id,))
            need_rows = cur.fetchall()

            needs = [ReplenishmentNeed(**row) for row in need_rows]

            return ReplenishmentQueueResponse(
                snapshot_id=snapshot_id,
                calculated_at=snapshot_row["calculated_at"],
                mandatory=needs,
                fill_candidates=[],
            )


# ==================== Recalculate ====================

@router.post("/recalculate", response_model=ReplenishmentSnapshot)
def recalculate(_: str = Depends(verify_api_key)):
    """Run full forecast update + replenishment calculation (7-step algorithm)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Load config
            cur.execute("SELECT * FROM replenishment_config WHERE id = 1")
            cfg = cur.fetchone()
            alpha = cfg["ses_alpha"]

            # ========== Step 1: Materialize product demand ==========
            _materialize_product_demand(cur)

            # ========== Step 2: SES forecast (products) ==========
            _update_product_forecasts(cur, alpha)

            # ========== Step 3: Calculate needs (7-day target) ==========
            needs = _calculate_needs(cur, cfg)

            # Save snapshot and return
            return _save_snapshot(cur, cfg, needs)


# ==================== Forecasts ====================

@router.get("/forecasts", response_model=list[ComponentForecast])
def get_forecasts(_: str = Depends(verify_api_key)):
    """Get all component forecasts."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cf.*, cd.name as component_name
                FROM component_forecast cf
                JOIN component_definitions cd ON cf.component_id = cd.id
                ORDER BY cf.velocity DESC
            """)
            return [ComponentForecast(**r) for r in cur.fetchall()]


# ==================== Helper Functions ====================

def _materialize_product_demand(cur):
    """Step 1b: Aggregate Shopify orders into daily product demand."""
    cur.execute("DELETE FROM product_daily_demand WHERE demand_date < CURRENT_DATE - INTERVAL '90 days'")

    cur.execute("""
        INSERT INTO product_daily_demand (product_sku, demand_date, quantity)
        SELECT
            p.sku,
            so.created_at::date as demand_date,
            SUM(soi.quantity) as quantity
        FROM shopify_order_items soi
        JOIN shopify_orders so ON soi.order_id = so.id
        JOIN products p ON soi.sku = p.sku OR soi.local_product_sku = p.sku
        WHERE so.created_at >= CURRENT_DATE - INTERVAL '90 days'
          AND so.financial_status IN ('paid', 'partially_refunded')
          AND so.cancelled_at IS NULL
        GROUP BY p.sku, so.created_at::date
        ON CONFLICT (product_sku, demand_date)
        DO UPDATE SET quantity = EXCLUDED.quantity
    """)


def _ses_forecast(history, alpha):
    """Run SES algorithm on demand history. Returns (velocity, forecast, std_dev)."""
    data_points = len(history)
    if data_points == 0:
        return 0, 0, 0
    if data_points < 14:
        avg = sum(r["quantity"] for r in history) / data_points
        return avg, avg, 0
    forecast = history[0]["quantity"]
    errors_sq = []
    for row in history[1:]:
        actual = row["quantity"]
        errors_sq.append((actual - forecast) ** 2)
        forecast = alpha * actual + (1 - alpha) * forecast
    std_dev = math.sqrt(sum(errors_sq) / len(errors_sq)) if errors_sq else 0
    return forecast, forecast, std_dev


def _update_ses_forecasts(cur, alpha, id_col, demand_table, forecast_table, id_query):
    """Generic SES forecast update for components or products."""
    cur.execute(id_query)
    all_ids = [r[list(r.keys())[0]] for r in cur.fetchall()]

    for entity_id in all_ids:
        cur.execute(f"""
            SELECT demand_date, quantity
            FROM {demand_table}
            WHERE {id_col} = %s
            ORDER BY demand_date ASC
        """, (entity_id,))
        history = cur.fetchall()

        velocity, forecast, std_dev = _ses_forecast(history, alpha)

        cur.execute(f"""
            SELECT COALESCE(AVG(quantity), 0) as avg_q
            FROM {demand_table}
            WHERE {id_col} = %s AND demand_date >= CURRENT_DATE - INTERVAL '7 days'
        """, (entity_id,))
        trailing_7d = cur.fetchone()["avg_q"]

        cur.execute(f"""
            SELECT COALESCE(AVG(quantity), 0) as avg_q
            FROM {demand_table}
            WHERE {id_col} = %s AND demand_date >= CURRENT_DATE - INTERVAL '30 days'
        """, (entity_id,))
        trailing_30d = cur.fetchone()["avg_q"]

        trend_ratio = (trailing_7d / trailing_30d) if trailing_30d > 0 else 1.0

        cur.execute(f"""
            INSERT INTO {forecast_table}
            ({id_col}, velocity, forecast, std_dev, trailing_7d, trailing_30d,
             trend_ratio, data_points, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT ({id_col})
            DO UPDATE SET
                velocity = EXCLUDED.velocity,
                forecast = EXCLUDED.forecast,
                std_dev = EXCLUDED.std_dev,
                trailing_7d = EXCLUDED.trailing_7d,
                trailing_30d = EXCLUDED.trailing_30d,
                trend_ratio = EXCLUDED.trend_ratio,
                data_points = EXCLUDED.data_points,
                updated_at = CURRENT_TIMESTAMP
        """, (entity_id, velocity, forecast, std_dev, trailing_7d, trailing_30d,
              trend_ratio, len(history)))


def _update_product_forecasts(cur, alpha):
    """Step 2b: SES forecast for each product."""
    _update_ses_forecasts(
        cur, alpha, "product_sku", "product_daily_demand",
        "product_forecast", "SELECT sku FROM products WHERE outsourced = FALSE",
    )


def _calculate_needs(cur, cfg):
    """Calculate replenishment needs using Periodic Review (R,S) Order-Up-To policy.

    S = d_adj × (R + L) + z × σ × √(R + L)
        expected demand     safety buffer
        over protection     (scales with demand
        interval            variability)

    Phase A: Compute product order-up-to levels from forecast data.
    Phase B: Derive component targets by summing across BOM.
    Phase C: Evaluate per-component needs vs effective stock.
    """
    min_stock = cfg["minimum_stock"]
    R = cfg.get("review_period_days", 7)       # review period (days)
    L = cfg.get("lead_time_days", 4)           # production lead time (days)
    z = cfg.get("service_z", 1.65)             # service level Z-score
    clamp_lo = cfg.get("trend_clamp_low", 0.85)
    clamp_hi = cfg.get("trend_clamp_high", 1.25)
    P = R + L  # protection interval

    # ===== Phase A: Product targets (Order-Up-To level) =====
    cur.execute("""
        SELECT product_sku, velocity, std_dev, trend_ratio
        FROM product_forecast
    """)
    product_forecasts = cur.fetchall()

    product_targets = {}  # sku → target_units
    for pf in product_forecasts:
        velocity = pf["velocity"]
        sigma = pf.get("std_dev", 0) or 0
        trend = max(clamp_lo, min(clamp_hi, pf.get("trend_ratio", 1.0) or 1.0))

        # Trend-adjusted daily demand
        d_adj = velocity * trend

        # Order-Up-To level: expected demand + safety buffer
        target_units = math.ceil(d_adj * P + z * sigma * math.sqrt(P))
        target_units = max(target_units, min_stock)

        product_targets[pf["product_sku"]] = target_units

        cur.execute("""
            UPDATE product_forecast
            SET target_units = %s
            WHERE product_sku = %s
        """, (target_units, pf["product_sku"]))

    # Roll bundle targets into source product targets so that source products
    # account for all demand (direct + bundle-derived). This prevents the
    # shared-resource problem where both show no deficit independently but
    # combined demand exceeds supply.
    cur.execute("""
        SELECT bundle_sku, source_product_sku
        FROM product_units
        ORDER BY bundle_sku, unit_index
    """)
    bundle_unit_rows = cur.fetchall()

    bundle_skus = set()
    for row in bundle_unit_rows:
        bsku = row["bundle_sku"]
        ssku = row["source_product_sku"]
        bundle_skus.add(bsku)

        bt = product_targets.get(bsku)
        if bt is None:
            continue

        # Add bundle's target to source product's target
        if ssku in product_targets:
            product_targets[ssku] += bt
        else:
            product_targets[ssku] = bt

    # Persist updated source product targets (after bundle rollup)
    for sku in product_targets:
        if sku not in bundle_skus:
            cur.execute("""
                UPDATE product_forecast
                SET target_units = %s
                WHERE product_sku = %s
            """, (product_targets[sku], sku))

    # ===== Phase B: Component targets via BOM =====
    # Include both direct product → component links AND
    # bundle → source product → component links
    cur.execute("""
        SELECT component_id, product_sku, quantity
        FROM (
            -- Direct: product uses component
            SELECT pc.component_id, pc.product_sku, pc.quantity
            FROM product_components pc

            UNION ALL

            -- Bundles: bundle target flows to source products' components
            SELECT pc.component_id, pu.bundle_sku as product_sku, pc.quantity
            FROM product_units pu
            JOIN product_components pc ON pu.source_product_sku = pc.product_sku
        ) combined
    """)
    bom_rows = cur.fetchall()

    component_target_map = {}   # component_id → target
    component_min_map = {}      # component_id → BOM-derived minimum
    component_velocity_map = {} # component_id → velocity (derived from products)

    # Also build product velocity map for deriving component velocity
    product_velocity_map = {pf["product_sku"]: pf["velocity"] for pf in product_forecasts}

    for bom in bom_rows:
        cid = bom["component_id"]
        sku = bom["product_sku"]
        bom_qty = bom["quantity"]

        # Accumulate BOM-derived minimum: product minimum × bom quantity
        component_min_map[cid] = component_min_map.get(cid, 0) + min_stock * bom_qty

        # Accumulate component velocity from product velocities × BOM
        pv = product_velocity_map.get(sku, 0)
        component_velocity_map[cid] = component_velocity_map.get(cid, 0) + pv * bom_qty

        pt = product_targets.get(sku)
        if pt is None:
            continue

        component_target_map[cid] = component_target_map.get(cid, 0) + pt * bom_qty

    # Enforce BOM-derived minimum floor and persist to component_forecast
    cur.execute("SELECT id FROM component_definitions")
    all_component_ids = [r["id"] for r in cur.fetchall()]

    for cid in all_component_ids:
        comp_min = component_min_map.get(cid, min_stock)
        target = max(component_target_map.get(cid, 0), comp_min)
        velocity = component_velocity_map.get(cid, 0)

        cur.execute("""
            UPDATE component_forecast
            SET target_stock = %s, velocity = %s
            WHERE component_id = %s
        """, (target, velocity, cid))

    # ===== Phase C: Evaluate needs =====
    cur.execute("""
        SELECT
            cd.id as component_id,
            COALESCE(ci.quantity_on_hand, 0) as current_stock,
            COALESCE(ci.quantity_reserved, 0) as reserved,
            COALESCE(cf.velocity, 0) as velocity,
            COALESCE(cf.target_stock, 0) as target_stock
        FROM component_definitions cd
        LEFT JOIN component_inventory ci ON cd.id = ci.component_id
        LEFT JOIN component_forecast cf ON cd.id = cf.component_id
    """)
    components = cur.fetchall()

    # Pipeline counts
    cur.execute("""
        SELECT sp.component_id, COALESCE(SUM(sp.quantity), 0) as pipeline
        FROM sheet_parts sp
        JOIN nesting_sheets ns ON sp.sheet_id = ns.id
        JOIN nesting_jobs nj ON ns.job_id = nj.id
        WHERE ns.status IN ('pending', 'cutting')
          AND nj.prototype = FALSE
        GROUP BY sp.component_id
    """)
    pipeline_map = {r["component_id"]: r["pipeline"] for r in cur.fetchall()}

    needs = []
    for comp in components:
        cid = comp["component_id"]
        target = comp["target_stock"]

        pipeline = pipeline_map.get(cid, 0)
        effective = comp["current_stock"] - comp["reserved"] + pipeline

        deficit = target - effective
        if deficit <= 0:
            continue

        needs.append({
            "component_id": cid,
            "velocity": comp["velocity"],
            "current_stock": comp["current_stock"],
            "reserved": comp["reserved"],
            "pipeline": pipeline,
            "effective_stock": effective,
            "target_stock": target,
            "deficit": deficit,
        })

    return needs


def _save_snapshot(cur, cfg, needs):
    """Save a replenishment snapshot and return the ReplenishmentSnapshot model."""
    config_snapshot = {k: v for k, v in cfg.items() if k != "id"}

    cur.execute("""
        INSERT INTO replenishment_snapshots
        (calculated_at, config_snapshot, total_mandatory, total_fill)
        VALUES (CURRENT_TIMESTAMP, %s, %s, 0)
        RETURNING id, calculated_at
    """, (json.dumps(config_snapshot, default=str), len(needs)))
    snap_row = cur.fetchone()
    snapshot_id = snap_row["id"]

    for need in needs:
        cur.execute("""
            INSERT INTO replenishment_needs
            (snapshot_id, component_id, velocity,
             current_stock, reserved, pipeline, effective_stock,
             target_stock, deficit, is_mandatory)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        """, (
            snapshot_id,
            need["component_id"], need["velocity"],
            need["current_stock"], need["reserved"],
            need["pipeline"], need["effective_stock"], need["target_stock"],
            need["deficit"],
        ))

    # Load snapshot for response
    cur.execute("""
        SELECT rn.component_id, rn.velocity, rn.current_stock, rn.reserved,
               rn.pipeline, rn.effective_stock, rn.target_stock, rn.deficit,
               cd.name as component_name, cd.dxf_filename
        FROM replenishment_needs rn
        JOIN component_definitions cd ON rn.component_id = cd.id
        WHERE rn.snapshot_id = %s
        ORDER BY rn.deficit DESC
    """, (snapshot_id,))
    need_models = [ReplenishmentNeed(**r) for r in cur.fetchall()]

    return ReplenishmentSnapshot(
        id=snapshot_id,
        calculated_at=snap_row["calculated_at"],
        total_mandatory=len(needs),
        total_fill=0,
        needs=need_models,
    )


def run_forecast_update():
    """Run demand materialization + SES forecast for products. Called by scheduler."""
    logger.info("Running scheduled forecast update...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ses_alpha FROM replenishment_config WHERE id = 1")
            row = cur.fetchone()
            alpha = row["ses_alpha"] if row else 0.3

            _materialize_product_demand(cur)
            _update_product_forecasts(cur, alpha)
    logger.info("Forecast update complete.")


def run_full_recalculation():
    """Run full pipeline: demand + forecast + needs + snapshot. Called by the 4AM scheduler job."""
    logger.info("Running full recalculation...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM replenishment_config WHERE id = 1")
            cfg = cur.fetchone()
            alpha = cfg["ses_alpha"]

            _materialize_product_demand(cur)
            _update_product_forecasts(cur, alpha)
            needs = _calculate_needs(cur, cfg)
            _save_snapshot(cur, cfg, needs)
    logger.info("Full recalculation complete.")
