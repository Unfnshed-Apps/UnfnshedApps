"""Component mating pairs API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import verify_api_key
from ..database import get_db
from ..models import ComponentMatingPair, ComponentMatingPairCreate

router = APIRouter(tags=["mating-pairs"])


@router.get("/mating-pairs", response_model=list[ComponentMatingPair])
def list_mating_pairs(_: str = Depends(verify_api_key)):
    """List all component mating pairs."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, pocket_component_id, mating_component_id,
                       pocket_index, clearance_inches
                FROM component_mating_pairs
                ORDER BY pocket_component_id, pocket_index
                """
            )
            rows = cur.fetchall()
            return [ComponentMatingPair(**r) for r in rows]


@router.get("/components/{component_id}/mating-pairs", response_model=list[ComponentMatingPair])
def get_component_mating_pairs(component_id: int, _: str = Depends(verify_api_key)):
    """Get mating pairs where this component is either the pocket or the tab."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, pocket_component_id, mating_component_id,
                       pocket_index, clearance_inches
                FROM component_mating_pairs
                WHERE pocket_component_id = %s OR mating_component_id = %s
                ORDER BY pocket_index
                """,
                (component_id, component_id)
            )
            rows = cur.fetchall()
            return [ComponentMatingPair(**r) for r in rows]


@router.post("/mating-pairs", response_model=ComponentMatingPair, status_code=status.HTTP_201_CREATED)
def create_mating_pair(body: ComponentMatingPairCreate, _: str = Depends(verify_api_key)):
    """Create a component mating pair."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Verify both components exist
            cur.execute(
                "SELECT id FROM component_definitions WHERE id = %s",
                (body.pocket_component_id,)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Pocket component not found")

            cur.execute(
                "SELECT id FROM component_definitions WHERE id = %s",
                (body.mating_component_id,)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Mating component not found")

            cur.execute(
                """
                INSERT INTO component_mating_pairs
                (pocket_component_id, mating_component_id, pocket_index, clearance_inches)
                VALUES (%s, %s, %s, %s)
                RETURNING id, pocket_component_id, mating_component_id,
                          pocket_index, clearance_inches
                """,
                (body.pocket_component_id, body.mating_component_id,
                 body.pocket_index, body.clearance_inches)
            )
            row = cur.fetchone()
            return ComponentMatingPair(**row)


@router.delete("/mating-pairs/{pair_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mating_pair(pair_id: int, _: str = Depends(verify_api_key)):
    """Delete a component mating pair."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM component_mating_pairs WHERE id = %s", (pair_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Mating pair not found")
