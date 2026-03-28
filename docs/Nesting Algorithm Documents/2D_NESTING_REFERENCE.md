# 2D Geometry Nesting: Complete Technical Reference for Claude Code

> **Purpose**: This document synthesizes 7 academic papers and 7 open-source repositories into a single reference for understanding and implementing 2D irregular geometry nesting (also called 2D irregular strip packing). It is designed to be read by an LLM agent tasked with adapting nesting algorithms to a specific application.
>
> **How to use this document**: Read Sections 1–3 to understand the problem. Read Section 4 to understand the geometric primitives. Read Section 5 for state-of-the-art algorithms. Read Section 6 to choose an approach. Section 7 lists open-source code.

---

## 1. WHAT IS 2D NESTING?

2D nesting is the problem of placing irregular (non-rectangular) shapes onto a flat surface while minimizing wasted material. It arises in manufacturing: cutting fabric for garments, sheet metal for automotive/aerospace parts, wood for furniture, leather for shoes. The problem is NP-hard — no polynomial-time optimal solution exists. All practical solutions use heuristics or meta-heuristics.

### Problem Variants

| Variant | Description | Objective |
|---------|-------------|-----------|
| **Strip Packing (2DISPP)** | Fixed-width strip, variable length | Minimize strip length |
| **Bin Packing (2DIBPP)** | Fixed-size rectangular bins | Minimize number of bins used |
| **Knapsack** | Fixed container, subset of items | Maximize value of placed items |
| **Open Dimension** | One or both container dimensions variable | Minimize area used |

Strip packing is the most common academic formulation. Bin packing is more common in manufacturing where stock sheets have fixed dimensions.

### What Makes It Hard

The problem combines two challenges: a **combinatorial challenge** (which piece goes where, in what order, at what rotation?) and a **geometric challenge** (do pieces overlap? do they fit inside the container?). Most of the research progress has come from finding faster ways to answer the geometric questions, freeing up computational budget for the combinatorial search.

---

## 2. PROBLEM STRUCTURE: THE THREE LAYERS

Every nesting system has three layers. Understanding this decomposition is essential:

```
┌─────────────────────────────────────┐
│  LAYER 3: GLOBAL SEARCH            │  GA, SA, local search, RL
│  (What order? What rotation?)       │  Explores the space of solutions
├─────────────────────────────────────┤
│  LAYER 2: PLACEMENT HEURISTIC      │  BLF, NFP-guided, gravity center
│  (Where does this piece go?)        │  Given an order, places each piece
├─────────────────────────────────────┤
│  LAYER 1: GEOMETRIC ENGINE          │  NFP, raster, phi-functions, CDE
│  (Do these overlap? Does it fit?)   │  Answers feasibility queries
└─────────────────────────────────────┘
```

**Layer 1** is called millions of times per optimization run. Speed here dominates total performance. **Layer 2** is called once per piece per candidate solution. **Layer 3** orchestrates the search. The key insight from Gardeyn (2024) is that these layers should be **decoupled** — you should be able to swap the search strategy without re-implementing geometry.

---

## 3. GEOMETRIC REPRESENTATIONS (LAYER 1)

### 3.1 No-Fit Polygon (NFP)

The NFP is the single most important geometric primitive in nesting. Given two polygons A and B, the NFP is the locus of all positions for B's reference point such that A and B touch but do not overlap. If B's reference point is **inside** the NFP, the pieces overlap. If it's **outside**, they don't. If it's **on the boundary**, they touch.

**How NFP works**: Fix polygon A. Slide polygon B around the boundary of A, keeping them touching. The path traced by B's reference point is the NFP.

**Why it matters**: It converts the expensive question "do these two arbitrary polygons overlap?" into the cheap question "is this point inside this polygon?" — a simple ray-casting test.

