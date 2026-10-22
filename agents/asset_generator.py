"""Asset Generator: Edge-TTS voice-over (with word timings for captions),
procedural visuals per shot, and a procedural music bed. Everything is logged
in assets/manifest.csv with source and licence.

The visuals stand in for the official media kit: the generator draws abstract,
face-free motifs (no real likeness) so nothing needs a consent form. Drop real
media-kit stills into assets/official/<shot_id>.png and they are used instead."""
from __future__ import annotations

import asyncio
import csv
import json
import math
import os
import random
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .common import DIRS, FONTS, RunContext, Shot, log_call, rel, say, sha256, traced
from .riso import BLUE, PAPER, RED, Plates

W, H = 1080, 1920
PAD = 1.10                       # Ken Burns headroom
IW, IH = int(W * PAD), int(H * PAD)

PALETTE = {"paper": PAPER, "blue": BLUE, "red": RED}
SR = 48000


# ------------------------------------------------------------------ fonts
def font(name: str, size: int, weight: int | None = None, width: int | None = None) -> ImageFont.FreeTypeFont:
    """arch = Archivo (variable wdth/wght) for everything; mono only for real code/log text."""
    files = {"arch": "Archivo[wdth,wght].ttf", "mono": "JetBrainsMono[wght].ttf",
             "plexmono": "IBMPlexMono-Regular.ttf"}
    f = ImageFont.truetype(str(FONTS / files[name]), size)
    if name in ("arch", "mono"):
        try:
            vals = []
            for a in f.get_variation_axes():
                nm = str(a.get("name", "")).lower()
                if "weight" in nm or "wght" in nm:
                    v = weight or a["default"]
                elif "width" in nm or "wdth" in nm:
                    v = width or a["default"]
                else:
                    v = a["default"]
                vals.append(min(max(v, a["minimum"]), a["maximum"]))
            f.set_variation_by_axes(vals)
        except Exception:
            pass
    return f


_CMAPS = {}


def has_glyph(f: ImageFont.FreeTypeFont, ch: str) -> bool:
    from fontTools.ttLib import TTFont
    path = f.path
    if path not in _CMAPS:
        _CMAPS[path] = set(TTFont(path).getBestCmap())
    return ord(ch) in _CMAPS[path] or ch.isspace()


def draw_text(d: ImageDraw.ImageDraw, xy, text, f, fill, anchor="la", fallback=None):
    """Draw text, swapping to a fallback font for glyphs the display font lacks."""
    fallback = fallback or font("plexmono", int(f.size * 0.9))
    runs, cur, cur_fb = [], "", None
    for ch in text:
        fb = not has_glyph(f, ch)
        if cur and fb != cur_fb:
            runs.append((cur, cur_fb))
            cur = ""
        cur += ch
        cur_fb = fb
    if cur:
        runs.append((cur, cur_fb))
    if len(runs) == 1 and not runs[0][1]:
        d.text(xy, text, font=f, fill=fill, anchor=anchor)
        return
    widths = [d.textlength(r, font=fallback if fb else f) for r, fb in runs]
    total = sum(widths)
    x, y = xy
    x -= {"l": 0, "m": total / 2, "r": total}[anchor[0]]
    for (r, fb), w in zip(runs, widths):
        d.text((x, y), r, font=fallback if fb else f, fill=fill, anchor="l" + anchor[1])
        x += w


# ------------------------------------------------------------------- visuals
def X(x):  # 1080-space -> padded canvas
    return int(x + (IW - W) / 2)


def Y(y):
    return int(y + (IH - H) / 2)


def _erase(p: Plates, box):
    """Paper shows through: knock both plates out (an opaque sheet of paper on top)."""
    p.b.rectangle(box, fill=0)
    p.r.rectangle(box, fill=0)


