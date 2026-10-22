"""Storyboarder: break the script into 6-12 shots (+ end card) with a visual
description, on-screen text, estimated duration and asset source."""
from __future__ import annotations

import json

from .common import RunContext, ScriptLine, Shot, say, write_json
from .llm import LLM, extract_json
from .planner import END_CARD_S, WORDS_PER_SECOND

# key -> (on-screen text, visual style, visual description). No faces, no real people.
LOOKS = {
    "hook":        ("The AI-ready graduate", "hook",
                    "Dark field, glowing neural lattice resolving into a graduation-cap glyph; title slams in."),
    "lab":         ("The Agentic AI Lab", "lab",
                    "Isometric lab bench of workstations rendered as light blocks; screens pulse with agent traffic."),
    "multiagent":  ("Multi-agent pipelines", "graph",
                    "Seven agent nodes light up in sequence; a critic arc loops back from the last node."),
    "rag":         ("Grounded, not guessed", "docs",
                    "Stacked PDF pages; retrieval beams highlight one sentence and pin a page citation."),
    "orchestr":    ("Every modality, one deadline", "tools",
                    "Four modality tiles - text, image, speech, video - snap onto one timeline."),
    "constraint":  ("3 hours. ₹500.", "clock",
                    "Countdown ring and budget meter; a sealed brief card flips open."),
    "logging":     ("Logged. Costed. Reproducible.", "terminal",
                    "Terminal window streaming JSONL log records with cost column ticking."),
    "deploy":      ("Shipped to the web", "deploy",
                    "Browser windows fan out from a deploy button onto a global grid."),
    "responsible": ("Responsible by design", "shield",
                    "Shield made of four checkmarks: grounding, consent, disclosure, licensing."),
    "portfolio":   ("A portfolio on GitHub", "graph",
                    "Commit graph growing into a tagged release v1.0-final."),
    "proof":       ("Student-built agents made this", "reel",
                    "This very reel shown as a filmstrip inside a 9:16 frame, agent badges on each frame."),
    "cta":         ("Hire AI-ready graduates", "cta",
                    "Spotlight sweep; CTA type locks centre-frame."),
}


def run(ctx: RunContext, llm: LLM, plan: dict, lines: list[ScriptLine]) -> list[Shot]:
    def offline() -> str:
        shots = []
        for i, l in enumerate(lines, 1):
            text, style, visual = LOOKS.get(l.key, (l.text[:28], "graph", "Abstract agent graph motif."))
            shots.append(Shot(shot_id=f"S{i:02d}", role=l.role, vo=l.text, on_screen_text=text,
                              visual=visual, style=style, fact_ids=l.fact_ids,
                              duration_est=round(len(l.text.split()) / WORDS_PER_SECOND + 0.25, 2),
                              asset_source="generated (procedural; placeholder for official media kit)"))
        shots.append(Shot(shot_id=f"S{len(lines) + 1:02d}", role="endcard", vo="",
                          on_screen_text=ctx.brief.cta, style="endcard", duration_est=END_CARD_S,
                          visual="End card: institute wordmark, CTA, AI-disclosure line.",
                          asset_source="generated (typographic end card)"))
        return json.dumps([s.model_dump() for s in shots], indent=2, ensure_ascii=False)

    raw = llm.complete(ctx, agent="storyboarder", prompt_id="storyboarder_v1",
                       variables={"script": json.dumps([l.model_dump() for l in lines], ensure_ascii=False),
                                  "shots": plan["shot_count"]}, offline=offline)
    shots = [Shot(**s) for s in extract_json(raw)]
    if not 6 <= len(shots) - 1 <= 12:
        raise ValueError(f"storyboard has {len(shots) - 1} shots, expected 6-12")
    write_json(ctx.work / "storyboard.json", [s.model_dump() for s in shots])
    say("storyboarder", f"{len(shots) - 1} shots + end card, est {sum(s.duration_est for s in shots):.1f}s")
    return shots
