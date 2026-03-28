"""
Nesting engine — raster-based 2D bin packing with FFT collision detection.

Three-layer architecture:
  Layer 1: RasterEngine (geometry.py) — FFT convolution collision detection
  Layer 2: BLFPlacer (placement.py) — bottom-left fill placement
  Layer 3: SimulatedAnnealing (optimizer.py)
  Orchestrator: pipeline.py — wires enrichment → grouping → placement → optimization
"""
from __future__ import annotations

from .pipeline import nest_parts

__all__ = ["nest_parts"]
