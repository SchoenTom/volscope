#!/usr/bin/env python
"""Compose the README hero banner: wordmark + tagline + the real IV/HV chart.

Expects docs/assets/iv-hv.png (the rendered Scope chart) to already exist.
Produces docs/assets/hero.png — the single eyecatcher at the top of the README.

    .venv/bin/python scripts/ops/make_repo_hero.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_ROOT = Path(__file__).resolve().parents[2]
_CHART = _ROOT / "docs" / "assets" / "iv-hv.png"
_OUT = _ROOT / "docs" / "assets" / "hero.png"

# Brand palette (theme.py COLORS)
_BG_TOP = (10, 11, 15)
_BG_BOT = (16, 17, 24)
_ACCENT = (0, 212, 170)
_ACCENT2 = (91, 140, 255)
_WARN = (255, 68, 102)
_TEXT = (224, 228, 239)
_MUTED = (138, 143, 158)
_FAINT = (90, 96, 112)

W = 1280


def _font(size: int, bold: bool = False):
    cands = (
        ["/System/Library/Fonts/SFNSRounded.ttf", "/System/Library/Fonts/SFNS.ttf"]
        if bold else
        ["/System/Library/Fonts/SFNS.ttf", "/Library/Fonts/Arial.ttf"]
    )
    cands += ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"]
    for p in cands:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _vgrad(w: int, h: int, top, bot) -> Image.Image:
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return base.resize((w, h))


def _hgrad_text(draw_size, text, font, c1, c2) -> Image.Image:
    """Render `text` filled with a horizontal c1->c2 gradient (transparent bg)."""
    tmp = Image.new("L", draw_size, 0)
    ImageDraw.Draw(tmp).text((0, 0), text, font=font, fill=255)
    grad = Image.new("RGB", draw_size)
    for x in range(draw_size[0]):
        t = x / max(1, draw_size[0] - 1)
        col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        for y in range(draw_size[1]):
            grad.putpixel((x, y), col)
    out = Image.new("RGBA", draw_size, (0, 0, 0, 0))
    out.paste(grad, (0, 0), tmp)
    return out


def main() -> int:
    chart = Image.open(_CHART).convert("RGB")
    cw, ch = chart.size
    chart_w = W - 96
    chart_h = int(ch * (chart_w / cw))
    chart = chart.resize((chart_w, chart_h), Image.LANCZOS)

    header_h = 248
    caption_h = 46
    H = header_h + chart_h + caption_h + 40

    canvas = _vgrad(W, H, _BG_TOP, _BG_BOT).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # Brand mark — a small ◈ diamond left of the wordmark
    mx, my = 60, 70
    d.line([(mx, my - 18), (mx + 18, my), (mx, my + 18), (mx - 18, my), (mx, my - 18)],
           fill=_ACCENT, width=4, joint="curve")
    d.ellipse([mx - 4, my - 4, mx + 4, my + 4], fill=_ACCENT)

    # Wordmark with gradient fill
    wf = _font(46, bold=True)
    wm = _hgrad_text((360, 64), "VolScope", wf, _ACCENT, _ACCENT2)
    canvas.alpha_composite(wm, (90, 42))

    # Tagline
    d.text((62, 128), "Is this stock's implied volatility cheap or expensive?",
           font=_font(27, bold=True), fill=_TEXT)
    # Sub-line
    d.text((62, 172),
           "A self-hosted volatility terminal — its own Black-Scholes solver "
           "(never Yahoo's IV), in a browser tab.",
           font=_font(17), fill=_MUTED)

    # Chart
    cx = (W - chart_w) // 2
    cy = header_h
    canvas.paste(chart, (cx, cy))
    # hairline frame around the chart
    d.rectangle([cx, cy, cx + chart_w - 1, cy + chart_h - 1],
                outline=(30, 32, 56), width=1)

    # Caption with the colour key
    cap_y = cy + chart_h + 16
    f = _font(15)
    d.text((cx, cap_y), "Implied vs realized volatility — ", font=f, fill=_MUTED)
    w1 = d.textlength("Implied vs realized volatility — ", font=f)
    d.text((cx + w1, cap_y), "green where options are cheap", font=f, fill=_ACCENT)
    w2 = d.textlength("green where options are cheap", font=f)
    d.text((cx + w1 + w2, cap_y), ", ", font=f, fill=_MUTED)
    w3 = d.textlength(", ", font=f)
    d.text((cx + w1 + w2 + w3, cap_y), "red where rich", font=f, fill=_WARN)
    w4 = d.textlength("red where rich", font=f)
    d.text((cx + w1 + w2 + w3 + w4, cap_y), ".   (QQQ, live data)", font=f, fill=_FAINT)

    canvas.convert("RGB").save(_OUT)
    print(f"wrote {_OUT}  ({_OUT.stat().st_size} bytes, {W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
