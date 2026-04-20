# fac-py

A top-down, pixel-art factory game scaffold in Python, built on `pygame-ce`,
engineered for **1,000,000 items on belts at 20 Hz** on a developer laptop.

It ships with:

- A centralized **design system** (palette, typography scale, theme tokens).
- A centralized **asset loader** with procedural sprite generation, a
  **zoom-quantized scaled-sprite cache**, and an LRU text cache.
- A working **item system**, **conveyor belt system**, and **building system**
  with typed input/output ports, recipes, and smooth animations.
- A **data-oriented belt simulator** (`BeltChainsSoA`): chains of belts are
  packed into contiguous `int16` NumPy arrays, and one tick is three
  vectorised ops across all chains.
- **Chunked rendering** with dirty-chunk baking, frustum culling and batched
  `surface.blits` so even at 1M items the renderer stays under the 16.7 ms
  budget on a single thread.
- A **fixed-timestep simulation** (20 Hz) decoupled from a 60 FPS render
  with `prev_slots` / `prev_offset` interpolation for buttery-smooth
  belts and items.
- A built-in **benchmark scene**, a **headless CLI bench**, and a
  **pytest-benchmark** perf-gate suite wired to CI.

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

First launch will:

1. Download the two Google Fonts into `assets/fonts/` (requires internet, one-time).
2. Generate all sprites into `assets/sprites/` from the color palette.

If you prefer to pre-populate fonts, drop these `.ttf` files into `assets/fonts/`:

- `PressStart2P-Regular.ttf` (Apache 2.0)
- `PixelifySans-Regular.ttf`, `PixelifySans-Medium.ttf`,
  `PixelifySans-SemiBold.ttf`, `PixelifySans-Bold.ttf` (SIL OFL 1.1)

## Controls

| Key / Action        | Effect                                     |
| ------------------- | ------------------------------------------ |
| WASD / Arrows       | Pan camera                                 |
| Middle-mouse drag   | Pan camera (1:1, with release inertia)     |
| Scroll wheel        | Zoom                                       |
| 1 - 5          | Select prefab (belt, miners, assemblers)        |
| R              | Rotate placement (or rotate building under cursor) |
| T              | Mirror placement (flip perpendicular to facing) |
| Mouse 4 (X1)   | Rotate placement (secondary binding)            |
| Mouse 5 (X2)   | Mirror placement (secondary binding)            |
| Left click     | Place                                           |
| Right click    | Delete                                          |
| **F3**         | Toggle live performance HUD                     |
| **F4**         | Toggle sprite studio                            |
| **J**          | Toggle objectives / stats window                |
| Esc            | Back / quit                                     |
| Enter (menu)   | Play                                            |
| **B (menu)**   | Launch the 1M-item benchmark scene              |

> **Rotation & Mirror**: Every placeable structure is rotatable in 90°
> steps via `R` / Mouse 4. Mirror (`T` / Mouse 5) performs a
> left/right flip across the building's facing axis -- for an
> East-facing assembler it swaps the input/output rows between the top
> and bottom of the footprint. Rotation and mirror are honoured by port
> simulation, rendering, the placement ghost, and the structure menu
> diagram. Pressing the same key while hovering a placed building
> rotates / mirrors that building in place (items buffered on its
> output port are flushed onto adjacent belts before the layout moves).

## Benchmarking

Three complementary harnesses share the same perf budgets in
`src/core/config.py`:

### 1. In-game benchmark scene

Press **B** on the title screen (or call `replace_scene(BenchmarkScene())`).
You get a cinematic flyover over a ~1M-item layout, a short warmup, a
15-second measurement window, and a PASS/FAIL banner keyed off the gates.

### 2. Headless CLI (`make bench`)

```bash
python -m bench                          # 1M items, 600 ticks
python -m bench --items 500000 --ticks 400
python -m bench --json                   # machine-readable output
python -m bench --render                 # also time a headless render pass
```

The CLI uses `SDL_VIDEODRIVER=dummy` and exits **non-zero** the instant any
gate is violated, so it plugs straight into CI.

### 3. pytest-benchmark gates (`make perf`)

```bash
pytest -m bench tests/benchmarks
```

- `test_chain_build_under_gate` — 1M-item SoA construction
- `test_belt_tick_p95_under_gate` — 1M-item `SoA.tick` p95 + max
- `test_render_frame_p95_under_gate` — headless render pass p95

### Perf gates (defaults)

