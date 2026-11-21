#!/usr/bin/env python3
"""The Poster for a Place That Isn't There.

A travel poster for VELMORA, the Floating Isles -- a place that does
not exist.  Pure Python 3 standard library, no network, no files read
at runtime.  All art is drawn procedurally (gradients, polygons,
circles, a hand-built vector stroke font) and the PNG is encoded by
hand with zlib.

Writes exactly one image: /output/entry.png, 1024 x 1024, <= 1 MiB.
Deterministic: fixed seed, fixed palette, fixed geometry.
"""
import math
import os
import random
import struct
import zlib

W = 1024
H = 1024
SEED = 20261121


# ---------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, w=W, h=H):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.px[i], self.px[i + 1], self.px[i + 2] = c

    def get(self, x, y):
        x = max(0, min(self.w - 1, x))
        y = max(0, min(self.h - 1, y))
        i = self._idx(x, y)
        return (self.px[i], self.px[i + 1], self.px[i + 2])

    def blend(self, x, y, c, a):
        """Alpha-over blend, a in 0..1."""
        if a <= 0.0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = self._idx(x, y)
        if a >= 1.0:
            self.px[i], self.px[i + 1], self.px[i + 2] = c
            return
        ia = 1.0 - a
        self.px[i] = int(self.px[i] * ia + c[0] * a + 0.5)
        self.px[i + 1] = int(self.px[i + 1] * ia + c[1] * a + 0.5)
        self.px[i + 2] = int(self.px[i + 2] * ia + c[2] * a + 0.5)

    def fill_rect(self, x0, y0, x1, y1, c):
        x0 = max(0, int(x0)); y0 = max(0, int(y0))
        x1 = min(self.w, int(x1)); y1 = min(self.h, int(y1))
        for y in range(y0, y1):
            i = self._idx(x0, y)
            for x in range(x0, x1):
                self.px[i], self.px[i + 1], self.px[i + 2] = c
                i += 3

    def vgrad(self, y0, y1, stops):
        """Vertical gradient; stops = [(pos0..1, (r,g,b)), ...] sorted."""
        for y in range(max(0, int(y0)), min(self.h, int(y1))):
            t = (y - y0) / max(1.0, (y1 - y0))
            c = _grad_at(stops, t)
            i = self._idx(0, y)
            for _ in range(self.w):
                self.px[i], self.px[i + 1], self.px[i + 2] = c
                i += 3

    def disc(self, cx, cy, r, c, a=1.0):
        r2 = r * r
        x0 = max(0, int(cx - r)); x1 = min(self.w - 1, int(cx + r) + 1)
        y0 = max(0, int(cy - r)); y1 = min(self.h - 1, int(cy + r) + 1)
        for y in range(y0, y1 + 1):
            dy = y - cy
            for x in range(x0, x1 + 1):
                dx = x - cx
                if dx * dx + dy * dy <= r2:
                    self.blend(x, y, c, a)

    def ellipse(self, cx, cy, rx, ry, c, a=1.0):
        x0 = max(0, int(cx - rx)); x1 = min(self.w - 1, int(cx + rx) + 1)
        y0 = max(0, int(cy - ry)); y1 = min(self.h - 1, int(cy + ry) + 1)
        for y in range(y0, y1 + 1):
            dy = (y - cy) / max(1.0, ry)
            for x in range(x0, x1 + 1):
                dx = (x - cx) / max(1.0, rx)
                if dx * dx + dy * dy <= 1.0:
                    self.blend(x, y, c, a)

    def glow(self, cx, cy, r, c, peak=0.85):
        """Soft radial glow: alpha falls off quadratically to 0 at r."""
        x0 = max(0, int(cx - r)); x1 = min(self.w - 1, int(cx + r) + 1)
        y0 = max(0, int(cy - r)); y1 = min(self.h - 1, int(cy + r) + 1)
        for y in range(y0, y1 + 1):
            dy = (y - cy) / r
            for x in range(x0, x1 + 1):
                dx = (x - cx) / r
                d2 = dx * dx + dy * dy
                if d2 < 1.0:
                    a = peak * (1.0 - d2) * (1.0 - d2)
                    self.blend(x, y, c, a)

    def poly(self, pts, c, a=1.0):
        """Scanline-filled polygon, pts = [(x,y), ...]."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.ceil(min(ys))))
        y1 = min(self.h - 1, int(math.floor(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x1, y1p = pts[i]
                x2, y2p = pts[(i + 1) % n]
                if (y1p <= y < y2p) or (y2p <= y < y1p):
                    t = (y - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                xa = max(0, int(math.ceil(xs[k])))
                xb = min(self.w - 1, int(math.floor(xs[k + 1])))
                for x in range(xa, xb + 1):
                    self.blend(x, y, c, a)

    def thick_line(self, x0, y0, x1, y1, w, c, a=1.0):
        """Line of width w with round caps."""
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-6:
            self.disc(x0, y0, w / 2.0, c, a)
            return
        nx, ny = -dy / L * w / 2.0, dx / L * w / 2.0
        self.poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                   (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], c, a)
        self.disc(x0, y0, w / 2.0, c, a)
        self.disc(x1, y1, w / 2.0, c, a)

    def hline(self, x0, x1, y, c, a=1.0):
        for x in range(max(0, int(x0)), min(self.w, int(x1))):
            self.blend(x, int(y), c, a)


def _grad_at(stops, t):
    if t <= stops[0][0]:
        return stops[0][1]
    for i in range(1, len(stops)):
        p0, c0 = stops[i - 1]
        p1, c1 = stops[i]
        if t <= p1:
            f = (t - p0) / max(1e-9, (p1 - p0))
            return (int(c0[0] + (c1[0] - c0[0]) * f + 0.5),
                    int(c0[1] + (c1[1] - c0[1]) * f + 0.5),
                    int(c0[2] + (c1[2] - c0[2]) * f + 0.5))
    return stops[-1][1]


def mix(c1, c2, f):
    return (int(c1[0] + (c2[0] - c1[0]) * f + 0.5),
            int(c1[1] + (c2[1] - c1[1]) * f + 0.5),
            int(c1[2] + (c2[2] - c1[2]) * f + 0.5))


# ---------------------------------------------------------------- PNG out
def write_png(cv, path):
    raw = bytearray()
    prev = bytearray(cv.w * 3)
    for y in range(cv.h):
        row = cv.px[y * cv.w * 3:(y + 1) * cv.w * 3]
        raw.append(2)  # filter: Up
        for i in range(len(row)):
            raw.append((row[i] - prev[i]) & 0xFF)
        prev = row
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------- vector font
# Hand-built geometric stroke font.  Each glyph is a list of strokes;
# a stroke is a polyline in a 10 x 14 grid (x 0..10, y 0..14, y down).
# Drawn with thick round-capped lines: a bold art-deco poster face.
FONT = {
    "A": [[(0, 14), (5, 0), (10, 14)], [(2.6, 9), (7.4, 9)]],
    "B": [[(0, 0), (0, 14)], [(0, 0), (6, 0), (9, 2), (9, 5), (6, 7), (0, 7)],
          [(0, 7), (6.5, 7), (9.5, 9.5), (9.5, 12), (6.5, 14), (0, 14)]],
    "C": [[(9, 2), (6, 0), (2.5, 0), (0, 3), (0, 11), (2.5, 14), (6, 14), (9, 12)]],
    "D": [[(0, 0), (0, 14), (5, 14), (9, 11), (9, 3), (5, 0), (0, 0)]],
    "E": [[(9, 0), (0, 0), (0, 14), (9, 14)], [(0, 7), (6, 7)]],
    "F": [[(9, 0), (0, 0), (0, 14)], [(0, 7), (6.5, 7)]],
    "G": [[(9, 2), (6, 0), (2.5, 0), (0, 3), (0, 11), (2.5, 14), (6.5, 14),
           (9, 11), (9, 7), (5.5, 7)]],
    "H": [[(0, 0), (0, 14)], [(10, 0), (10, 14)], [(0, 7), (10, 7)]],
    "I": [[(5, 0), (5, 14)], [(2, 0), (8, 0)], [(2, 14), (8, 14)]],
    "J": [[(3, 0), (8, 0), (8, 10), (6, 14), (2, 14), (0, 11)]],
    "K": [[(0, 0), (0, 14)], [(9, 0), (0, 7), (9, 14)]],
    "L": [[(0, 0), (0, 14), (9, 14)]],
    "M": [[(0, 14), (0, 0), (5, 8), (10, 0), (10, 14)]],
    "N": [[(0, 14), (0, 0), (10, 14), (10, 0)]],
    "O": [[(5, 0), (9, 2), (10, 5), (10, 9), (9, 12), (5, 14), (1, 12),
           (0, 9), (0, 5), (1, 2), (5, 0)]],
    "P": [[(0, 0), (0, 14)], [(0, 0), (6, 0), (9, 2), (9, 5), (6, 7), (0, 7)]],
    "Q": [[(5, 0), (9, 2), (10, 5), (10, 9), (9, 12), (5, 14), (1, 12),
           (0, 9), (0, 5), (1, 2), (5, 0)], [(6, 10), (10, 14)]],
    "R": [[(0, 0), (0, 14)], [(0, 0), (6, 0), (9, 2), (9, 5), (6, 7), (0, 7)],
          [(6, 7), (10, 14)]],
    "S": [[(9, 2), (6, 0), (3, 0), (0, 3), (0, 6), (3, 7), (7, 7), (10, 8),
           (10, 11), (7, 14), (4, 14), (1, 12)]],
    "T": [[(0, 0), (10, 0)], [(5, 0), (5, 14)]],
    "U": [[(0, 0), (0, 10), (2, 14), (8, 14), (10, 10), (10, 0)]],
    "V": [[(0, 0), (5, 14), (10, 0)]],
    "W": [[(0, 0), (2.5, 14), (5, 5), (7.5, 14), (10, 0)]],
    "X": [[(0, 0), (10, 14)], [(10, 0), (0, 14)]],
    "Y": [[(0, 0), (5, 7), (10, 0)], [(5, 7), (5, 14)]],
    "Z": [[(0, 0), (10, 0), (0, 14), (10, 14)]],
    "0": [[(5, 0), (9, 2), (10, 5), (10, 9), (9, 12), (5, 14), (1, 12),
           (0, 9), (0, 5), (1, 2), (5, 0)]],
    "1": [[(2, 3), (5, 0), (5, 14)], [(2, 14), (8, 14)]],
    "2": [[(1, 3), (3, 0), (7, 0), (9, 2), (9, 5), (2, 14), (9, 14)]],
    "3": [[(1, 2), (4, 0), (7, 0), (9, 2), (9, 5), (6, 7), (9, 9), (9, 12),
           (7, 14), (4, 14), (1, 12)]],
    "4": [[(0, 10), (7, 0), (7, 14)], [(0, 10), (9, 10)]],
    "5": [[(9, 0), (1, 0), (1, 7), (6, 7), (9, 9), (9, 12), (7, 14),
           (3, 14), (1, 12)]],
    "6": [[(8, 1), (5, 0), (1, 2), (0, 6), (0, 11), (2, 14), (6, 14),
           (9, 12), (10, 9), (9, 6), (5, 6), (2, 6)]],
    "7": [[(0, 0), (10, 0), (4, 14)]],
    "8": [[(5, 0), (8, 1), (9, 3), (8, 5), (5, 6), (2, 5), (1, 3), (2, 1), (5, 0)],
          [(5, 6), (8, 7), (10, 10), (9, 13), (5, 14), (1, 13), (0, 10),
           (2, 7), (5, 6)]],
    "9": [[(2, 13), (5, 14), (9, 12), (10, 8), (10, 3), (8, 0), (4, 0),
           (1, 2), (0, 5), (1, 8), (5, 8), (8, 8)]],
    " ": [],
    ".": [[(4.4, 12.6), (5.6, 12.6)]],
    "-": [[(1, 7), (9, 7)]],
    "'": [[(5, 0), (4, 4)]],
    ",": [[(4.4, 12.6), (5.6, 12.6)], [(5, 13), (3.6, 16)]],
    "&": [[(8, 0), (5, 0), (2, 2), (2, 5), (5, 7), (9, 7), (10, 9), (8, 11),
           (4, 14)], [(9, 1), (5, 6), (1, 11), (0, 13)]],
    "!": [[(5, 0), (5, 10)], [(4.4, 12.6), (5.6, 12.6)]],
}

ADV = 11.5  # advance width, in grid units


def text_width(text, scale, spacing=1.0):
    w = 0.0
    for ch in text:
        if ch == " ":
            w += ADV * 0.62 * scale
        else:
            w += ADV * scale * spacing
    return w - (ADV * scale * spacing * 0.22 if text else 0)


def draw_text(cv, text, cx, top, scale, color, weight=None, spacing=1.0,
              shadow=None, shadow_dy=None):
    """Draw centred text; cap height = 14*scale px.  Returns width."""
    if weight is None:
        weight = max(2.0, scale * 1.9)
    w = text_width(text, scale, spacing)
    x = cx - w / 2.0
    if shadow is not None:
        _draw_text_at(cv, text, x, top + (shadow_dy or scale * 0.9),
                      scale, shadow, weight, spacing)
    _draw_text_at(cv, text, x, top, scale, color, weight, spacing)
    return w


def _draw_text_at(cv, text, x, top, scale, color, weight, spacing):
    for ch in text:
        glyph = FONT.get(ch.upper())
        if glyph is None:
            x += ADV * scale * spacing
            continue
        if ch == " ":
            x += ADV * 0.62 * scale
            continue
        for stroke in glyph:
            for (ax, ay), (bx, by) in zip(stroke, stroke[1:]):
                cv.thick_line(x + ax * scale, top + ay * scale,
                              x + bx * scale, top + by * scale,
                              weight, color)
        x += ADV * scale * spacing


# ---------------------------------------------------------------- scene helpers
def cloud_puff(cv, cx, cy, rx, ry, c, a):
    cv.ellipse(cx, cy, rx, ry, c, a)
    cv.ellipse(cx - rx * 0.55, cy + ry * 0.25, rx * 0.6, ry * 0.7, c, a)
    cv.ellipse(cx + rx * 0.55, cy + ry * 0.3, rx * 0.62, ry * 0.68, c, a)


def birds(cv, pts, c, s=1.0):
    for (x, y, w) in pts:
        cv.thick_line(x - w, y, x, y - 3.5 * s, 2.6, c)
        cv.thick_line(x, y - 3.5 * s, x + w, y, 2.6, c)


def stars(cv, rng, n, y_max, c, rmax=2.2):
    for _ in range(n):
        x = rng.uniform(30, W - 30)
        y = rng.uniform(20, y_max)
        r = rng.uniform(0.8, rmax)
        cv.disc(x, y, r, c, rng.uniform(0.5, 1.0))


def frame(cv, c, inset=26, w=3):
    cv.hline(inset, W - inset, inset, c)
    cv.hline(inset, W - inset, H - inset, c)
    for y in range(inset, H - inset):
        cv.blend(inset, y, c, 1.0)
        cv.blend(W - 1 - inset, y, c, 1.0)
    cv.hline(inset + 9, W - inset - 9, inset + 9, c, 0.7)
    cv.hline(inset + 9, W - inset - 9, H - inset - 9, c, 0.7)
    for y in range(inset + 9, H - inset - 9):
        cv.blend(inset + 9, y, c, 0.7)
        cv.blend(W - 1 - inset - 9, y, c, 0.7)


def title_block(cv, name, sub, top, name_scale, color, shadow,
                sub_scale=None, rule=True):
    """Big name + small letterspaced subtitle, centred."""
    if sub_scale is None:
        sub_scale = name_scale * 0.26
    draw_text(cv, name, W / 2, top, name_scale, color,
              shadow=shadow, shadow_dy=name_scale * 1.1, spacing=1.06)
    sub_top = top + 14 * name_scale + name_scale * 1.6
    if sub:
        tw = text_width(sub, sub_scale, spacing=1.9)
        if rule:
            gap = 26
            y = sub_top + 7 * sub_scale
            cv.thick_line(W / 2 - tw / 2 - gap - 70, y, W / 2 - tw / 2 - gap, y,
                          2.5, color, 0.85)
            cv.thick_line(W / 2 + tw / 2 + gap, y, W / 2 + tw / 2 + gap + 70, y,
                          2.5, color, 0.85)
        draw_text(cv, sub, W / 2, sub_top, sub_scale, color,
                  weight=max(2.0, sub_scale * 1.5), spacing=1.9,
                  shadow=shadow, shadow_dy=sub_scale * 0.8)


# ---------------------------------------------------------------- variant A
def scene_velmora(cv):
    rng = random.Random(SEED)
    # golden-hour sky
    cv.vgrad(0, H, [
        (0.00, (38, 36, 88)),
        (0.30, (94, 62, 128)),
        (0.52, (196, 96, 104)),
        (0.68, (244, 158, 96)),
        (0.82, (250, 196, 138)),
        (1.00, (253, 228, 178)),
    ])
    # sun + glow, low and right
    cv.glow(700, 330, 260, (255, 214, 140), 0.55)
    cv.glow(700, 330, 150, (255, 236, 180), 0.75)
    cv.disc(700, 330, 56, (255, 244, 205))
    # haze band across the sun
    cv.ellipse(700, 330, 96, 10, (244, 158, 96), 0.22)
    # faint high clouds
    for (x, y, rx, ry, a) in [(180, 250, 150, 16, 0.16), (850, 210, 170, 14, 0.14),
                              (420, 180, 120, 12, 0.12), (120, 430, 130, 15, 0.14)]:
        cloud_puff(cv, x, y, rx, ry, (255, 226, 190), a)
    # small hot-air balloon drifting near the sun
    balloon(cv, 838, 372)
    # distant floating islet, far right, grassy top + one tree
    islet(cv, 852, 436, 108, 0.7, (122, 74, 110), (150, 128, 84))
    tree(cv, 852, 436, 22, (72, 92, 60))
    # main floating island
    island(cv, 430, 470)
    # small islet lower right with a tree
    islet(cv, 772, 600, 96, 0.8, (74, 52, 96), (140, 92, 96))
    tree(cv, 772, 600, 26, (52, 74, 52))
    # birds
    birds(cv, [(600, 240, 13), (645, 268, 10), (560, 300, 9), (770, 250, 11)],
          (52, 40, 84))
    # sea of clouds, layered, denser toward the bottom
    cloud_sea(cv, rng)
    # warm sun-glow patch in the cloud sea, under the sun
    cv.glow(700, 800, 220, (255, 196, 130), 0.30)
    cv.ellipse(700, 806, 180, 22, (255, 226, 170), 0.35)
    # tiny distant islet adrift in the clouds
    islet(cv, 205, 872, 84, 0.55, (150, 108, 130), (168, 138, 112))
    tree(cv, 205, 872, 18, (96, 108, 84))
    # title
    title_block(cv, "VELMORA", "THE FLOATING ISLES", 62, 8.3,
                (255, 243, 214), (30, 26, 70))
    frame(cv, (255, 243, 214), inset=26)
    return cv


def balloon(cv, cx, cy):
    # small hot-air balloon: coral envelope, dark basket, warm glow
    cv.glow(cx, cy, 46, (255, 190, 140), 0.35)
    cv.ellipse(cx, cy, 24, 28, (232, 110, 88))
    cv.ellipse(cx - 12, cy, 10, 28, (244, 150, 110), 0.8)
    cv.ellipse(cx + 12, cy, 10, 28, (244, 150, 110), 0.8)
    cv.thick_line(cx - 12, cy + 24, cx - 7, cy + 42, 2, (80, 60, 70))
    cv.thick_line(cx + 12, cy + 24, cx + 7, cy + 42, 2, (80, 60, 70))
    cv.poly([(cx - 8, cy + 42), (cx + 8, cy + 42), (cx + 6, cy + 54),
             (cx - 6, cy + 54)], (80, 60, 70))


def islet(cv, cx, cy, w, s, rock, grass):
    """Small floating rock with a grassy top, no tower."""
    hw = w / 2.0
    cv.poly([(cx - hw, cy), (cx + hw, cy), (cx + hw * 0.55, cy + 26 * s),
             (cx, cy + 66 * s), (cx - hw * 0.55, cy + 26 * s)], rock)
    cv.poly([(cx - hw, cy), (cx + hw, cy), (cx + hw * 0.86, cy + 8 * s),
             (cx - hw * 0.86, cy + 8 * s)], grass)
    cv.poly([(cx - hw * 0.7, cy + 2), (cx + hw * 0.7, cy + 2),
             (cx + hw * 0.4, cy + 22 * s), (cx - hw * 0.4, cy + 22 * s)],
            (255, 226, 190), 0.18)


def tree(cv, x, y, h, c):
    cv.thick_line(x, y, x, y - h * 0.55, 4, (58, 44, 66))
    cv.disc(x, y - h * 0.75, h * 0.42, c)
    cv.disc(x - h * 0.3, y - h * 0.5, h * 0.3, c)
    cv.disc(x + h * 0.3, y - h * 0.5, h * 0.3, c)


def island(cv, cx, top_y):
    """The hero floating island: grassy plateau, rock body, waterfall."""
    # small rock shards adrift below the island (clouds will veil them)
    cv.poly([(cx + 128, top_y + 292), (cx + 168, top_y + 292),
             (cx + 148, top_y + 330)], (96, 66, 104))
    cv.poly([(cx - 168, top_y + 330), (cx - 128, top_y + 330),
             (cx - 148, top_y + 362)], (96, 66, 104))
    # rock body tapering to a point below, tip nudged left for asymmetry
    body = [(cx - 235, top_y + 18), (cx + 235, top_y + 18),
            (cx + 205, top_y + 70), (cx + 130, top_y + 150),
            (cx + 55, top_y + 235), (cx - 18, top_y + 268),
            (cx - 78, top_y + 228), (cx - 130, top_y + 150),
            (cx - 205, top_y + 70)]
    cv.poly(body, (88, 58, 96))
    # strata shading on the rock
    cv.poly([(cx - 205, top_y + 70), (cx + 205, top_y + 70),
             (cx + 185, top_y + 96), (cx - 185, top_y + 96)], (70, 46, 82), 0.55)
    cv.poly([(cx - 130, top_y + 150), (cx + 130, top_y + 150),
             (cx + 100, top_y + 176), (cx - 100, top_y + 176)], (70, 46, 82), 0.5)
    cv.poly([(cx - 55, top_y + 235), (cx + 55, top_y + 235),
             (cx + 22, top_y + 258), (cx - 22, top_y + 258)], (70, 46, 82), 0.5)
    # warm sunlit right edge, stronger
    cv.poly([(cx + 235, top_y + 18), (cx + 205, top_y + 70),
             (cx + 130, top_y + 150), (cx + 150, top_y + 150),
             (cx + 215, top_y + 66)], (214, 138, 102), 0.65)
    cv.poly([(cx + 130, top_y + 150), (cx + 55, top_y + 235),
             (cx - 18, top_y + 268), (cx + 6, top_y + 262),
             (cx + 70, top_y + 226), (cx + 142, top_y + 152)], (214, 138, 102), 0.4)
    # grassy plateau top
    cv.poly([(cx - 235, top_y + 18), (cx + 235, top_y + 18),
             (cx + 208, top_y - 6), (cx - 208, top_y - 6)], (96, 128, 74))
    cv.poly([(cx - 208, top_y - 6), (cx + 208, top_y - 6),
             (cx + 180, top_y - 16), (cx - 180, top_y - 16)], (122, 152, 88))
    # trees on the plateau
    tree(cv, cx - 150, top_y - 8, 46, (58, 88, 58))
    tree(cv, cx - 108, top_y - 10, 34, (70, 100, 62))
    tree(cv, cx + 168, top_y - 8, 40, (58, 88, 58))
    # white lighthouse tower with warm lantern + tiny flag
    tx = cx + 62
    cv.poly([(tx - 16, top_y - 118), (tx + 16, top_y - 118),
             (tx + 22, top_y - 12), (tx - 22, top_y - 12)], (250, 240, 222))
    cv.poly([(tx - 16, top_y - 118), (tx + 16, top_y - 118),
             (tx + 18, top_y - 92), (tx - 18, top_y - 92)], (232, 122, 96))
    cv.disc(tx, top_y - 128, 15, (250, 240, 222))
    cv.disc(tx, top_y - 128, 9, (255, 214, 120))
    cv.glow(tx, top_y - 128, 72, (255, 214, 120), 0.65)
    cv.thick_line(tx, top_y - 143, tx, top_y - 158, 2.5, (80, 60, 70))
    cv.poly([(tx, top_y - 158), (tx + 16, top_y - 153), (tx, top_y - 148)],
            (232, 110, 88))
    cv.hline(tx - 22, tx + 22, top_y - 118, (232, 122, 96))
    # waterfall pouring off the left edge into the clouds: tapered,
    # gently curving band with a bright core and mist at the base
    wx = cx - 196
    left, right = [], []
    for k in range(0, 17):
        t = k / 16.0
        y = top_y + 16 + 234 * t
        sway = math.sin(t * math.pi) * 10 - t * 6
        wdt = 11 + 10 * t
        left.append((wx + sway - wdt / 2, y))
        right.append((wx + sway + wdt / 2, y))
    cv.poly(left + right[::-1], (204, 226, 238))
    core_l, core_r = [], []
    for k in range(0, 17):
        t = k / 16.0
        y = top_y + 16 + 234 * t
        sway = math.sin(t * math.pi) * 10 - t * 6
        wdt = 5 + 5 * t
        core_l.append((wx + sway - wdt / 2, y))
        core_r.append((wx + sway + wdt / 2, y))
    cv.poly(core_l + core_r[::-1], (255, 255, 255), 0.8)
    cv.disc(wx + 4, top_y + 252, 26, (240, 244, 248), 0.8)
    cv.disc(wx + 4, top_y + 252, 14, (255, 255, 255), 0.65)


def cloud_sea(cv, rng):
    # layered puffs: peach, cream, then a soft lilac floor at the bottom
    rows = [
        (726, 150, 26, (255, 222, 178), 0.55),
        (790, 190, 30, (255, 232, 200), 0.6),
        (862, 230, 34, (252, 214, 196), 0.65),
        (936, 260, 36, (238, 196, 208), 0.7),
    ]
    for (y, rx, ry, c, a) in rows:
        x = 40
        while x < W:
            cloud_puff(cv, x + rng.uniform(-30, 30), y + rng.uniform(-8, 8),
                       rx * rng.uniform(0.8, 1.25), ry * rng.uniform(0.8, 1.2),
                       c, a)
            x += int(rx * 1.7)
    # soft floor
    cv.vgrad(960, H, [(0.0, (238, 196, 208)), (1.0, (214, 168, 196))])


# ---------------------------------------------------------------- variant B
def scene_nymara(cv):
    rng = random.Random(SEED + 1)
    # dusk sky
    cv.vgrad(0, 620, [
        (0.00, (26, 22, 64)),
        (0.45, (74, 46, 110)),
        (0.75, (158, 74, 118)),
        (1.00, (232, 128, 96)),
    ])
    stars(cv, rng, 90, 300, (255, 244, 220))
    # two moons
    cv.glow(748, 210, 130, (255, 236, 200), 0.5)
    cv.disc(748, 210, 46, (255, 240, 214))
    cv.disc(736, 200, 8, (232, 214, 180), 0.8)
    cv.disc(762, 224, 6, (232, 214, 180), 0.8)
    cv.disc(250, 150, 21, (255, 228, 190), 0.95)
    # lagoon
    cv.vgrad(560, H, [
        (0.00, (30, 84, 96)),
        (0.35, (20, 62, 82)),
        (1.00, (12, 34, 58)),
    ])
    # horizon glow
    cv.glow(512, 560, 420, (240, 150, 110), 0.28)
    # glowing ripple rings around the spire
    for r, a in [(150, 0.5), (205, 0.38), (265, 0.28), (330, 0.18)]:
        for k in range(0, 360, 6):
            ang = math.radians(k)
            x = 512 + math.cos(ang) * r
            y = 640 + math.sin(ang) * r * 0.30
            cv.disc(x, y, 3.2, (86, 232, 214), a)
    # reflection of the spire
    cv.poly([(498, 640), (526, 640), (540, 900), (484, 900)], (120, 200, 210), 0.16)
    # the singing shell spire
    shell_spire(cv, 512, 620)
    # dark shore foreground with glowing tide pools
    cv.poly([(0, 1024), (0, 930), (180, 900), (330, 936), (470, 912),
             (620, 940), (800, 906), (1024, 936), (1024, 1024)], (16, 22, 46))
    for (x, y, r) in [(150, 968, 14), (330, 958, 9), (700, 972, 12), (880, 962, 8),
                      (60, 990, 8), (950, 992, 10)]:
        cv.glow(x, y, r * 2.4, (86, 232, 214), 0.5)
        cv.disc(x, y, r, (60, 200, 190), 0.85)
    # fireflies / spores above the water
    for _ in range(26):
        x = rng.uniform(60, W - 60)
        y = rng.uniform(600, 880)
        cv.disc(x, y, rng.uniform(1.5, 3.0), (140, 240, 220),
                rng.uniform(0.4, 0.9))
    title_block(cv, "NYMARA", "THE SINGING LAGOON", 62, 8.0,
                (255, 238, 196), (22, 16, 56))
    frame(cv, (255, 238, 196), inset=26)
    return cv


def shell_spire(cv, cx, base_y):
    """A giant spiral shell rising from the lagoon: stacked tapering
    whorls, pearl-lit, with warm windows and a glowing crown."""
    # body: stacked ellipses narrowing upward, pearl with violet shade
    whorls = [
        (150, 40, (238, 224, 226)), (132, 30, (226, 208, 216)),
        (112, 22, (238, 224, 226)), (92, 16, (214, 194, 208)),
        (72, 12, (238, 224, 226)), (54, 9, (222, 202, 214)),
        (38, 7, (240, 228, 230)),
    ]
    y = base_y
    for (rx, rh, c) in whorls:
        cv.ellipse(cx, y - rh, rx, rh, c)
        y -= rh * 2 - 6
    # spiral ridge: diagonal highlight bands across the whorls
    for i in range(6):
        x0 = cx - 120 + i * 34
        y0 = base_y - 20 - i * 34
        cv.thick_line(x0, y0, x0 + 66, y0 - 26, 7, (255, 250, 244), 0.55)
    # violet shadow on the right side
    cv.poly([(cx + 40, base_y - 250), (cx + 150, base_y - 40),
             (cx + 150, base_y), (cx + 40, base_y)], (150, 110, 160), 0.28)
    # warm arched windows
    for (wx, wy, wr) in [(-58, 520, 10), (30, 470, 9), (-18, 420, 8),
                         (52, 540, 8), (-70, 575, 7)]:
        cv.disc(cx + wx, wy, wr, (255, 196, 110))
        cv.glow(cx + wx, wy, wr * 3.0, (255, 196, 110), 0.45)
    # glowing crown at the tip
    tip_y = y + 6
    cv.glow(cx, tip_y, 70, (140, 240, 220), 0.7)
    cv.disc(cx, tip_y, 14, (200, 250, 240))
    # glow ring at the waterline
    cv.ellipse(cx, base_y + 6, 168, 20, (86, 232, 214), 0.5)
    cv.ellipse(cx, base_y + 6, 132, 14, (140, 244, 224), 0.55)


# ---------------------------------------------------------------- variant C
def scene_aerthwaite(cv):
    rng = random.Random(SEED + 2)
    # midnight sky
    cv.vgrad(0, 700, [
        (0.00, (10, 18, 48)),
        (0.5, (22, 42, 84)),
        (1.00, (48, 84, 110)),
    ])
    stars(cv, rng, 130, 420, (255, 250, 235))
    # aurora ribbons
    aurora(cv, rng)
    # moon
    cv.glow(830, 170, 110, (230, 240, 255), 0.4)
    cv.disc(830, 170, 34, (240, 244, 252))
    # mountain ranges, far then near
    cv.poly([(0, 700), (120, 520), (260, 640), (400, 500), (560, 660),
             (720, 540), (880, 650), (1024, 560), (1024, 1024), (0, 1024)],
            (36, 58, 92))
    cv.poly([(120, 520), (160, 560), (200, 530), (150, 500)], (226, 236, 244), 0.9)
    cv.poly([(400, 500), (440, 545), (480, 520), (430, 480)], (226, 236, 244), 0.9)
    cv.poly([(0, 1024), (0, 760), (180, 640), (330, 760), (470, 660),
             (640, 790), (820, 690), (1024, 800), (1024, 1024)],
            (20, 34, 62))
    cv.poly([(180, 640), (215, 680), (250, 655), (205, 625)], (214, 226, 238), 0.9)
    cv.poly([(820, 690), (855, 728), (890, 700), (845, 668)], (214, 226, 238), 0.9)
    # glowing river winding to the horizon
    cv.poly([(470, 700), (554, 700), (580, 820), (640, 1024),
             (380, 1024), (440, 820)], (64, 170, 180))
    cv.poly([(498, 700), (526, 700), (540, 820), (560, 1024),
             (460, 1024), (480, 820)], (110, 220, 214), 0.6)
    # stone bridge arching over the river
    bridge(cv, 512, 760)
    # cabins with warm windows on the far bank
    cabin(cv, 330, 700, 1.0)
    cabin(cv, 700, 690, 0.85)
    cabin(cv, 240, 720, 0.7)
    # foreground pines
    for (x, y, h) in [(90, 1024, 150), (180, 1024, 110), (940, 1024, 140),
                      (860, 1024, 100), (40, 1024, 100)]:
        pine(cv, x, y, h, (14, 30, 50))
    title_block(cv, "AERTHWAITE", "WHERE THE SKY SINGS AT NIGHT", 62, 6.4,
                (240, 246, 252), (8, 14, 40))
    frame(cv, (240, 246, 252), inset=26)
    return cv


def aurora(cv, rng):
    # three translucent wavy ribbons, green-teal, brightest in the middle
    for (base_y, amp, col, a) in [(150, 46, (90, 230, 170), 0.30),
                                  (230, 60, (60, 200, 190), 0.24),
                                  (310, 40, (140, 240, 190), 0.18)]:
        top, bot = [], []
        for x in range(0, W + 1, 32):
            y = base_y + math.sin(x / 170.0 + base_y) * amp \
                + math.sin(x / 61.0) * 12
            top.append((x, y))
            bot.append((x, y + 66))
        cv.poly(top + bot[::-1], col, a)


def bridge(cv, cx, y):
    # stone arch bridge: arc band + deck + tiny posts
    pts_top, pts_bot = [], []
    for k in range(0, 33):
        t = k / 32.0
        x = cx - 190 + 380 * t
        yy = y - math.sin(t * math.pi) * 95
        pts_top.append((x, yy))
        pts_bot.append((x, yy + 26))
    cv.poly(pts_top + pts_bot[::-1], (58, 52, 66))
    cv.poly(pts_top + [(cx + 190, y + 26), (cx - 190, y + 26)], (84, 78, 92), 0.6)
    for k in range(1, 8):
        t = k / 8.0
        x = cx - 190 + 380 * t
        yy = y - math.sin(t * math.pi) * 95
        cv.thick_line(x, yy - 14, x, yy, 4, (200, 190, 170), 0.9)
    # warm lantern on the bridge crown
    cv.glow(cx, y - 95 - 8, 34, (255, 200, 120), 0.7)
    cv.disc(cx, y - 95 - 8, 7, (255, 214, 140))


def cabin(cv, x, y, s):
    w, h = 64 * s, 44 * s
    cv.poly([(x - w / 2, y), (x + w / 2, y), (x + w / 2, y - h),
             (x, y - h - 22 * s), (x - w / 2, y - h)], (52, 40, 48))
    cv.poly([(x - w / 2 - 4, y - h), (x + w / 2 + 4, y - h),
             (x, y - h - 28 * s)], (30, 44, 62))
    cv.disc(x - w * 0.18, y - h * 0.45, 5 * s, (255, 200, 110))
    cv.disc(x + w * 0.18, y - h * 0.45, 5 * s, (255, 200, 110))
    cv.glow(x, y - h * 0.45, 26 * s, (255, 200, 110), 0.35)


def pine(cv, x, base_y, h, c):
    cv.poly([(x - h * 0.30, base_y), (x + h * 0.30, base_y),
             (x, base_y - h)], c)
    cv.poly([(x - h * 0.22, base_y - h * 0.45), (x + h * 0.22, base_y - h * 0.45),
             (x, base_y - h * 1.25)], c)


# ---------------------------------------------------------------- main
SCENES = {"velmora": scene_velmora, "nymara": scene_nymara,
          "aerthwaite": scene_aerthwaite}


def render(variant, out_path):
    cv = Canvas()
    SCENES[variant](cv)
    n = write_png(cv, out_path)
    return n


def main():
    import sys
    variant = sys.argv[1] if len(sys.argv) > 1 else "velmora"
    out = sys.argv[2] if len(sys.argv) > 2 else "/output/entry.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = render(variant, out)
    print(f"{variant}: {out} {n} bytes")


if __name__ == "__main__":
    main()
