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
    "target_days_a", "target_days_b",
    "reorder_days_a", "reorder_days_b",
    "minimum_stock", "tolerance_ceiling",
    "ses_alpha",
    "trend_clamp_low", "trend_clamp_high",
    "fill_weight_urgency", "fill_weight_velocity",
    "fill_weight_geometric", "fill_weight_value",
    "max_fill_types_per_sheet",
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
                    COALESCE(cf.abc_class, 'C') as abc_class,
                    COALESCE(cf.target_stock, 0) as target_stock,
                    COALESCE(cf.reorder_point, 0) as reorder_point
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
                    reorder_point=0,
                    abc_class="C",
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
                    reorder_point=0,
                    abc_class="C",
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
                SELECT rn.*, cd.name as component_name, cd.dxf_filename
                FROM replenishment_needs rn
                JOIN component_definitions cd ON rn.component_id = cd.id
                WHERE rn.snapshot_id = %s
                ORDER BY rn.is_mandatory DESC, rn.fill_score DESC NULLS LAST
            """, (snapshot_id,))
            need_rows = cur.fetchall()

            mandatory = []
            fill_candidates = []
            for row in need_rows:
                need = ReplenishmentNeed(**row)
                if row["is_mandatory"]:
                    mandatory.append(need)
                else:
                    fill_candidates.append(need)

            return ReplenishmentQueueResponse(
                snapshot_id=snapshot_id,
                calculated_at=snapshot_row["calculated_at"],
                mandatory=mandatory,
                fill_candidates=fill_candidates,
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
                ORDER BY cf.abc_class ASC, cf.velocity DESC
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


def _update_abc_classification(cur):
    """Step 3: ABC classification at product level, derived to components."""
    # --- Product-level ABC ---
    cur.execute("""
        SELECT product_sku, COALESCE(SUM(quantity), 0) as volume
        FROM product_daily_demand
        WHERE demand_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY product_sku
        ORDER BY volume DESC
    """)
    ranked_products = cur.fetchall()

    total = len(ranked_products)
    if total > 0:
        for i, row in enumerate(ranked_products):
            pct = (i + 1) / total
            if pct <= 0.20:
                abc = "A"
            elif pct <= 0.50:
                abc = "B"
            else:
                abc = "C"

            cur.execute("""
                UPDATE product_forecast
                SET abc_class = %s
                WHERE product_sku = %s
            """, (abc, row["product_sku"]))

    # Products with no demand get class C
    cur.execute("""
        UPDATE product_forecast
        SET abc_class = 'C'
        WHERE product_sku NOT IN (
            SELECT DISTINCT product_sku FROM product_daily_demand
            WHERE demand_date >= CURRENT_DATE - INTERVAL '30 days'
        )
    """)

    # --- Derive component ABC from product ABC ---
    # Each component inherits the highest class (MIN since A < B < C) of any product
    # using it, including products referenced as units in bundles.
    cur.execute("""
        SELECT component_id, MIN(abc_class) as best_abc
        FROM (
            -- Direct: product uses component via BOM
            SELECT pc.component_id, pf.abc_class
            FROM product_components pc
            JOIN product_forecast pf ON pc.product_sku = pf.product_sku

            UNION ALL

            -- Bundles: bundle's ABC flows to source products' components
            SELECT pc.component_id, pf.abc_class
            FROM product_units pu
            JOIN product_forecast pf ON pu.bundle_sku = pf.product_sku
            JOIN product_components pc ON pu.source_product_sku = pc.product_sku
        ) combined
        GROUP BY component_id
    """)
    component_abc = cur.fetchall()

    for row in component_abc:
        cur.execute("""
            UPDATE component_forecast
            SET abc_class = %s
            WHERE component_id = %s
        """, (row["best_abc"], row["component_id"]))

    # Components not linked to any product get class C
    cur.execute("""
        UPDATE component_forecast
        SET abc_class = 'C'
        WHERE component_id NOT IN (
            SELECT DISTINCT component_id FROM product_components
        )
    """)


def _calculate_needs(cur, cfg):
    """Calculate replenishment needs using flat 7-day inventory targets.

    Phase A: Compute product targets from velocity × 7 days.
    Phase B: Derive component targets by summing across BOM.
    Phase C: Evaluate per-component needs vs effective stock.
    """
    min_stock = cfg["minimum_stock"]
    target_days = 7

    # ===== Phase A: Product targets =====
    cur.execute("""
        SELECT product_sku, velocity, trend_ratio
        FROM product_forecast
    """)
    product_forecasts = cur.fetchall()

    product_targets = {}  # sku → target_units
    for pf in product_forecasts:
        velocity = pf["velocity"]
        target_units = math.ceil(velocity * target_days)
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
            "abc_class": "C",
            "velocity": comp["velocity"],
            "trend_ratio": 1.0,
            "current_stock": comp["current_stock"],
            "reserved": comp["reserved"],
            "pipeline": pipeline,
            "effective_stock": effective,
            "target_stock": target,
            "reorder_point": 0,
            "tolerance_ceiling": target,
            "deficit": deficit,
            "is_mandatory": True,
        })

    return needs


def _score_fill_candidates(needs, cfg):
    """Step 5: Score fill candidates with weighted formula."""
    fill_candidates = [n for n in needs if not n["is_mandatory"]]
    if not fill_candidates:
        return

    max_velocity = max((n["velocity"] for n in fill_candidates), default=1) or 1
    max_deficit = max((n["deficit"] for n in fill_candidates), default=1) or 1

    w_urgency = cfg["fill_weight_urgency"]
    w_velocity = cfg["fill_weight_velocity"]
    w_geometric = cfg["fill_weight_geometric"]
    w_value = cfg["fill_weight_value"]

    for n in fill_candidates:
        if n["target_stock"] > 0:
            urgency = 1.0 - (n["effective_stock"] / n["target_stock"])
            urgency = max(0, min(1, urgency))
        else:
            urgency = 0

        velocity_score = n["velocity"] / max_velocity if max_velocity > 0 else 0
        geometric_score = 0.5
        value_score = n["deficit"] / max_deficit if max_deficit > 0 else 0

        score = (
            w_urgency * urgency
            + w_velocity * velocity_score
            + w_geometric * geometric_score
            + w_value * value_score
        )

        n["fill_score"] = round(score, 4)
        n["fill_score_urgency"] = round(urgency, 4)
        n["fill_score_velocity"] = round(velocity_score, 4)
        n["fill_score_geometric"] = round(geometric_score, 4)
        n["fill_score_value"] = round(value_score, 4)


def _save_snapshot(cur, cfg, needs):
    """Save a replenishment snapshot and return the ReplenishmentSnapshot model."""
    mandatory_count = sum(1 for n in needs if n["is_mandatory"])
    fill_count = len(needs) - mandatory_count

    config_snapshot = {k: v for k, v in cfg.items() if k != "id"}

    cur.execute("""
        INSERT INTO replenishment_snapshots
        (calculated_at, config_snapshot, total_mandatory, total_fill)
        VALUES (CURRENT_TIMESTAMP, %s, %s, %s)
        RETURNING id, calculated_at
    """, (json.dumps(config_snapshot, default=str), mandatory_count, fill_count))
    snap_row = cur.fetchone()
    snapshot_id = snap_row["id"]

    for need in needs:
        cur.execute("""
            INSERT INTO replenishment_needs
            (snapshot_id, component_id, abc_class, velocity, trend_ratio,
             current_stock, reserved, pipeline, effective_stock,
             target_stock, reorder_point, tolerance_ceiling, deficit,
             is_mandatory, fill_score,
             fill_score_urgency, fill_score_velocity,
             fill_score_geometric, fill_score_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            snapshot_id,
            need["component_id"], need["abc_class"], need["velocity"],
            need["trend_ratio"], need["current_stock"], need["reserved"],
            need["pipeline"], need["effective_stock"], need["target_stock"],
            need["reorder_point"], need["tolerance_ceiling"], need["deficit"],
            need["is_mandatory"], need.get("fill_score"),
            need.get("fill_score_urgency"), need.get("fill_score_velocity"),
            need.get("fill_score_geometric"), need.get("fill_score_value"),
        ))

    # Load full snapshot for response
    cur.execute("""
        SELECT rn.*, cd.name as component_name, cd.dxf_filename
        FROM replenishment_needs rn
        JOIN component_definitions cd ON rn.component_id = cd.id
        WHERE rn.snapshot_id = %s
        ORDER BY rn.is_mandatory DESC, rn.fill_score DESC NULLS LAST
    """, (snapshot_id,))
    need_models = [ReplenishmentNeed(**r) for r in cur.fetchall()]

    return ReplenishmentSnapshot(
        id=snapshot_id,
        calculated_at=snap_row["calculated_at"],
        total_mandatory=mandatory_count,
        total_fill=fill_count,
        needs=need_models,
    )


