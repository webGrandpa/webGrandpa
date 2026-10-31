#!/usr/bin/env python3
"""
webGrandpa · profile plates
===========================
Generates every visual in ../README.md as a pair of animated SVGs
(<name>-dark.svg / <name>-light.svg). GitHub picks the right one through
<picture> + prefers-color-scheme.

    pip install fonttools brotli
    python3 design/build.py

Fonts (SIL OFL, see fonts/) are subset per file and embedded as base64 WOFF2,
so every plate renders identically and makes zero network requests.
Copy, projects and colours live in the DATA section at the bottom.
"""
import base64
import io
import math
import os
import random
from collections import defaultdict
from xml.sax.saxutils import escape

from fontTools import subset as fts
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
OUT = os.path.normpath(os.path.join(HERE, "..", "assets"))

# ─────────────────────────────── palette ───────────────────────────────
THEMES = {
    "dark": dict(bg="#0d0d0c", bg2="#12110f", tile="#151411", line="#25221e", line2="#3b352d",
                 gold="#C9A878", hi="#F1DDB6", lo="#8a7350", ink="#F3EDE3", ink2="#B4AB9D",
                 ink3="#7C756A", blend="screen", glow=.15),
    "light": dict(bg="#F6F1E8", bg2="#EFE8DB", tile="#F1EADD", line="#E2D9C9", line2="#CBBEA8",
                  gold="#8E6B38", hi="#C9A06A", lo="#B49B76", ink="#161411", ink2="#4C463D",
                  ink3="#857D71", blend="multiply", glow=.17),
}
EASE = ".45 0 .55 1"
SNAP = ".7 0 .2 1"
HOLD = "0 0 1 1"


# ──────────────────────────────── fonts ────────────────────────────────
class Font:
    def __init__(self, key, file, fallback):
        self.key, self.fallback = key, fallback
        self.path = os.path.join(FONT_DIR, file)
        tt = TTFont(self.path)
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]
        self.upem = tt["head"].unitsPerEm
        self.family = f"wg-{key}"
        self._cache = {}

    def width(self, s, size, ls=0.0):
        adv = 0
        for ch in s:
            g = self.cmap.get(ord(ch))
            adv += self.hmtx[g][0] if g else self.upem * 0.5
        return adv / self.upem * size + ls * len(s)

    def b64(self, chars):
        key = "".join(sorted(chars))
        if key not in self._cache:
            opts = fts.Options()
            opts.flavor = "woff2"
            font = fts.load_font(self.path, opts)
            sub = fts.Subsetter(opts)
            sub.populate(text=key)
            sub.subset(font)
            buf = io.BytesIO()
            fts.save_font(font, buf, opts)
            self._cache[key] = base64.b64encode(buf.getvalue()).decode("ascii")
        return self._cache[key]


FONTS = {k: Font(k, f, fb) for k, (f, fb) in {
    "serif": ("instrument-serif-latin-400-normal.woff2", "Georgia, serif"),
    "serifI": ("instrument-serif-latin-400-italic.woff2", "Georgia, serif"),
    "sans": ("inter-latin-400-normal.woff2", "Helvetica, Arial, sans-serif"),
    "sansM": ("inter-latin-500-normal.woff2", "Helvetica, Arial, sans-serif"),
    "mono": ("jetbrains-mono-latin-400-normal.woff2", "Menlo, Consolas, monospace"),
    "monoM": ("jetbrains-mono-latin-500-normal.woff2", "Menlo, Consolas, monospace"),
    "geo": ("noto-serif-georgian-georgian-400-normal.woff2", "serif"),
}.items()}


def tw(s, font, size, ls=0.0):
    return FONTS[font].width(s, size, ls)


def wrap(text, font, size, maxw, ls=0.0):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and tw(trial, font, size, ls) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    return lines


def n(v):
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


def smooth(pts, closed=False):
    """Catmull-Rom through pts → cubic Bézier path."""
    N = len(pts)
    d = [f"M{n(pts[0][0])} {n(pts[0][1])}"]
    for i in range(N if closed else N - 1):
        p0 = pts[(i - 1) % N] if (closed or i > 0) else pts[0]
        p1, p2 = pts[i], pts[(i + 1) % N]
        p3 = pts[(i + 2) % N] if (closed or i + 2 < N) else pts[-1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {n(p2[0])} {n(p2[1])}")
    if closed:
        d.append("Z")
    return "".join(d)


# ───────────────────────────── svg builder ─────────────────────────────
class SVG:
    def __init__(self, name, w, h, theme, title, desc=""):
        self.name, self.w, self.h, self.theme = name, w, h, theme
        self.t = THEMES[theme]
        self.title, self.desc = title, desc or title
        self.defs, self.body, self.css = [], [], []
        self.chars = defaultdict(set)
        self._id = 0

    def uid(self, p="i"):
        self._id += 1
        return f"{p}{self._id}"

    def c(self, key):
        return self.t.get(key, key)

    def add(self, *parts):
        self.body.extend(parts)

    def d(self, *parts):
        self.defs.extend(parts)

    def _use(self, font, s):
        F = FONTS[font]
        for ch in s:
            if ch != " " and ord(ch) not in F.cmap:
                print(f"  ! {self.name}: {font} lacks {ch!r}")
            self.chars[font].add(ch)
        return F

    def text(self, x, y, s, font="sans", size=16, fill="ink", anchor=None, ls=0, opacity=None, attrs=""):
        F = self._use(font, s)
        a = [f'x="{n(x)}" y="{n(y)}" font-family="{F.family}, {F.fallback}" font-size="{n(size)}" fill="{self.c(fill)}"']
        if anchor:
            a.append(f'text-anchor="{anchor}"')
        if ls:
            a.append(f'letter-spacing="{ls}"')
        if opacity is not None:
            a.append(f'opacity="{opacity}"')
        if attrs:
            a.append(attrs)
        return f'<text {" ".join(a)}>{escape(s)}</text>'

    def rich(self, x, y, parts, font="mono", size=15, ls=0, anchor=None):
        """parts: [(text, colour)] rendered as tspans on one baseline."""
        F = FONTS[font]
        spans = []
        for s, col in parts:
            self._use(font, s)
            spans.append(f'<tspan fill="{self.c(col)}">{escape(s)}</tspan>')
        a = f'x="{n(x)}" y="{n(y)}" font-family="{F.family}, {F.fallback}" font-size="{n(size)}"'
        if ls:
            a += f' letter-spacing="{ls}"'
        if anchor:
            a += f' text-anchor="{anchor}"'
        return f'<text {a} xml:space="preserve">{"".join(spans)}</text>'

    def render(self):
        faces = "".join(
            "@font-face{font-family:'%s';src:url(data:font/woff2;base64,%s) format('woff2')}"
            % (FONTS[k].family, FONTS[k].b64(ch)) for k, ch in sorted(self.chars.items()) if ch)
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(self.title)}</title><desc id="desc">{escape(self.desc)}</desc>',
            f"<style>{faces}{''.join(self.css)}</style>",
            f"<defs>{''.join(self.defs)}</defs>",
            *self.body,
            "</svg>",
        ])


# ─────────────────────────────── glyphs ────────────────────────────────
def arrow_ne(x, y, size, color, sw=1.5):
    return (f'<path d="M{n(x)} {n(y + size)}L{n(x + size)} {n(y)}M{n(x + size * .3)} {n(y)}H{n(x + size)}V{n(y + size * .7)}" '
            f'stroke="{color}" stroke-width="{sw}" fill="none"/>')


def arrow_e(x, y, size, color, sw=1.4):
    h = size * .32
    return (f'<path d="M{n(x)} {n(y)}H{n(x + size)}M{n(x + size - h)} {n(y - h)}L{n(x + size)} {n(y)}L{n(x + size - h)} {n(y + h)}" '
            f'stroke="{color}" stroke-width="{sw}" fill="none"/>')


def check(x, y, s, color, sw=1.6):
    return (f'<path d="M{n(x)} {n(y)}l{n(s * .36)} {n(s * .36)}l{n(s * .64)} {n(-s * .8)}" stroke="{color}" '
            f'stroke-width="{sw}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def led(s, x, y, r=3.2, period=2.4):
    g = s.c("gold")
    return (f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}" fill="{g}"/>'
            f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}" fill="none" stroke="{g}">'
            f'<animate attributeName="r" values="{r};{r * 4}" dur="{period}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".8;0" dur="{period}s" repeatCount="indefinite"/></circle>')


