"""
G-code generator for ShopSabre CNC.

Generates .tap files from nesting DXF entity data (already positioned).
Supports layer-based cutting:
- Pocket cuts (from "Pocket" layer): Single pass at pocket depth
- Internal cuts (from "Internal" layer): Two-pass (rough + finish) at full depth, inward offset
- Outline cuts (from "Outline" layer): Two-pass (rough + finish) at full depth, outward offset

Z reference is configurable:
- Spoilboard zero: Z=0 at spoilboard, material top at Z=+thickness
- Top zero: Z=0 at material top, cuts go into negative Z
Material thickness comes from per-sheet measurement at runtime.

Outputs smooth curves using G2/G3 arc commands when entity data has bulges.
"""

import math
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from shapely.geometry import Polygon

from .config import ZERO_FROM_TOP
from .dxf_loader import (
    NestingDXFEntities, EntityPath,
    CircleEntity, PolylineEntity,
)


@dataclass
class GCodeSettings:
    """Settings for G-code generation."""
    # Tool settings — outline cuts use separate tools for rough and finish
    # passes (internals share these). Pockets have their own tool.
    outline_rough_tool_number: int = 5
    outline_rough_tool_diameter: float = 0.375
    outline_finish_tool_number: int = 5
    outline_finish_tool_diameter: float = 0.375
    pocket_tool_number: int = 5
    pocket_tool_diameter: float = 0.375
    spindle_rpm: int = 18000

    # Feed rates
    feed_xy_rough: int = 650  # Roughing pass XY feed
    feed_xy_finish: int = 350  # Finishing pass XY feed
    feed_z: int = 60  # Z plunge rate

    # Z heights
    safe_z: float = 0.2004  # Safe travel height
    retract_z: float = 0.1969  # Retract height between moves

    # Material settings (resolved at generation time from sheet thickness)
    material_thickness: float = 0.7087  # Set from per-sheet measurement
    cut_depth_adjustment: float = 0.0  # Final cut depth offset (+/- up to 0.25")
    roughing_pct: int = 80  # Roughing pass as percentage of material thickness
    pocket_depth: float = 0.5512  # Pocket cut depth (thickness - 4mm)
    pocket_clearance: float = 0.0079  # Extra width for variable pockets (~0.2mm)
    zero_from: str = "spoilboard"  # "spoilboard" or "top"

    # Ramp entry
    ramp_angle: float = 5.0  # Lead-in ramp angle in degrees (from horizontal)

    # Timing
    spindle_dwell: float = 4.0  # Seconds to wait for spindle spin-up

    # End position
    end_position_offset: float = 3.0  # Inches past sheet corner
    end_z_height: float = 2.0  # Z height when job completes

    # Tool-path direction — assumes CCW spindle (ShopSabre).
    # Shapely buffer emits CW exterior coords; "climb" reverses to CCW for
    # outlines and keeps CW for inside cuts (pocket/internal). Each tool
    # brings its own direction; internals use the outline-rough/outline-finish
    # direction matching the pass.
    outline_rough_direction: str = "climb"
    outline_finish_direction: str = "climb"
    pocket_direction: str = "climb"


