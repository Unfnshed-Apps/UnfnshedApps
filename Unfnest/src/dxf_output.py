"""
Generate DXF output files for nested sheets.

Preserves original geometry (curves, splines, circles) from source DXF files.
"""

import ezdxf
from ezdxf.math import Matrix44
from ezdxf import bbox as ezdxf_bbox
from pathlib import Path
import math

from .nesting_models import NestedSheet, PlacedPart
from .resources import get_dxf_directory, get_output_directory


def _rotation_components(rotation_degrees):
    """Return (cos_r, sin_r) for a rotation in degrees."""
    rad = math.radians(rotation_degrees)
    return math.cos(rad), math.sin(rad)


class DXFOutputGenerator:
    """Generates DXF files showing nested part layouts."""

    def __init__(self, output_directory: str = None, dxf_directory: str = None):
        if output_directory is None:
            self.output_directory = get_output_directory()
        else:
            self.output_directory = Path(output_directory)
        self.output_directory.mkdir(exist_ok=True)

        if dxf_directory is None:
            self.dxf_directory = get_dxf_directory()
        else:
            self.dxf_directory = Path(dxf_directory)
        # Cache loaded source DXF documents
        self._source_cache = {}
        # DXF filenames whose pocket entities should be tagged as Pocket_Variable
        self._variable_pocket_sources: set[str] = set()

    def set_variable_pocket_sources(self, filenames: set[str]):
        """Set which source DXF filenames should have pockets tagged as Pocket_Variable."""
        self._variable_pocket_sources = filenames

    def generate_sheet_dxf(
        self,
        sheet: NestedSheet,
        filename_prefix: str = "nested_sheet"
    ) -> tuple[str, list[tuple[float, float]]]:
        """
        Generate a DXF file for a single nested sheet.

        Returns (filepath, centroids) where centroids is a list of per-part
        bbox centers in sheet.parts order. A centroid may be (part.x, part.y)
        as fallback if the source DXF couldn't be loaded.
        """
        doc = ezdxf.new()
        msp = doc.modelspace()

        # Draw sheet boundary
        self._draw_rectangle(
            msp,
            0, 0,
            sheet.width, sheet.height,
            layer="SHEET_BOUNDARY",
            color=8  # Gray
        )

        # Draw each placed part by copying from source DXF
        centroids = []
        for part in sheet.parts:
            centroid = self._copy_part_from_source(msp, part)
            if centroid is None:
                # Fallback: use raw nesting position
                centroid = (part.x, part.y)
            centroids.append(centroid)

        # Save file
        output_path = self.output_directory / f"{filename_prefix}_{sheet.sheet_number:02d}.dxf"
        doc.saveas(str(output_path))

        return str(output_path), centroids

    def generate_all_sheets(
        self,
        sheets: list[NestedSheet],
        filename_prefix: str = "nested_sheet"
    ) -> list[tuple[str, list[tuple[float, float]]]]:
        """Generate DXF files for all sheets.

        Returns list of (filepath, centroids) per sheet.
        """
        results = []
        for sheet in sheets:
            result = self.generate_sheet_dxf(sheet, filename_prefix)
            results.append(result)
        # Clear cache after generating all sheets
        self._source_cache.clear()
        return results

    def _get_source_doc(self, filename: str):
        """Load and cache source DXF document."""
        if filename not in self._source_cache:
            filepath = self.dxf_directory / filename
            if filepath.exists():
                self._source_cache[filename] = ezdxf.readfile(str(filepath))
            else:
                return None
        return self._source_cache[filename]

    def _copy_part_from_source(self, target_msp, part: PlacedPart):
        """
        Copy entities from source DXF file to target, applying transformation.
        Preserves original geometry (curves, circles, splines).

        Returns the transformed bbox center (x, y) of the part, or None on failure.
        """
        source_doc = self._get_source_doc(part.source_filename)
        if source_doc is None:
            # Fallback to polygon drawing if source not found
            self._draw_part_from_polygon(target_msp, part)
            return None

        source_msp = source_doc.modelspace()

        # First, find the bounding box of the source geometry to normalize to origin
        all_entities = list(source_msp)
        if not all_entities:
            return None

        # Calculate source bounding box
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')

        for entity in all_entities:
            try:
                entity_bbox = ezdxf_bbox.extents([entity])
                if entity_bbox.has_data:
                    min_x = min(min_x, entity_bbox.extmin.x)
                    min_y = min(min_y, entity_bbox.extmin.y)
                    max_x = max(max_x, entity_bbox.extmax.x)
                    max_y = max(max_y, entity_bbox.extmax.y)
            except Exception:
                pass

        if min_x == float('inf'):
            # Couldn't calculate bbox, fallback
            self._draw_part_from_polygon(target_msp, part)
            return None

        # Build transformation matrix:
        # 1. Translate to origin (normalize)
        # 2. Rotate around origin
        # 3. Translate to final position (accounting for rotation shift)

        # Calculate rotation offset - after rotating, the bounding box shifts
        width = max_x - min_x
        height = max_y - min_y
        cos_r, sin_r = _rotation_components(part.rotation)

        # Corners of original bbox at origin
        corners = [(0, 0), (width, 0), (width, height), (0, height)]
        rotated_corners = [
            (c[0] * cos_r - c[1] * sin_r, c[0] * sin_r + c[1] * cos_r)
            for c in corners
        ]
        rot_min_x = min(c[0] for c in rotated_corners)
        rot_min_y = min(c[1] for c in rotated_corners)

        # Build transformation matrix
        rad = math.radians(part.rotation)
        m = Matrix44.translate(-min_x, -min_y, 0)  # Normalize to origin
        m @= Matrix44.z_rotate(rad)  # Rotate
        m @= Matrix44.translate(-rot_min_x + part.x, -rot_min_y + part.y, 0)  # Final position

        # Compute transformed bbox center for accurate placement tracking
        src_center_x = (min_x + max_x) / 2
        src_center_y = (min_y + max_y) / 2
        transformed_center = m.transform((src_center_x, src_center_y, 0))
        centroid = (transformed_center[0], transformed_center[1])

        # Copy and transform each entity
        tag_variable = part.source_filename in self._variable_pocket_sources
        for entity in all_entities:
            try:
                # Create a copy of the entity
                new_entity = entity.copy()
                # Apply transformation
                new_entity.transform(m)
                # Re-tag pocket entities from variable-pocket components
                if tag_variable and getattr(new_entity.dxf, 'layer', '').lower() == 'pocket':
                    new_entity.dxf.layer = 'Pocket_Variable'
                # Add to target
                target_msp.add_entity(new_entity)
            except Exception as e:
                # Some entities may not support transform, skip them
                pass

        return centroid

    def _draw_part_from_polygon(self, msp, part: PlacedPart):
        """Fallback: draw part from polygon approximation, preserving layers."""
        if not part.polygon:
            return

        cos_r, sin_r = _rotation_components(part.rotation)

        def _rotate(points):
            return [(px * cos_r - py * sin_r, px * sin_r + py * cos_r)
                    for px, py in points]

        # Rotate outline to get the normalization offset
        rotated_outline = _rotate(part.polygon)
        min_rx = min(p[0] for p in rotated_outline)
        min_ry = min(p[1] for p in rotated_outline)

        def _transform(points):
            rotated = _rotate(points)
            return [(rx - min_rx + part.x, ry - min_ry + part.y)
                    for rx, ry in rotated]

        # Draw outline
        msp.add_lwpolyline(
            _transform(part.polygon), close=True,
            dxfattribs={"layer": "Outline", "color": 7}
        )

        # Draw pocket polygons
        tag_variable = part.source_filename in self._variable_pocket_sources
        for poly in part.pocket_polygons:
            if len(poly) < 3:
                continue
            layer = "Pocket_Variable" if tag_variable else "Pocket"
            msp.add_lwpolyline(
                _transform(poly), close=True,
                dxfattribs={"layer": layer, "color": 5}
            )

        # Draw internal polygons
        for poly in part.internal_polygons:
            if len(poly) < 3:
                continue
            msp.add_lwpolyline(
                _transform(poly), close=True,
                dxfattribs={"layer": "Internal", "color": 3}
            )

    def _draw_rectangle(
        self,
        msp,
        x1: float, y1: float,
        x2: float, y2: float,
        layer: str = "0",
        color: int = 7
    ):
        """Draw a rectangle."""
        points = [
            (x1, y1),
            (x2, y1),
            (x2, y2),
            (x1, y2),
            (x1, y1)  # Close
        ]
        msp.add_lwpolyline(
            points,
            close=True,
            dxfattribs={"layer": layer, "color": color}
        )
