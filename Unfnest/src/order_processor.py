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
    product_unit: Optional[int] = None  # Explicit unit index for block nesting


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

        Handles bundle products by resolving each unit to its source product
        and expanding that product's components. Part IDs use the source
        product SKU, not the bundle SKU.

        Example:
            Input: [OrderItem(sku="SHELF-01", quantity=10)]
            If SHELF-01 has 2 tabletops and 4 legs per unit:
            Output: 20 tabletop instances + 40 leg instances = 60 PartInstances

        Side effect: populates self.last_product_comp_qty with
        {(sku, component_name): quantity} for downstream enrichment.
        """
        part_instances = []
        instance_counters: dict[str, int] = {}
        self.last_product_comp_qty: dict[tuple[str, str], int] = {}
        unit_counter: dict[str, int] = {}  # source_sku -> next unit number

        for order_item in items:
            product = self.db.get_product(order_item.sku)

            if not product:
                print(f"Warning: SKU '{order_item.sku}' not found in database")
                continue

            if getattr(product, 'units', None):
                # Bundle product — expand each unit's source product
                for _copy in range(order_item.quantity):
                    for unit in product.units:
                        source = self.db.get_product(unit.source_product_sku)
                        if not source or not source.components:
                            print(f"Warning: Bundle unit '{unit.source_product_sku}' "
                                  f"not found or has no components")
                            continue
                        src_sku = source.sku
                        current_unit = unit_counter.get(src_sku, 0)
                        unit_counter[src_sku] = current_unit + 1
                        self._expand_product(
                            source, instance_counters, part_instances,
                            product_unit=current_unit,
                        )
            else:
                # Base product
                if not product.components:
                    print(f"Warning: SKU '{order_item.sku}' has no components defined")
                    continue

                src_sku = order_item.sku
                for _unit_num in range(order_item.quantity):
                    current_unit = unit_counter.get(src_sku, 0)
                    unit_counter[src_sku] = current_unit + 1
                    self._expand_product(
                        product, instance_counters, part_instances,
                        product_unit=current_unit,
                    )

        return part_instances

    def _expand_product(
        self,
        product,
        instance_counters: dict[str, int],
        part_instances: list,
        product_unit: int = 0,
    ) -> None:
        """Expand one unit of a product into PartInstances."""
        sku = product.sku

        for component in product.components:
            # Capture per-unit component quantity for enrichment
            self.last_product_comp_qty[(sku, component.component_name)] = component.quantity

            for _comp_instance in range(component.quantity):
                counter_key = f"{sku}_{component.dxf_filename}"
                if counter_key not in instance_counters:
                    instance_counters[counter_key] = 0
                instance_counters[counter_key] += 1

                part_id = f"{sku}_{component.component_name}_{instance_counters[counter_key]:03d}"

                geometry = self._get_geometry(component.dxf_filename)
                if geometry is None:
                    continue

                part_instances.append(PartInstance(
                    part_id=part_id,
                    sku=sku,
                    component_name=component.component_name,
                    dxf_filename=component.dxf_filename,
                    geometry=geometry,
                    product_unit=product_unit,
                ))

    def _get_geometry(self, filename: str) -> Optional[PartGeometry]:
        """Load geometry with caching."""
        if filename not in self._geometry_cache:
            self._geometry_cache[filename] = self.dxf_loader.load_part(filename)
        return self._geometry_cache[filename]

