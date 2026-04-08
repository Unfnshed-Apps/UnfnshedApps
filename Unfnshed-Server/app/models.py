"""Pydantic models for API request/response validation."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ==================== Machine Models ====================

class MachineCreate(BaseModel):
    name: str


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None


class Machine(BaseModel):
    id: int
    name: str
    active: bool

    class Config:
        from_attributes = True


# ==================== Component Models ====================

class ComponentDefinitionBase(BaseModel):
    name: str
    dxf_filename: str
    variable_pockets: bool = False
    mating_role: str = "neutral"


class ComponentDefinitionCreate(ComponentDefinitionBase):
    pass


class ComponentDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    dxf_filename: Optional[str] = None
    variable_pockets: Optional[bool] = None
    mating_role: Optional[str] = None


class ComponentDefinition(ComponentDefinitionBase):
    id: int

    class Config:
        from_attributes = True


# ==================== Product Models ====================

class ProductMatingPairSpec(BaseModel):
    """A mating pair definition within a product context (no product_sku - inferred from product)."""
    pocket_component_id: int
    mating_component_id: int
    pocket_index: int = 0
    clearance_inches: float = 0.0079


class ProductComponentBase(BaseModel):
    component_id: int
    quantity: int = 1


class ProductComponentCreate(ProductComponentBase):
    pass


class ProductComponent(ProductComponentBase):
    id: int
    product_sku: str
    component_name: str
    dxf_filename: str

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    sku: str
    name: str
    description: Optional[str] = ""
    outsourced: bool = False


class ProductUnitSpec(BaseModel):
    """A unit within a bundle — references a source product."""
    source_product_sku: str
    unit_index: int = 0


class ProductUnit(ProductUnitSpec):
    """A unit as returned in a product response (includes id and source name)."""
    id: int
    source_product_name: str = ""

    class Config:
        from_attributes = True


class ProductCreate(ProductBase):
    components: list[ProductComponentCreate] = []
    mating_pairs: list[ProductMatingPairSpec] = []
    units: list[ProductUnitSpec] = []


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    outsourced: Optional[bool] = None
    components: Optional[list[ProductComponentCreate]] = None
    mating_pairs: Optional[list[ProductMatingPairSpec]] = None
    units: Optional[list[ProductUnitSpec]] = None


class ProductMatingPair(ProductMatingPairSpec):
    """A mating pair as returned in a product response (includes id)."""
    id: int

    class Config:
        from_attributes = True


class Product(ProductBase):
    components: list[ProductComponent] = []
    mating_pairs: list[ProductMatingPair] = []
    units: list[ProductUnit] = []

    class Config:
        from_attributes = True



# ==================== File Models ====================

class FileInfo(BaseModel):
    """Information about a stored file."""
    filename: str
    size: int
    checksum: str


class FileUploadResponse(BaseModel):
    """Response after uploading a file."""
    filename: str
    size: int
    checksum: str
    message: str = "File uploaded successfully"


# ==================== Inventory Models ====================

class ComponentInventoryBase(BaseModel):
    component_id: int
    quantity_on_hand: int = 0
    quantity_reserved: int = 0


class ComponentInventory(ComponentInventoryBase):
    id: int
    component_name: str
    dxf_filename: str
    last_updated: Optional[datetime] = None

    class Config:
        from_attributes = True


class InventoryAdjustment(BaseModel):
    """Request to adjust component inventory."""
    quantity: int  # positive=add, negative=remove
    reason: str  # adjustment, damaged, correction
    notes: Optional[str] = None


class InventoryTransactionBase(BaseModel):
    component_id: int
    transaction_type: str
    quantity: int
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None


class InventoryTransaction(InventoryTransactionBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==================== Nesting Job Models ====================

class SheetPartBase(BaseModel):
    component_id: int
    quantity: int = 1


class SheetPartCreate(SheetPartBase):
    product_sku: Optional[str] = None


class SheetPart(SheetPartBase):
    id: int
    sheet_id: int
    component_name: Optional[str] = None
    product_sku: Optional[str] = None
    assembled_qty: int = 0

    class Config:
        from_attributes = True


class SheetPartPlacementCreate(BaseModel):
    component_id: int
    order_id: Optional[int] = None
    instance_index: int = 0
    x: float
    y: float
    rotation: float = 0.0
    source_dxf: Optional[str] = None
    product_sku: Optional[str] = None


class SheetPartPlacement(SheetPartPlacementCreate):
    id: int
    sheet_id: int
    component_name: Optional[str] = None

    class Config:
        from_attributes = True


class NestingSheetBase(BaseModel):
    sheet_number: int
    dxf_filename: Optional[str] = None
    gcode_filename: Optional[str] = None


class NestingSheetCreate(NestingSheetBase):
    parts: list[SheetPartCreate] = []
    placements: list[SheetPartPlacementCreate] = []
    order_ids: list[int] = []
    has_variable_pockets: bool = False


class NestingSheet(NestingSheetBase):
    id: int
    job_id: int
    status: str = "pending"
    cut_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    has_variable_pockets: bool = False
    actual_thickness_inches: Optional[float] = None
    parts: list[SheetPart] = []
    placements: list[SheetPartPlacement] = []
    order_ids: list[int] = []

    class Config:
        from_attributes = True


class NestingJobBase(BaseModel):
    name: Optional[str] = None


class NestingJobCreate(NestingJobBase):
    sheets: list[NestingSheetCreate] = []
    created_by: Optional[str] = None
    order_ids: list[int] = []
    prototype: bool = False


class NestingJob(NestingJobBase):
    id: int
    status: str = "pending"
    total_sheets: int = 0
    completed_sheets: int = 0
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    prototype: bool = False
    sheets: list[NestingSheet] = []
    order_ids: list[int] = []

    class Config:
        from_attributes = True


# ==================== Products Available Models ====================

class ComponentAvailability(BaseModel):
    """Component availability for a specific product."""
    component_id: int
    name: str
    required: int
    available: int
    shared: bool  # True if used by multiple products


class ProductAvailability(BaseModel):
    """How many of a product can be made from current inventory."""
    sku: str
    name: str
    max_individual: int  # Max if only making this product
    limiting_component: Optional[str] = None
    has_shared_components: bool
    components: list[ComponentAvailability]


class ComponentSummary(BaseModel):
    """Summary of a component used across products."""
    id: int
    name: str
    available: int
    used_by: list[str]  # List of product SKUs


class ProductsAvailableResponse(BaseModel):
    """Response for products-available endpoint."""
    components_summary: list[ComponentSummary]
    products: list[ProductAvailability]


# ==================== Build Plan Models ====================

class BuildPlanItem(BaseModel):
    sku: str
    qty: int


class BuildPlanRequest(BaseModel):
    items: list[BuildPlanItem]


class ComponentNeed(BaseModel):
    component_id: int
    name: str
    need: int
    have: int
    ok: bool


class BuildPlanResponse(BaseModel):
    valid: bool
    components_needed: list[ComponentNeed]
    message: Optional[str] = None


# ==================== Product Inventory Models ====================

class ProductInventoryBase(BaseModel):
    product_sku: str
    quantity_on_hand: int = 0
    quantity_reserved: int = 0


class ProductInventory(ProductInventoryBase):
    id: int
    product_name: str
    last_updated: Optional[datetime] = None

    class Config:
        from_attributes = True



# ==================== CNC Machine Models ====================

class UpdateGcodeFilename(BaseModel):
    """Request to update a sheet's gcode_filename after local generation."""
    gcode_filename: str


