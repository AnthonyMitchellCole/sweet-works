# fac-py

A top-down, pixel-art factory game scaffold in Python, built on `pygame-ce`.

It ships with:

- A centralized **design system** (palette, typography scale, theme tokens).
- A centralized **asset loader** with procedural sprite generation (no art required).
- A working **item system**, **conveyor belt system**, and **building system** with
  typed input/output ports, recipes, and smooth animations.
- A fixed-timestep simulation (20 Hz) decoupled from a 60 FPS render with
  interpolation for buttery-smooth belts and items.

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

| Key / Action   | Effect                                     |
| -------------- | ------------------------------------------ |
| WASD / Arrows  | Pan camera                                 |
| Scroll wheel   | Zoom                                       |
| 1 - 5          | Select prefab (belt, miners, assembler)    |
| R              | Rotate placement                           |
| Left click     | Place                                      |
| Right click    | Delete                                     |
| Esc            | Back / quit                                |
| Enter (menu)   | Start                                      |

## Folder map

```text
fac-py/
  main.py
  assets/
    fonts/                  Google Fonts TTFs
    sprites/                procedurally generated PNGs (cache)
  src/
    core/         game loop, config, clock, input, event bus
    design/       palette, typography, theme, easing
    assets/       asset loader + procedural sprite generator
    world/        grid, tile, camera, direction, world
    items/        item types + registry + runtime items
    belts/        conveyor belt, belt network, renderer
    buildings/    port, building base, miner, assembler, registry
    rendering/    layers, renderer, tween/animation, pixel helpers
    ui/           widget, HUD, toolbar, placement cursor
    scenes/       scene base, menu, play
```

## Fonts / licensing

- **Press Start 2P** by CodeMan38 — Apache License 2.0
- **Pixelify Sans** by Stefie Justprince — SIL Open Font License 1.1

Both are permissive. Attribution is included in `assets/fonts/LICENSE.txt` once
the loader fetches them.
