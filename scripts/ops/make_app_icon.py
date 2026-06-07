#!/usr/bin/env python
"""Generate VolScope.app's icon (VolScope.icns) from scratch.

Draws the ◈ wordmark on a dark squircle in the brand gradient, renders a
1024px master, then builds the full .iconset and runs `iconutil` to produce
the .icns. Re-run any time the brand changes:

    .venv/bin/python scripts/ops/make_app_icon.py

Depends on Pillow (a Streamlit transitive dep) + macOS `iconutil`/`sips`.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_ROOT = Path(__file__).resolve().parents[2]
_ICNS_OUT = _ROOT / "VolScope.app" / "Contents" / "Resources" / "VolScope.icns"

# Brand palette (mirrors volscope/ui/styles/theme.py COLORS).
_BG_TOP = (10, 11, 15)        # #0a0b0f
_BG_BOT = (18, 19, 26)        # #12131a
_ACCENT = (0, 212, 170)       # #00d4aa
_ACCENT2 = (91, 140, 255)     # #5b8cff
_TEXT = (224, 228, 239)       # #e0e4ef

_S = 1024                     # master size


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vertical_gradient(size: int, top: tuple, bot: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        grad.putpixel((0, y), _lerp(top, bot, y / max(1, size - 1)))
    return grad.resize((size, size))


def _squircle_mask(size: int, radius_frac: float = 0.225) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/System/Library/Fonts/SFNSRounded.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_diamond(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
                  color: tuple, width: int) -> None:
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    draw.line(pts + [pts[0]], fill=color, width=width, joint="curve")


def _master() -> Image.Image:
    bg = _vertical_gradient(_S, _BG_TOP, _BG_BOT).convert("RGBA")
    layer = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cx, cy = _S // 2, int(_S * 0.42)
    # Filled diamond with a gradient feel: a solid accent diamond + an inner
    # accent2 diamond, plus a soft glow ring.
    _draw_diamond(d, cx, cy, int(_S * 0.205), _ACCENT, width=int(_S * 0.018))
    _draw_diamond(d, cx, cy, int(_S * 0.125), _ACCENT2, width=int(_S * 0.014))
    d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=_ACCENT)

    # Wordmark
    font = _load_font(int(_S * 0.105))
    text = "VolScope"
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text((cx - tw / 2 - tb[0], int(_S * 0.66) - tb[1]), text,
           font=font, fill=_TEXT)

    out = Image.alpha_composite(bg, layer)
    mask = _squircle_mask(_S)
    rounded = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    rounded.paste(out, (0, 0), mask)
    return rounded


def main() -> int:
    _ICNS_OUT.parent.mkdir(parents=True, exist_ok=True)
    master = _master()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "VolScope.iconset"
        iconset.mkdir()
        specs = [
            (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
        ]
        for px, name in specs:
            master.resize((px, px), Image.LANCZOS).save(iconset / name)
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(_ICNS_OUT)],
            check=True,
        )
    print(f"wrote {_ICNS_OUT}  ({_ICNS_OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