**Generation methods**:
- **Orbiting algorithm**: Slide B around A's boundary. Conceptually simple. Struggles with concavities.
- **Decomposition**: Decompose both polygons into convex parts, compute NFP for each pair, merge results. More robust.
- **Minkowski sums**: NFP = Minkowski sum of A and (-B). Mathematically elegant. Requires convex decomposition for non-convex shapes.

**Degenerate cases** (from Rocha et al. 2019):
- **Perfect fits**: B fits exactly into a concavity of A. The NFP has isolated vertices (zero-area regions).
- **Perfect sliding**: Two edges align exactly, allowing linear motion. Creates degenerate edges in the NFP.
- **Interlocking concavities**: Multiple concave features interact, creating holes in the NFP.
- **NFP holes**: Regions inside the NFP boundary where B can actually be placed (inside a cavity of A). Must be detected and preserved.

**Robust NFP generation** (Rocha et al. 2019 algorithm):
1. Convex decomposition of both pieces
2. Generate NFP for each convex pair using slope diagrams
3. Compute intersection points between NFP components
4. Insert midpoint vertices for refinement
5. Build directed graph from NFP components
6. Eliminate contained vertices
7. Extract outline using OExAlgo (handles holes, perfect fits, perfect slides)
8. Reconstruct final NFP with degenerate case annotations

**Complexity**: O(n_A × n_B × (log(m_A + m_B) + m_A × m_B)) where n is convex components, m is edges.

### 3.2 Inner-Fit Polygon (IFP)

The IFP is the containment equivalent of the NFP. Given a container C and a piece P, the IFP is the locus of positions for P's reference point such that P is fully inside C. The **feasible placement region** for a piece is: IFP minus all NFPs with already-placed pieces.

### 3.3 Raster (Pixel) Method

Divide the sheet into a grid of pixels. Each cell is 0 (empty) or 1 (occupied). Overlap detection = bitwise AND. Containment = all piece pixels within container bounds.

**Pros**: Simple to implement, easy overlap detection, handles any shape.
**Cons**: Memory intensive, precision limited by pixel size, cannot exactly represent non-orthogonal edges.

### 3.4 Semi-Discrete Representation

A hybrid: discretize only the x-axis into equidistant vertical lines at spacing R. Each piece is represented as sets of vertical line segments (y-intervals) at each resolution line. Overlap detection reduces to y-coordinate interval comparisons.

**From Cherri et al. 2022 (Chehrazad, Roose & Wauters)**:
- Resolution parameter R controls precision vs. speed tradeoff
- Extension algorithm ensures original pieces don't overlap despite discretization
- Each interval labeled M (middle), L (left edge), R (right edge) for precise handling

**Data structure**:
```
Piece = [
    resolution_line_0: [(y_bottom, y_top, label), ...],
    resolution_line_1: [(y_bottom, y_top, label), ...],
    ...
]
```

**Performance vs. NFP** (Cherri et al. 2022 benchmarks):
| Resolution R | Wasted Space | Speed vs NFP |
|-------------|--------------|--------------|
| R = 1.0 | 23.3% | ~6000x faster |
| R = 0.1 | 13.6% | ~3000x faster |
| R = 0.01 | 12.1% | ~1400x faster |

The semi-discrete approach is 3–4 orders of magnitude faster than NFP-based methods but produces 10–20% more waste. The greedy heuristic (not the discretization) is the primary quality limiter.

### 3.5 Phi-Functions

Mathematical functions encoding the relative position of two objects: positive when separated, zero when touching, negative when overlapping. Used in mathematical programming formulations (LP, MIP, NLP). More general than NFPs but harder to compute and less commonly implemented in practice.

### 3.6 Hazard Proximity Index (jagua-rs)

From Gardeyn 2024. A unifying abstraction: any spatial constraint is a **hazard**. Interior hazards = space occupied by other items. Exterior hazards = space outside the container. A placement is feasible if the item doesn't intersect any hazard.

**Implementation**: Quadtree data structure that recursively divides 2D space. Each node tracks: no hazard / partial hazard / fully hazardous. Unresolved edges stored at leaf nodes for narrow-phase testing.