def motif(style: str, rng: random.Random, ctx_info: dict) -> Image.Image:
    """Draw one shot's still as two ink separations; content stays in y 300-1010 (1080 space)."""
    p = Plates(IW, IH)
    B, R = p.b, p.r
    cx = X(540)
    big = lambda s, w=125, wt=900: font("arch", s, wt, w)

    if style == "hook":
        disc = Image.new("L", (IW, IH), 0)
        ImageDraw.Draw(disc).ellipse([cx - 340, Y(310), cx + 340, Y(990)], fill=255)
        grad = np.linspace(1.0, 0.25, IH, dtype=np.float32)[:, None] * np.ones((1, IW), np.float32)
        disc = Image.fromarray((np.asarray(disc, np.float32) * grad).astype(np.uint8))
        p.mask_halftone("red", disc, pitch=18)
        cy = Y(640)
        B.polygon([(cx - 250, cy - 20), (cx, cy - 130), (cx + 250, cy - 20), (cx, cy + 90)], fill=255)
        B.rectangle([cx - 140, cy + 30, cx + 140, cy + 170], fill=255)
        B.polygon([(cx - 140, cy + 30), (cx, cy + 92), (cx + 140, cy + 30)], fill=0)
        B.line([(cx + 250, cy - 20), (cx + 250, cy + 150)], fill=255, width=10)
        B.rectangle([cx + 236, cy + 150, cx + 264, cy + 210], fill=255)

    elif style == "lab":
        def iso(x, y, z):
            return cx + (x - y) * 82, Y(470) + (x + y) * 47 - z
        for gx in range(4):
            for gy in range(4):
                h = 70 + 34 * ((gx * 3 + gy) % 3)
                top = [iso(gx, gy, h), iso(gx + .82, gy, h), iso(gx + .82, gy + .82, h), iso(gx, gy + .82, h)]
                left = [iso(gx, gy + .82, h), iso(gx + .82, gy + .82, h), iso(gx + .82, gy + .82, 0), iso(gx, gy + .82, 0)]
                right = [iso(gx + .82, gy, h), iso(gx + .82, gy + .82, h), iso(gx + .82, gy + .82, 0), iso(gx + .82, gy, 0)]
                for poly in (left, right, top):
                    B.polygon(poly, fill=0)
                    R.polygon(poly, fill=0)
                side = Image.new("L", (IW, IH), 0)
                ImageDraw.Draw(side).polygon(right, fill=150)
                ImageDraw.Draw(side).polygon(left, fill=70)
                p.mask_halftone("blue", side, pitch=10)
                if (gx + 2 * gy) % 3 == 0:
                    R.polygon(top, fill=255)
                for poly in (left, right, top):
                    B.polygon(poly, outline=255, width=4)
        draw_text(B, (cx, Y(985)), "LY Agentic AI Lab · final year", big(40, 100, 700), 255, anchor="ms")

    elif style == "graph":
        names = ["Planner", "Researcher", "Script", "Storyboard", "Assets", "Editor", "Critic"]
        nodes = []
        for i, n in enumerate(names):
            ang = -math.pi / 2 + i * 2 * math.pi / len(names)
            nodes.append((cx + 300 * math.cos(ang), Y(640) + 300 * math.sin(ang), n))
        for i in range(len(nodes) - 1):
            B.line([nodes[i][:2], nodes[i + 1][:2]], fill=255, width=6)
        R.line([nodes[-1][:2], (cx, Y(640)), nodes[2][:2]], fill=255, width=14, joint="curve")
        for i, (x, y, n) in enumerate(nodes):
            s = 66
            _erase(p, [x - s, y - s, x + s, y + s])
            B.rectangle([x - s, y - s, x + s, y + s], outline=255, width=7)
            if n == "Critic":
                R.rectangle([x - s + 12, y - s + 12, x + s - 12, y + s - 12], fill=255)
            draw_text(B, (x, y), f"{i + 1}", big(64), 255, anchor="mm")
            draw_text(B, (x, y + s + 30), n, big(30, 100, 700), 255, anchor="mm")

    elif style == "docs":
        for k, (dx, dy) in enumerate([(-120, 0), (80, 40), (-20, 90)]):
            x0, y0 = cx - 260 + dx, Y(320) + dy
            box = [x0, y0, x0 + 520, y0 + 640]
            _erase(p, box)
            B.rectangle(box, outline=255, width=6)
            for j in range(13):
                yy = y0 + 70 + j * 40
                w = 430 if j % 4 else 260
                if k == 2 and j == 6:
                    R.rectangle([x0 + 28, yy - 16, x0 + 492, yy + 18], fill=255)
                    w = 440
                B.rectangle([x0 + 40, yy - 5, x0 + 40 + w, yy + 6], fill=255)
            if k == 2:
                draw_text(B, (x0 + 40, y0 + 34), "LY_AgenticAI_Lab_Handout.pdf", font("mono", 22, 600), 255,
                          anchor="lm")
                R.rectangle([x0 + 330, y0 + 560, x0 + 500, y0 + 620], outline=255, width=6)
                draw_text(R, (x0 + 415, y0 + 590), "p. 1", big(36, 110), 255, anchor="mm")

    elif style == "tools":
        for i, lab in enumerate(["Text", "Image", "Speech", "Video"]):
            x0 = X(120 + (i % 2) * 440)
            y0 = Y(320 + (i // 2) * 330)
            B.rectangle([x0, y0, x0 + 400, y0 + 290], outline=255, width=7)
            gx, gy = x0 + 200, y0 + 120
            if lab == "Text":
                draw_text(B, (gx, gy), "Aa", big(130), 255, anchor="mm")
            elif lab == "Image":
                R.polygon([(gx - 110, gy + 60), (gx - 20, gy - 60), (gx + 60, gy + 60)], fill=255)
                B.ellipse([gx + 40, gy - 70, gx + 100, gy - 10], fill=255)
            elif lab == "Speech":
                for j, hh in enumerate([20, 50, 90, 60, 110, 40, 80, 100, 50, 70, 30]):
                    B.rectangle([gx - 120 + j * 22, gy - hh / 2, gx - 108 + j * 22, gy + hh / 2], fill=255)
            else:
                R.polygon([(gx - 50, gy - 70), (gx + 70, gy), (gx - 50, gy + 70)], fill=255)
            draw_text(B, (x0 + 24, y0 + 262), lab, big(34, 100, 800), 255, anchor="ls")

    elif style == "clock":
        c = (cx, Y(600))
        R.arc([c[0] - 330, c[1] - 330, c[0] + 330, c[1] + 330], -90, 200, fill=255, width=44)
        B.ellipse([c[0] - 330, c[1] - 330, c[0] + 330, c[1] + 330], outline=255, width=6)
        draw_text(B, (c[0], c[1] - 20), "3:00", big(190, 100), 255, anchor="mm")
        draw_text(B, (c[0], c[1] + 120), "hours, hard stop", big(40, 100, 700), 255, anchor="mm")
        y = Y(985)
        B.rectangle([X(120), y - 46, X(960), y], outline=255, width=6)
        p.halftone("blue", (X(132), y - 36, X(960) - 10, y - 8), 0.35, pitch=10)
        draw_text(B, (X(120), y - 62), "API budget", big(34, 100, 800), 255, anchor="ls")
        draw_text(B, (X(960), y - 62), "₹500 cap", big(34, 100, 800), 255, anchor="rs")

    elif style == "terminal":
        # the run log printed as a till receipt
        x0, x1, y0, y1 = X(170), X(910), Y(300), Y(990)
        B.rectangle([x0, y0, x1, y1], outline=255, width=5)
        for i in range(0, x1 - x0, 40):
            B.polygon([(x0 + i, y1), (x0 + i + 20, y1 + 24), (x0 + i + 40, y1)], fill=255)
        draw_text(B, ((x0 + x1) / 2, y0 + 56), "RUN LOG · RECEIPT", big(40, 125), 255, anchor="mm")
        B.line([(x0 + 30, y0 + 96), (x1 - 30, y0 + 96)], fill=255, width=3)
        recs = ctx_info.get("log_tail", [])[-10:]
        f = font("mono", 24, 600)
        fr = font("plexmono", 24)
        for i, r in enumerate(recs):
            yy = y0 + 136 + i * 42
            B.text((x0 + 36, yy), f"{r['agent'][:13]:<13} {r['tool'][:14]:<14}", font=f, fill=255, anchor="lm")
            R.text((x1 - 36, yy), f"₹{r['cost_inr']:.2f}", font=fr, fill=255, anchor="rm")
        yy = y0 + 136 + len(recs) * 42 + 10
        B.line([(x0 + 30, yy), (x1 - 30, yy)], fill=255, width=3)
        draw_text(B, (x0 + 36, yy + 40), "TOTAL", big(36, 112), 255, anchor="lm")
        draw_text(R, (x1 - 36, yy + 40), f"₹{sum(r['cost_inr'] for r in recs):.2f}", big(36, 112), 255,
                  anchor="rm")

    elif style == "deploy":
        for i, u in enumerate(["github.io", "huggingface.co/spaces", "streamlit.app"]):
            x0, y0 = X(110 + i * 80), Y(330 + i * 170)
            box = [x0, y0, x0 + 700, y0 + 420]
            _erase(p, box)
            B.rectangle(box, outline=255, width=6)
            B.line([(x0, y0 + 70), (x0 + 700, y0 + 70)], fill=255, width=4)
            draw_text(B, (x0 + 30, y0 + 36), u, font("mono", 26, 600), 255, anchor="lm")
            for j in range(3):
                B.rectangle([x0 + 34, y0 + 110 + j * 70, x0 + 34 + (560 - j * 140), y0 + 140 + j * 70], fill=255)
        R.line([(X(250), Y(990)), (X(890), Y(420))], fill=255, width=34)
        R.polygon([(X(940), Y(370)), (X(800), Y(400)), (X(900), Y(510))], fill=255)

    elif style == "shield":
        c = (cx, Y(560))
        sh = [(c[0], c[1] - 230), (c[0] + 240, c[1] - 140), (c[0] + 205, c[1] + 140), (c[0], c[1] + 260),
              (c[0] - 205, c[1] + 140), (c[0] - 240, c[1] - 140)]
        inner = Image.new("L", (IW, IH), 0)
        ImageDraw.Draw(inner).polygon(sh, fill=110)
        p.mask_halftone("blue", inner, pitch=12)
        B.polygon(sh, outline=255, width=12)
        R.line([(c[0] - 105, c[1] + 10), (c[0] - 20, c[1] + 100), (c[0] + 140, c[1] - 95)], fill=255, width=42,
               joint="curve")
        draw_text(B, (c[0], Y(985)), "grounding · consent · disclosure · licensing", big(30, 100, 700), 255,
                  anchor="ms")

    elif style == "reel":
        thumbs = ctx_info.get("thumbs", [])
        x0, x1 = cx - 250, cx + 250
        B.rectangle([x0, Y(300), x1, Y(1000)], fill=255)
        for yy in range(Y(318), Y(990), 44):
            B.rectangle([x0 + 14, yy, x0 + 34, yy + 22], fill=0)
            B.rectangle([x1 - 34, yy, x1 - 14, yy + 22], fill=0)
        for i in range(3):
            fy = Y(318 + i * 228)
            box = [x0 + 52, fy, x1 - 52, fy + 210]
            B.rectangle(box, fill=0)
            if i < len(thumbs):
                t = Image.open(thumbs[-(i + 1)]).convert("L").resize((box[2] - box[0], box[3] - box[1]))
                ink = np.clip((255 - np.asarray(t, np.float32)) * 2.2, 0, 255).astype(np.uint8)
                p.blue.paste(Image.fromarray(ink), (box[0], box[1]))
            R.rectangle([box[2] - 150, box[3] - 46, box[2] - 8, box[3] - 8], fill=255)
            draw_text(R, (box[2] - 79, box[3] - 27), ["edit", "board", "script"][i], big(26, 100, 800), 0,
                      anchor="mm")

    elif style == "cta":
        disc = Image.new("L", (IW, IH), 0)
        ImageDraw.Draw(disc).ellipse([cx - 360, Y(300), cx + 360, Y(1020)], fill=120)
        p.mask_halftone("blue", disc, pitch=16)
        R.rectangle([cx - 260, Y(620), cx + 120, Y(700)], fill=255)
        R.polygon([(cx + 280, Y(660)), (cx + 90, Y(500)), (cx + 90, Y(820))], fill=255)

    # shrink the drawing toward its baseline so Ken Burns never pushes it into the folio line at y=262-322
    s_, ax, ay = 0.88, cx, Y(1005)
    for name in ("blue", "red"):
        plate = getattr(p, name)
        small = plate.resize((int(IW * s_), int(IH * s_)), Image.LANCZOS)
        out = Image.new("L", (IW, IH), 0)
        out.paste(small, (int(ax - ax * s_), int(ay - ay * s_)))
        setattr(p, name, out)
    return p.print(seed=rng.randint(0, 1 << 30))


# ---------------------------------------------------------------------- TTS
async def _tts(text: str, voice: str, rate: str, out: Path):
    import edge_tts
    words = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(out, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"w": chunk["text"], "t0": chunk["offset"] / 1e7,
                              "t1": (chunk["offset"] + chunk["duration"]) / 1e7})
    return words


def tts(text, voice, rate, out, attempts=7):
    for i in range(attempts):  # the Edge endpoint drops connections now and then
        try:
            return asyncio.run(_tts(text, voice, rate, out))
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2.0 * (i + 1))


