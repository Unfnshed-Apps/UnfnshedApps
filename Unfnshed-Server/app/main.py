"""
Nesting API - FastAPI server for the CNC Nesting Application.

Provides REST API endpoints for managing products, components, and Shopify orders.
"""

import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import components, products, files, inventory, nesting_jobs, sheet_operations, pallets, mating_pairs, replenishment, bundles, admin
from .scheduler import lifespan

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nesting-api")

app = FastAPI(
    title="Nesting API",
    description="API for CNC Nesting Application with Shopify integration",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - origins configurable via CORS_ORIGINS env var (comma-separated)
settings = get_settings()
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming requests with device info."""
    device_name = request.headers.get("X-Device-Name", "unknown")
    client_ip = request.client.host if request.client else "unknown"

    # Skip logging health checks to reduce noise
    if request.url.path not in ["/health", "/"]:
        logger.info(f"[{device_name}] {request.method} {request.url.path} from {client_ip}")

    response = await call_next(request)
    return response

# Include routers
app.include_router(components.router)
app.include_router(products.router)
app.include_router(files.router)
app.include_router(inventory.router)
# sheet_operations MUST be registered before nesting_jobs so that
# /nesting-jobs/claimed-sheets matches before /{job_id} catches it
app.include_router(sheet_operations.router)
app.include_router(nesting_jobs.router)
app.include_router(pallets.router)
app.include_router(mating_pairs.router)
app.include_router(replenishment.router)
app.include_router(bundles.router)
app.include_router(admin.router)


@app.get("/")
def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "Nesting API"}


@app.get("/health")
def health():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)