**Two-phase collision detection**:
1. **Broad phase**: Traverse quadtree. If edge crosses fully-hazardous node → collision. If no hazards → clear.
2. **Narrow phase**: For indeterminate cases, test unresolved edges via line segment intersection.

**Fail-fast surrogates**: Before exact polygon tests, check cheaper approximations:
- **Poles of Inaccessibility**: Circles inscribed as far from boundaries as possible. Fast to transform and test.
- **Piers**: Line segments in narrow regions of pieces.

**Design philosophy**: Always err on the side of caution. False positives (reporting collision when none exists) are acceptable. False negatives (missing a real collision) are forbidden. Exact fits are always deemed infeasible.

**Performance**: Capable of millions of collision queries per second.

### 3.7 Image-Based Representation

From Meng et al. 2025. Represent pieces as binary images. Use normalized 2D cross-correlation for template matching to find placement positions. Overlap detection via pixel counting.

**Pros**: No polygon math needed, naturally handles any shape, simple implementation.
**Cons**: Limited to discrete rotation angles (0°, 90°, 180°, 270° in the paper), precision tied to pixel resolution, greedy placement with no backtracking, no guarantee of optimality.

---

## 4. PLACEMENT HEURISTICS (LAYER 2)

### 4.1 Bottom-Left Fill (BLF)

The most common placement heuristic. For each piece (in the given order): place it as far bottom-left as possible without overlap, filling gaps in previously placed pieces.

**Algorithm**:
1. Sort pieces (typically by decreasing bounding box area)
2. For each piece and each allowed rotation:
   - Try to place at the lowest, leftmost feasible position
   - Use NFP or semi-discrete overlap checks
3. Select the rotation that produces the minimum strip length increase

**Characteristics**: Greedy, fast, produces compact layouts. Usually embedded inside a meta-heuristic loop that varies the piece ordering.

**Semi-discrete BLF** (Cherri et al. 2022): Instead of NFP-based feasibility, check y-interval overlaps on resolution lines. For each piece interval, if it overlaps a filled interval, shift upward to minimum clear y. If no valid y exists on current line, move to next resolution line.

### 4.2 NFP-Guided Placement

Use the NFP and IFP directly to enumerate or sample feasible positions. Place the piece at the position that optimizes some criterion (leftmost, lowest gravity center, maximum utilization).

### 4.3 Lowest Gravity Center

Select the position that minimizes the center of gravity of the piece — pushing it as close to already-placed pieces as possible. Effective for producing dense, stable layouts.

### 4.4 Maximum Utilization

Select the position that maximizes area utilization in the current container. Greedy for local density.

---

## 5. SEARCH STRATEGIES (LAYER 3)

### 5.1 Genetic Algorithm (GA)

The most common meta-heuristic for nesting. Encode the piece ordering and rotations as a chromosome. Use selection, crossover, and mutation to evolve a population of solutions. Each individual is evaluated by running the placement heuristic and measuring strip length or utilization.

**Typical encoding**: Permutation of piece indices (ordering) + rotation angles.

### 5.2 Simulated Annealing (SA)

Accept worse solutions with decreasing probability (temperature schedule). Swap piece orderings or adjust rotations as neighborhood moves. Often competitive with GA for nesting.

### 5.3 Sparrow: Local Search with Collision Resolution (CURRENT SOTA)

From Gardeyn 2025. The current state-of-the-art for 2D irregular strip packing.

**Core idea**: Instead of maintaining feasibility throughout the search, **allow temporary collisions** and use local search to resolve them.

**Architecture** — two phases:

**Phase 1 — Exploration**:
1. Start with a greedy initial solution
2. Shrink the strip by R_e = 1% (making it infeasible)
3. Run the **separation procedure**: iteratively move colliding items to resolve overlaps
4. If all collisions resolved → feasible solution found → shrink again
5. If stuck → add to pool of infeasible solutions, disrupt by swapping two large items, retry
6. Continue until time limit TL_e (80% of total time)

