"""CLI entrypoint: ``python -m src.assets.sprites``.

Regenerates the on-disk sprite cache. Intended to be wired into the
``Makefile`` as ``make sprites``.
"""

from __future__ import annotations

import argparse
import os
import sys

import pygame

from ...core import config
from . import generate_all, regenerate


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m src.assets.sprites",
        description="Regenerate procedural sprites used by fac-py.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing sprites (default: only write missing ones).",
    )
    p.add_argument(
        "--key",
        "-k",
        action="append",
        default=[],
        metavar="KEY",
        help="Regenerate only the given sprite key (may be repeated). Implies --force.",
    )
    p.add_argument("--tile", type=int, default=None, help="Override config.TILE.")
    p.add_argument("--item", type=int, default=None, help="Override config.ITEM_PX.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.tile is not None:
        config.TILE = int(args.tile)
    if args.item is not None:
        config.ITEM_PX = int(args.item)

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    try:
        pygame.display.set_mode((1, 1))
    except pygame.error:
        pass

    if args.key:
        keys = regenerate(keys=args.key)
        print(f"Regenerated {len(keys)} sprite(s):")
        for k in keys:
            print(f"  {k}")
    else:
        generate_all(force=args.force)
        print("Sprite generation complete.")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
