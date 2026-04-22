# Unfnshed Server

FastAPI backend for Unfnshed applications. Provides a REST API for managing products, components, orders, and more.

## Architecture

```
Server Machine (Mac Mini)
├── PostgreSQL Database (localhost:5432)
├── FastAPI Server (localhost:8000)
│   └── Cloudflare Tunnel → unfnshedapi.gradschoolalternative.com
├── Admin App (PySide6 GUI)
│   ├── Shopify credentials management
│   ├── Auto-sync configuration
│   └── Orders viewer
└── Background Scheduler (APScheduler)

Remote Devices (laptops, etc.)
└── Unfnest App
    ├── View orders (read-only from server)
    └── Select orders for nesting
```

## Setup

The server runs on a dedicated Mac and is accessible via:
- **Local**: `http://127.0.0.1:8000` or `http://192.168.0.242:8000`
- **Remote**: `https://unfnshedapi.gradschoolalternative.com`

## Database

- **Database**: `unfnshed_db`
- **User**: `unfnshed_user`
- **Schemas**: `nesting`, `inventory`, `timekeeping`, `files`

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
DATABASE_URL=postgresql://unfnshed_user:PASSWORD@localhost:5432/unfnshed_db
API_KEYS=your-api-key-here
HOST=0.0.0.0
PORT=8000
```

## Running

```bash
# Development
./venv/bin/uvicorn app.main:app --reload

# Production (via launchd)
# Configured in ~/Library/LaunchAgents/com.nesting.api.plist
```

## API Endpoints

- `GET /health` - Health check
- `GET/POST/PUT/DELETE /components` - Component definitions
- `GET/POST/PUT/DELETE /products` - Products with components
- `GET/POST/PATCH/DELETE /orders` - Shopify orders
- `GET/PUT/DELETE /settings/shopify` - Shopify settings

---

## Admin App

The Admin App is a GUI for managing Shopify integration directly on the server. It provides:

- **Shopify Settings Tab**: Configure store URL, Client ID, Client Secret, API version
- **Sync Control Tab**: Enable auto-sync, set interval, trigger manual sync
- **Orders Tab**: View synced orders with filters

### Installation

```bash
cd ~/Unfnshed-Server

# Install dependencies (first time only)
pip install -r requirements.txt

# Enable auto-start and launch
./install_admin.sh
```

### Usage

| Action | How |
|--------|-----|
| Launch manually | Double-click `UnfnshedAdmin.app` |
| Add to Dock | Drag `UnfnshedAdmin.app` to Dock |
| Hide window | Click the X button (app keeps running) |
| Restore window | Click the Dock icon |
| Quit completely | File > Quit (Cmd+Q) |

### Auto-Start Behavior

After running `install_admin.sh`:
- Starts automatically on login
- Restarts automatically if it crashes
- Closing the window hides it (doesn't quit)

### Disable Auto-Start

```bash
./uninstall_admin.sh
```

Or manually:
```bash
launchctl unload ~/Library/LaunchAgents/com.unfnshed.server-admin.plist
```

### Re-enable Auto-Start

```bash
launchctl load ~/Library/LaunchAgents/com.unfnshed.server-admin.plist
```

### Log Files

- `admin/admin.log` - App activity log
- `admin/admin-stdout.log` - Standard output
- `admin/admin-stderr.log` - Error output
