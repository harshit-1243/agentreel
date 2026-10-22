"""Editor: assemble the 1080x1920 reel with MoviePy.

Ken Burns on every still, cross-dissolves, headline per shot, burned-in
karaoke captions (word timings from Edge-TTS) inside the 9:16 safe zones,
ducked music bed, 4 s end card with CTA + AI-disclosure line, then a
two-pass ffmpeg loudnorm to -14 LUFS. Also writes the .srt and edit_meta.json."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .asset_generator import IH, IW, PALETTE, H, W, draw_text, font
from .common import DIRS, ROOT, RunContext, Shot, log_call, rel, say, traced
from .riso import Plates
from .planner import END_CARD_S

FPS = 30
GAP = 0.30          # breath between VO lines
XFADE = 0.35        # visual cross-dissolve
SAFE_TOP, SAFE_BOTTOM = 250, H - 350
DISCLOSURE = "Created with AI agents — LY Agentic AI Lab"
font = lru_cache(maxsize=64)(font)


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------------------------------------------------------------- typography
def _wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


HEAD_Y = 1050      # headline block top; motif lives above, captions below
BLUE, RED = PALETTE["blue"], PALETTE["red"]
OVER = tuple(int(b * r / 255) for b, r in zip(PALETTE["blue"], PALETTE["red"]))  # blue printed over scarlet
LEFT = 80


def headline_layer(text: str, kicker: str):
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    size = 108
    while True:
        f = font("arch", size, 900, 108)
        lines = _wrap(tmp, text, f, W - 2 * LEFT)
        if len(lines) <= 2 or size <= 76:
            break
        size -= 8
    lh = int(size * 0.98)
    h = 74 + lh * len(lines) + 16
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    num, _, role = kicker.partition("  ·  ")
    d.text((LEFT, 22), num, font=font("arch", 34, 900, 125), fill=(*RED, 255), anchor="lm")
    nx = LEFT + d.textlength(num, font=font("arch", 34, 900, 125)) + 18
    d.text((nx, 22), role.lower(), font=font("arch", 30, 600, 100), fill=(*BLUE, 255), anchor="lm")
    for i, ln in enumerate(lines):
        draw_text(d, (LEFT, 66 + i * lh), ln, f, (*BLUE, 255), anchor="la")
    return img


def caption_layer(words: list[str], active: int):
    f = font("arch", 60, 800, 100)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    text = " ".join(words)
    tw = tmp.textlength(text, font=f)
    pad_x, h = 22, 96
    img = Image.new("RGBA", (int(tw + 2 * pad_x), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = pad_x
    for i, w in enumerate(words):
        ww = tmp.textlength(w, font=f)
        if i == active:  # highlighter swipe on the spoken word, printed under the blue
            d.rectangle([x - 8, 14, x + ww + 8, h - 12], fill=(*RED, 255))
        d.text((x, h // 2), w, font=f, fill=(*(OVER if i == active else BLUE), 255), anchor="lm")
        x += tmp.textlength(w + " ", font=f)
    return img


def topbar_layer(brief_id: str):
    img = Image.new("RGBA", (W, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font("arch", 26, 700, 100)
    d.text((LEFT, 24), "KJSSE × LY Agentic AI Lab", font=f, fill=(*BLUE, 255), anchor="lm")
    d.text((W - LEFT, 24), f"Brief {brief_id}", font=f, fill=(*BLUE, 255), anchor="rm")
    d.line([(LEFT, 52), (W - LEFT, 52)], fill=(*BLUE, 255), width=3)
    return img


def endcard_frame(brief) -> Image.Image:
    p = Plates(W, H)
    logo = DIRS["assets"] / "official" / "logo.png"
    f_name = font("arch", 40, 800, 100)
    p.b.text((LEFT, 300), "K J Somaiya School of Engineering", font=f_name, fill=255, anchor="ls")
    p.b.text((LEFT, 344), "Somaiya Vidyavihar University", font=font("arch", 28, 500, 100), fill=255, anchor="ls")
    p.r.rectangle([0, 420, W, 1060], fill=255)
    f = font("arch", 128, 900, 106)
    lines = _wrap(p.b, brief.cta, f, W - 2 * LEFT)
    for i, ln in enumerate(lines):
        draw_text(p.b, (LEFT, 470 + i * 124), ln, f, 255, anchor="la")
    p.b.text((LEFT, 1160), "AI-ready. Industry-ready.", font=font("arch", 52, 800, 112), fill=255, anchor="ls")
    p.b.line([(LEFT, 1420), (W - LEFT, 1420)], fill=255, width=3)
    draw_text(p.b, (LEFT, 1480), DISCLOSURE, font("arch", 34, 800, 100), 255, anchor="ls")
    p.b.text((LEFT, 1528), "Facts: LY Agentic AI Lab handout · Brief " + brief.id, font=font("arch", 26, 500, 100),
             fill=255, anchor="ls")
    img = p.print(seed=99)
    if logo.exists():  # official logo, undistorted, when the media kit provides it
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((300, 150))
        img = img.convert("RGBA")
        img.alpha_composite(lg, (W - LEFT - lg.width, 230))
    return img.convert("RGB")


# -------------------------------------------------------------------- timing
def chunk_words(words, max_words=4, max_chars=24):
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x["w"] for x in cur + [w])) > max_chars
                    or cur[-1]["w"].endswith((".", "?", "!", ":", ","))):
            chunks.append(cur)
            cur = []
        cur.append(w)
    return chunks + ([cur] if cur else [])


def punctuate(words, text):
    """Edge-TTS word boundaries drop punctuation; restore it from the VO text so
    captions break on sentence/clause ends ("...hard stop." | "A five-hundred...")."""
    out, cur, low = [], 0, text.lower()
    for w in words:
        i = low.find(w["w"].lower(), cur)
        if i < 0:
            out.append(dict(w))
            continue
        j = i + len(w["w"])
        while j < len(text) and text[j] in ".,?!:;":
            j += 1
        out.append({**w, "w": text[i:j]})
        cur = j
    return out


def build_timeline(shots: list[Shot], assets: dict):
    t, timeline, captions = 0.0, [], []
    for s in shots:
        if s.style == "endcard":
            timeline.append({"shot": s.shot_id, "start": round(t, 3), "end": round(t + END_CARD_S, 3),
                             "style": "endcard"})
            t += END_CARD_S
            continue
        vo = assets["vo"][s.shot_id]
        start = t
        a0 = start + 0.10
        dur = vo["duration"] + GAP
        timeline.append({"shot": s.shot_id, "start": round(start, 3), "end": round(start + dur, 3),
                         "audio_start": round(a0, 3), "style": s.style, "text": s.on_screen_text})
        for ch in chunk_words(punctuate(assets["words"].get(s.shot_id, []), s.vo)):
            captions.append({"shot": s.shot_id, "start": round(a0 + ch[0]["t0"], 3),
                             "end": round(a0 + ch[-1]["t1"] + 0.12, 3),
                             "words": [{"w": w["w"].rstrip("."), "t0": a0 + w["t0"], "t1": a0 + w["t1"]}
                                       for w in ch]})
        t += dur
    for i in range(len(captions) - 1):  # no overlap, no flicker gaps < 0.15s
        nxt = captions[i + 1]["start"]
        if captions[i]["end"] > nxt or nxt - captions[i]["end"] < 0.15:
            captions[i]["end"] = nxt
    return timeline, captions, round(t, 3)


def srt_time(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(captions, path: Path):
    out = []
    for i, c in enumerate(captions, 1):
        out += [str(i), f"{srt_time(c['start'])} --> {srt_time(c['end'])}", " ".join(w["w"] for w in c["words"]), ""]
    path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------- agent
def run(ctx: RunContext, shots: list[Shot], assets: dict) -> dict:
    from moviepy.editor import AudioClip, AudioFileClip, CompositeAudioClip, VideoClip

    timeline, captions, total = build_timeline(shots, assets)
    stills = {s["shot"]: Image.open(ROOT / assets["img"][s["shot"]]).convert("RGB")
              for s in timeline if s["style"] != "endcard"}
    endcard = endcard_frame(ctx.brief)
    topbar = topbar_layer(ctx.brief.id)
    n_body = sum(1 for s in timeline if s["style"] != "endcard")
    heads = {}
    for i, s in enumerate(timeline):
        if s["style"] != "endcard":
            sh = next(x for x in shots if x.shot_id == s["shot"])
            kicker = f"{i + 1:02d} / {n_body:02d}  ·  {sh.role.upper()}"
            heads[s["shot"]] = headline_layer(s["text"], kicker)
    cap_cache = {}
    boxes = {"topbar": [262, 322], "headline": [], "caption": []}

    def still_frame(seg, t):
        img = stills[seg["shot"]]
        u = (t - seg["start"]) / max(0.01, seg["end"] - seg["start"])
        idx = [x["shot"] for x in timeline].index(seg["shot"])
        z = 1.0 + 0.07 * u if idx % 2 == 0 else 1.07 - 0.07 * u
        cw, ch = W / z, H / z
        cx = IW / 2 + (u - 0.5) * 30 * (1 if idx % 3 else -1)
        cy = IH / 2 + (u - 0.5) * 24
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return img.resize((W, H), Image.BILINEAR, box=box)

    def compose(seg, t):
        if seg["style"] == "endcard":
            return endcard.copy().convert("RGBA")
        fr = still_frame(seg, t).convert("RGBA")
        fr.alpha_composite(topbar, (0, 262))
        hd = heads[seg["shot"]]
        k = min(1.0, (t - seg["start"]) / 0.45)
        e = 1 - (1 - k) ** 3
        if e < 1:
            a = np.asarray(hd).copy()
            a[..., 3] = (a[..., 3] * e).astype(np.uint8)
            hd_img = Image.fromarray(a)
        else:
            hd_img = hd
        y = int(HEAD_Y + 40 * (1 - e))
        fr.alpha_composite(hd_img, (0, y))
        boxes["headline"].append([y, y + hd.height])
        # progress bar
        prog = min(1.0, t / (total - END_CARD_S))
        dr = ImageDraw.Draw(fr)
        dr.line([(LEFT, 1558), (W - LEFT, 1558)], fill=(*BLUE, 255), width=2)
        dr.rectangle([LEFT, 1552, LEFT + int((W - 2 * LEFT) * prog), 1564], fill=(*RED, 255))
        return fr


    def seg_at(t):
        for i, s in enumerate(timeline):
            if s["start"] <= t < s["end"]:
                return i
        return len(timeline) - 1

    def make_frame(t):
        i = seg_at(t)
        seg = timeline[i]
        fr = compose(seg, t)
        if i > 0 and t - seg["start"] < XFADE:  # cross-dissolve from previous shot
            prev = compose(timeline[i - 1], t)
            fr = Image.blend(prev, fr, (t - seg["start"]) / XFADE)
        for c in captions:
            if c["start"] <= t < c["end"]:
                act = max([j for j, w in enumerate(c["words"]) if w["t0"] <= t] or [0])
                key = (id(c), act)
                if key not in cap_cache:
                    cap_cache[key] = caption_layer([w["w"] for w in c["words"]], act)
                cl = cap_cache[key]
                y = 1436
                fr.alpha_composite(cl, (LEFT - 22, y))
                boxes["caption"].append([y, y + cl.height])
                break
        return np.asarray(fr.convert("RGB"))

    # ------------------------------------------------------------ audio mix
    with wave.open(str(ROOT / assets["music"]), "rb") as wf:
        music = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).reshape(-1, 2) / 32768.0
    vo_spans = [(s["audio_start"], s["audio_start"] + assets["vo"][s["shot"]]["duration"])
                for s in timeline if s["style"] != "endcard"]

    def duck(tt):
        g = np.full_like(tt, 0.30, dtype=np.float64)
        for a, b in vo_spans:
            inside = np.clip(np.minimum(tt - (a - 0.25), (b + 0.35) - tt) / 0.25, 0, 1)
            g = np.minimum(g, 0.30 - 0.20 * inside)
        return g

    def music_frame(tt):
        tt = np.atleast_1d(np.asarray(tt, dtype=np.float64))
        idx = np.clip((tt * 48000).astype(int), 0, len(music) - 1)
        return music[idx] * duck(tt)[:, None]

    bed = AudioClip(music_frame, duration=total, fps=48000)
    bed.nchannels = 2
    vos = [AudioFileClip(str(ROOT / assets["vo"][s["shot"]]["path"])).set_start(s["audio_start"])
           for s in timeline if s["style"] != "endcard"]
    mix = CompositeAudioClip([bed, *vos]).set_duration(total)

    out_dir = DIRS["outputs"]
    tmp = out_dir / "_work"
    tmp.mkdir(parents=True, exist_ok=True)
    raw = tmp / "raw.mp4"
    final = out_dir / f"{ctx.final_stem}.mp4"
    srt = out_dir / f"{ctx.final_stem}.srt"

    with traced(ctx, "editor", "moviepy-render", provider="local", model="moviepy+libx264",
                output_path=raw) as t:
        clip = VideoClip(make_frame, duration=total).set_audio(mix)
        clip.write_videofile(str(raw), fps=FPS, codec="libx264", audio_codec="aac", audio_fps=48000,
                             audio_bitrate="160k", preset="medium", threads=4, logger=None,
                             ffmpeg_params=["-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "19"],
                             temp_audiofile=str(tmp / "mix.m4a"))
        t["units"] = f"{total:.2f}s @ {FPS}fps"

    with traced(ctx, "editor", "ffmpeg-loudnorm", provider="local", model="ffmpeg loudnorm 2-pass",
                output_path=final) as t:
        meas = loudnorm_measure(raw)
        flt = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
               f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
               f"offset={meas['target_offset']}:linear=true")
        subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", str(raw), "-c:v", "copy", "-af", flt,
                        "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                        str(final)], check=True)
        t["units"] = f"in {meas['input_i']} LUFS -> -14"

    write_srt(captions, srt)
    log_call(ctx, agent="editor", tool="srt", units=f"{len(captions)} cues", output_path=srt)

    # representative frames for the frontend / report
    fdir = out_dir / "frames"
    fdir.mkdir(exist_ok=True)
    frames = {}
    for s in timeline:
        tm = s["start"] + (s["end"] - s["start"]) * (0.5 if s["style"] != "endcard" else 0.6)
        p = fdir / f"{s['shot']}.jpg"
        Image.fromarray(make_frame(tm)).save(p, quality=86)
        frames[s["shot"]] = rel(p)

    meta = {"final": rel(final), "srt": rel(srt), "duration_s": total, "fps": FPS, "size": [W, H],
            "timeline": timeline, "captions": captions, "frames": frames,
            "layout": {"safe_top": SAFE_TOP, "safe_bottom": SAFE_BOTTOM,
                       "topbar": boxes["topbar"],
                       "headline": [min(b[0] for b in boxes["headline"]), max(b[1] for b in boxes["headline"])],
                       "caption": [min(b[0] for b in boxes["caption"]), max(b[1] for b in boxes["caption"])]},
            "loudnorm_pass1": meas, "disclosure": DISCLOSURE, "cta": ctx.brief.cta}
    (out_dir / "edit_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    say("editor", f"{final.name} {total:.1f}s, {len(captions)} caption cues, loudnorm from {meas['input_i']} LUFS")
    return meta


def loudnorm_measure(path: Path) -> dict:
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path), "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    return json.loads(re.findall(r"\{[^{}]+\}", r.stderr)[-1])
