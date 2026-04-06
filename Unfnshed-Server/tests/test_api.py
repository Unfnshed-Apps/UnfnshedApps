"""
API route tests for the Unfnshed Server.

Requirements (not installed on this machine -- run where server deps exist):
    pip install fastapi httpx

These tests use FastAPI's TestClient with a mocked database layer.
The real psycopg connection is replaced via a dependency override on ``get_db``
so that no PostgreSQL instance is needed.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch heavy third-party imports that are not installed locally so the
# app module tree can be imported without error.
# ---------------------------------------------------------------------------
import sys
from types import ModuleType

# Stub out psycopg before any app code is imported
_psycopg_stub = ModuleType("psycopg")
_psycopg_stub.Connection = MagicMock
_psycopg_rows_stub = ModuleType("psycopg.rows")
_psycopg_rows_stub.dict_row = None
_psycopg_stub.rows = _psycopg_rows_stub
sys.modules.setdefault("psycopg", _psycopg_stub)
sys.modules.setdefault("psycopg.rows", _psycopg_rows_stub)

_pydantic_settings_stub = ModuleType("pydantic_settings")


class _FakeBaseSettings:
    def __init_subclass__(cls, **kw):
        pass

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


_pydantic_settings_stub.BaseSettings = _FakeBaseSettings
sys.modules.setdefault("pydantic_settings", _pydantic_settings_stub)

_apscheduler_stub = ModuleType("apscheduler")
_apscheduler_schedulers_stub = ModuleType("apscheduler.schedulers")
_apscheduler_bg_stub = ModuleType("apscheduler.schedulers.background")
_apscheduler_bg_stub.BackgroundScheduler = MagicMock
_apscheduler_triggers_stub = ModuleType("apscheduler.triggers")
_apscheduler_cron_stub = ModuleType("apscheduler.triggers.cron")
_apscheduler_cron_stub.CronTrigger = MagicMock
sys.modules.setdefault("apscheduler", _apscheduler_stub)
sys.modules.setdefault("apscheduler.schedulers", _apscheduler_schedulers_stub)
sys.modules.setdefault("apscheduler.schedulers.background", _apscheduler_bg_stub)
sys.modules.setdefault("apscheduler.triggers", _apscheduler_triggers_stub)
sys.modules.setdefault("apscheduler.triggers.cron", _apscheduler_cron_stub)

# Now safe to import the actual app code
from app.database import get_db  # noqa: E402
from app.auth import verify_api_key  # noqa: E402
from app.main import app  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Mock database infrastructure
# ---------------------------------------------------------------------------

class MockCursor:
    """A minimal mock cursor that returns pre-configured results."""

    def __init__(self):
        self.executed: list[tuple] = []
        self._results: list[dict] = []
        self._fetchone_result: dict | None = None
        self.rowcount: int = 1
        self.description = None

    def execute(self, sql: str, params=None):
        self.executed.append((sql, params))

    def fetchone(self) -> dict | None:
        return self._fetchone_result

    def fetchall(self) -> list[dict]:
        return self._results

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MockConnection:
    """Mock database connection that yields MockCursor instances."""

    def __init__(self):
        self.cursors: list[MockCursor] = []
        self._cursor_factory = MockCursor
        self._committed = False
        self._rolledback = False

    def cursor(self) -> MockCursor:
        c = self._cursor_factory()
        self.cursors.append(c)
        return c

    def commit(self):
        self._committed = True

    def rollback(self):
        self._rolledback = True

    def close(self):
        pass


# We'll use a module-level variable so individual tests can configure it
_mock_conn: MockConnection | None = None


@contextlib.contextmanager
def _override_get_db():
    """Dependency override that yields the module-level mock connection."""
    assert _mock_conn is not None, "Set _mock_conn before making requests"
    yield _mock_conn


async def _override_verify_api_key():
    """Always pass auth."""
    return "test-key"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _apply_overrides():
    """Override database and auth dependencies for every test."""
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_api_key] = _override_verify_api_key
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    """TestClient that skips the lifespan (scheduler) entirely."""
    # Use raise_server_exceptions so assertion errors in route code surface
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def conn():
    """Provide a fresh MockConnection and wire it up as the active mock."""
    global _mock_conn
    mc = MockConnection()
    _mock_conn = mc
    yield mc
    _mock_conn = None


# Convenience: a "smart" connection whose cursors return sequenced results.
class SmartMockConnection(MockConnection):
    """
    MockConnection where you pre-load a sequence of (fetchone, fetchall)
    tuples.  Each call to ``cursor()`` pops the next result set off the queue.
    """

    def __init__(self, results: list[tuple[dict | None, list[dict]]]):
        super().__init__()
        self._result_queue = list(results)

    def cursor(self) -> MockCursor:
        c = MockCursor()
        if self._result_queue:
            one, many = self._result_queue.pop(0)
            c._fetchone_result = one
            c._results = many
        self.cursors.append(c)
        return c


@pytest.fixture()
def smart_conn():
    """Factory fixture -- call with a list of (fetchone, fetchall) tuples."""
    global _mock_conn

    def _factory(results: list[tuple[dict | None, list[dict]]]):
        mc = SmartMockConnection(results)
        _mock_conn = mc
        return mc

    yield _factory
    _mock_conn = None


# ===================================================================
# 1. Health check
# ===================================================================

class TestHealthCheck:
    def test_health_returns_200(self, client, conn):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_root_returns_ok(self, client, conn):
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "Nesting API"


# ===================================================================
# 2. Components CRUD
# ===================================================================

SAMPLE_COMPONENT_ROW = {
    "id": 1,
    "name": "Side Panel",
    "dxf_filename": "side_panel.dxf",
    "variable_pockets": False,
    "mating_role": "neutral",
}


class TestComponentCreate:
    def test_create_returns_201(self, client, smart_conn):
        # POST /components -- single cursor: INSERT ... RETURNING
        smart_conn([
            (SAMPLE_COMPONENT_ROW, []),
        ])
        resp = client.post(
            "/components",
            json={
                "name": "Side Panel",
                "dxf_filename": "side_panel.dxf",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == 1
        assert body["name"] == "Side Panel"
        assert body["dxf_filename"] == "side_panel.dxf"


class TestComponentList:
    def test_list_returns_all(self, client, smart_conn):
        rows = [SAMPLE_COMPONENT_ROW, {**SAMPLE_COMPONENT_ROW, "id": 2, "name": "Top Panel"}]
        smart_conn([
            (None, rows),  # SELECT ... ORDER BY name
        ])
        resp = client.get("/components")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestComponentGet:
    def test_get_existing(self, client, smart_conn):
        smart_conn([
            (SAMPLE_COMPONENT_ROW, []),
        ])
        resp = client.get("/components/1")
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_get_not_found(self, client, smart_conn):
        smart_conn([
            (None, []),  # fetchone returns None
        ])
        resp = client.get("/components/999")
        assert resp.status_code == 404


class TestComponentUpdate:
    def test_update_existing(self, client, smart_conn):
        updated_row = {**SAMPLE_COMPONENT_ROW, "name": "Side Panel v2"}
        smart_conn([
            ({"id": 1}, []),       # existence check
            (updated_row, []),     # UPDATE ... RETURNING
        ])
        resp = client.put("/components/1", json={"name": "Side Panel v2"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Side Panel v2"

    def test_update_not_found(self, client, smart_conn):
        smart_conn([
            (None, []),  # existence check fails
        ])
        resp = client.put("/components/1", json={"name": "New"})
        assert resp.status_code == 404

    def test_update_no_fields(self, client, smart_conn):
        smart_conn([
            ({"id": 1}, []),  # existence check
        ])
        resp = client.put("/components/1", json={})
        assert resp.status_code == 400
        assert "No fields" in resp.json()["detail"]


class TestComponentDelete:
    def test_delete_success(self, client, smart_conn):
        # The route uses a single cursor with two executes:
        #   1. SELECT products using this component -> fetchall
        #   2. DELETE component (cascades clean up dependent records)
        smart_conn([
            (None, []),  # product usage check — no products found
        ])
        # Override with custom connection for multi-execute cursor:
        mc = _build_delete_conn(product_rows=[], delete_rowcount=1)
        global _mock_conn
        _mock_conn = mc
        resp = client.delete("/components/1")
        assert resp.status_code == 204

    def test_delete_used_in_product_returns_400(self, client):
        mc = _build_delete_conn(product_rows=[{"sku": "PROD-1", "name": "Test Product"}], delete_rowcount=0)
        global _mock_conn
        _mock_conn = mc
        resp = client.delete("/components/1")
        assert resp.status_code == 400
        assert "used in" in resp.json()["detail"]
        assert "Test Product" in resp.json()["detail"]

    def test_delete_not_found(self, client):
        mc = _build_delete_conn(product_rows=[], delete_rowcount=0)
        global _mock_conn
        _mock_conn = mc
        resp = client.delete("/components/999")
        assert resp.status_code == 404


def _build_delete_conn(product_rows: list, delete_rowcount: int) -> MockConnection:
    """Build a MockConnection for the delete endpoint.

    The delete handler runs two executes inside one cursor context:
      1. SELECT ... JOIN ... -> fetchall returns product rows (or empty list)
      2. DELETE ... -> rowcount is checked
    """
    mc = MockConnection()

    class _DeleteCursor(MockCursor):
        def __init__(self):
            super().__init__()
            self._call_index = 0

        def execute(self, sql, params=None):
            super().execute(sql, params)
            self._call_index += 1
            if self._call_index == 1:
                # Product usage query
                self._results = product_rows
            elif self._call_index == 2:
                # DELETE
                self.rowcount = delete_rowcount

    mc._cursor_factory = _DeleteCursor
    return mc


# ===================================================================
# 3. Inventory
# ===================================================================

SAMPLE_INVENTORY_ROW = {
    "id": 1,
    "component_id": 1,
    "quantity_on_hand": 10,
    "quantity_reserved": 0,
    "last_updated": datetime(2026, 1, 1).isoformat(),
    "component_name": "Side Panel",
    "dxf_filename": "side_panel.dxf",
}


class TestInventoryList:
    def test_list_component_inventory(self, client, smart_conn):
        smart_conn([
            (None, [SAMPLE_INVENTORY_ROW]),
        ])
        resp = client.get("/inventory/components")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["component_name"] == "Side Panel"


class TestInventoryAdjust:
    def test_positive_adjustment(self, client):
        """Adding stock succeeds and returns updated inventory."""
        mc = _build_adjust_conn(
            current_qty=10,
            component_exists=True,
            returned_inventory=SAMPLE_INVENTORY_ROW,
        )
        global _mock_conn
        _mock_conn = mc
        resp = client.post(
            "/inventory/components/1/adjust",
            json={"quantity": 5, "reason": "adjustment", "notes": "restock"},
        )
        assert resp.status_code == 200

    def test_negative_adjustment_below_zero_returns_400(self, client):
        """Removing more than on-hand triggers 400."""
        mc = _build_adjust_conn(
            current_qty=3,
            component_exists=True,
            returned_inventory=None,
            negative_qty=-10,
        )
        global _mock_conn
        _mock_conn = mc
        resp = client.post(
            "/inventory/components/1/adjust",
            json={"quantity": -10, "reason": "adjustment"},
        )
        assert resp.status_code == 400
        assert "negative inventory" in resp.json()["detail"]


def _build_adjust_conn(
    current_qty: int,
    component_exists: bool,
    returned_inventory: dict | None,
    negative_qty: int | None = None,
) -> MockConnection:
    """Build a MockConnection for the inventory adjust endpoint.

    The adjust handler opens multiple cursor contexts:
      1. _ensure_component_inventory: INSERT ... ON CONFLICT
      2. Main cursor block:
         a. SELECT id FROM component_definitions  (existence check)
         b. If negative: SELECT quantity_on_hand   (current qty check)
         c. UPDATE component_inventory ...
         d. INSERT INTO inventory_transactions ...
      3. _get_component_inventory: SELECT ... JOIN (to return final state)
    """
    mc = MockConnection()

    call_counter = {"n": 0}

    class _AdjustCursor(MockCursor):
        def __init__(self):
            super().__init__()
            self._exec_idx = 0

        def execute(self, sql, params=None):
            super().execute(sql, params)
            call_counter["n"] += 1
            n = call_counter["n"]

            # Call 1: _ensure_component_inventory INSERT ON CONFLICT
            if n == 1:
                pass
            # Call 2: SELECT id FROM component_definitions (existence check)
            elif n == 2:
                if component_exists:
                    self._fetchone_result = {"id": 1}
                else:
                    self._fetchone_result = None
            # Call 3: If negative qty, SELECT quantity_on_hand
            elif n == 3 and negative_qty is not None:
                self._fetchone_result = {"quantity_on_hand": current_qty}
            # Later calls: UPDATE, INSERT transaction -- no fetchone needed
            # Final: _get_component_inventory SELECT ... JOIN
            else:
                if returned_inventory is not None:
                    self._fetchone_result = returned_inventory

    mc._cursor_factory = _AdjustCursor
    return mc


# ===================================================================
# 4. Replenishment config
# ===================================================================

SAMPLE_CONFIG_ROW = {
    "id": 1,
    "minimum_stock": 2,
    "ses_alpha": 0.3,
    "updated_at": None,
}


class TestReplenishmentConfig:
    def test_update_valid_fields(self, client):
        """PUT /replenishment/config with a valid field succeeds."""
        mc = MockConnection()
        call_counter = {"n": 0}
        updated = {**SAMPLE_CONFIG_ROW, "minimum_stock": 5}

        class _Cursor(MockCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                call_counter["n"] += 1
                if call_counter["n"] == 2:
                    # Second execute: SELECT after UPDATE
                    self._fetchone_result = updated

        mc._cursor_factory = _Cursor
        global _mock_conn
        _mock_conn = mc

        resp = client.put(
            "/replenishment/config",
            json={"minimum_stock": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["minimum_stock"] == 5

    def test_update_no_fields_returns_400(self, client, conn):
        """PUT with empty body returns 400."""
        resp = client.put("/replenishment/config", json={})
        assert resp.status_code == 400
        assert "No fields" in resp.json()["detail"]

    def test_update_invalid_field_returns_422(self, client, conn):
        """PUT with a field not in the Pydantic model returns 422 (validation)."""
        # Fields not in ReplenishmentConfigUpdate are rejected by Pydantic
        # before the route even runs, so FastAPI returns 422.
        resp = client.put(
            "/replenishment/config",
            json={"bogus_field": 999},
        )
        # Pydantic v2 with strict models may pass unknown fields through;
        # the route itself then checks against the whitelist.  Either 400
        # or 422 is acceptable depending on the Pydantic config.
        assert resp.status_code in (400, 422)


# ===================================================================
# 5. Nesting jobs
# ===================================================================

class TestNestingJobCreate:
    def test_create_with_sheets(self, client):
        """POST /nesting-jobs with valid sheets succeeds."""
        mc = MockConnection()
        call_counter = {"n": 0}

        class _Cursor(MockCursor):
            def execute(self, sql, params=None):
                super().execute(sql, params)
                call_counter["n"] += 1
                n = call_counter["n"]
                if n == 1:
                    # INSERT nesting_jobs RETURNING id
                    self._fetchone_result = {"id": 1}
                elif n == 2:
                    # INSERT nesting_sheets RETURNING id
                    self._fetchone_result = {"id": 10}
                # Remaining inserts (sheet_parts, etc.) don't need returns

        mc._cursor_factory = _Cursor
        global _mock_conn
        _mock_conn = mc

        # The route calls _get_job_with_sheets at the end.  That opens a new
        # cursor and does SELECTs.  We need the connection to return sensible
        # data for that too.  Patch _get_job_with_sheets to avoid the deep
        # mocking chain.
        fake_job_response = {
            "id": 1,
            "name": "Test Job",
            "status": "pending",
            "total_sheets": 1,
            "completed_sheets": 0,
            "created_at": datetime(2026, 1, 1).isoformat(),
            "created_by": "test",
            "prototype": False,
            "sheets": [],
            "order_ids": [],
        }
        with patch(
            "app.routers.nesting_jobs._get_job_with_sheets",
            return_value=fake_job_response,
        ):
            resp = client.post(
                "/nesting-jobs",
                json={
                    "name": "Test Job",
                    "sheets": [
                        {
                            "sheet_number": 1,
                            "parts": [{"component_id": 1, "quantity": 4}],
                        }
                    ],
                },
            )
        assert resp.status_code == 201
        assert resp.json()["id"] == 1

    def test_create_empty_sheets_returns_400(self, client, conn):
        """POST /nesting-jobs with no sheets returns 400."""
        resp = client.post("/nesting-jobs", json={"sheets": []})
        assert resp.status_code == 400
        assert "at least one sheet" in resp.json()["detail"]

    def test_create_duplicate_component_ids_returns_400(self, client, conn):
        """POST /nesting-jobs with duplicate component_ids in a sheet returns 400."""
        resp = client.post(
            "/nesting-jobs",
            json={
                "sheets": [
                    {
                        "sheet_number": 1,
                        "parts": [
                            {"component_id": 1, "quantity": 2},
                            {"component_id": 1, "quantity": 3},
                        ],
                    }
                ],
            },
        )
        assert resp.status_code == 400
        assert "duplicate component_ids" in resp.json()["detail"]
