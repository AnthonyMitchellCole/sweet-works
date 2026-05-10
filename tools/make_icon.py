"""Bake the OS window/app icon from ``assets/branding/menu_logo.png``.

Produces two artefacts next to the source logo:

* ``icon.png`` -- a square 256x256 RGBA snapshot used at runtime by
  :func:`pygame.display.set_icon` (loaded in ``Game.__init__``).
* ``icon.ico`` -- a multi-resolution Windows icon (16/32/48/64/128/256)
  for shortcut + installer use.

Pipeline (deliberately simple so the result stays in lockstep with whatever
artwork lives at ``menu_logo.png``):

1. Open the logo as RGBA.
2. Crop tightly to the opaque content (``image.getbbox()`` on the alpha
   channel) so any transparent margin baked into the source PNG is
   stripped before sizing.
3. Pad the shorter side with transparency so the canvas becomes a square
   without distorting the aspect ratio.
4. Resize to 256x256 with Lanczos resampling.
5. Save as ``icon.png`` and as a multi-size ``icon.ico``.

This script is dev-only -- runtime never imports Pillow.

Usage::

    python -m tools.make_icon
    python -m tools.make_icon --source assets/branding/menu_logo.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - dev-only dep
    raise SystemExit(
        "Pillow is required to bake icons. Install dev deps:\n"
        "    python -m pip install 'pillow>=10'"
    ) from exc


_ROOT: Path = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE: Path = _ROOT / "assets" / "branding" / "menu_logo.png"
_DEFAULT_PNG: Path = _ROOT / "assets" / "branding" / "icon.png"
_DEFAULT_ICO: Path = _ROOT / "assets" / "branding" / "icon.ico"

# Resolutions baked into the multi-res .ico. 16 -> 256 covers everything from
# Explorer's tiny list view up to the largest "extra-large" icons.
_ICO_SIZES: tuple[tuple[int, int], ...] = (
    (16, 16),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)

# Final ``icon.png`` size -- 256x256 matches the largest .ico tier and is
# what pygame.display.set_icon() picks up at runtime.
_PNG_SIZE: int = 256


def _trim_to_content(image: Image.Image) -> Image.Image:
    """Crop transparent margins; no-op when the logo already fills the canvas."""
    bbox = image.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def _pad_to_square(image: Image.Image) -> Image.Image:
    """Centre-pad the shorter side with transparency so the canvas is square."""
    w, h = image.size
    side = max(w, h)
    if w == h:
        return image
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - w) // 2, (side - h) // 2), image)
    return canvas


def bake(source: Path, out_png: Path, out_ico: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source logo not found: {source}")

    out_png.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as raw:
        rgba = raw.convert("RGBA")

    trimmed = _trim_to_content(rgba)
    square = _pad_to_square(trimmed)
    icon = square.resize((_PNG_SIZE, _PNG_SIZE), Image.Resampling.LANCZOS)

    icon.save(out_png, format="PNG", optimize=True)
    icon.save(out_ico, format="ICO", sizes=_ICO_SIZES)

    print(f"Wrote {out_png.relative_to(_ROOT)}  ({_PNG_SIZE}x{_PNG_SIZE} RGBA)")
    print(f"Wrote {out_ico.relative_to(_ROOT)}  ({len(_ICO_SIZES)} sizes)")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m tools.make_icon",
        description=__doc__.splitlines()[0] if __doc__ else None,
    )
    p.add_argument(
        "--source",
        type=Path,
        default=_DEFAULT_SOURCE,
        help=f"Source logo PNG (default: {_DEFAULT_SOURCE.relative_to(_ROOT)}).",
    )
    p.add_argument(
        "--out-png",
        type=Path,
        default=_DEFAULT_PNG,
        help=f"Destination PNG (default: {_DEFAULT_PNG.relative_to(_ROOT)}).",
    )
    p.add_argument(
        "--out-ico",
        type=Path,
        default=_DEFAULT_ICO,
        help=f"Destination ICO (default: {_DEFAULT_ICO.relative_to(_ROOT)}).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    bake(args.source, args.out_png, args.out_ico)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
