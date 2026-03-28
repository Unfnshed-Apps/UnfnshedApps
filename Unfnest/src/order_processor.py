"""
Order processing - converts SKU quantities to a list of parts for nesting.
"""

from dataclasses import dataclass
from typing import Optional

from .database import Database
from .dxf_loader import DXFLoader, PartGeometry


@dataclass
class OrderItem:
    """A single item in an order."""
    sku: str
    quantity: int


@dataclass
class PartInstance:
    """A single instance of a part to be nested."""
    part_id: str  # Unique ID like "SHELF-01_tabletop_003"
    sku: str
    component_name: str
    dxf_filename: str
    geometry: Optional[PartGeometry]


class OrderProcessor:
    """
    Processes orders by expanding SKUs into individual part instances.
    """

    def __init__(self, db: Database, dxf_loader: DXFLoader):
        self.db = db
        self.dxf_loader = dxf_loader
        self._geometry_cache: dict[str, PartGeometry] = {}

    def process_order(self, items: list[OrderItem]) -> list[PartInstance]:
        """
        Convert an order (list of SKU/quantity pairs) into individual part instances.

        Example:
            Input: [OrderItem(sku="SHELF-01", quantity=10)]
            If SHELF-01 has 2 tabletops and 4 legs per unit:
            Output: 20 tabletop instances + 40 leg instances = 60 PartInstances

        Side effect: populates self.last_product_comp_qty with
        {(sku, component_name): quantity} for downstream enrichment.
        """
        part_instances = []
        instance_counters: dict[str, int] = {}  # Track instance numbers per component
        self.last_product_comp_qty: dict[tuple[str, str], int] = {}

        for order_item in items:
            product = self.db.get_product(order_item.sku)

            if not product:
                print(f"Warning: SKU '{order_item.sku}' not found in database")
                continue

            if not product.components:
                print(f"Warning: SKU '{order_item.sku}' has no components defined")
                continue

            # Capture component quantities for enrichment
            for component in product.components:
                self.last_product_comp_qty[
                    (order_item.sku, component.component_name)
                ] = component.quantity

            # For each unit ordered
            for unit_num in range(order_item.quantity):
                # For each component type in the product
                for component in product.components:
                    # For each instance of this component per product
                    for comp_instance in range(component.quantity):
                        # Generate unique part ID
                        counter_key = f"{order_item.sku}_{component.dxf_filename}"
                        if counter_key not in instance_counters:
                            instance_counters[counter_key] = 0
                        instance_counters[counter_key] += 1

                        part_id = f"{order_item.sku}_{component.component_name}_{instance_counters[counter_key]:03d}"

                        # Load geometry (with caching)
                        geometry = self._get_geometry(component.dxf_filename)
                        if geometry is None:
                            continue  # Skip components with no loadable geometry

                        part_instances.append(PartInstance(
                            part_id=part_id,
                            sku=order_item.sku,
                            component_name=component.component_name,
                            dxf_filename=component.dxf_filename,
                            geometry=geometry
                        ))

        return part_instances

    def _get_geometry(self, filename: str) -> Optional[PartGeometry]:
        """Load geometry with caching."""
        if filename not in self._geometry_cache:
            self._geometry_cache[filename] = self.dxf_loader.load_part(filename)
        return self._geometry_cache[filename]