def plate(s, rx=22, glow=None):
    t = s.t
    s.add(f'<rect x=".5" y=".5" width="{s.w - 1}" height="{s.h - 1}" rx="{rx}" fill="{t["bg"]}" stroke="{t["line"]}"/>')
    clip = s.uid("pc")
    s.d(f'<clipPath id="{clip}"><rect x="1" y="1" width="{s.w - 2}" height="{s.h - 2}" rx="{rx - 1}"/></clipPath>')
    if glow:
        cx, cy, r, k = glow
        gid = s.uid("gl")
        s.d(f'<radialGradient id="{gid}" cx="{cx}" cy="{cy}" r="{r}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{t["gold"]}" stop-opacity="{t["glow"] * k:.3f}"/>'
            f'<stop offset="1" stop-color="{t["gold"]}" stop-opacity="0"/></radialGradient>')
        s.add(f'<rect x="1" y="1" width="{s.w - 2}" height="{s.h - 2}" rx="{rx - 1}" fill="url(#{gid})"/>')
    return clip


def frame(s, inset=16):
    """Inner hairline frame with print registration marks."""
    t = s.t
    x0, y0, x1, y1 = inset, inset, s.w - inset, s.h - inset
    s.add(f'<rect x="{x0 + .5}" y="{y0 + .5}" width="{x1 - x0 - 1}" height="{y1 - y0 - 1}" rx="3" fill="none" stroke="{t["line"]}"/>')
    L = 6
    s.add('<path d="' + "".join(f"M{x - L} {y + .5}H{x + L}M{x + .5} {y - L}V{y + L}" for x, y in
                                ((x0, y0), (x1 - 1, y0), (x0, y1 - 1), (x1 - 1, y1 - 1))) +
          f'" stroke="{t["gold"]}" stroke-opacity=".85"/>')