def run_forecast_update():
    """Run demand materialization + SES + trend for both components and products. Called by scheduler."""
    logger.info("Running scheduled forecast update...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ses_alpha FROM replenishment_config WHERE id = 1")
            row = cur.fetchone()
            alpha = row["ses_alpha"] if row else 0.3

            _materialize_demand(cur)
            _materialize_product_demand(cur)
            _update_forecasts(cur, alpha)
            _update_product_forecasts(cur, alpha)
    logger.info("Forecast update complete.")


def run_full_recalculation():
    """Run all 7 pipeline steps + save snapshot. Called by the 4AM scheduler job."""
    logger.info("Running full recalculation...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM replenishment_config WHERE id = 1")
            cfg = cur.fetchone()
            alpha = cfg["ses_alpha"]

            _materialize_demand(cur)
            _materialize_product_demand(cur)
            _update_forecasts(cur, alpha)
            _update_product_forecasts(cur, alpha)
            _update_abc_classification(cur)
            needs = _calculate_needs(cur, cfg)
            _score_fill_candidates(needs, cfg)
            _save_snapshot(cur, cfg, needs)
    logger.info("Full recalculation complete.")


def run_abc_reclassification():
    """Run ABC reclassification. Called by scheduler."""
    logger.info("Running scheduled ABC reclassification...")
    with get_db() as conn:
        with conn.cursor() as cur:
            _update_abc_classification(cur)
    logger.info("ABC reclassification complete.")
