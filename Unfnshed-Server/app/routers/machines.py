"""CNC machine registry API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import Machine, MachineCreate, MachineUpdate

router = APIRouter(prefix="/machines", tags=["machines"])


@router.get("", response_model=list[Machine])
def list_machines(
    active: Optional[bool] = Query(None),
    _: str = Depends(verify_api_key),
):
    """List all machines, optionally filtered by active status."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if active is not None:
                cur.execute(
                    "SELECT id, name, active FROM machines WHERE active = %s ORDER BY name",
                    (active,)
                )
            else:
                cur.execute("SELECT id, name, active FROM machines ORDER BY name")
            return [Machine(**row) for row in cur.fetchall()]


@router.post("", response_model=Machine, status_code=status.HTTP_201_CREATED)
def create_machine(body: MachineCreate, _: str = Depends(verify_api_key)):
    """Register a new machine."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM machines WHERE name = %s",
                (body.name,)
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail=f"Machine '{body.name}' already exists")
            cur.execute(
                "INSERT INTO machines (name) VALUES (%s) RETURNING id, name, active",
                (body.name,)
            )
            return Machine(**cur.fetchone())


@router.put("/{machine_id}", response_model=Machine)
def update_machine(machine_id: int, body: MachineUpdate, _: str = Depends(verify_api_key)):
    """Update a machine's name or active status."""
    with get_db() as conn:
        with conn.cursor() as cur:
            updates = []
            values = []
            if body.name is not None:
                updates.append("name = %s")
                values.append(body.name)
            if body.active is not None:
                updates.append("active = %s")
                values.append(body.active)

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            values.append(machine_id)
            cur.execute(
                f"UPDATE machines SET {', '.join(updates)} WHERE id = %s RETURNING id, name, active",
                values
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Machine not found")
            return Machine(**row)


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, _: str = Depends(verify_api_key)):
    """Delete a machine."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM machines WHERE id = %s", (machine_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Machine not found")