class ClaimSheetRequest(BaseModel):
    """Request to claim the next pending sheet for a CNC machine."""
    machine_id: str
    prototype: bool = False


class DamagedPartReport(BaseModel):
    """A single damaged part report within a cut sheet."""
    component_id: int
    quantity: int


class MarkCutWithDamagesRequest(BaseModel):
    """Request to mark a sheet as cut, optionally reporting damaged parts."""
    damaged_parts: list[DamagedPartReport] = []


class QueueJobSummary(BaseModel):
    """Summary of a single job in the queue."""
    id: int
    name: Optional[str] = None
    status: str
    total_sheets: int
    completed_sheets: int


class QueueSummary(BaseModel):
    """Queue overview for CNC operators."""
    pending_sheets: int
    cutting_sheets: int
    completed_today: int
    prototype_pending_sheets: int = 0
    prototype_cutting_sheets: int = 0
    jobs: list[QueueJobSummary]


class ClaimedSheetInfo(BaseModel):
    """Lightweight info about a sheet claimed by a machine (for crash recovery)."""
    job_id: int
    sheet_id: int
    sheet_number: int
    job_name: Optional[str] = None


# ==================== Mating Pair Models ====================

class ComponentMatingPairCreate(BaseModel):
    """Request to create a component mating pair."""
    product_sku: str
    pocket_component_id: int
    mating_component_id: int
    pocket_index: int = 0
    clearance_inches: float = 0.0079


class ComponentMatingPair(ComponentMatingPairCreate):
    id: int

    class Config:
        from_attributes = True




