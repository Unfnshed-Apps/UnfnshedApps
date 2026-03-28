# Unfnshed

CNC nesting, machine operation, and inventory management suite.

## Apps

| App | Purpose |
|-----|---------|
| **Unfnest** | 2D nesting optimizer — lays out parts on 4'x8' sheets for CNC cutting |
| **UnfnCNC** | CNC machine operator — claims sheets from the queue, generates G-code, reports damage |
| **Unfnventory** | Inventory manager — component/product stock levels and replenishment |
| **Unfnshed-Admin** | Server dashboard — Shopify order sync, order viewer, system settings |
| **Unfnshed-Server** | FastAPI REST API + PostgreSQL backend |

All client apps are PySide6/QML desktop applications that connect to the server via REST API.

## Quick Start

```bash
# Run an app
cd Unfnest && python3 main.py

# Run tests
python3 run_tests.py

# Build for distribution
cd Unfnest && python3 build.py --clean
```

## Stack

- **Client apps:** Python 3.11+, PySide6, QML
- **Server:** FastAPI, PostgreSQL, psycopg3
- **Nesting engine:** NumPy, SciPy (FFT convolution), Shapely
- **DXF processing:** ezdxf
- **Integrations:** Shopify Admin API (OAuth 2.0)
