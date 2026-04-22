# Unfnshed Monorepo

CNC nesting, machine operation, and inventory management suite.

## Architecture

Five apps + shared library, all PySide6 QML clients talking to one FastAPI server:

```
shared/              Base classes used by all client apps
Unfnest/             Nesting optimizer — lays out parts on sheets
UnfnCNC/             CNC machine operator — claims sheets, generates G-code, cuts
Unfnventory/         Inventory manager — stock levels, replenishment settings
Unfnshed-Admin/      Server dashboard — Shopify sync, order viewer, settings
Unfnshed-Server/     FastAPI REST API + PostgreSQL (runs on dedicated Mac Mini)
```

## App Structure (all client apps follow this)

```
AppName/
  src/               Core logic (config, api_client, app-specific modules)
  bridge/            PySide6 controllers exposing Python to QML via signals/slots
  bridge/models/     QAbstractListModel subclasses for QML table views
  qml/               Qt QML UI files (Main.qml, dialogs/, tabs/, components/)
  tests/             Pytest test suite
  main.py            Entry point — creates QApplication, registers controllers, loads QML
  build.py           PyInstaller build (delegates to shared/build_common.py)
  AppName.spec       PyInstaller spec file
```

## Shared Package

`shared/` provides base classes that eliminate duplication across the 4 client apps:
- `config_base.py` — Config loading/saving with per-app config dirs and extensible fields via `CONFIG_SECTIONS` (ClassVar)
- `api_client_base.py` — HTTP client with auto-detection (localhost -> LAN -> remote), env var config via `ENV_PREFIX`
- `app_controller_base.py` — Connection lifecycle, retry timer, setup/test slots for QML
- `connection_worker.py` — Background QThread for health checks
- `dxf_preview_base.py` — QQuickPaintedItem for DXF thumbnail rendering
- `build_common.py` — Shared PyInstaller build script

Each app subclasses these and adds only its domain-specific logic.

## Server

FastAPI at `localhost:8000`, exposed via Cloudflare Tunnel to `unfnshedapi.gradschoolalternative.com`.
- PostgreSQL database (psycopg3, dict_row)
- API key auth via `X-API-Key` header (dev mode: no keys required)
- Background scheduler: replenishment recalculation (daily 4AM) + Shopify sync (configurable interval)
- Routers: components, products, inventory, nesting_jobs, sheet_operations, bundles, mating_pairs, replenishment, files, admin

### Nesting Job Lifecycle
```
create_nesting_job -> sheets status: "pending"
claim_next_sheet   -> "cutting" (FOR UPDATE SKIP LOCKED)
mark_sheet_cut     -> "cut" (increments inventory, checks order/bundle completion)
mark_sheet_failed  -> "failed"
release_sheet      -> back to "pending"
```

## Nesting Engine (Unfnest)

`src/nesting/` — raster-based FFT nesting, three layers:
1. `geometry.py` — RasterEngine: FFT convolution collision detection (numpy + scipy)
2. `placement.py` — BLFPlacer: bottom-left fill with PlacementResult dataclass
3. `optimizer.py` — SimulatedAnnealing: searches over part ordering + rotation
4. `pipeline.py` — `nest_parts()` orchestrator (enrichment -> grouping -> placement -> optimization)

Data models live in `src/nesting_models.py` (PlacedPart, NestedSheet, NestingResult, SheetMetadata).

## Key Patterns

- Controllers exposed as QML context properties (singletons set on engine.rootContext())
- QQuickPaintedItem for DXF preview + sheet preview (class-level shared references)
- `constant=True` on Property is INCOMPATIBLE with `notify=` signal — use one or the other
- QML subdirectories need `qmldir` files + relative path imports
- Models use QAbstractListModel with custom roles (Qt.UserRole + N)
- `RefreshableController` base class handles the worker-thread refresh pattern (Unfnest)

## Build & Run

```bash
# Run any app
cd AppName && python3 main.py

# Build for distribution
cd AppName && python3 build.py --clean

# Run all tests
python3 run_tests.py          # each app runs in its own pytest process
python3 run_tests.py -v       # verbose

# Run one app's tests
python3 -m pytest Unfnest/tests/ -v
```

Use `python3` not `python` — `python` is not on PATH on this macOS system.

**Test isolation:** Do NOT run `pytest .` from the monorepo root. All apps use `from src.config import ...` with different `src` packages — a single pytest process caches the first `src.config` and breaks subsequent apps. Always use `run_tests.py` (spawns a subprocess per app) or run one app at a time.

## Database

- Server: PostgreSQL (schema.sql + migrations/)
- Unfnest local fallback: SQLite via src/database.py (legacy, used when API unavailable)
- Config: `~/Library/Application Support/{AppName}/config.ini` on macOS

## Non-Obvious Decisions

- **Unfnest's app_controller doesn't use AppControllerBase** — it has a unique Database fallback + DXF sync worker that differs from the simpler client pattern
- **UnfnCNC's dxf_loader is different from Unfnest's** — it preserves raw entity data (bulge arcs) for G-code generation, while Unfnest's extracts polygons for nesting
- **The admin app no longer connects to PostgreSQL directly** — all data flows through the FastAPI server's /admin/ endpoints
- **Shopify sync runs server-side** via app/shopify_sync.py, scheduled by app/scheduler.py
