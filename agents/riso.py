"""Two-ink risograph look shared by the generated stills, the Editor overlays,
the agent graph and the report.

The medium has four parts and nothing else:
  paper   - cool newsprint with fibre noise
  blue    - every word that must be read and every structural line
  scarlet - one accent per frame, printed on its own plate 5 px off register
  overprint / halftone - plates multiply where they overlap; shading is dots, never gradients
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PAPER = (237, 233, 224)
BLUE = (38, 58, 140)
RED = (232, 65, 44)
MISREG = (5, 3)          # scarlet plate offset in px


def hexc(rgb):
    return "#%02x%02x%02x" % rgb


class Plates:
    """Two greyscale ink masks (0 = no ink, 255 = full ink) drawn like print separations."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.blue = Image.new("L", (w, h), 0)
        self.red = Image.new("L", (w, h), 0)
        self.b = ImageDraw.Draw(self.blue)
        self.r = ImageDraw.Draw(self.red)

    def halftone(self, plate: str, box, density: float, pitch: int = 14, angle_shift: bool = False):
        """Fill `box` with a dot screen; density 0..1 sets the dot radius."""
        d = self.b if plate == "blue" else self.r
        x0, y0, x1, y1 = map(int, box)
        rad = max(0.6, pitch * 0.5 * np.sqrt(density) * 1.15)
        for j, y in enumerate(range(y0, y1, pitch)):
            off = pitch // 2 if (j % 2 and angle_shift) else 0
            for x in range(x0 + off, x1, pitch):
                d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=255)

    def mask_halftone(self, plate: str, mask: Image.Image, pitch: int = 12):
        """Turn a soft greyscale mask into dots (radius follows the mask value)."""
        d = self.b if plate == "blue" else self.r
        m = np.asarray(mask.convert("L"), dtype=np.float32) / 255
        for y in range(pitch // 2, self.h, pitch):
            for x in range(pitch // 2, self.w, pitch):
                v = m[min(y, m.shape[0] - 1), min(x, m.shape[1] - 1)]
                if v > 0.04:
                    r = pitch * 0.5 * np.sqrt(v) * 1.1
                    d.ellipse([x - r, y - r, x + r, y + r], fill=255)

    def print(self, seed: int = 0, paper: Image.Image | None = None) -> Image.Image:
        """Multiply both plates onto paper, with ink texture and the scarlet plate off register."""
        rng = np.random.default_rng(seed)
        base = np.asarray(paper if paper is not None else paper_texture(self.w, self.h, seed),
                          dtype=np.float32) / 255
        out = base.copy()
        for plate, col, shift in ((self.blue, BLUE, (0, 0)), (self.red, RED, MISREG)):
            m = np.asarray(plate, dtype=np.float32) / 255
            if shift != (0, 0):
                m = np.roll(np.roll(m, shift[1], axis=0), shift[0], axis=1)
            # riso ink never lays down perfectly flat: speckle + slight starvation
            tex = 0.86 + 0.14 * rng.random(m.shape, dtype=np.float32)
            a = (m * tex * 0.95)[..., None]
            ink = np.array(col, np.float32) / 255
            out = out * (1 - a + a * ink)
        return Image.fromarray((out.clip(0, 1) * 255).astype(np.uint8), "RGB")


def paper_texture(w: int, h: int, seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed + 7)
    base = np.ones((h, w, 3), np.float32) * np.array(PAPER, np.float32)
    fine = rng.normal(0, 3.2, (h, w, 1)).astype(np.float32)
    fibre = Image.fromarray((rng.random((h // 6 + 1, w // 2 + 1)) * 255).astype(np.uint8))
    fibre = np.asarray(fibre.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2)),
                       np.float32)[..., None] / 255 - 0.5
    return Image.fromarray((base + fine + fibre * 7).clip(0, 255).astype(np.uint8), "RGB")