| Metric              | Gate (ms) | Where                       |
| ------------------- | --------- | --------------------------- |
| `belt_tick_p95`     | 20.0      | `GATE_BELT_TICK_P95_MS`     |
| `belt_tick_max`     | 40.0      | `GATE_BELT_TICK_MAX_MS`     |
| `render_frame_p95`  | 16.7      | `GATE_RENDER_FRAME_P95_MS`  |
| `chain_build`       | 500.0     | `GATE_CHAIN_BUILD_MS`       |

## Testing

```bash
make test          # default unit tests (golden traces, topology)
make perf          # perf-gate benchmarks (slower; bench-marked tests only)
make lint          # ruff
```

Or directly:

```bash
pytest                    # unit run (bench-marked tests auto-deselected)
pytest -m bench           # only the perf gates
```

## Folder map

```text
fac-py/
  main.py
  bench/                  headless CLI benchmark
  assets/
    fonts/                Google Fonts TTFs
    sprites/              procedurally generated PNGs (cache)
  src/
    core/         game loop, config, clock, input, event bus, perf counters
    design/       palette, typography, theme, easing
    assets/       asset loader + procedural sprite generator
    world/        grid (dirty chunks), tile, camera, direction, world
    items/        item types + registry + int16 SoA item ids + pool
    belts/        ConveyorBelt tile, BeltChainsSoA, topology builder
    buildings/    Port (ring buffer), building base, miner, assembler, registry
    rendering/    chunk renderer, scaled-sprite cache, cull, surface pool,
                  layers, renderer, tween/animation, pixel helpers
    stats/        StatsTracker, ObjectivesState + catalog
    ui/           widget, HUD, toolbar, placement cursor, perf HUD,
                  sprite studio, objectives window
    scenes/       scene base, menu, play, benchmark
  tests/
    conftest.py
    test_belt_sim.py          golden traces for SoA tick
    test_topology.py          chain merge / successor / port tests
    benchmarks/
      test_perf_gates.py      pytest-benchmark perf gates
```

## Architecture notes

- **Struct-of-arrays belt sim.** A belt chain is a maximal linear run of
  belts. All chains share four NumPy arrays (`slots`, `chain_offset`,
  `boundary_mask`, topology). One tick =
  `(propagation) → (tail exits) → (render snapshot)`, each a single
  vectorised write across every slot.
- **Sim/render decoupling.** `clock.dt` drives the render loop; the
  simulator always steps at fixed 20 Hz. Items are drawn at
  `slots` + `sim_alpha * prev_offset`, so the 60 FPS render sees smooth
  motion even though the sim only moves items at 20 discrete steps per
  second.
- **Allocation discipline.** Hot paths allocate nothing: `Port` is a
  NumPy ring buffer, `ItemType` ids are `int16`, the event bus defers
  handler removals, and UI overlays reuse surfaces from `SurfacePool`.
- **Rendering budget.** Floor + belt backgrounds are baked per
  `CHUNK_SIZE` (16x16) chunk per zoom bin. Only dirty chunks re-bake.
  Animated belts and items are culled per-chain and drawn via
  `surface.blits` in a single call per chain.

## Objectives & stats

The play scene owns a single `StatsTracker` (`src/stats/tracker.py`)
that subscribes once to `item.produced`, `item.consumed`,
`building.placed`, and `building.removed`. It keeps per-item
1-second ring buffers over the last hour of history (so every UI
query window fits inside) and surfaces totals, rates, averages,
medians, mins, maxes, peaks, and per-second net series through a
read-only query API. Building counts are mirrored into both
per-prefab and per-class buckets, and a session record samples
belt-tile / building / items-in-world totals once per simulated
second. Both the HUD tooltip and the objectives window read from
that single source of truth.

On top of the tracker, `ObjectivesState` (`src/stats/objectives.py`)
evaluates an immutable catalog of `ObjectiveSpec` entries each
frame -- produce totals, sustained rates over a rolling window,
building-count milestones, belt-tile milestones -- and emits
`objective.completed` on the event bus the first tick a spec
crosses its threshold. The default catalog in
`src/stats/catalog.py` chains tiers via `prereq_ids` so late-game
goals stay locked until their foundations are done.

Press **J** (or click the `OBJECTIVES` pill in the top HUD bar, next
to `RESEARCH`) to open a right-docked, slide-in window with four
tabs -- Objectives, Items, Buildings, Session -- mirroring the
`SpriteStudio` idiom (beveled panels, `Tween` / `AnimValue`
animations, `_Hit` dispatch, `THEME` / `PALETTE` / `TYPE` tokens)
so it feels native to the rest of the UI.

## Fonts / licensing

- **Press Start 2P** by CodeMan38 — Apache License 2.0
- **Pixelify Sans** by Stefie Justprince — SIL Open Font License 1.1

Both are permissive. Attribution is included in `assets/fonts/LICENSE.txt`
once the loader fetches them.