class GCodeGenerator:
    """Generates G-code for ShopSabre CNC from nesting DXF entity data.

    Entities are already positioned in sheet coordinates by Unfnest.
    No per-part transforms needed.
    """

    def __init__(self, settings: GCodeSettings = None):
        self.settings = settings or GCodeSettings()
        s = self.settings
        thick = s.material_thickness
        rough_depth = thick * (s.roughing_pct / 100.0)
        finish_depth = thick + s.cut_depth_adjustment

        if s.zero_from == ZERO_FROM_TOP:
            # Z=0 at material top, negative goes into material
            self.z_top = 0.0
            self.z_safe = s.safe_z
            self.z_retract = s.retract_z
            self.z_rough = -(rough_depth)
            self.z_finish = -(finish_depth)
            self.z_pocket = -(s.pocket_depth)
            self.z_end = s.end_z_height
        else:
            # Z=0 at spoilboard, material top at Z=+thickness
            self.z_top = thick
            self.z_safe = thick + s.safe_z
            self.z_retract = thick + s.retract_z
            self.z_rough = thick - rough_depth
            self.z_finish = thick - finish_depth
            self.z_pocket = thick - s.pocket_depth
            self.z_end = thick + s.end_z_height

    def _outline_tool_diameter(self, pass_type: str) -> float:
        """Tool diameter for outline/internal cuts at the given pass."""
        if pass_type == 'rough':
            return self.settings.outline_rough_tool_diameter
        return self.settings.outline_finish_tool_diameter

    def _outline_direction(self, pass_type: str) -> str:
        """Climb/conventional setting for outline/internal cuts at the given pass."""
        if pass_type == 'rough':
            return self.settings.outline_rough_direction
        return self.settings.outline_finish_direction

    def generate_from_nesting_dxf(
        self,
        entities: NestingDXFEntities,
        output_path: Path,
        pocket_targets: list[dict] = None,
    ) -> Path:
        """Generate a G-code file from nesting DXF entity data.

        Phase order (grouped by tool to minimise tool changes):
        1. Pockets                                   — pocket_tool
        2. Internal roughing passes                  — outline_rough_tool
        3. Outline roughing passes                   — outline_rough_tool
        4. Internal finishing passes (full depth)    — outline_finish_tool
        5. Outline finishing passes (cuts part free) — outline_finish_tool
        6. Footer with end position

        Part stability: during step 4 the part is still held by the outline's
        remaining rough-layer material, so through-cutting the internals is
        safe. The outline isn't fully severed until step 5.

        Args:
            entities: NestingDXFEntities from DXFLoader.load_nesting_dxf_entities()
            output_path: Full path for the output .tap file
            pocket_targets: Optional list of dicts with mating_thickness_inches
                and clearance_inches from the server's pocket-targets endpoint.
                When provided, variable pockets are scaled to the mating tab's
                actual measured thickness instead of the global material_thickness.

        Returns:
            Path to the generated file
        """
        lines = []
        s = self.settings

        # Resolve mating thickness for variable pockets
        mating_thickness = None
        mating_clearance = None
        if pocket_targets:
            thicknesses = [pt["mating_thickness_inches"] for pt in pocket_targets
                          if pt.get("mating_thickness_inches")]
            if thicknesses:
                mating_thickness = thicknesses[0]
                mating_clearance = pocket_targets[0].get("clearance_inches", s.pocket_clearance)

        has_pockets = bool(entities.pocket_contours) or bool(entities.variable_pocket_contours)
        has_internals = bool(entities.internal_contours)
        has_outlines = bool(entities.outline_contours)

        rough_tool = s.outline_rough_tool_number
        finish_tool = s.outline_finish_tool_number
        pocket_tool = s.pocket_tool_number

        # Decide which tool the header prepares. First non-empty phase wins.
        if has_pockets:
            first_tool = pocket_tool
        elif has_internals or has_outlines:
            first_tool = rough_tool
        else:
            first_tool = rough_tool  # empty job, still emit a valid header
        lines.extend(self._generate_header(tool_number=first_tool))
        current_tool = first_tool

        def ensure_tool(target: int) -> None:
            nonlocal current_tool
            if target != current_tool:
                lines.extend(self._generate_tool_change(target))
                current_tool = target

        # === PHASE 1: Pockets ===
        if has_pockets:
            for contour in entities.pocket_contours:
                lines.extend(self._generate_pocket_contour(contour))
            for contour in entities.variable_pocket_contours:
                scaled = self._scale_variable_pocket(
                    contour, mating_thickness, mating_clearance
                )
                lines.extend(self._generate_pocket_contour(scaled))

        # === PHASE 2+3: Rough internals then rough outlines (shared tool) ===
        if has_internals or has_outlines:
            ensure_tool(rough_tool)

        if has_internals:
            lines.append('')
            lines.append('( === INTERNAL ROUGHING PASSES === )')
            for contour in entities.internal_contours:
                lines.extend(self._generate_internal_contour(contour, pass_type='rough'))

        if has_outlines:
            lines.append('')
            lines.append('( === ROUGHING PASSES === )')
            for contour in entities.outline_contours:
                lines.extend(self._generate_outline_contour(contour, pass_type='rough'))

        # === PHASE 4+5: Finish internals then finish outlines (shared tool) ===
        if has_internals or has_outlines:
            ensure_tool(finish_tool)

        if has_internals:
            lines.append('')
            lines.append('( === INTERNAL FINISHING PASSES === )')
            for contour in entities.internal_contours:
                lines.extend(self._generate_internal_contour(contour, pass_type='finish'))

        if has_outlines:
            lines.append('')
            lines.append('( === FINISHING PASSES === )')
            for contour in entities.outline_contours:
                lines.extend(self._generate_outline_contour(contour, pass_type='finish'))

        # Footer
        lines.extend(self._generate_footer(
            entities.sheet_width, entities.sheet_height
        ))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('\n'.join(lines))
        return output_path

    # ==================== Header / Footer / Tool Change ====================

    def _generate_header(self, tool_number: int = None) -> list[str]:
        s = self.settings
        tool = tool_number if tool_number is not None else s.outline_rough_tool_number
        return [
            'G90',
            f'G0 Z{self.z_safe:.4f}',
            'G0 X0.0000 Y0.0000',
            'M5',
            f'T{tool}',
            f'S{s.spindle_rpm}',
            'M50',
            'M3',
            f'g4 x {int(s.spindle_dwell)}',
            f'G0 Z{self.z_safe:.4f}',
            'G0 X0.0000 Y0.0000',
            f'F{s.feed_xy_rough} XY',
            f'F{s.feed_z} Z',
        ]

    def _generate_tool_change(self, new_tool_number: int) -> list[str]:
        s = self.settings
        return [
            '',
            '( Tool Change )',
            f'G0 Z{self.z_safe:.4f}',
            'G0 X0.0000 Y0.0000',
            'M5',
            f'T{new_tool_number}',
            f'S{s.spindle_rpm}',
            'M3',
            f'g4 x {int(s.spindle_dwell)}',
            f'G0 Z{self.z_safe:.4f}',
            f'F{s.feed_xy_rough} XY',
            f'F{s.feed_z} Z',
            '',
        ]

    def _generate_footer(self, sheet_width: float, sheet_height: float) -> list[str]:
        s = self.settings
        end_x = sheet_width + s.end_position_offset
        end_y = sheet_height + s.end_position_offset
        return [
            f'G0 Z{self.z_end:.4f}',
            f'G0 X{end_x:.4f} Y{end_y:.4f}',
            'M5',
            'm51',
        ]

    # ==================== Pocket Cutting ====================

    def _generate_pocket_contour(self, contour: EntityPath) -> list[str]:
        """Generate pocket clearing for a single contour.

        Uses concentric offset passes (outside-in) at pocket depth.
        """
        lines = []
        s = self.settings
        tool_radius = s.pocket_tool_diameter / 2.0

        # Convert entity to polygon for offset operations
        poly_points = contour.to_polygon_points()
        if len(poly_points) < 3:
            return lines

        polygon = Polygon(poly_points)
        # Offset inward by tool radius
        inset = polygon.buffer(-tool_radius, join_style=2)
        if inset.is_empty or not inset.is_valid:
            return lines

        # Generate clearing paths (concentric inward passes)
        clearing_paths = self._generate_pocket_clearing_paths(inset, s.pocket_tool_diameter)
        if not clearing_paths:
            return lines

        if s.pocket_direction == "conventional":
            clearing_paths = [list(reversed(p)) for p in clearing_paths]

        first_path = True
        for path_coords in clearing_paths:
            if len(path_coords) < 2:
                continue

            if first_path:
                path_coords = self._reorder_path_for_longest_edge(path_coords)

            start_x, start_y = path_coords[0]

            if first_path:
                lines.append(f'G0 X{start_x:.4f} Y{start_y:.4f} Z{self.z_retract:.4f}')
                lines.append(f'G1   Z{self.z_top:.4f} F{s.feed_z:.1f}')

                if len(path_coords) > 1:
                    next_x, next_y = path_coords[1]
                    lines.append(f'G1 X{next_x:.4f} Y{next_y:.4f} Z{self.z_pocket:.4f} ')

                lines.append(f'G1  F{s.feed_xy_rough:.1f}')

                for x, y in path_coords[2:]:
                    lines.append(f'G1 X{x:.4f} Y{y:.4f} ')

                lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f} ')

                if len(path_coords) > 1:
                    lines.append(f'G1 X{next_x:.4f} Y{next_y:.4f} ')

                first_path = False
            else:
                lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f} ')

                for x, y in path_coords[1:]:
                    lines.append(f'G1 X{x:.4f} Y{y:.4f} ')

                lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f} ')

        lines.append(f'G0   Z{self.z_retract:.4f}')
        return lines

    def _generate_pocket_clearing_paths(
        self, polygon: Polygon, tool_diameter: float
    ) -> list[list[tuple[float, float]]]:
        """Generate concentric offset paths to clear a pocket area."""
        paths = []
        stepover = tool_diameter * 0.4
        current_poly = polygon

        while True:
            if current_poly.is_empty or not current_poly.is_valid:
                break

            if current_poly.geom_type == 'Polygon':
                coords = list(current_poly.exterior.coords)
                if len(coords) >= 3:
                    paths.append(coords)
            elif current_poly.geom_type == 'MultiPolygon':
                for poly in current_poly.geoms:
                    coords = list(poly.exterior.coords)
                    if len(coords) >= 3:
                        paths.append(coords)

            current_poly = current_poly.buffer(-stepover, join_style=2)

            if len(paths) > 100:
                break

        return paths

    # ==================== Outline Cutting ====================

    def _generate_outline_contour(
        self, contour: EntityPath, pass_type: str = 'rough'
    ) -> list[str]:
        """Generate outline cuts for a single contour.

        Args:
            pass_type: 'rough' or 'finish'
        """
        if not contour.entities:
            return []

        first_entity = contour.entities[0]

        if isinstance(first_entity, CircleEntity):
            return self._generate_circle_outline(first_entity, pass_type)

        if isinstance(first_entity, PolylineEntity):
            return self._generate_polyline_outline(first_entity, pass_type)

        # Fallback: convert to polygon coords
        poly_points = contour.to_polygon_points()
        return self._generate_polygon_outline(poly_points, pass_type)

    def _generate_circle_outline(
        self, circle: CircleEntity, pass_type: str
    ) -> list[str]:
        """Generate outline cuts for a circle using G2/G3 arcs."""
        lines = []
        s = self.settings
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        # Offset circle outward by tool radius
        r = circle.radius + tool_radius
        if r <= 0:
            return lines

        cx, cy = circle.center
        start_x = cx + r
        start_y = cy
        mid_x = cx - r
        mid_y = cy

        arc = 'G2' if self._outline_direction(pass_type) == 'conventional' else 'G3'

        lines.append(f'G0 X{start_x:.4f} Y{start_y:.4f} Z{self.z_retract:.4f}')

        if pass_type == 'rough':
            lines.append(f'G1 Z{self.z_top:.4f} F{s.feed_z:.1f}')
            # Ramp into first half-circle
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000 Z{self.z_rough:.4f}')
            lines.append(f'G1 F{s.feed_xy_rough:.1f}')
            # Complete circle
            lines.append(f'{arc} X{start_x:.4f} Y{start_y:.4f} I{r:.4f} J0.0000')
            # Re-cut first half at rough depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000')
            lines.append(f'G0 Z{self.z_retract:.4f}')

        elif pass_type == 'finish':
            lines.append(f'G1 Z{self.z_rough:.4f} F{s.feed_z:.1f}')
            # Ramp to final depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000 Z{self.z_finish:.4f} F{s.feed_xy_finish:.1f}')
            # Complete circle
            lines.append(f'{arc} X{start_x:.4f} Y{start_y:.4f} I{r:.4f} J0.0000')
            # Re-cut first half at final depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000')
            lines.append(f'G0 Z{self.z_retract:.4f}')

        return lines

    def _generate_polyline_outline(
        self, polyline: PolylineEntity, pass_type: str
    ) -> list[str]:
        """Generate outline cuts for a polyline with possible bulge arcs."""
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        points = polyline.points
        bulges = polyline.bulges
        n = len(points)

        if n < 2:
            return []

        has_arcs = any(abs(b) > 1e-6 for b in bulges)

        if has_arcs:
            return self._generate_polyline_with_arcs_outline(
                points, bulges, polyline.closed, tool_radius, pass_type,
                reverse_path=(self._outline_direction(pass_type) == "climb"),
            )
        else:
            # Pure linear - use polygon offset
            poly_points = EntityPath(entities=[polyline]).to_polygon_points()
            return self._generate_polygon_outline(poly_points, pass_type)

    @staticmethod
    def _find_best_ramp_segment(
        points: list[tuple[float, float]],
        bulges: list[float],
        closed: bool,
    ) -> int:
        """Find the best segment index for ramp entry.

        Prefers vertical (Y-dominant) straight segments; among equally-oriented
        segments the longest wins. Arc segments are never considered vertical.

        Returns:
            Index into *points* where the ramp should begin.
        """
        n = len(points)
        best_idx = 0
        best_score = -1.0

        for i in range(n):
            next_i = (i + 1) % n if closed else (i + 1 if i < n - 1 else None)
            if next_i is None:
                continue

            p1, p2 = points[i], points[next_i]
            bulge = bulges[i] if i < len(bulges) else 0

            if abs(bulge) < 1e-6:
                length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                dx = abs(p2[0] - p1[0])
                dy = abs(p2[1] - p1[1])
                is_vertical = dy > dx
            else:
                chord = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                theta = 4 * math.atan(abs(bulge))
                radius = chord / (2 * math.sin(theta / 2)) if theta > 0 else chord
                length = radius * theta
                is_vertical = False

            score = length + (1_000_000 if is_vertical else 0)
            if score > best_score:
                best_score = score
                best_idx = i

        return best_idx

    def _generate_polyline_with_arcs_outline(
        self,
        points: list[tuple[float, float]],
        bulges: list[float],
        closed: bool,
        tool_radius: float,
        pass_type: str,
        reverse_path: bool = False,
    ) -> list[str]:
        """Generate G-code for a polyline with arc segments."""
        lines = []
        s = self.settings
        n = len(points)

        best_idx = self._find_best_ramp_segment(points, bulges, closed)

        # Reorder to start at chosen segment
        if best_idx > 0:
            points = points[best_idx:] + points[:best_idx]
            bulges = bulges[best_idx:] + bulges[:best_idx]

        # Apply tool offset using Shapely polygon buffer
        offset_points = self._offset_polyline_points(points, bulges, tool_radius, closed)
        if len(offset_points) < 2:
            return lines

        if reverse_path:
            offset_points = list(reversed(offset_points))

        start_x, start_y = offset_points[0]
        lines.append(f'G0 X{start_x:.4f} Y{start_y:.4f} Z{self.z_retract:.4f}')

        if pass_type == 'rough':
            lines.append(f'G1 Z{self.z_top:.4f} F{s.feed_z:.1f}')

            # Ramp along first segment using configured angle
            if len(offset_points) > 1:
                ramp_lines, ramp_end_idx, recut_path = self._ramp_to_depth(
                    offset_points, bulges, self.z_top, self.z_rough
                )
                lines.extend(ramp_lines)
                # Adjust start index for remaining path traversal
                ramp_start_idx = ramp_end_idx
            else:
                ramp_start_idx = 1
                recut_path = []

            lines.append(f'G1 F{s.feed_xy_rough:.1f}')

            # Continue around path (skip segments already covered by ramp)
            for i in range(ramp_start_idx, len(offset_points) - 1):
                bulge = bulges[i] if i < len(bulges) else 0
                if abs(bulge) < 1e-6:
                    lines.append(f'G1 X{offset_points[i + 1][0]:.4f} Y{offset_points[i + 1][1]:.4f}')
                else:
                    arc_lines, _ = self._bulge_arc_to_gcode(
                        offset_points[i], offset_points[i + 1], bulge
                    )
                    lines.extend(arc_lines)

            # Close path + re-cut only the ramped portion at full depth
            if closed:
                lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f}')
                for rx, ry in recut_path:
                    lines.append(f'G1 X{rx:.4f} Y{ry:.4f}')

            lines.append(f'G0 Z{self.z_retract:.4f}')

        elif pass_type == 'finish':
            lines.append(f'G1 Z{self.z_rough:.4f} F{s.feed_z:.1f}')

            # Ramp along first segment using configured angle
            if len(offset_points) > 1:
                ramp_lines, ramp_end_idx, recut_path = self._ramp_to_depth(
                    offset_points, bulges, self.z_rough, self.z_finish, s.feed_xy_finish
                )
                lines.extend(ramp_lines)
                ramp_start_idx = ramp_end_idx
            else:
                ramp_start_idx = 1
                recut_path = []

            for i in range(ramp_start_idx, len(offset_points) - 1):
                bulge = bulges[i] if i < len(bulges) else 0
                if abs(bulge) < 1e-6:
                    lines.append(f'G1 X{offset_points[i + 1][0]:.4f} Y{offset_points[i + 1][1]:.4f}')
                else:
                    arc_lines, _ = self._bulge_arc_to_gcode(
                        offset_points[i], offset_points[i + 1], bulge
                    )
                    lines.extend(arc_lines)

            if closed:
                lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f}')
                for rx, ry in recut_path:
                    lines.append(f'G1 X{rx:.4f} Y{ry:.4f}')

            lines.append(f'G0 Z{self.z_retract:.4f}')

        return lines

    def _generate_polygon_outline(
        self, poly_points: list[tuple[float, float]], pass_type: str
    ) -> list[str]:
        """Generate outline cuts from polygon coordinates (linear paths)."""
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        if len(poly_points) < 3:
            return []

        polygon = Polygon(poly_points)
        offset_polygon = polygon.buffer(tool_radius, join_style=2)
        if offset_polygon.is_empty or not offset_polygon.is_valid:
            return []

        coords = list(offset_polygon.exterior.coords)
        if len(coords) < 2:
            return []

        if self._outline_direction(pass_type) == "climb":
            coords = list(reversed(coords))

        coords = self._reorder_path_for_longest_edge(coords)
        return self._generate_linear_outline_gcode(coords, pass_type)

    def _generate_linear_outline_gcode(
        self, coords: list[tuple[float, float]], pass_type: str
    ) -> list[str]:
        """Generate outline G-code for a purely linear path."""
        lines = []
        s = self.settings

        if len(coords) < 2:
            return lines

        # Build zero-bulge list for _ramp_to_depth compatibility
        bulges = [0.0] * len(coords)

        start_x, start_y = coords[0]
        lines.append(f'G0 X{start_x:.4f} Y{start_y:.4f} Z{self.z_retract:.4f}')

        if pass_type == 'rough':
            lines.append(f'G1 Z{self.z_top:.4f} F{s.feed_z:.1f}')

            if len(coords) > 1:
                ramp_lines, ramp_end_idx, recut_path = self._ramp_to_depth(
                    coords, bulges, self.z_top, self.z_rough
                )
                lines.extend(ramp_lines)
            else:
                ramp_end_idx = 1
                recut_path = []

            lines.append(f'G1 F{s.feed_xy_rough:.1f}')

            for x, y in coords[ramp_end_idx:]:
                lines.append(f'G1 X{x:.4f} Y{y:.4f}')

            lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f}')

            for rx, ry in recut_path:
                lines.append(f'G1 X{rx:.4f} Y{ry:.4f}')

            lines.append(f'G0 Z{self.z_retract:.4f}')

        elif pass_type == 'finish':
            lines.append(f'G1 Z{self.z_rough:.4f} F{s.feed_z:.1f}')

            if len(coords) > 1:
                ramp_lines, ramp_end_idx, recut_path = self._ramp_to_depth(
                    coords, bulges, self.z_rough, self.z_finish, s.feed_xy_finish
                )
                lines.extend(ramp_lines)
            else:
                ramp_end_idx = 1
                recut_path = []

            for x, y in coords[ramp_end_idx:]:
                lines.append(f'G1 X{x:.4f} Y{y:.4f}')

            lines.append(f'G1 X{start_x:.4f} Y{start_y:.4f}')

            for rx, ry in recut_path:
                lines.append(f'G1 X{rx:.4f} Y{ry:.4f}')

            lines.append(f'G0 Z{self.z_retract:.4f}')

        return lines

    # ==================== Internal Cutting (Through-cut holes, inward offset) ====================

    def _generate_internal_contour(
        self, contour: EntityPath, pass_type: str = 'rough'
    ) -> list[str]:
        """Generate internal cuts for a single contour.

        Internal = through-cut depth + inward tool offset (cutting a hole).
        """
        if not contour.entities:
            return []

        first_entity = contour.entities[0]

        if isinstance(first_entity, CircleEntity):
            return self._generate_circle_internal(first_entity, pass_type)

        if isinstance(first_entity, PolylineEntity):
            return self._generate_polyline_internal(first_entity, pass_type)

        # Fallback: convert to polygon coords
        poly_points = contour.to_polygon_points()
        return self._generate_polygon_internal(poly_points, pass_type)

    def _generate_circle_internal(
        self, circle: CircleEntity, pass_type: str
    ) -> list[str]:
        """Generate internal cuts for a circle using G2/G3 arcs (inward offset)."""
        lines = []
        s = self.settings
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        # Offset circle inward by tool radius
        r = circle.radius - tool_radius
        if r <= 0:
            return lines

        cx, cy = circle.center
        start_x = cx + r
        start_y = cy
        mid_x = cx - r
        mid_y = cy

        arc = 'G2' if self._outline_direction(pass_type) == 'climb' else 'G3'

        lines.append(f'G0 X{start_x:.4f} Y{start_y:.4f} Z{self.z_retract:.4f}')

        if pass_type == 'rough':
            lines.append(f'G1 Z{self.z_top:.4f} F{s.feed_z:.1f}')
            # Ramp into first half-circle
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000 Z{self.z_rough:.4f}')
            lines.append(f'G1 F{s.feed_xy_rough:.1f}')
            # Complete circle
            lines.append(f'{arc} X{start_x:.4f} Y{start_y:.4f} I{r:.4f} J0.0000')
            # Re-cut first half at rough depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000')
            lines.append(f'G0 Z{self.z_retract:.4f}')

        elif pass_type == 'finish':
            lines.append(f'G1 Z{self.z_rough:.4f} F{s.feed_z:.1f}')
            # Ramp to final depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000 Z{self.z_finish:.4f} F{s.feed_xy_finish:.1f}')
            # Complete circle
            lines.append(f'{arc} X{start_x:.4f} Y{start_y:.4f} I{r:.4f} J0.0000')
            # Re-cut first half at final depth
            lines.append(f'{arc} X{mid_x:.4f} Y{mid_y:.4f} I{-r:.4f} J0.0000')
            lines.append(f'G0 Z{self.z_retract:.4f}')

        return lines

    def _generate_polyline_internal(
        self, polyline: PolylineEntity, pass_type: str
    ) -> list[str]:
        """Generate internal cuts for a polyline (inward offset)."""
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        points = polyline.points
        bulges = polyline.bulges
        n = len(points)

        if n < 2:
            return []

        has_arcs = any(abs(b) > 1e-6 for b in bulges)

        if has_arcs:
            # Use negative tool_radius for inward offset
            return self._generate_polyline_with_arcs_outline(
                points, bulges, polyline.closed, -tool_radius, pass_type,
                reverse_path=(self._outline_direction(pass_type) == "conventional"),
            )
        else:
            # Pure linear - use polygon offset
            poly_points = EntityPath(entities=[polyline]).to_polygon_points()
            return self._generate_polygon_internal(poly_points, pass_type)

    def _generate_polygon_internal(
        self, poly_points: list[tuple[float, float]], pass_type: str
    ) -> list[str]:
        """Generate internal cuts from polygon coordinates (inward offset)."""
        tool_radius = self._outline_tool_diameter(pass_type) / 2.0

        if len(poly_points) < 3:
            return []

        polygon = Polygon(poly_points)
        # Buffer inward (negative) for internal cuts
        offset_polygon = polygon.buffer(-tool_radius, join_style=2)
        if offset_polygon.is_empty or not offset_polygon.is_valid:
            return []

        coords = list(offset_polygon.exterior.coords)
        if len(coords) < 2:
            return []

        if self._outline_direction(pass_type) == "conventional":
            coords = list(reversed(coords))

        coords = self._reorder_path_for_longest_edge(coords)
        return self._generate_linear_outline_gcode(coords, pass_type)

    # ==================== Variable Pocket Scaling ====================

    @staticmethod
    def _compute_pocket_scale_transform(
        poly_points: list[tuple[float, float]],
        target_depth: float,
        pocket_clearance: float,
    ) -> Optional[tuple[tuple[float, float], tuple[float, float], float]]:
        """Compute the transform parameters for scaling a variable pocket.

        Finds the minimum rotated rectangle, identifies the short axis,
        and computes the scale factor needed to resize it.

        Args:
            poly_points: Polygon vertices of the pocket.
            target_depth: Target mating thickness in inches.
            pocket_clearance: Additional clearance in inches.

        Returns:
            (centroid, short_axis_unit_vector, scale_factor) or None if
            the polygon is degenerate.
        """
        if len(poly_points) < 3:
            return None

        polygon = Polygon(poly_points)
        if polygon.is_empty or not polygon.is_valid:
            return None

        mrr = polygon.minimum_rotated_rectangle
        mrr_coords = list(mrr.exterior.coords)[:4]

        edge0 = (mrr_coords[1][0] - mrr_coords[0][0], mrr_coords[1][1] - mrr_coords[0][1])
        edge1 = (mrr_coords[2][0] - mrr_coords[1][0], mrr_coords[2][1] - mrr_coords[1][1])
        len0 = math.sqrt(edge0[0]**2 + edge0[1]**2)
        len1 = math.sqrt(edge1[0]**2 + edge1[1]**2)

        if len0 <= len1:
            short_len = len0
            short_dir = (edge0[0] / len0, edge0[1] / len0) if len0 > 1e-10 else (1, 0)
        else:
            short_len = len1
            short_dir = (edge1[0] / len1, edge1[1] / len1) if len1 > 1e-10 else (0, 1)

        if short_len < 1e-10:
            return None

        target_short = target_depth + pocket_clearance
        scale_factor = target_short / short_len
        centroid = (polygon.centroid.x, polygon.centroid.y)

        return centroid, short_dir, scale_factor

    @staticmethod
    def _apply_pocket_scale(
        points: list[tuple[float, float]],
        centroid: tuple[float, float],
        short_dir: tuple[float, float],
        scale_factor: float,
    ) -> list[tuple[float, float]]:
        """Scale points along the short axis relative to centroid."""
        cx, cy = centroid
        sx, sy = short_dir
        scaled = []
        for px, py in points:
            dx, dy = px - cx, py - cy
            short_component = dx * sx + dy * sy
            delta = (short_component * scale_factor) - short_component
            scaled.append((px + delta * sx, py + delta * sy))
        return scaled

    def scale_variable_pocket_polygon(
        self,
        poly_points: list[tuple[float, float]],
        target_thickness: float = None,
        clearance: float = None,
    ) -> list[tuple[float, float]]:
        """Scale a variable pocket polygon's short dimension for preview display.

        Same math as _scale_variable_pocket but operates on polygon point lists.
        """
        if target_thickness is None:
            target_thickness = self.settings.material_thickness
        if clearance is None:
            clearance = self.settings.pocket_clearance

        transform = self._compute_pocket_scale_transform(
            poly_points, target_thickness, clearance
        )
        if transform is None:
            return poly_points

        centroid, short_dir, scale_factor = transform
        return self._apply_pocket_scale(poly_points, centroid, short_dir, scale_factor)

    def _scale_variable_pocket(
        self,
        contour: EntityPath,
        target_thickness: float = None,
        clearance: float = None,
    ) -> EntityPath:
        """Scale a variable pocket's short dimension to target_thickness + clearance.

        When target_thickness is provided (from mating tab's actual measurement),
        uses that instead of the global material_thickness. This ensures the pocket
        is sized to fit the specific tab that will mate with it.

        Args:
            contour: The variable pocket contour to scale
            target_thickness: Mating tab's actual thickness (defaults to material_thickness)
            clearance: Pocket clearance (defaults to pocket_clearance setting)
        """
        if target_thickness is None:
            target_thickness = self.settings.material_thickness
        if clearance is None:
            clearance = self.settings.pocket_clearance

        poly_points = contour.to_polygon_points()
        transform = self._compute_pocket_scale_transform(
            poly_points, target_thickness, clearance
        )
        if transform is None:
            return contour

        centroid, short_dir, scale_factor = transform
        scaled_points = self._apply_pocket_scale(
            poly_points, centroid, short_dir, scale_factor
        )

        return EntityPath(entities=[
            PolylineEntity(points=scaled_points, bulges=[0] * len(scaled_points), closed=True)
        ])

    # ==================== Utility Methods ====================

    def _reorder_path_for_longest_edge(
        self, path_coords: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Reorder a closed path to start at best edge for ramp entry.

        Prefers vertical (Y-dominant) edges; among equally-oriented edges
        the longest wins.
        """
        if len(path_coords) < 3:
            return path_coords

        best_idx = 0
        best_score = -1

        for i in range(len(path_coords) - 1):
            x1, y1 = path_coords[i]
            x2, y2 = path_coords[i + 1]
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            is_vertical = dy > dx
            score = length + (1_000_000 if is_vertical else 0)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx == 0:
            return path_coords

        open_path = path_coords[:-1] if path_coords[0] == path_coords[-1] else path_coords
        reordered = open_path[best_idx:] + open_path[:best_idx]
        reordered.append(reordered[0])
        return reordered

    def _offset_polyline_points(
        self,
        points: list[tuple[float, float]],
        bulges: list[float],
        offset: float,
        closed: bool,
    ) -> list[tuple[float, float]]:
        """Offset polyline points for tool compensation using Shapely."""
        entity_path = EntityPath(entities=[
            PolylineEntity(points=list(points), bulges=list(bulges), closed=closed)
        ])
        poly_points = entity_path.to_polygon_points()

        if len(poly_points) < 3:
            return points

        polygon = Polygon(poly_points)
        offset_polygon = polygon.buffer(offset, join_style=2)

        if offset_polygon.is_empty or not offset_polygon.is_valid:
            return points

        return list(offset_polygon.exterior.coords)

    def _bulge_arc_to_gcode(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        bulge: float,
        feed_str: str = '',
    ) -> tuple[list[str], tuple[float, float]]:
        """Convert a bulge arc to G-code."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        chord_len = math.sqrt(dx * dx + dy * dy)

        if chord_len < 1e-10:
            return [f'G1 X{end[0]:.4f} Y{end[1]:.4f}{feed_str}'], end

        theta = 4 * math.atan(abs(bulge))
        radius = chord_len / (2 * math.sin(theta / 2))

        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2

        perp_x = -dy / chord_len
        perp_y = dx / chord_len

        h = radius * math.cos(theta / 2)

        if bulge > 0:  # CCW
            cx = mid_x + h * perp_x
            cy = mid_y + h * perp_y
            g_code = 'G3'
        else:  # CW
            cx = mid_x - h * perp_x
            cy = mid_y - h * perp_y
            g_code = 'G2'

        i = cx - start[0]
        j = cy - start[1]

        return [f'{g_code} X{end[0]:.4f} Y{end[1]:.4f} I{i:.4f} J{j:.4f}{feed_str}'], end

    def _ramp_to_depth(
        self,
        offset_points: list[tuple[float, float]],
        bulges: list[float],
        z_start: float,
        z_end: float,
        feed_xy: Optional[float] = None,
    ) -> tuple[list[str], int, list[tuple[float, float]]]:
        """Ramp from z_start to z_end along path using configured ramp angle.

        Returns (gcode_lines, next_segment_index, recut_path):
          - gcode_lines: the ramp G-code
          - next_segment_index: where the main traversal should continue from
          - recut_path: points traversed during descent — used by the caller
            to re-cut ONLY the ramped portion at full depth (not the entire
            first segment).
        """
        z_drop = abs(z_end - z_start)
        if z_drop < 1e-6:
            return [], 1, []

        angle_rad = math.radians(max(self.settings.ramp_angle, 0.5))
        max_ramp_xy = z_drop / math.tan(angle_rad)

        lines = []
        recut_path: list[tuple[float, float]] = []
        xy_traveled = 0.0
        seg_idx = 0

        while seg_idx < len(offset_points) - 1 and xy_traveled < max_ramp_xy:
            p1 = offset_points[seg_idx]
            p2 = offset_points[seg_idx + 1]
            bulge = bulges[seg_idx] if seg_idx < len(bulges) else 0

            if abs(bulge) < 1e-6:
                seg_len = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                remaining_ramp = max_ramp_xy - xy_traveled

                if seg_len <= remaining_ramp:
                    # Use full segment
                    frac = (xy_traveled + seg_len) / max_ramp_xy
                    z_at = z_start + (z_end - z_start) * frac
                    feed_str = f' F{feed_xy:.1f}' if feed_xy and seg_idx == 0 else ''
                    lines.append(f'G1 X{p2[0]:.4f} Y{p2[1]:.4f} Z{z_at:.4f}{feed_str}')
                    recut_path.append((p2[0], p2[1]))
                    xy_traveled += seg_len
                    seg_idx += 1
                else:
                    # Partial segment — interpolate to ramp endpoint
                    t = remaining_ramp / seg_len
                    mid_x = p1[0] + t * (p2[0] - p1[0])
                    mid_y = p1[1] + t * (p2[1] - p1[1])
                    feed_str = f' F{feed_xy:.1f}' if feed_xy and seg_idx == 0 else ''
                    lines.append(f'G1 X{mid_x:.4f} Y{mid_y:.4f} Z{z_end:.4f}{feed_str}')
                    recut_path.append((mid_x, mid_y))
                    # Finish remainder of this segment at target depth
                    lines.append(f'G1 X{p2[0]:.4f} Y{p2[1]:.4f}')
                    xy_traveled = max_ramp_xy
                    seg_idx += 1
            else:
                # Arc segment — ramp over entire arc for simplicity
                feed_val = feed_xy if feed_xy and seg_idx == 0 else None
                seg_len_approx = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                theta = 4 * math.atan(abs(bulge))
                radius = seg_len_approx / (2 * math.sin(theta / 2)) if theta > 0 else seg_len_approx
                arc_len = radius * theta

                frac = min((xy_traveled + arc_len) / max_ramp_xy, 1.0)
                z_at = z_start + (z_end - z_start) * frac
                arc_lines = self._bulge_to_gcode_with_z(
                    p1, p2, bulge, z_at, feed_val
                )
                lines.extend(arc_lines)
                recut_path.append((p2[0], p2[1]))
                xy_traveled += arc_len
                seg_idx += 1

        # If we ran out of segments before reaching target depth, ensure we're at z_end
        if xy_traveled < max_ramp_xy and seg_idx >= len(offset_points) - 1:
            # Already at the last point, just plunge to final depth
            if lines:
                pass  # Z was set proportionally; it may not be exactly z_end
            # The close-path logic will handle coming back around

        return lines, seg_idx, recut_path

    def _bulge_to_gcode_with_z(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        bulge: float,
        z: float,
        feed: float = None,
    ) -> list[str]:
        """Generate G2/G3 arc with Z movement (for ramping)."""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        chord_len = math.sqrt(dx * dx + dy * dy)

        if chord_len < 1e-10:
            feed_str = f' F{feed:.1f}' if feed else ''
            return [f'G1 X{end[0]:.4f} Y{end[1]:.4f} Z{z:.4f}{feed_str}']

        theta = 4 * math.atan(abs(bulge))
        radius = chord_len / (2 * math.sin(theta / 2))

        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2

        perp_x = -dy / chord_len
        perp_y = dx / chord_len

        h = radius * math.cos(theta / 2)

        if bulge > 0:
            cx = mid_x + h * perp_x
            cy = mid_y + h * perp_y
            g_code = 'G3'
        else:
            cx = mid_x - h * perp_x
            cy = mid_y - h * perp_y
            g_code = 'G2'

        i = cx - start[0]
        j = cy - start[1]

        feed_str = f' F{feed:.1f}' if feed else ''
        return [f'{g_code} X{end[0]:.4f} Y{end[1]:.4f} I{i:.4f} J{j:.4f} Z{z:.4f}{feed_str}']