def rule_sweep(s, x0, x1, y, dur=7, seg=64, begin=0):
    """A short gold segment gliding along a hairline."""
    g = s.c("gold")
    return (f'<rect x="{n(x0)}" y="{n(y - .75)}" width="{seg}" height="1.5" fill="{g}" opacity="0">'
            f'<animate attributeName="x" values="{n(x0)};{n(x1 - seg)};{n(x1 - seg)}" keyTimes="0;.6;1" dur="{dur}s" begin="{begin}s" repeatCount="indefinite" calcMode="spline" keySplines="{EASE};{HOLD}"/>'
            f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.08;.52;.6;1" dur="{dur}s" begin="{begin}s" repeatCount="indefinite"/></rect>')


def pill(s, x, cy, label, size=10.5, ls=1.4, h=24, padx=11):
    w = tw(label, "mono", size, ls) - ls + padx * 2
    s.add(f'<rect x="{n(x + .5)}" y="{n(cy - h / 2 + .5)}" width="{n(w - 1)}" height="{h - 1}" rx="{(h - 1) / 2}" '
          f'fill="none" stroke="{s.t["line2"]}"/>')
    s.add(s.text(x + padx, cy + size * .36, label, "mono", size, "ink2", ls=ls))
    return w


def waves(s, *, y0, y1, count, seed, amp0, amp1, mask=None, op0=.1, op1=.7, dur=60,
          period=1200, x0=0, x1=None, breathe=7, sw=1.0, color="gold", step=60, index=0):
    """Engraving-style flow field: coherent sine stacks drifting sideways and breathing."""
    x1 = s.w if x1 is None else x1
    rnd = random.Random(seed)
    p = [rnd.uniform(0, math.tau) for _ in range(3)]
    col = s.c(color)
    out = [f'<g mask="url(#{mask})">' if mask else "<g>"]
    for i in range(count):
        f = i / (count - 1)
        base = y0 + (y1 - y0) * f
        A = amp0 + (amp1 - amp0) * f
        pts, x = [], x0
        while x <= x1 + period + .1:
            u = math.tau * x / period
            y = base + A * (math.sin(u + p[0] + f * 1.9) + .45 * math.sin(2 * u + p[1] + f * 3.1)
                            + .2 * math.sin(3 * u + p[2] - f * 2.3))
            pts.append((x, y))
            x += step
        op = op0 + (op1 - op0) * f ** 1.4
        w = sw
        if index and i % index == index - 1:  # contour "index" line, like a survey map
            op, w = min(1, op + .2), sw * 1.45
        bob = (f - .5) * breathe * 2
        out.append(
            f'<g><animateTransform attributeName="transform" type="translate" values="0 0;0 {n(bob)};0 0" keyTimes="0;.5;1" '
            f'calcMode="spline" keySplines="{EASE};{EASE}" dur="11s" repeatCount="indefinite"/>'
            f'<path d="{smooth(pts)}" stroke="{col}" stroke-opacity="{op:.2f}" stroke-width="{w}" fill="none">'
            f'<animateTransform attributeName="transform" type="translate" from="0 0" to="{-period} 0" dur="{dur}s" '
            f'repeatCount="indefinite"/></path></g>')
    out.append("</g>")
    s.add(*out)


def hmask(s, stops):
    """Horizontal luminance mask: stops = [(offset, 0..1), …]."""
    m, g = s.uid("m"), s.uid("mg")
    st = "".join(f'<stop offset="{o}" stop-color="#fff" stop-opacity="{a}"/>' for o, a in stops)
    s.d(f'<linearGradient id="{g}" x1="0" y1="0" x2="1" y2="0">{st}</linearGradient>'
        f'<mask id="{m}" maskUnits="userSpaceOnUse" x="0" y="0" width="{s.w}" height="{s.h}">'
        f'<rect width="{s.w}" height="{s.h}" fill="url(#{g})"/></mask>')
    return m


# ──────────────────────────────── hero ─────────────────────────────────
def hero(theme):
    W, H = 1200, 520
    s = SVG("hero", W, H, theme, "Giorgi Khiladze — frontend developer & designer",
            "Giorgi Khiladze (გიორგი ხილაძე) — frontend developer and designer in Batumi, Georgia. "
            "Designed & built artisser.io and fixmob.ge, building SportGen, teaching JavaScript & React at 10x Academy.")
    t = s.t
    clip = plate(s, glow=(960, 420, 640, 1))
    m = hmask(s, [(.18, 0), (.6, 1)])
    s.add(f'<g clip-path="url(#{clip})">')
    waves(s, y0=118, y1=470, count=30, seed=11, amp0=7, amp1=28, mask=m, op0=.05, op1=.72, dur=72, index=5)
    s.add("</g>")
    frame(s)

    s.add(s.text(48, 62, "No. 00 — PROFILE", "mono", 11.5, "gold", ls=2.2))
    lbl = "BATUMI, GEORGIA · UTC+04:00"
    s.add(s.text(1152, 62, lbl, "mono", 11.5, "ink3", anchor="end", ls=2.2))
    s.add(led(s, 1152 - tw(lbl, "mono", 11.5, 2.2) - 12, 58))
    s.add(s.text(0, 0, "41.6168° N · 41.6367° E", "mono", 10.5, "ink3", anchor="middle", ls=3,
                 attrs='transform="translate(1166 268) rotate(90)"'))

    sh = s.uid("sh")
    s.d(f'<linearGradient id="{sh}" gradientUnits="userSpaceOnUse" x1="-760" y1="0" x2="-160" y2="0">'
        f'<stop offset="0" stop-color="{t["ink"]}"/><stop offset=".36" stop-color="{t["ink"]}"/>'
        f'<stop offset=".5" stop-color="{t["hi"]}"/><stop offset=".64" stop-color="{t["ink"]}"/>'
        f'<stop offset="1" stop-color="{t["ink"]}"/>'
        f'<animateTransform attributeName="gradientTransform" type="translate" values="0 0;1600 0;1600 0" '
        f'keyTimes="0;.45;1" dur="11s" repeatCount="indefinite" calcMode="spline" keySplines="{EASE};{HOLD}"/></linearGradient>')
    s.add(s.text(42, 200, "Giorgi", "serif", 132, f"url(#{sh})", ls=-1.5))
    s.add(s.text(42, 310, "Khiladze", "serif", 132, f"url(#{sh})", ls=-1.5))
    s.add(s.text(50, 356, "გიორგი ხილაძე", "geo", 23, "gold", ls=1.5))
    s.add(s.text(48, 404, "Frontend developer & designer", "serifI", 32, "ink2"))

    # status log — rolls through what's happening
    rows = [("designed + built", "artisser.io"), ("designed + built", "fixmob.ge"),
            ("building", "SportGen — multi-sport SaaS"), ("teaching", "JavaScript & React @ 10x Academy"),
            ("obsessed with", "shaders, scroll scenes & clean architecture")]
    x, y, size, lh, slot, move = 70, 451, 14.5, 30, 3.3, .55
    s.add(led(s, 52, y - 5, 3))
    clipid = s.uid("tk")
    s.d(f'<clipPath id="{clipid}"><rect x="{x - 2}" y="{y - size - 5}" width="1000" height="{size + 11}"/></clipPath>')
    M, T = len(rows), slot * len(rows)
    vals, kts, kss = [], [], []
    for i in range(M):
        vals += [f"0 {-i * lh}", f"0 {-i * lh}"]
        kts += [i * slot / T, (i * slot + slot - move) / T]
        kss += [HOLD, SNAP]
    vals.append(f"0 {-M * lh}")
    kts.append(1)
    g = [f'<g clip-path="url(#{clipid})"><g>',
         f'<animateTransform attributeName="transform" type="translate" values="{";".join(vals)}" '
         f'keyTimes="{";".join(f"{k:.4f}" for k in kts)}" calcMode="spline" keySplines="{";".join(kss)}" '
         f'dur="{T:.2f}s" repeatCount="indefinite"/>']
    for i, (k, v) in enumerate(rows + rows[:1]):
        line = f"{k:<18}{v}"
        g.append(s.rich(x, y + i * lh, [(f"{k:<18}", "ink3"), (v, "ink")], "mono", size))
        cw = tw(line, "mono", size)
        g.append(f'<rect x="{n(x + cw + 5)}" y="{n(y + i * lh - size * .82)}" width="{n(size * .56)}" height="{n(size * 1.02)}" '
                 f'fill="{t["gold"]}"><animate attributeName="opacity" values="1;0" calcMode="discrete" dur="1.1s" repeatCount="indefinite"/></rect>')
    g.append("</g></g>")
    s.add(*g)

    s.add(s.text(48, 486, "FRONTEND · DESIGN · MOTION · SYSTEMS", "mono", 11, "ink3", ls=2.4))
    s.add(s.text(1152, 486, "@webGrandpa", "mono", 11, "ink3", anchor="end", ls=1.6))
    return s


# ──────────────────────────────── about ────────────────────────────────
def about(theme):
    W, H = 1200, 440
    stats = [("8", "", "Apps in the SportGen ecosystem"),
             ("30", "", "Criteria in the player evaluation framework"),
             ("6", "YRS", "Operating critical systems at Batumi Oil Terminal"),
             ("10", "×", "Explore tenfold for every concept taught")]
    s = SVG("about", W, H, theme, "I design interfaces — and build everything behind them.",
            "From GLSL shaders and scroll-driven scenes to Postgres schemas and multi-tenant SaaS architecture. " +
            "; ".join(f"{a}{b}: {c}" for a, b, c in stats) + ".")
    t = s.t
    plate(s, glow=(1150, -40, 760, .7))
    frame(s)
    s.add(s.text(48, 62, "FIG. 1 — IN SHORT", "mono", 11.5, "gold", ls=2.2))
    s.add(s.text(1152, 62, "BATUMI · BLACK SEA COAST", "mono", 11.5, "ink3", anchor="end", ls=2.2))
    s.add(s.text(44, 150, "I design interfaces — and build", "serif", 62, "ink", ls=-.6))
    s.add(s.text(44, 214, "everything behind them.", "serifI", 62, "gold", ls=-.6))
    s.add(s.text(47, 258, "From GLSL shaders and scroll-driven scenes to Postgres schemas and multi-tenant SaaS architecture.",
                 "sans", 17, "ink2"))
    s.add(f'<path d="M48 296.5H1152" stroke="{t["line2"]}"/>', rule_sweep(s, 48, 1152, 296.5, dur=9, seg=90))
    colw = (1152 - 48) / 4
    for k, (num, unit, label) in enumerate(stats):
        x = 48 + k * colw + (26 if k else 0)
        if k:
            s.add(f'<path d="M{n(48 + k * colw)} 318V408" stroke="{t["line"]}"/>')
        s.add(s.text(x - 2, 364, num, "serif", 64, "gold", ls=-1))
        if unit == "×":
            s.add(s.text(x + tw(num, "serif", 64, -1) + 2, 364, unit, "serif", 46, "gold"))
        elif unit:
            s.add(s.text(x + tw(num, "serif", 64, -1) + 4, 364, unit, "mono", 14, "gold", ls=1))
        for i, L in enumerate(wrap(label.upper(), "mono", 10.5, colw - 44, 1.3)):
            s.add(s.text(x, 390 + i * 16, L, "mono", 10.5, "ink3", ls=1.3))
    return s


# ─────────────────────────────── headers ───────────────────────────────
def header(theme, key, num, title, meta):
    W, H = 1200, 112
    s = SVG(f"h-{key}", W, H, theme, f"{num} — {title}")
    t = s.t
    s.add(s.text(2, 72, num, "mono", 14, "gold", ls=1))
    s.add(s.text(42, 82, title, "serif", 56, "ink", ls=-.6))
    x0 = 42 + tw(title, "serif", 56, -.6) + 28
    s.add(f'<path d="M{n(x0)} 68.5H{W - 2}" stroke="{t["line2"]}"/>')
    s.add(f'<rect x="{W - 8}" y="65" width="6" height="7" fill="{t["gold"]}"/>')
    s.add(rule_sweep(s, x0, W - 12, 68.5, dur=8, seg=72))
    s.add(s.text(W - 2, 52, meta, "mono", 11.5, "ink3", anchor="end", ls=2.2))
    return s


# ─────────────────────────────── cards ─────────────────────────────────
def card(theme, key, d):
    W, H = 600, 450
    s = SVG(f"card-{key}", W, H, theme, f'{d["title"]} — {d["tagline"]}',
            f'{d["title"]}: {d["tagline"]} Built with {", ".join(d["tags"])}.')
    t = s.t
    plate(s, rx=20)
    VX, VY, VW, VH = 16, 16, 568, 258
    vc = s.uid("vc")
    s.d(f'<clipPath id="{vc}"><rect x="{VX}" y="{VY}" width="{VW}" height="{VH}" rx="12"/></clipPath>')
    s.add(f'<rect x="{VX + .5}" y="{VY + .5}" width="{VW - 1}" height="{VH - 1}" rx="12" fill="{t["bg2"]}" stroke="{t["line"]}"/>')
    s.add(f'<g clip-path="url(#{vc})">')
    d["illus"](s, VX, VY, VW, VH)
    s.add("</g>")
    s.add(s.text(VX + 18, VY + 30, d["label"], "mono", 10.5, "ink3", ls=1.8))
    s.add(arrow_ne(VX + VW - 31, VY + 17, 12, t["gold"]))
    s.add(s.text(33, 336, d["title"], "serif", 50, "ink", ls=-.5))
    s.add(s.text(566, 336, d["domain"], "mono", 12, "gold", anchor="end", ls=1))
    for i, L in enumerate(wrap(d["tagline"], "sans", 15.5, 528)[:2]):
        s.add(s.text(35, 366 + i * 22, L, "sans", 15.5, "ink2"))
    x = 35
    for tag in d["tags"]:
        x += pill(s, x, 420, tag) + 8
    return s


def mini(theme, key, d):
    W, H = 600, 230
    s = SVG(f"mini-{key}", W, H, theme, f'{d["title"]} — {d["tagline"]}',
            f'{d["title"]}: {d["tagline"]} Built with {", ".join(d["tags"])}.')
    t = s.t
    plate(s, rx=20)
    GX, GY, GW, GH = 432, 16, 152, 198
    gc = s.uid("gc")
    s.d(f'<clipPath id="{gc}"><rect x="{GX}" y="{GY}" width="{GW}" height="{GH}" rx="12"/></clipPath>')
    s.add(f'<rect x="{GX + .5}" y="{GY + .5}" width="{GW - 1}" height="{GH - 1}" rx="12" fill="{t["bg2"]}" stroke="{t["line"]}"/>')
    s.add(f'<g clip-path="url(#{gc})">')
    d["illus"](s, GX, GY, GW, GH)
    s.add("</g>")
    s.add(arrow_ne(GX + GW - 29, GY + 15, 11, t["gold"]))
    s.add(s.text(32, 50, d["label"], "mono", 10.5, "ink3", ls=1.8))
    s.add(s.text(30, 104, d["title"], "serif", 44, "ink", ls=-.4))
    for i, L in enumerate(wrap(d["tagline"], "sans", 15, 380)[:2]):
        s.add(s.text(32, 136 + i * 21, L, "sans", 15, "ink2"))
    x = 32
    for tag in d["tags"]:
        x += pill(s, x, 194, tag) + 8
    if x > GX:
        print(f"  ! mini-{key}: tags overflow ({x:.0f}px)")
    return s


# ─────────────────────────── illustrations ─────────────────────────────
def illus_artisser(s, VX, VY, VW, VH):
    """A starling murmuration: one flock, no leader, folding along a figure-eight."""
    t = s.t
    cx, cy = VX + VW / 2 + 10, VY + VH / 2 + 4
    a, b = 206, 140
    pts = [(cx + a * math.sin(th), cy + b * math.sin(th) * math.cos(th))
           for th in (math.tau * k / 72 for k in range(72))]
    d = smooth(pts, closed=True)
    fp = s.uid("fp")
    s.add(f'<path id="{fp}" d="{d}" fill="none" stroke="{t["line2"]}" stroke-dasharray="1.5 7"/>')
    rnd = random.Random(7)
    dur = 16
    for _ in range(170):
        lag = rnd.random() ** 1.25 * 2.1
        rho, phi = math.sqrt(rnd.random()), rnd.uniform(0, math.tau)
        ox, oy = 15 * rho * math.cos(phi), 10 * rho * math.sin(phi)
        r = rnd.uniform(.85, 1.6) if rnd.random() < .85 else rnd.uniform(1.6, 2.2)
        col = t["gold"] if rnd.random() < .2 else t["ink"]
        s.add(f'<g><animateTransform attributeName="transform" type="translate" '
              f'values="{n(ox)} {n(oy)};{n(ox * 1.8)} {n(oy * .55)};{n(ox * .65)} {n(oy * 1.6)};{n(ox)} {n(oy)}" '
              f'keyTimes="0;.33;.66;1" calcMode="spline" keySplines="{EASE};{EASE};{EASE}" dur="7s" repeatCount="indefinite"/>'
              f'<circle r="{n(r)}" fill="{col}" opacity="{rnd.uniform(.5, 1):.2f}">'
              f'<animateMotion dur="{dur}s" begin="-{lag:.2f}s" repeatCount="indefinite"><mpath xlink:href="#{fp}"/></animateMotion></circle></g>')
    s.add(s.text(VX + 18, VY + VH - 18, "MURMURATION · n = 170 · NO LEADER", "mono", 10, "ink3", ls=1.6))


def illus_fixmob(s, VX, VY, VW, VH):
    """Exploded phone anatomy — layers separate, get diagnosed, snap back."""
    t = s.t
    cx, cy, sc = VX + 196, VY + 178, .8
    iso = "matrix(.866 .5 -.866 .5 0 0)"
    ns = 'vector-effect="non-scaling-stroke"'
    body = "x=\"-45\" y=\"-90\" width=\"90\" height=\"180\" rx=\"14\""
    dg = s.uid("dg")
    s.d(f'<linearGradient id="{dg}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{t["gold"]}" stop-opacity=".34"/>'
        f'<stop offset="1" stop-color="{t["gold"]}" stop-opacity=".04"/></linearGradient>')
    layers = [
        ("BACK COVER", f'<rect {body} fill="{t["tile"]}" stroke="{t["line2"]}" {ns}/>'
                       f'<rect x="-37" y="-82" width="32" height="32" rx="9" fill="none" stroke="{t["ink3"]}" {ns}/>'
                       f'<circle cx="-28" cy="-73" r="5" fill="none" stroke="{t["ink3"]}" {ns}/>'
                       f'<circle cx="-14" cy="-73" r="5" fill="none" stroke="{t["ink3"]}" {ns}/>'
                       f'<circle cx="-28" cy="-59" r="5" fill="none" stroke="{t["ink3"]}" {ns}/>'),
        ("BOARD + BATTERY", f'<rect x="-38" y="-84" width="76" height="70" rx="6" fill="none" stroke="{t["line2"]}" {ns}/>'
                            f'<rect x="-26" y="-72" width="22" height="22" rx="2" fill="none" stroke="{t["gold"]}" {ns}/>'
                            f'<rect x="6" y="-74" width="20" height="12" rx="2" fill="none" stroke="{t["ink3"]}" {ns}/>'
                            f'<rect x="8" y="-56" width="18" height="10" rx="2" fill="none" stroke="{t["ink3"]}" {ns}/>'
                            f'<path d="M-4 -61H6M-15 -50V-30M16 -46V-30H-15" fill="none" stroke="{t["line2"]}" {ns}/>'
                            f'<rect x="-34" y="-6" width="68" height="88" rx="7" fill="{t["gold"]}" fill-opacity=".07" stroke="{t["lo"]}" {ns}/>'
                            f'<path d="M-6 36H6M0 30V42" stroke="{t["lo"]}" {ns}/>'),
        ("FRAME", f'<rect {body} fill="none" stroke="{t["ink3"]}" {ns}/>'
                  f'<rect x="-40" y="-85" width="80" height="170" rx="10" fill="none" stroke="{t["line2"]}" {ns}/>'),
        ("DISPLAY", f'<rect x="-42" y="-87" width="84" height="174" rx="11" fill="url(#{dg})" stroke="{t["line2"]}" {ns}/>'
                    f'<rect x="-30" y="-74" width="34" height="5" rx="2.5" fill="{t["ink3"]}" opacity=".5"/>'
                    f'<rect x="-30" y="-60" width="60" height="38" rx="5" fill="{t["gold"]}" opacity=".18"/>'
                    f'<rect x="-30" y="-14" width="48" height="5" rx="2.5" fill="{t["ink3"]}" opacity=".45"/>'
                    f'<rect x="-30" y="-2" width="30" height="5" rx="2.5" fill="{t["ink3"]}" opacity=".35"/>'),
        ("GLASS", f'<rect {body} fill="{t["ink"]}" fill-opacity=".035" stroke="{t["gold"]}" {ns}/>'
                  f'<path d="M-30 60L28 -78" stroke="{t["ink"]}" stroke-opacity=".12" {ns}/>'),
    ]
    kt = "0;.14;.42;.62;.9;1"
    ks = f"{HOLD};{SNAP};{HOLD};{SNAP};{HOLD}"
    dur, ga, ge = 8, 7, 30
    s.add(f'<g transform="translate({n(cx)} {n(cy)}) scale({sc})">')
    for z, (name, shapes) in enumerate(layers):
        a, e = -z * ga, -z * ge
        s.add(f'<g><animateTransform attributeName="transform" type="translate" values="0 {a};0 {a};0 {e};0 {e};0 {a};0 {a}" '
              f'keyTimes="{kt}" calcMode="spline" keySplines="{ks}" dur="{dur}s" repeatCount="indefinite"/>')
        s.add(f'<g opacity="0"><animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="{kt}" calcMode="spline" '
              f'keySplines="{ks}" dur="{dur}s" repeatCount="indefinite"/>'
              f'<path d="M121 -22.5H180" stroke="{t["line2"]}" {ns}/><circle cx="121" cy="-22.5" r="2.4" fill="{t["gold"]}"/>' +
              s.text(188, -18, name, "mono", 12.5, "ink2", ls=1.5) + "</g>")
        s.add(f'<g transform="{iso}">{shapes}</g></g>')
    s.add("</g>")
    tx, ty = VX + 382, VY + 214
    s.add(s.rich(tx, ty, [("$ ", "gold"), ("diagnose --all", "ink2")], "mono", 12))
    s.add(check(tx + 1, ty + 18, 10, t["gold"]))
    s.add(s.text(tx + 18, ty + 23, "system restored", "mono", 12, "ink"))


TOOTH = ("M-38 -42C-40 -66 -20 -74 -8 -66C-3 -63 3 -63 8 -66C20 -74 40 -66 38 -42C37 -22 31 -8 28 10"
         "C25 32 22 62 12 66C4 69 4 40 0 30C-4 40 -4 69 -12 66C-22 62 -25 32 -28 10C-31 -8 -37 -22 -38 -42Z")


def illus_densi(s, VX, VY, VW, VH):
    """300-frame scroll hero: a tooth drawn frame by frame, with a counter and a film strip."""
    t = s.t
    tx, ty = VX + 128, VY + 138
    s.add(f'<g transform="translate({tx} {ty}) scale(1.28)">'
          f'<path d="{TOOTH}" fill="none" stroke="{t["line2"]}" vector-effect="non-scaling-stroke"/>'
          f'<path d="{TOOTH}" fill="{t["gold"]}" fill-opacity=".05" stroke="{t["gold"]}" stroke-width="1.7" pathLength="1" '
          f'stroke-dasharray="1 1" vector-effect="non-scaling-stroke">'
          f'<animate attributeName="stroke-dashoffset" values="1;0;0;-1" keyTimes="0;.45;.72;1" calcMode="spline" '
          f'keySplines="{EASE};{HOLD};{EASE}" dur="6s" repeatCount="indefinite"/></path>'
          f'<path d="M-25 -40C-17 -50 -8 -48 0 -44C8 -48 17 -50 25 -40" fill="none" stroke="{t["ink3"]}" '
          f'vector-effect="non-scaling-stroke"/></g>')
    # frame counter (odometer)
    fx, fy, fs = VX + 290, VY + 132, 46
    cw = fs * .6
    s.add(s.text(fx, VY + 76, "FRAME", "mono", 10.5, "ink3", ls=2.2))
    for col, (count, dur) in enumerate(((3, 30), (10, 10), (10, 1))):
        cid = s.uid("dc")
        s.d(f'<clipPath id="{cid}"><rect x="{n(fx + col * cw)}" y="{fy - fs * .78}" width="{n(cw)}" height="{fs * .98}"/></clipPath>')
        lh = fs
        vals = ";".join(f"0 {-k * lh}" for k in range(count))
        digits = "".join(s.text(fx + col * cw, fy + k * lh, str(k), "mono", fs, "ink") for k in range(count))
        s.add(f'<g clip-path="url(#{cid})"><g><animateTransform attributeName="transform" type="translate" values="{vals}" '
              f'calcMode="discrete" dur="{dur}s" repeatCount="indefinite"/>{digits}</g></g>')
    s.add(s.text(fx + 3 * cw + 8, fy, "/ 300", "mono", 19, "ink3"))
    s.add(f'<rect x="{fx}" y="{fy + 20}" width="236" height="2" fill="{t["line2"]}"/>'
          f'<rect x="{fx}" y="{fy + 20}" width="0" height="2" fill="{t["gold"]}">'
          f'<animate attributeName="width" values="0;236" dur="30s" repeatCount="indefinite"/></rect>')
    s.add(s.text(fx, fy + 48, "SCROLL-SCRUBBED HERO", "mono", 10.5, "ink3", ls=1.8))
    # film strip
    sx0, sy, fw, fh, gap, P = VX + 252, VY + 202, 44, 30, 8, 6
    sc = s.uid("sc")
    s.d(f'<clipPath id="{sc}"><rect x="{sx0}" y="{sy - 10}" width="{VX + VW - 16 - sx0}" height="{fh + 20}"/></clipPath>')
    frames = []
    for k in range(14):
        x = sx0 + k * (fw + gap)
        ang = -14 + (k % P) * 5.6
        frames.append(f'<rect x="{x + .5}" y="{sy + .5}" width="{fw - 1}" height="{fh - 1}" rx="3" fill="none" stroke="{t["line2"]}"/>'
                      f'<path d="{TOOTH}" transform="translate({n(x + fw / 2)} {n(sy + fh / 2)}) rotate({n(ang)}) scale(.17)" '
                      f'fill="none" stroke="{t["ink3"]}" vector-effect="non-scaling-stroke"/>'
                      f'<path d="M{x + 4} {sy - 5}h5M{x + 18} {sy - 5}h5M{x + 32} {sy - 5}h5M{x + 4} {sy + fh + 5}h5M{x + 18} {sy + fh + 5}h5M{x + 32} {sy + fh + 5}h5" stroke="{t["line2"]}" stroke-width="2"/>')
    s.add(f'<g clip-path="url(#{sc})"><g><animateTransform attributeName="transform" type="translate" from="0 0" '
          f'to="{-P * (fw + gap)} 0" dur="5s" repeatCount="indefinite"/>{"".join(frames)}</g></g>')
    hx = sx0 + 2 * (fw + gap) - 3
    s.add(f'<rect x="{hx}" y="{sy - 3}" width="{fw + 6}" height="{fh + 6}" rx="4" fill="none" stroke="{t["gold"]}" stroke-width="1.4"/>')


def illus_fitfactory(s, VX, VY, VW, VH):
    """A fragment shader, approximated: drifting light fields over a pixel grid."""
    t = s.t
    dark = s.theme == "dark"
    cols = [t["gold"], "#7a5a33" if dark else "#d9c09a", t["hi"], "#3d2c18" if dark else "#a8875a"]
    blobs = [(.30, .55, 150, 19, [(0, 0), (120, -40), (60, 50), (-40, 20)]),
             (.70, .40, 170, 23, [(0, 0), (-110, 50), (-30, -40), (40, 30)]),
             (.50, .80, 120, 17, [(0, 0), (90, -60), (-80, -30), (20, 10)]),
             (.85, .85, 130, 29, [(0, 0), (-60, -70), (-140, 10), (-20, 20)])]
    s.add("<g>")
    for (fx, fy, r, dur, path), col in zip(blobs, cols):
        gid = s.uid("bl")
        s.d(f'<radialGradient id="{gid}"><stop offset="0" stop-color="{col}" stop-opacity="{.85 if dark else .75}"/>'
            f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></radialGradient>')
        vals = ";".join(f"{n(x)} {n(y)}" for x, y in path + path[:1])
        kt = ";".join(f"{k / len(path):.3f}" for k in range(len(path) + 1))
        ksp = ";".join([EASE] * len(path))
        s.add(f'<circle cx="{n(VX + VW * fx)}" cy="{n(VY + VH * fy)}" r="{r}" fill="url(#{gid})" '
              f'style="mix-blend-mode:{t["blend"]}">'
              f'<animateTransform attributeName="transform" type="translate" values="{vals}" keyTimes="{kt}" '
              f'calcMode="spline" keySplines="{ksp}" dur="{dur}s" repeatCount="indefinite"/></circle>')
    s.add("</g>")
    pid = s.uid("px")
    s.d(f'<pattern id="{pid}" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="1.2" height="1.2" fill="{t["bg"]}"/></pattern>')
    s.add(f'<rect x="{VX}" y="{VY}" width="{VW}" height="{VH}" fill="url(#{pid})" opacity=".55"/>')
    bx, by = VX + 18, VY + VH - 92
    s.add(f'<rect x="{bx}" y="{by}" width="318" height="74" rx="8" fill="{t["bg"]}" fill-opacity=".86" stroke="{t["line"]}"/>')
    code = [[("uniform ", "gold"), ("float uTime;", "ink2")],
            [("vec3 ", "gold"), ("col = field(uv, uTime);", "ink2")],
            [("gl_FragColor", "ink"), (" = vec4(col, 1.0);", "ink2")]]
    for i, parts in enumerate(code):
        s.add(s.rich(bx + 14, by + 22 + i * 19, parts, "mono", 11.5))
    s.add(s.text(VX + VW - 18, VY + VH - 18, "GLSL · FRAGMENT", "mono", 10, "ink3", anchor="end", ls=1.6))


def illus_fincotime(s, GX, GY, GW, GH):
    """Two bubbles, one message: live translation."""
    t = s.t
    for side, (bx, by) in enumerate(((GX + 18, GY + 52), (GX + 54, GY + 112))):
        w, h = 82, 48
        s.add(f'<rect x="{bx + .5}" y="{by + .5}" width="{w}" height="{h}" rx="10" fill="{t["tile"]}" stroke="{t["line2"]}"/>')
        tail = (f"M{bx + 14} {by + h + .5}l-2 9l11 -9" if side == 0 else f"M{bx + w - 14} {by + h + .5}l2 9l-11 -9")
        s.add(f'<path d="{tail}" fill="{t["tile"]}" stroke="{t["line2"]}"/>')
        for i, lw in enumerate((54, 40, 60)[: 2 + side]):
            ly = by + 14 + i * 11
            s.add(f'<rect x="{bx + 12}" y="{ly}" width="{lw}" height="4" rx="2" fill="{t["line2"]}"/>')
            s.add(f'<rect x="{bx + 12}" y="{ly}" width="0" height="4" rx="2" fill="{t["gold"]}">'
                  f'<animate attributeName="width" values="0;0;{lw};{lw};0" keyTimes="0;{.08 + side * .38 + i * .05:.2f};'
                  f'{.24 + side * .38 + i * .05:.2f};.9;1" dur="4.4s" repeatCount="indefinite"/></rect>')
    s.add(f'<path d="M{GX + 112} {GY + 82}c10 4 14 12 12 22" fill="none" stroke="{t["gold"]}" stroke-dasharray="2 4"/>')


def illus_overtap(s, GX, GY, GW, GH):
    """Tap. Tap. Tap."""
    t = s.t
    cx, cy = GX + GW / 2, GY + GH / 2 + 8
    for k in range(3):
        s.add(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="8" fill="none" stroke="{t["gold"]}">'
              f'<animate attributeName="r" values="8;62" dur="2.4s" begin="{k * .8}s" repeatCount="indefinite" calcMode="spline" keyTimes="0;1" keySplines=".2 .6 .4 1"/>'
              f'<animate attributeName="opacity" values=".9;0" dur="2.4s" begin="{k * .8}s" repeatCount="indefinite"/></circle>')
    s.add(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="7" fill="{t["gold"]}">'
          f'<animate attributeName="r" values="7;5;7" dur=".8s" repeatCount="indefinite"/></circle>')
    s.add(s.text(cx, GY + GH - 18, "1 v 1 · DUEL", "mono", 10, "ink3", anchor="middle", ls=1.6))


# ────────────────────────────── flagship ───────────────────────────────
def flagship(theme, d):
    W, H = 1200, 460
    s = SVG("card-sportgen", W, H, theme, f'{d["title"]} — {d["tagline"]}',
            f'{d["title"]}: {d["tagline"]} {d["extra"]} Built with {", ".join(d["tags"])}.')
    t = s.t
    plate(s, glow=(890, 236, 430, .8))
    frame(s)
    s.add(s.rich(48, 62, [("01 / FLAGSHIP", "gold"), ("  —  ARCHITECTURE · DESIGN · FRONTEND", "ink3")], "mono", 11.5, ls=2))
    s.add(s.text(1130, 62, d["domain"], "mono", 12, "gold", anchor="end", ls=1))
    s.add(arrow_ne(1140, 51, 11, t["gold"]))
    s.add(s.text(42, 170, d["title"], "serif", 96, "ink", ls=-1.2))
    for i, L in enumerate(wrap(d["tagline"], "sans", 18, 520)):
        s.add(s.text(46, 214 + i * 27, L, "sans", 18, "ink2"))
    # 4 web + 4 mobile, lighting up in sequence
    gx, gy = 48, 306
    for k in range(8):
        if k < 4:
            x = gx + k * 34
            shape = (f'<rect x="{x + .5}" y="{gy + .5}" width="25" height="18" rx="2.5" fill="none" stroke="{t["ink3"]}">' + "{a}</rect>"
                     f'<path d="M{x + 1} {gy + 5.5}H{x + 25}" stroke="{t["line2"]}"/>')
        else:
            x = gx + 4 * 34 + 10 + (k - 4) * 22
            shape = (f'<rect x="{x + .5}" y="{gy - 3.5}" width="12" height="22" rx="3" fill="none" stroke="{t["ink3"]}">' + "{a}</rect>"
                     f'<path d="M{x + 4.5} {gy + 14.5}H{x + 8.5}" stroke="{t["line2"]}"/>')
        a = (f'<animate attributeName="stroke" values="{t["ink3"]};{t["gold"]};{t["ink3"]};{t["ink3"]}" keyTimes="0;.05;.2;1" '
             f'dur="5s" begin="{k * .2:.1f}s" repeatCount="indefinite"/>')
        s.add(shape.replace("{a}", a))
    s.add(s.text(gx + 4 * 34 + 10 + 4 * 22 + 14, gy + 14, "4 WEB + 4 MOBILE", "mono", 10.5, "ink3", ls=1.6))
    s.add(s.text(48, 360, "  ·  ".join(d["apps"]), "mono", 11, "gold", ls=1.6))
    x = 48
    for tag in d["tags"]:
        x += pill(s, x, 404, tag) + 8
    # radar — 30 criteria, morphing between three player profiles
    cx, cy, R, N = 890, 236, 150, 30
    ang = [-math.pi / 2 + math.tau * k / N for k in range(N)]
    for r in (.2, .4, .6, .8, 1):
        pts = " ".join(f"{n(cx + R * r * math.cos(a))},{n(cy + R * r * math.sin(a))}" for a in ang)
        s.add(f'<polygon points="{pts}" fill="none" stroke="{t["line2"] if r == 1 else t["line"]}"/>')
    s.add('<path d="' + "".join(f"M{cx} {cy}L{n(cx + R * math.cos(a))} {n(cy + R * math.sin(a))}" for a in ang) +
          f'" stroke="{t["line"]}"/>')
    for k in range(4, N, 5):
        a = ang[k]
        s.add(s.text(cx + (R + 17) * math.cos(a), cy + (R + 17) * math.sin(a) + 3.5, f"{k + 1:02d}", "mono", 9.5, "ink3",
                     anchor="middle"))
    profiles = []
    for seed in (3, 8, 21):
        rnd = random.Random(seed)
        ph = [rnd.uniform(0, math.tau) for _ in range(3)]
        vals = [.6 + .17 * math.sin(k * math.tau / N * 2 + ph[0]) + .1 * math.sin(k * math.tau / N * 5 + ph[1])
                + .06 * math.sin(k * math.tau / N * 9 + ph[2]) + rnd.uniform(-.04, .04) for k in range(N)]
        profiles.append([min(.96, max(.3, v)) for v in vals])
    order = [0, 0, 1, 1, 2, 2, 0]
    kt = "0;.25;.3333;.5833;.6667;.9167;1"
    ks = ";".join([HOLD, SNAP] * 3)
    dur = 12

    def poly(v):
        return " ".join(f"{n(cx + R * v[k] * math.cos(a))},{n(cy + R * v[k] * math.sin(a))}" for k, a in enumerate(ang))

    P = [poly(v) for v in profiles]
    anim = f'keyTimes="{kt}" calcMode="spline" keySplines="{ks}" dur="{dur}s" repeatCount="indefinite"'
    s.add(f'<polygon points="{P[0]}" fill="{t["gold"]}" fill-opacity=".13" stroke="{t["gold"]}" stroke-width="1.5" '
          f'stroke-linejoin="round"><animate attributeName="points" values="{";".join(P[i] for i in order)}" {anim}/></polygon>')
    for k, a in enumerate(ang):
        xs = [n(cx + R * v[k] * math.cos(a)) for v in profiles]
        ys = [n(cy + R * v[k] * math.sin(a)) for v in profiles]
        s.add(f'<circle cx="{xs[0]}" cy="{ys[0]}" r="2.1" fill="{t["gold"]}">'
              f'<animate attributeName="cx" values="{";".join(xs[i] for i in order)}" {anim}/>'
              f'<animate attributeName="cy" values="{";".join(ys[i] for i in order)}" {anim}/></circle>')
    s.add(s.text(1078, 150, "PROFILE", "mono", 10, "ink3", ls=2))
    for i in range(3):
        y = 176 + i * 24
        op = ";".join("1" if order[j] == i else ".28" for j in range(7))
        s.add(f'<g opacity="{1 if i == 0 else .28}"><animate attributeName="opacity" values="{op}" {anim}/>'
              f'<rect x="1078" y="{y - 8}" width="8" height="8" fill="{t["gold"]}"/>' +
              s.text(1094, y, f"P-0{i + 1}", "mono", 12, "ink", ls=1.4) + "</g>")
    s.add(s.text(cx, 430, "30 CRITERIA · AGE-PHASE WEIGHTING · RAE CORRECTION", "mono", 10, "ink3", anchor="middle", ls=1.7))
    return s


# ────────────────────────────── how I work ─────────────────────────────
def how(theme, tiles):
    W, H = 1200, 440
    s = SVG("how", W, H, theme, "How I work",
            " ".join(f"{i + 1:02d}. {a.replace('→', 'to')}: {b}" for i, (a, b) in enumerate(tiles)))
    t = s.t
    plate(s)
    TW, TH = 576, 196
    for i, (title, body) in enumerate(tiles):
        tx, ty = 16 + (i % 2) * (TW + 16), 16 + (i // 2) * (TH + 16)
        s.add(f'<rect x="{tx + .5}" y="{ty + .5}" width="{TW - 1}" height="{TH - 1}" rx="14" fill="{t["bg2"]}" stroke="{t["line"]}"/>')
        if i == 2:  # the nightly review bot gets a sweep
            cid, gid = s.uid("tc"), s.uid("sw")
            s.d(f'<clipPath id="{cid}"><rect x="{tx}" y="{ty}" width="{TW}" height="{TH}" rx="14"/></clipPath>'
                f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="{t["gold"]}" stop-opacity="0"/>'
                f'<stop offset=".9" stop-color="{t["gold"]}" stop-opacity=".07"/><stop offset="1" stop-color="{t["gold"]}" stop-opacity=".2"/></linearGradient>')
            s.add(f'<g clip-path="url(#{cid})"><g><rect x="{tx - 160}" y="{ty}" width="160" height="{TH}" fill="url(#{gid})"/>'
                  f'<rect x="{tx - 1}" y="{ty}" width="1" height="{TH}" fill="{t["gold"]}" opacity=".55"/>'
                  f'<animateTransform attributeName="transform" type="translate" values="0 0;{TW + 160} 0;{TW + 160} 0" '
                  f'keyTimes="0;.55;1" dur="7s" repeatCount="indefinite" calcMode="spline" keySplines="{EASE};{HOLD}"/></g></g>')
        s.add(s.text(tx + 28, ty + 42, f"{i + 1:02d}", "mono", 11.5, "gold", ls=2))
        s.add(f'<g transform="translate({tx + TW - 92} {ty + 26})">{tile_glyph(s, i)}</g>')
        x = tx + 26
        for j, part in enumerate(title.split("→")):
            part = part.strip()
            if j:
                s.add(arrow_e(x + 6, ty + 81, 26, t["gold"], 1.6))
                x += 44
            s.add(s.text(x, ty + 92, part, "serif", 36, "ink", ls=-.4))
            x += tw(part, "serif", 36, -.4)
        for k, L in enumerate(wrap(body, "sans", 16, TW - 60)):
            s.add(s.text(tx + 28, ty + 128 + k * 24, L, "sans", 16, "ink2"))
    return s


def tile_glyph(s, i):
    """64×40 line glyphs, one per principle."""
    t = s.t
    g, i3, l2, bg = t["gold"], t["ink3"], t["line2"], t["bg2"]
    if i == 0:  # artboard → markup
        return (f'<rect x=".5" y="6.5" width="28" height="22" rx="2" fill="none" stroke="{i3}"/>'
                f'<circle cx="9" cy="15" r="3" fill="none" stroke="{i3}"/><path d="M5 25l7-6 5 4 6-6" fill="none" stroke="{i3}"/>'
                f'<path d="M43 10l-6 7.5 6 7.5M57 10l6 7.5-6 7.5M52 8l-4 19" fill="none" stroke="{g}" stroke-width="1.4"/>'
                f'<circle r="1.6" fill="{g}"><animateMotion dur="2.6s" repeatCount="indefinite" path="M29 17.5H36"/>'
                f'<animate attributeName="opacity" values="0;1;0" dur="2.6s" repeatCount="indefinite"/></circle>')
    if i == 1:  # one root, many packages
        kids = [(6, 34), (32, 34), (58, 34)]
        out = f'<path d="' + "".join(f"M32 6L{x} {y}" for x, y in kids) + f'" stroke="{l2}"/>'
        for k, (x, y) in enumerate(kids):
            out += (f'<circle r="2" fill="{g}"><animateMotion dur="3s" begin="{k * .35:.2f}s" repeatCount="indefinite" '
                    f'path="M32 6L{x} {y}" keyPoints="0;1;1" keyTimes="0;.4;1" calcMode="linear"/>'
                    f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.05;.38;.42;1" dur="3s" begin="{k * .35:.2f}s" repeatCount="indefinite"/></circle>'
                    f'<rect x="{x - 4.5}" y="{y - 4.5}" width="9" height="9" rx="2" fill="{bg}" stroke="{i3}"/>')
        return out + f'<circle cx="32" cy="6" r="4.5" fill="{bg}" stroke="{g}" stroke-width="1.3"/>'
    if i == 2:  # nightly review
        out = (f'<circle cx="20" cy="20" r="13" fill="{g}" fill-opacity=".9"/><circle cx="27" cy="14" r="11.5" fill="{bg}"/>'
               + check(42, 21, 14, g, 1.6))
        for k, (x, y) in enumerate(((52, 6), (60, 30), (36, 34))):
            out += (f'<circle cx="{x}" cy="{y}" r="1.3" fill="{i3}"><animate attributeName="opacity" values=".2;1;.2" '
                    f'dur="{2.2 + k * .7:.1f}s" repeatCount="indefinite"/></circle>')
        return out
    # docs first
    out = (f'<path d="M14.5 .5H40L48.5 9V39.5H14.5Z" fill="none" stroke="{i3}"/><path d="M40 .5V9H48.5" fill="none" stroke="{i3}"/>')
    for k, w in enumerate((22, 26, 18)):
        y = 15 + k * 7
        out += (f'<rect x="20" y="{y}" width="{w}" height="2" rx="1" fill="{l2}"/>'
                f'<rect x="20" y="{y}" width="0" height="2" rx="1" fill="{g}"><animate attributeName="width" '
                f'values="0;0;{w};{w};0" keyTimes="0;{.1 + k * .18:.2f};{.25 + k * .18:.2f};.92;1" dur="4s" repeatCount="indefinite"/></rect>')
    return out


# ─────────────────────────────── toolkit ───────────────────────────────
def toolkit(theme, groups):
    W, H = 1200, 444
    total = sum(len(i) for _, i in groups)
    s = SVG("toolkit", W, H, theme, "Toolkit, grouped by layer",
            ". ".join(f"{g}: {', '.join(i)}" for g, i in groups) + ".")
    t = s.t
    plate(s, glow=(600, 470, 640, .55))
    frame(s)
    s.css.append(".b{opacity:.25;animation:bp 4.6s ease-in-out infinite}"
                 "@keyframes bp{0%,100%{opacity:.25}10%{opacity:1}28%{opacity:.25}}")
    idx = 0
    colw = (1152 - 52) / len(groups)
    for gi, (name, items) in enumerate(groups):
        x = 52 + gi * colw
        s.add(s.rich(x, 80, [(f"{gi + 1:02d}  ", "gold"), (name, "ink2")], "mono", 11, ls=2))
        s.add(f'<path d="M{n(x)} 98.5H{n(x + colw - 40)}" stroke="{t["line2"]}"/>')
        for k, it in enumerate(items):
            y = 140 + k * 36
            s.add(f'<rect class="b" x="{n(x)}" y="{y - 9}" width="7" height="7" fill="{t["gold"]}" style="animation-delay:{idx * .11:.2f}s"/>')
            s.add(s.text(x + 20, y, it, "mono", 15.5, "ink"))
            idx += 1
    s.add(f'<path d="M52 382.5H1148" stroke="{t["line"]}"/>')
    s.add(s.text(52, 410, f"{total} TOOLS · {len(groups)} LAYERS · ONE WORKSPACE", "mono", 11, "ink3", ls=2.2))
    s.add(s.text(1148, 410, "pnpm + Turborepo by default", "mono", 11, "gold", anchor="end", ls=1))
    return s


# ──────────────────────────────── path ─────────────────────────────────
def path_plate(theme, rows, langs):
    W, H = 1200, 440
    s = SVG("path", W, H, theme, "Path — from operator to instructor",
            " ".join(f"{p}: {r}, {o}. {nt}" for p, r, o, nt in rows) +
            " Languages: " + ", ".join(f"{a} ({b})" for a, b in langs) + ".")
    t = s.t
    plate(s, glow=(80, 120, 520, .6))
    frame(s)
    s.add(s.text(48, 62, "FIG. 5 — TRAJECTORY", "mono", 11.5, "gold", ls=2.2))
    s.add(s.text(1152, 62, "2020 — NOW", "mono", 11.5, "ink3", anchor="end", ls=2.2))
    ys = [118, 208, 298]
    lx = 74
    s.add(f'<path d="M{lx + .5} {ys[0]}V{ys[-1]}" stroke="{t["line2"]}"/>')
    s.add(f'<circle cx="{lx + .5}" cy="{ys[-1]}" r="3" fill="{t["gold"]}" opacity="0">'
          f'<animate attributeName="cy" values="{ys[-1]};{ys[0]};{ys[0]}" keyTimes="0;.6;1" calcMode="spline" keySplines="{EASE};{HOLD}" dur="5s" repeatCount="indefinite"/>'
          f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.1;.5;.6;1" dur="5s" repeatCount="indefinite"/></circle>')
    for i, ((period, role, org, note), y) in enumerate(zip(rows, ys)):
        if i == 0:
            s.add(led(s, lx + .5, y, 6, 2.6))
        else:
            s.add(f'<circle cx="{lx + .5}" cy="{y}" r="5.5" fill="{t["bg"]}" stroke="{t["gold"]}"/>')
        s.add(s.text(112, y + 5, period, "mono", 11.5, "gold", ls=2.2))
        s.add(s.text(300, y + 10, role, "serif", 40, "ink", ls=-.4))
        s.add(s.text(302, y + 38, org, "mono", 12, "ink3", ls=1.4))
        for k, L in enumerate(wrap(note, "sans", 15.5, 380)):
            s.add(s.text(770, y + 4 + k * 22, L, "sans", 15.5, "ink2"))
        if i < len(rows) - 1:
            s.add(f'<path d="M112 {y + 54.5}H1152" stroke="{t["line"]}"/>')
    yl = 386
    s.add(f'<path d="M48 {yl - 34.5}H1152" stroke="{t["line2"]}"/>')
    s.add(s.text(112, yl, "LANGUAGES", "mono", 11.5, "gold", ls=2.2))
    parts = []
    for i, (a, b) in enumerate(langs):
        parts += [(("   ·   " if i else "") + a, "ink"), (f" — {b}", "ink3")]
    s.add(s.rich(300, yl, parts, "sans", 16))
    return s


# ────────────────────────────── contact ────────────────────────────────
def button(theme, key, label, handle, i=0):
    W, H = 380, 92
    s = SVG(f"btn-{key}", W, H, theme, f"{label} — {handle}")
    t = s.t
    s.add(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="{(H - 1.5) / 2}" fill="{t["bg"]}" '
          f'stroke="{t["gold"]}" stroke-opacity=".75" stroke-width="1.5"/>')
    s.add(s.text(40, 51, label, "serif", 34, "ink", ls=-.3))
    s.add(s.text(41, 71, handle, "mono", 11, "ink3", ls=1.1))
    cx = W - 50
    s.add(f'<circle cx="{cx}" cy="{H / 2}" r="24" fill="none" stroke="{t["line2"]}"/>')
    s.add(f'<g>{arrow_ne(cx - 7, H / 2 - 7, 14, t["gold"], 1.6)}'
          f'<animateTransform attributeName="transform" type="translate" values="0 0;0 0;3 -3;0 0" keyTimes="0;.7;.85;1" '
          f'dur="3s" begin="{i * .45:.2f}s" repeatCount="indefinite"/></g>')
    return s


def footer(theme):
    W, H = 1200, 340
    s = SVG("footer", W, H, theme, "I am mentoring to learn, and learning to lead.",
            "Giorgi Khiladze · Batumi, Georgia. Set in Instrument Serif, Inter and JetBrains Mono.")
    t = s.t
    clip = plate(s, glow=(600, 360, 560, .9))
    m = hmask(s, [(0, 0), (.22, 1), (.78, 1), (1, 0)])
    s.add(f'<g clip-path="url(#{clip})">')
    waves(s, y0=214, y1=332, count=17, seed=4, amp0=3, amp1=13, mask=m, op0=.12, op1=.7, dur=90, breathe=4)
    s.add("</g>")
    frame(s)
    s.add(s.text(48, 62, "COLOPHON", "mono", 11.5, "gold", ls=2.2))
    s.add(s.text(1152, 62, "SET IN INSTRUMENT SERIF · INTER · JETBRAINS MONO", "mono", 11, "ink3", anchor="end", ls=2))
    s.add(s.text(600, 140, "“I am mentoring to learn, and learning to lead.”", "serifI", 46, "ink", anchor="middle", ls=-.3))
    s.add(s.text(600, 184, "GIORGI KHILADZE  ·  BATUMI, GEORGIA", "mono", 11.5, "ink3", anchor="middle", ls=2.6))
    return s


# ──────────────────────────────── DATA ─────────────────────────────────
SPORTGEN = dict(
    title="SportGen", domain="sportgen.org",
    tagline="Multi-sport SaaS ecosystem — 8 apps (4 web + 4 mobile) for scouting, federation management, "
            "CRM, coaches and referees, built around youth-sports training standards.",
    extra="Ships a 30-criteria player evaluation framework with age-phase weighting and RAE correction.",
    apps=["SCOUT PRO", "FMS", "CRM", "COACH", "REFEREE"],
    tags=["NEXT.JS", "REACT NATIVE", "TYPESCRIPT", "POSTGRESQL", "TURBOREPO"])

CARDS = {
    "artisser": dict(label="02 / DESIGN + FRONTEND", title="Artisser", domain="artisser.io",
                     tagline="Engineering-studio website built around a starling-murmuration concept — "
                             "interactive flock, engraved plates, light/dark theme.",
                     tags=["UI/UX DESIGN", "FRONTEND", "MOTION"], illus=illus_artisser),
    "fixmob": dict(label="03 / DESIGN + FRONTEND", title="FixMob", domain="fixmob.ge",
                   tagline="Phone repair studio in Batumi — trilingual site with a scroll-driven "
                           "phone-anatomy story.",
                   tags=["UI/UX DESIGN", "FRONTEND", "KA · EN · RU"], illus=illus_fixmob),
    "densi": dict(label="04 / SITE + MANAGEMENT SYSTEM", title="DENSI", domain="view live",
                  tagline="Dental clinic, end to end — cinematic 300-frame scroll hero, "
                          "patient CRM and appointment booking.",
                  tags=["REACT", "GSAP", "NEXT.JS", "SUPABASE"], illus=illus_densi),
    "fitfactory": dict(label="05 / PLATFORM + WEBGL", title="Fit Factory", domain="view live",
                       tagline="Management platform for a sports complex, fronted by a custom "
                               "WebGL shader hero.",
                       tags=["REACT", "WEBGL", "GLSL"], illus=illus_fitfactory),
}

MINIS = {
    "fincotime": dict(label="06 / ALSO SHIPPED", title="FincoTime",
                      tagline="Bilingual workforce management — tasks & notifications with live translation.",
                      tags=["NEXT.JS", "SUPABASE", "GOOGLE TRANSLATE API"], illus=illus_fincotime),
    "overtap": dict(label="07 / ON GOOGLE PLAY", title="overtap",
                    tagline="Mobile game — multiplayer, duel and competitive bill-splitting modes.",
                    tags=["REACT NATIVE", "FIREBASE"], illus=illus_overtap),
}

HEADERS = [
    ("about", "01", "About", "THE SHORT VERSION"),
    ("work", "02", "Selected work", "5 FEATURED · 2 MORE SHIPPED · 3 IN PROGRESS"),
    ("how", "03", "How I work", "4 PRINCIPLES"),
    ("toolkit", "04", "Toolkit", "GROUPED BY LAYER"),
    ("path", "05", "Path", "OPERATOR · MENTOR · INSTRUCTOR"),
    ("signal", "06", "Signal", "LIVE FROM GITHUB"),
    ("contact", "07", "Contact", "SAY HELLO"),
]

HOW = [
    ("Design → code", "One pair of hands: I design the interface and build it, so nothing gets lost in handoff."),
    ("Monorepo by default", "pnpm + Turborepo. SportGen alone spans an 8-app ecosystem in one workspace."),
    ("AI-assisted engineering", "Codebases onboarded for Claude Code — CLAUDE.md router, conventions and architecture "
                                "docs — plus a nightly senior code-review bot sweeping every app."),
    ("Docs before code", "Build briefs, architecture decisions and handoff documents come first. "
                         "Code follows the plan, not the other way round."),
]

TOOLKIT = [
    ("INTERFACE", ["TypeScript", "JavaScript", "React", "Next.js", "Tailwind CSS", "Sass", "Vite"]),
    ("MOTION & GRAPHICS", ["GSAP", "Framer Motion", "Lenis", "Three.js", "WebGL · GLSL", "Remotion", "After Effects"]),
    ("DATA & BACKEND", ["Node.js", "PostgreSQL · RLS", "Supabase", "Firebase", "Prisma"]),
    ("MOBILE & TOOLING", ["React Native", "pnpm", "Turborepo", "Git", "Jira", "Claude Code"]),
]

PATH = [
    ("NOW", "Programming Instructor", "10X ACADEMY · TENIXI LLC", "Teaching JavaScript & React. For every concept taught, I explore tenfold."),
    ("EARLIER", "Mentor", "10X ACADEMY", "Same team, earlier role — mentoring to learn."),
    ("2020 — 2026", "Operator", "BATUMI OIL TERMINAL", "Complex systems where failure is not an option. That discipline came with me."),
]
LANGS = [("Georgian", "native"), ("Russian", "C2"), ("English", "B2"), ("Turkish", "A2")]

BUTTONS = [("linkedin", "LinkedIn", "in/giorgi-khiladze"), ("instagram", "Instagram", "@goga.khilo"),
           ("email", "Email", "goga.khilo@gmail.com")]


def build():
    os.makedirs(OUT, exist_ok=True)
    total = 0
    for theme in THEMES:
        plates = [hero(theme), about(theme), flagship(theme, SPORTGEN), how(theme, HOW),
                  toolkit(theme, TOOLKIT), path_plate(theme, PATH, LANGS), footer(theme)]
        plates += [header(theme, *h) for h in HEADERS]
        plates += [card(theme, k, d) for k, d in CARDS.items()]
        plates += [mini(theme, k, d) for k, d in MINIS.items()]
        plates += [button(theme, *b, i) for i, b in enumerate(BUTTONS)]
        for p in plates:
            path = os.path.join(OUT, f"{p.name}-{theme}.svg")
            data = p.render()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data)
            total += len(data.encode())
            print(f"  {p.name}-{theme}.svg  {len(data.encode()) / 1024:6.1f} KB")
    print(f"total {total / 1024:.0f} KB")


if __name__ == "__main__":
    build()