def audio_duration(path: Path) -> float:
    from moviepy.editor import AudioFileClip
    with AudioFileClip(str(path)) as a:
        return float(a.duration)


# -------------------------------------------------------------------- music
def music_bed(seconds: float, seed: int, out: Path) -> Path:
    """Procedural ambient bed (Am-F-C-G, 92 BPM) - generated by the pipeline, CC0."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    bpm, beat = 92, 60 / 92
    chords = [[57, 60, 64], [53, 57, 60], [48, 55, 64], [55, 59, 62]]  # midi
    bar = beat * 4
    out_l = np.zeros(n)
    out_r = np.zeros(n)
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    for bi in range(int(seconds / bar) + 1):
        ch = chords[bi % 4]
        s0 = int(bi * bar * SR)
        s1 = min(n, int((bi + 1) * bar * SR) + int(0.4 * SR))
        if s0 >= n:
            break
        tt = t[s0:s1] - t[s0]
        env = np.minimum(1, tt / 0.8) * np.exp(-tt / 5.0)
        for k, m in enumerate(ch):
            f = hz(m)
            for det, pan in ((-0.12, 0.3), (0.12, 0.7)):
                w = np.sin(2 * np.pi * (f + det) * tt) + 0.25 * np.sin(2 * np.pi * 2 * (f + det) * tt)
                out_l[s0:s1] += w * env * 0.05 * (1 - pan)
                out_r[s0:s1] += w * env * 0.05 * pan
        bass = np.sin(2 * np.pi * hz(ch[0] - 12) * tt) * np.exp(-tt / 1.4) * 0.12
        out_l[s0:s1] += bass
        out_r[s0:s1] += bass
        for st in range(8):  # soft arpeggio pluck on eighth notes
            p0 = s0 + int(st * beat / 2 * SR)
            if p0 >= n:
                break
            m = ch[st % 3] + 12 * (1 + (st // 3) % 2)
            ln = min(n - p0, int(0.45 * SR))
            tp = np.arange(ln) / SR
            pl = np.sin(2 * np.pi * hz(m) * tp) * np.exp(-tp / 0.16) * 0.045
            pan = 0.5 + 0.35 * math.sin(st)
            out_l[p0:p0 + ln] += pl * (1 - pan)
            out_r[p0:p0 + ln] += pl * pan
        for st in range(4):  # felt kick + shaker
            p0 = s0 + int(st * beat * SR)
            ln = min(n - p0, int(0.25 * SR))
            if ln <= 0:
                break
            tp = np.arange(ln) / SR
            kick = np.sin(2 * np.pi * (48 + 60 * np.exp(-tp / 0.03)) * tp) * np.exp(-tp / 0.11) * 0.22
            out_l[p0:p0 + ln] += kick
            out_r[p0:p0 + ln] += kick
            q0 = p0 + int(beat / 2 * SR)
            ln2 = min(n - q0, int(0.06 * SR))
            if ln2 > 0:
                sh = rng.normal(0, 1, ln2) * np.exp(-np.arange(ln2) / SR / 0.015) * 0.025
                out_l[q0:q0 + ln2] += sh
                out_r[q0:q0 + ln2] += sh
    fade = np.minimum(1, np.minimum(t / 1.5, (seconds - t) / 2.5)).clip(0, 1)
    st = np.stack([out_l * fade, out_r * fade], axis=1)
    st = st / (np.abs(st).max() + 1e-9) * 0.7
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((st * 32767).astype(np.int16).tobytes())
    return out


# -------------------------------------------------------------------- agent
def run(ctx: RunContext, shots: list[Shot], rate: str = "+0%") -> dict:
    voice = os.getenv("TTS_VOICE", "en-US-AndrewMultilingualNeural")
    adir = DIRS["assets"] / "generated"
    for sub in ("vo", "img"):
        (adir / sub).mkdir(parents=True, exist_ok=True)
    rows, out = [], {"vo": {}, "img": {}, "words": {}, "voice": voice, "rate": rate}
    rng = random.Random(ctx.seed)

    # 1) voice-over, one file per shot, with word boundaries for captions
    for s in shots:
        if not s.vo:
            continue
        mp3 = adir / "vo" / f"{s.shot_id}.mp3"
        with traced(ctx, "asset_generator", "edge-tts", provider="microsoft-edge", model=voice,
                    output_path=mp3) as t:
            words = tts(s.vo, voice, rate, mp3)
            dur = audio_duration(mp3)
            t["units"] = f"{len(s.vo)} chars / {dur:.2f}s"
        out["vo"][s.shot_id] = {"path": rel(mp3), "duration": dur}
        out["words"][s.shot_id] = words
        rows.append([f"vo_{s.shot_id}", "voice-over", rel(mp3), s.shot_id, f"Edge-TTS {voice}",
                     "Generated speech; Microsoft Edge TTS, synthetic voice (no real person cloned)",
                     "edge-tts", sha256(mp3)])

    # 2) visuals - official media kit first, generated only if missing
    log_tail = []
    from .common import RUN_LOG
    if RUN_LOG.exists():
        log_tail = [json.loads(l) for l in RUN_LOG.read_text(encoding="utf-8").splitlines()
                    if l.strip() and f'"{ctx.run_id}"' in l]
    thumbs = []
    for s in shots:
        if s.style == "endcard":
            continue
        png = adir / "img" / f"{s.shot_id}.png"
        official = DIRS["assets"] / "official" / f"{s.shot_id}.png"
        with traced(ctx, "asset_generator", "official-media-kit" if official.exists() else "procedural-image",
                    provider="local", model="PIL/numpy", output_path=png) as t:
            if official.exists():
                Image.open(official).convert("RGB").resize((IW, IH)).save(png)
                src, lic = "Official media kit", "Institutional media kit (as provided)"
            else:
                motif(s.style, random.Random(rng.random()), {"log_tail": log_tail, "thumbs": thumbs}).save(png)
                src, lic = "Generated (procedural, no faces)", "CC0 - generated by this pipeline"
            t["units"] = "1 image 1188x2112"
        thumbs.append(png)
        out["img"][s.shot_id] = rel(png)
        rows.append([f"img_{s.shot_id}", "image", rel(png), s.shot_id, src, lic, "agents/asset_generator.py",
                     sha256(png)])

    # 3) music bed
    total = sum(v["duration"] for v in out["vo"].values()) + 0.35 * len(out["vo"]) + 6
    wav = adir / "music_bed.wav"
    with traced(ctx, "asset_generator", "procedural-music", provider="local", model="numpy-synth",
                output_path=wav) as t:
        music_bed(total, ctx.seed, wav)
        t["units"] = f"{total:.1f}s stereo 48k"
    out["music"] = rel(wav)
    rows.append(["music_bed", "music", rel(wav), "-", "Generated (numpy synth, Am-F-C-G 92 BPM)",
                 "CC0 - generated by this pipeline", "agents/asset_generator.py", sha256(wav)])
    for fnt in sorted(FONTS.glob("*.ttf")):
        rows.append([f"font_{fnt.stem}", "font", rel(fnt), "-", "Google Fonts / IBM Plex",
                     "SIL Open Font License 1.1", "-", sha256(fnt)])

    man = DIRS["assets"] / "manifest.csv"
    with open(man, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["asset_id", "type", "path", "shot_id", "source", "licence", "generator", "sha256"])
        w.writerows(rows)
    log_call(ctx, agent="asset_generator", tool="manifest", units=f"{len(rows)} assets", output_path=man)
    say("asset_generator", f"{len(out['vo'])} VO clips ({voice}), {len(out['img'])} images, music bed, "
                           f"manifest {len(rows)} rows")
    return out