**Phase 2 — Compression**:
1. Start from best feasible solution from exploration
2. Shrink strip by progressively smaller amounts (R starts at 0.05%, decays to 0.001%)
3. Run separation procedure for each shrink
4. Continue until time limit TL_c (20% of total time)

**Separation procedure** (the core local search):
1. Identify all colliding items I_c
2. For each colliding item (random order):
   - **Sample** random positions in the strip (uniform + focused near current position)
   - **Evaluate** each sample using collision severity × item-pair weights
   - **Refine** best samples via adaptive coordinate descent
   - Move item to best found position
3. **Update weights** using Guided Local Search: increase weights for frequently-colliding pairs, decay weights for resolved pairs
4. **Strike mechanism**: If no improvement after n_max iterations, add a strike. After k_max strikes, restore best solution and restart.

**Key parameters** (from Gardeyn's experiments):
| Parameter | Value | Meaning |
|-----------|-------|---------|
| R_e | 1% | Exploration shrink ratio |
| R_s^u, R_s^l | 0.05%, 0.001% | Compression shrink range |
| M_u, M_l, M_d | 2.0, 1.2, 0.95 | GLS weight multipliers |
| N_WORKERS | 3 | Parallel threads for move_items |
| K_e, N_e | 3, 200 | Exploration: strikes, iterations per strike |
| K_c, N_c | 5, 100 | Compression: strikes, iterations per strike |
| TL_e, TL_c | 16min, 4min | Time limits (of 20min total) |

**Benchmark results** (utilization ρ, higher = better):
| Instance | Sparrow | Previous SOTA (ROMA) | Improvement |
|----------|---------|---------------------|-------------|
| ALBANO | 89.47% | 87.55% | +1.9% |
| DAGLI | 89.26% | 87.50% | +1.8% |
| JAKOBS2 | 84.77% | 83.77% | +1.0% |
| MAO | 86.14% | 83.76% | +2.4% |
| SHIRTS | 89.66% | 87.62% | +2.0% |
| SWIM | 78.26% | 74.29% | +4.0% |
| TROUSERS | 91.73% | 90.48% | +1.3% |

Sparrow beats or matches previous SOTA on all 13 standard benchmark instances.

### 5.4 GFPack++: ML-Based Placement (ICCV 2025)

From Xue et al. 2024/2025. A fundamentally different paradigm using deep learning.

**Architecture**: Score-based diffusion model that learns a gradient field to guide piece placement.

**How it works**:
1. Encode each polygon as a graph of contour points with GCN (4 layers)
2. Use multi-head attention to encode relationships between polygons
3. Diffusion process: start from random positions, iteratively denoise using learned velocity field
4. Model predicts (x, y, θ) velocities for each piece at each timestep
5. 128 diffusion steps per inference
6. Run batch of 128–512 samples, select best result

**Training**: Uses SVGnest as teacher to generate ~100K training examples. Trained on 4× RTX 4090 GPUs for 168+ hours. Loss: denoising score matching.

**Key results** (avg utilization):
| Dataset | SVGnest | GFPack++ |
|---------|---------|----------|
| Garment | 74.22% | 77.04% |
| Dental | 73.64% | 75.51% |
| Puzzle (square) | 67.22% | 92.15% |
| Puzzle (arbitrary) | 74.51% | 98.16% |

**Strengths**: Supports continuous rotation, fast inference (0.2–15s), excels at high-utilization scenarios.
**Limitations**: No strict collision-free guarantee (needs post-processing), limited to shapes seen in training distribution, struggles with strip packing under rotation constraints, requires GPU.

### 5.5 Other Meta-Heuristics

- **Ant Colony Optimization (ACO)**: Pheromone-based search for piece ordering. Good for sequential optimization.
- **Particle Swarm Optimization (PSO)**: Simpler and faster than GA. Often converges prematurely.
- **Tabu Search**: Prevents backtracking. Good for escaping local optima.
- **Cuckoo Search**: Guided random seeding. Less widely used.
- **Hyper-Heuristics**: High-level algorithms that select which low-level heuristic to apply. Good robustness across problem instances.

---

## 6. CHOOSING AN APPROACH: DECISION GUIDE

### By Priority

| If you need... | Use... | Why |
|----------------|--------|-----|
| Best packing quality, time not critical | Sparrow (jagua-rs + local search) | Current SOTA on all benchmarks |
| Custom solver with own search strategy | jagua-rs as geometry engine | Clean API, swap search freely |
| Quick browser demo / prototype | SVGnest (JavaScript) | Runs in browser, well-known |
| ML-based placement / continuous rotation | GFPack++ (PyTorch) | Novel, fast, but less mature |
| Very fast greedy placement (speed over quality) | Semi-discrete BLF (Cherri 2022) | 1000x+ faster than NFP, ~15% more waste |
| Only NFP generation | libnfporb (C++) or Rocha algorithm | Standalone geometric primitive |
| Educational / readable prototype | seanys Python repo | Step-by-step Python |

### By Implementation Complexity

1. **Simplest**: Image-based template matching (Meng 2025). Binary images, cross-correlation, no polygon math. Limited to 4 rotation angles.
2. **Moderate**: Semi-discrete BLF (Cherri 2022). Discretize x-axis, interval comparisons. Fast, reasonable quality.
3. **Standard**: NFP + BLF + GA. The "classic" nesting pipeline. Well-understood, many implementations exist (SVGnest, libnest2d).
4. **Advanced**: jagua-rs as engine + custom search. Decoupled architecture, best extensibility.
5. **State-of-the-art**: Sparrow. Collision-tolerant local search on jagua-rs. Best results but complex to implement from scratch.

### Recommended Reading Order

**Phase 1 — Understand the problem**: Lu et al. 2022 survey (Paper 1). Skim Meng et al. 2025 (Paper 7) literature review section for 2025-era context.

**Phase 2 — Understand the geometry**: Rocha et al. 2019 (Paper 2) for NFP generation. Cherri et al. 2022 (Paper 3) for semi-discrete alternative.

**Phase 3 — Study the state of the art**: Gardeyn 2024 (Paper 4, jagua-rs architecture) then Gardeyn 2025 (Paper 5, Sparrow algorithm). Xue et al. 2025 (Paper 6, GFPack++) for the ML frontier.

**Phase 4 — Study code**: Clone Sparrow or jagua-rs for classical. Clone GFPack-pp for ML. Clone SVGnest for simplest readable NFP+GA.

---

## 7. OPEN-SOURCE REPOSITORIES

### Tier 1: Production-Ready / Academic SOTA

| Repository | Language | URL | Notes |
|-----------|----------|-----|-------|
| **Sparrow** | Rust | github.com/JeroenGar/sparrow | Current SOTA solver. Python wrapper: github.com/PaulDL-RS/spyrrow |
| **jagua-rs** | Rust | github.com/JeroenGar/jagua-rs | Collision detection engine. Peer-reviewed (INFORMS JoC). Use as geometry backend. |
| **SVGnest** | JavaScript | github.com/Jack000/SVGnest | Most popular (~3k stars). NFP+GA. Browser-based. No longer SOTA quality. |

### Tier 2: Specialized

| Repository | Language | URL | Notes |
|-----------|----------|-----|-------|
| **GFPack-pp** | Python/PyTorch | github.com/TimHsue/GFPack-pp | ML-based (ICCV 2025). Continuous rotation support. |
| **libnest2d** | C++11 | github.com/tamasmeszaros/libnest2d | Used in PrusaSlicer. Clean API for bin packing. |
| **libnfporb** | C++ | github.com/kallaballa/libnfporb | Standalone NFP generation via orbiting. |

### Tier 3: Educational

| Repository | Language | URL | Notes |
|-----------|----------|-----|-------|
| **2D-Irregular-Packing-Algorithm** | Python | github.com/seanys/2D-Irregular-Packing-Algorithm | BLF + GA + NFP in readable Python. Not production-speed. |

---

## 8. KEY CONCEPTS GLOSSARY

| Term | Definition |
|------|-----------|
| **NFP (No-Fit Polygon)** | Locus of positions for piece B's reference point where A and B touch but don't overlap. Core geometric primitive. Generated via orbiting, decomposition, or Minkowski sums. |
| **IFP (Inner-Fit Polygon)** | Locus of positions for a piece's reference point where it's fully inside the container. Feasible region = IFP minus all NFPs. |
| **BLF (Bottom-Left Fill)** | Greedy heuristic: place each piece at the lowest, leftmost feasible position. Fast, usually inside a meta-heuristic loop. |
| **Strip Packing (2DISPP)** | Pack items on a fixed-width strip, minimizing length. Most common academic formulation. |
| **Bin Packing (2DIBPP)** | Pack items into fewest fixed-size bins. Common in manufacturing with fixed stock sheets. |
| **Phi-Functions** | Mathematical functions: positive when separated, zero when touching, negative when overlapping. Used in mathematical programming. |
| **Hazard** | Unified abstraction in jagua-rs for any spatial constraint (other items = interior hazards, container boundary = exterior hazard). |
| **Pole of Inaccessibility** | Point inside a polygon furthest from all boundaries. Used for numerically safe point-in-polygon tests. |
| **Semi-Discrete Repr.** | Discretize x-axis only (vertical lines at spacing R), keep y continuous. Trades precision for massive speed gain. |
| **GLS (Guided Local Search)** | Weight-based mechanism to escape local optima: increase weights on frequently-violated constraints, decay when resolved. |
| **Separation Procedure** | Sparrow's core: allow temporary collisions, iteratively move pieces to resolve all overlaps. |
| **Score-Based Diffusion** | GFPack++'s approach: learn a gradient field that guides pieces from random positions to good placements via iterative denoising. |

---

## 9. STANDARD BENCHMARK INSTANCES

These datasets are used across the literature for comparison:

ALBANO, DAGLI, FU, JAKOBS1, JAKOBS2, MAO, MARQUES, SHAPES0, SHAPES1, SHAPES2, SHIRTS, SWIM, TROUSERS

When evaluating a nesting algorithm, report utilization density ρ (higher = better, expressed as percentage of strip area actually used by pieces). Current best results (Sparrow): 68–92% depending on instance.

---

## 10. SOURCES

All papers are freely accessible:

1. Lu et al. 2022 — "Two-Dimensional Irregular Packing Problems: A Review" — Frontiers in Mechanical Engineering — https://www.frontiersin.org/articles/10.3389/fmech.2022.966691/full
2. Rocha et al. 2019 — "Robust NFP Generation for Nesting Problems" — arXiv:1903.11139 — https://arxiv.org/abs/1903.11139
3. Chehrazad, Roose & Wauters 2022 — "A Fast and Scalable Bottom-Left-Fill Algorithm" — arXiv:2103.08739 — https://arxiv.org/abs/2103.08739
4. Gardeyn & Vanden Berghe 2024 — "Decoupling Geometry from Optimization" (jagua-rs) — arXiv:2508.08341 — https://arxiv.org/abs/2508.08341
5. Gardeyn & Vanden Berghe 2025 — "An Open-Source Heuristic to Reboot 2D Nesting Research" (Sparrow) — arXiv:2509.13329 — https://arxiv.org/abs/2509.13329
6. Xue et al. 2025 — "GFPack++: Improving 2D Irregular Packing by Learning Gradient Field with Attention" — ICCV 2025 / arXiv:2406.07579 — https://arxiv.org/abs/2406.07579
7. Meng et al. 2025 — "Optimizing 2D irregular packing via image processing and computational intelligence" — Nature Scientific Reports — https://www.nature.com/articles/s41598-025-97202-0
