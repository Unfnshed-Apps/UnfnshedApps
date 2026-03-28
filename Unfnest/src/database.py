"""
Database module for managing components and products.

Components are the foundational entities (name + DXF file).
Products are combinations of components with quantities.
"""

import sqlite3
from typing import Optional
from dataclasses import dataclass

from .resources import get_database_path


@dataclass
class ComponentDefinition:
    """A component definition - the master record for a component type."""
    id: int
    name: str
    dxf_filename: str
    variable_pockets: bool = False
    mating_role: str = "neutral"


@dataclass
class ComponentMatingPair:
    """A mating relationship between two components."""
    pocket_component_id: int
    mating_component_id: int
    pocket_index: int = 0
    clearance_inches: float = 0.0079


@dataclass
class ProductComponent:
    """A component used in a product, with quantity."""
    id: int
    product_sku: str
    component_id: int
    component_name: str
    dxf_filename: str
    quantity: int


@dataclass
class Product:
    """Represents a product with its components."""
    sku: str
    name: str
    description: str
    components: list[ProductComponent]
    outsourced: bool = False  # If True, product is made externally and won't be nested


def _ensure_column_exists(cursor, table: str, column: str, definition: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class Database:
    """SQLite database for components and products."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(get_database_path())
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """Create tables if they don't exist."""
        cursor = self.conn.cursor()

        # Master list of component definitions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS component_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                dxf_filename TEXT NOT NULL,
                variable_pockets INTEGER DEFAULT 0,
                mating_role TEXT DEFAULT 'neutral'
            )
        """)

        # Migration: Add columns if they don't exist (for existing databases)
        _ensure_column_exists(cursor, "component_definitions", "variable_pockets", "INTEGER DEFAULT 0")
        _ensure_column_exists(cursor, "component_definitions", "mating_role", "TEXT DEFAULT 'neutral'")
        # Products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                outsourced INTEGER DEFAULT 0
            )
        """)

        # Migration: Add outsourced column if it doesn't exist (for existing databases)
        _ensure_column_exists(cursor, "products", "outsourced", "INTEGER DEFAULT 0")

        # Product-component relationship (which components make up a product)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_sku TEXT NOT NULL,
                component_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (product_sku) REFERENCES products(sku),
                FOREIGN KEY (component_id) REFERENCES component_definitions(id)
            )
        """)

        self.conn.commit()

    # ==================== Component Definition Methods ====================

    def add_component_definition(self, name: str, dxf_filename: str, variable_pockets: bool = False) -> int:
        """Add a new component definition. Returns the component ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO component_definitions (name, dxf_filename, variable_pockets) VALUES (?, ?, ?)",
            (name, dxf_filename, 1 if variable_pockets else 0)
        )
        self.conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _component_from_row(row) -> ComponentDefinition:
        """Build a ComponentDefinition from a database row."""
        return ComponentDefinition(
            id=row["id"],
            name=row["name"],
            dxf_filename=row["dxf_filename"],
            variable_pockets=bool(row["variable_pockets"]),
            mating_role=row["mating_role"] if "mating_role" in row.keys() else "neutral",
        )

    def get_component_definition(self, component_id: int) -> Optional[ComponentDefinition]:
        """Get a component definition by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM component_definitions WHERE id = ?", (component_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._component_from_row(row)

    def get_component_definition_by_name(self, name: str) -> Optional[ComponentDefinition]:
        """Get a component definition by name."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM component_definitions WHERE name = ?", (name,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._component_from_row(row)

    def get_all_component_definitions(self) -> list[ComponentDefinition]:
        """Get all component definitions."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM component_definitions ORDER BY name")
        return [self._component_from_row(row) for row in cursor.fetchall()]

    def update_component_definition(self, component_id: int, name: str, dxf_filename: str, variable_pockets: bool = False, mating_role: str = "neutral") -> None:
        """Update a component definition."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE component_definitions SET name = ?, dxf_filename = ?, variable_pockets = ?, mating_role = ? WHERE id = ?",
            (name, dxf_filename, 1 if variable_pockets else 0, mating_role, component_id)
        )
        self.conn.commit()

    def delete_component_definition(self, component_id: int) -> bool:
        """Delete a component definition. Returns False if component is used in products."""
        cursor = self.conn.cursor()
        # Check if used in any products
        cursor.execute("SELECT COUNT(*) FROM product_components WHERE component_id = ?", (component_id,))
        if cursor.fetchone()[0] > 0:
            return False  # Can't delete, it's in use

        cursor.execute("DELETE FROM component_definitions WHERE id = ?", (component_id,))
        self.conn.commit()
        return True

    def get_all_mating_pairs(self) -> list[ComponentMatingPair]:
        """Get all component mating pairs.

        Mating pairs are only stored on the server, so the local SQLite
        database always returns an empty list. When using APIClient,
        the server's mating pairs are returned instead.
        """
        return []

    # ==================== Product Methods ====================

    def add_product(self, sku: str, name: str, description: str = "", outsourced: bool = False) -> None:
        """Add a new product."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO products (sku, name, description, outsourced) VALUES (?, ?, ?, ?)",
            (sku, name, description, 1 if outsourced else 0)
        )
        self.conn.commit()

    def add_product_component(self, product_sku: str, component_id: int, quantity: int = 1) -> int:
        """Add a component to a product. Returns the relationship ID."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO product_components (product_sku, component_id, quantity) VALUES (?, ?, ?)",
            (product_sku, component_id, quantity)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_product(self, sku: str) -> Optional[Product]:
        """Get a product with all its components."""
        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM products WHERE sku = ?", (sku,))
        product_row = cursor.fetchone()

        if not product_row:
            return None

        # Join to get component details
        cursor.execute("""
            SELECT pc.id, pc.product_sku, pc.component_id, pc.quantity,
                   cd.name as component_name, cd.dxf_filename
            FROM product_components pc
            JOIN component_definitions cd ON pc.component_id = cd.id
            WHERE pc.product_sku = ?
        """, (sku,))

        components = [
            ProductComponent(
                id=row["id"],
                product_sku=row["product_sku"],
                component_id=row["component_id"],
                component_name=row["component_name"],
                dxf_filename=row["dxf_filename"],
                quantity=row["quantity"]
            )
            for row in cursor.fetchall()
        ]

        return Product(
            sku=product_row["sku"],
            name=product_row["name"],
            description=product_row["description"] or "",
            components=components,
            outsourced=bool(product_row["outsourced"])
        )

    def get_all_products(self) -> list[Product]:
        """Get all products with their components."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT sku FROM products ORDER BY sku")
        skus = [row["sku"] for row in cursor.fetchall()]
        return [self.get_product(sku) for sku in skus]

    def delete_product(self, sku: str) -> None:
        """Delete a product and its component relationships."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM product_components WHERE product_sku = ?", (sku,))
        cursor.execute("DELETE FROM products WHERE sku = ?", (sku,))
        self.conn.commit()

    def clear_product_components(self, sku: str) -> None:
        """Remove all components from a product."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM product_components WHERE product_sku = ?", (sku,))
        self.conn.commit()

    def close(self):
        """Close database connection."""
        self.conn.close()