class PocketTarget(BaseModel):
    """Resolved pocket target thickness for G-code generation."""
    component_id: int
    pocket_index: int
    mating_thickness_inches: float
    clearance_inches: float


class SetSheetThicknessRequest(BaseModel):
    """Request to set a sheet's actual thickness."""
    actual_thickness_inches: float


# ==================== Replenishment Models ====================

class ReplenishmentConfig(BaseModel):
    """Tunable parameters for the replenishment system."""
    minimum_stock: int = 2
    ses_alpha: float = 0.3
    review_period_days: int = 7
    lead_time_days: int = 3
    service_z: float = 1.65
    trend_clamp_low: float = 0.85
    trend_clamp_high: float = 1.25
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReplenishmentConfigUpdate(BaseModel):
    """Partial update for replenishment config."""
    minimum_stock: Optional[int] = None
    ses_alpha: Optional[float] = None
    review_period_days: Optional[int] = None
    lead_time_days: Optional[int] = None
    service_z: Optional[float] = None
    trend_clamp_low: Optional[float] = None
    trend_clamp_high: Optional[float] = None


class ComponentForecast(BaseModel):
    """Forecast state for a single component."""
    component_id: int
    component_name: str = ""
    velocity: float = 0
    target_stock: int = 0
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReplenishmentNeed(BaseModel):
    """Per-component replenishment need from a snapshot."""
    component_id: int
    component_name: str = ""
    dxf_filename: str = ""
    velocity: float = 0
    current_stock: int = 0
    reserved: int = 0
    pipeline: int = 0
    effective_stock: int = 0
    target_stock: int = 0
    deficit: int = 0

    class Config:
        from_attributes = True


class ReplenishmentSnapshot(BaseModel):
    """Point-in-time replenishment calculation."""
    id: int
    calculated_at: Optional[datetime] = None
    total_mandatory: int = 0
    total_fill: int = 0
    needs: list[ReplenishmentNeed] = []

    class Config:
        from_attributes = True


class ReplenishmentStatus(BaseModel):
    """Live stock position for a single component."""
    component_id: int
    component_name: str = ""
    dxf_filename: str = ""
    current_stock: int = 0
    reserved: int = 0
    pipeline: int = 0
    effective_stock: int = 0
    target_stock: int = 0
    velocity: float = 0
    outsourced: bool = False
    status: str = "adequate"  # adequate, below_target

    class Config:
        from_attributes = True


class ProductReplenishmentStatus(BaseModel):
    """Live stock position for a single product."""
    product_sku: str
    product_name: str = ""
    current_stock: int = 0
    reserved: int = 0
    target_stock: int = 0
    velocity: float = 0
    deficit: int = 0
    status: str = "adequate"  # adequate, below_target
    is_derived: bool = False  # True for bundles (stock derived from source products)

    class Config:
        from_attributes = True


class ReplenishmentQueueResponse(BaseModel):
    """Response for the replenishment queue endpoint."""
    snapshot_id: Optional[int] = None
    calculated_at: Optional[datetime] = None
    mandatory: list[ReplenishmentNeed] = []
    fill_candidates: list[ReplenishmentNeed] = []


# ==================== Bundle Models ====================

class BundleCreate(BaseModel):
    """Request to create a sheet bundle."""
    sheet_ids: list[int]


class SheetBundleSheet(BaseModel):
    """Sheet info within a bundle."""
    id: int
    sheet_number: int
    job_id: int
    job_name: Optional[str] = None
    status: str = "pending"
    dxf_filename: Optional[str] = None

    class Config:
        from_attributes = True


class SheetBundle(BaseModel):
    """A bundle of 2-4 mating sheets."""
    id: int
    status: str = "pending"
    sheet_count: int = 0
    claimed_by: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    sheets: list[SheetBundleSheet] = []

    class Config:
        from_attributes = True


# ==================== Shipping Models ====================

class ShippingLineItem(BaseModel):
    """A line item in a shipping queue order."""
    sku: str = ""
    title: str = ""
    variant_title: str = ""
    quantity: int = 1
    stock: int = 0
    in_stock: bool = False
    is_bundle: bool = False


class ShippingQueueItem(BaseModel):
    """An unfulfilled order in the shipping queue."""
    order_id: int
    order_number: str = ""
    name: str = ""
    customer_name: str = ""
    email: str = ""
    shipping_address: Optional[dict] = None
    created_at: Optional[datetime] = None
    note: str = ""
    total_price: str = "0.00"
    items: list[ShippingLineItem] = []
    ready_to_ship: bool = False
