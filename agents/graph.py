"""Draws docs/agent_graph.png - the architecture diagram, printed in the
project's two-ink risograph style (blue structure, one scarlet accent)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, Rectangle

from .common import FONTS
from .riso import BLUE, PAPER, RED, hexc

PAPER_H, BLUE_H, RED_H = hexc(PAPER), hexc(BLUE), hexc(RED)

NODES = [  # (key, title, subtitle, output, x, y)
    ("brief", "Brief", "briefs/C05.yaml", "", 0.6, 3.0),
    ("planner", "1  Planner", "budget + time split", "plan.json", 2.4, 3.0),
    ("research", "2  Researcher", "PyMuPDF > Chroma\nMiniLM embeddings", "facts.json", 4.2, 3.0),
    ("script", "3  Scriptwriter", "A/B hooks, lines\nbound to fact ids", "script.md", 6.0, 3.0),
    ("story", "4  Storyboarder", "6-12 shots", "storyboard.json", 7.8, 3.0),
    ("assets", "5  Asset Gen", "Edge-TTS, PIL, synth", "manifest.csv", 7.8, 1.1),
    ("editor", "6  Editor", "MoviePy, captions,\nloudnorm -14", "final.mp4 + .srt", 6.0, 1.1),
    ("critic", "7  Critic", "20 rules, 2 gates", "qa_report.json", 4.2, 1.1),
    ("human", "Checkpoint", "pre-export review", "interventions.md", 2.4, 1.1),
    ("export", "Export", "dashboard + report", "process_report.pdf", 0.6, 1.1),
]


def _font(name):
    p = FONTS / name
    font_manager.fontManager.addfont(str(p))
    return font_manager.FontProperties(fname=str(p))


def draw_agent_graph(out: Path):
    arch = _font("Archivo[wdth,wght].ttf")
    mono = _font("IBMPlexMono-Regular.ttf")
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=200)
    fig.patch.set_facecolor(PAPER_H)
    ax.set_facecolor(PAPER_H)
    ax.set_xlim(-0.4, 8.9)
    ax.set_ylim(-0.5, 4.6)
    ax.axis("off")
    pos = {}
    for key, title, sub, outp, x, y in NODES:
        pos[key] = (x, y)
        if key == "critic":  # the scarlet plate, a few px off register
            ax.add_patch(Rectangle((x - 0.8 + 0.04, y - 0.55 - 0.03), 1.6, 1.1, fc=RED_H, ec="none", alpha=0.9))
        ax.add_patch(Rectangle((x - 0.8, y - 0.55), 1.6, 1.1, fc="none", ec=BLUE_H, lw=2.2))
        ax.text(x - 0.7, y + 0.33, title, ha="left", va="center", color=BLUE_H, fontproperties=arch,
                fontsize=11, fontweight="black")
        ax.text(x - 0.7, y + 0.02, sub, ha="left", va="center", color=BLUE_H, fontproperties=arch, fontsize=7.4,
                linespacing=1.1)
        if outp:
            ax.plot([x - 0.8, x + 0.8], [y - 0.3, y - 0.3], color=BLUE_H, lw=1)
            ax.text(x - 0.7, y - 0.42, outp, ha="left", va="center", color=BLUE_H, fontproperties=mono,
                    fontsize=6.8)

    def arrow(a, b):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        dx, dy = x2 - x1, y2 - y1
        sx = 0.82 if abs(dx) > abs(dy) else 0
        sy = 0.57 if abs(dy) >= abs(dx) else 0
        ax.add_patch(FancyArrowPatch((x1 + sx * np.sign(dx), y1 + sy * np.sign(dy)),
                                     (x2 - sx * np.sign(dx), y2 - sy * np.sign(dy)),
                                     arrowstyle="-|>", mutation_scale=13, color=BLUE_H, lw=1.6))

    for a, b in [("brief", "planner"), ("planner", "research"), ("research", "script"), ("script", "story"),
                 ("story", "assets"), ("assets", "editor"), ("editor", "critic"), ("critic", "human"),
                 ("human", "export")]:
        arrow(a, b)
    ax.add_patch(FancyArrowPatch((4.45, 1.66), (5.75, 2.44), arrowstyle="-|>", mutation_scale=14, color=RED_H,
                                 lw=3, connectionstyle="arc3,rad=-0.35"))
    ax.text(5.5, 1.86, "fail: back to Scriptwriter\n(word budget, hook, numbers)", color=RED_H,
            fontproperties=arch, fontsize=7.2, ha="left")
    ax.add_patch(FancyArrowPatch((4.2, 0.53), (6.0, 0.53), arrowstyle="-|>", mutation_scale=14, color=RED_H,
                                 lw=3, connectionstyle="arc3,rad=0.45"))
    ax.text(5.1, -0.33, "fail: back to Asset Gen / Editor (duration, loudness, safe zones), max 3 loops",
            color=RED_H, fontproperties=arch, fontsize=7.2, ha="center")
    ax.add_patch(FancyArrowPatch((4.0, 2.44), (4.0, 1.66), arrowstyle="-|>", mutation_scale=12, color=BLUE_H,
                                 lw=1.2, ls=(0, (2, 2))))
    ax.text(3.92, 2.05, "fact-id check", color=BLUE_H, fontproperties=mono, fontsize=6.5, ha="right")
    ax.text(-0.3, 4.3, "AGENTREEL", color=BLUE_H, fontproperties=arch, fontsize=26, fontweight="black",
            ha="left", va="center", fontstretch="expanded")
    ax.text(2.55, 4.26, "agent graph, run end to end by one command", color=BLUE_H, fontproperties=arch,
            fontsize=10, ha="left", va="center")
    ax.text(8.8, 4.26, "every call > logs/run_log.jsonl", color=BLUE_H, fontproperties=mono, fontsize=7.5,
            ha="right", va="center")
    ax.plot([-0.3, 8.8], [3.95, 3.95], color=BLUE_H, lw=2.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=PAPER_H, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return out
