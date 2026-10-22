"""Planner: parse the brief and emit plan.json with per-stage time and cost
budgets, a word budget for the voice-over and explicit success criteria."""
from __future__ import annotations

import json

from .common import TOTAL_BUDGET_INR, RunContext, say, write_json
from .llm import LLM, extract_json

END_CARD_S = 4.0
WORDS_PER_SECOND = 2.3           # measured: Edge "Andrew" neural voice at +5% incl. commas/full stops
HOOK_WPS = 3.0                   # short single-clause lines have no internal pauses (measured 3.3)
SHOT_OVERHEAD_S = 0.4            # lead-in + breath the Editor adds per VO shot
TTS_RATE = "+5%"

# share of the Rs 500 live-run budget and the 180-minute slot per stage
STAGES = [
    ("planner",         0.02, 5),
    ("researcher",      0.10, 15),
    ("scriptwriter",    0.20, 15),
    ("storyboarder",    0.10, 10),
    ("asset_generator", 0.40, 40),
    ("editor",          0.08, 30),
    ("critic",          0.10, 15),
]


def run(ctx: RunContext, llm: LLM) -> dict:
    b = ctx.brief
    w, h = (1080, 1920) if b.format == "video_9x16" else (1920, 1080)
    shots = max(6, min(12, round((b.duration_s - END_CARD_S) / 5)))
    vo_s = round(b.duration_s - END_CARD_S - SHOT_OVERHEAD_S * (shots + 1), 1)
    words = int(vo_s * WORDS_PER_SECOND)

    def offline() -> str:
        plan = {
            "brief_id": b.id,
            "run_id": ctx.run_id,
            "seed": ctx.seed,
            "deliverable": f"outputs/{ctx.final_stem}.mp4",
            "format": {"width": w, "height": h, "fps": 30, "codec": "h264-high/yuv420p",
                       "audio": "aac 48kHz stereo 160k", "loudness_lufs": -14},
            "timing": {"target_s": b.duration_s, "min_s": 30, "max_s": 60,
                       "vo_s": vo_s, "end_card_s": END_CARD_S, "hook_s": 3},
            "word_budget": {"target": words, "max": int(words * 1.15), "wps": WORDS_PER_SECOND},
            "tts_rate": TTS_RATE,
            "shot_count": {"min": 6, "max": 12, "target": shots},
            "budget_inr": {"total": TOTAL_BUDGET_INR,
                           "stages": {s: round(TOTAL_BUDGET_INR * f, 2) for s, f, _ in STAGES}},
            "time_budget_min": {"total": 180, "stages": {s: m for s, _, m in STAGES}},
            "stages": [s for s, _, _ in STAGES],
            "critic_max_loops": 3,
            "checkpoints": ["pre-export human review (mandatory for Category A/C)"],
            "success_criteria": [
                f"duration within 30-60 s, close to {b.duration_s} s",
                f"{w}x{h} @ 30 fps, H.264 High, yuv420p, AAC 48 kHz",
                "topic clear in first 3 s (hook)",
                "every factual line cites a verified fact id",
                "no numbers or statistics that are absent from facts.json",
                *[f"must include: {m}" for m in b.must_include],
                *[f"must avoid: {m}" for m in b.must_avoid],
                f"CTA on end card: {b.cta}",
                "AI-disclosure line on end card",
                "burned-in captions inside 9:16 safe zones + .srt",
                f"total spend <= Rs {TOTAL_BUDGET_INR:.0f}",
            ],
            "creative": {
                "audience_insight": ("Aspirants want proof the degree turns into real skills; recruiters "
                                     "want evidence graduates can ship, log and govern AI systems."),
                "angle": "Show, don't claim: the reel itself is the proof - built by student-made agents.",
                "tone": b.tone,
            },
        }
        return json.dumps(plan, indent=2)

    raw = llm.complete(ctx, agent="planner", prompt_id="planner_v1",
                       variables={"brief": b.model_dump_json(indent=2), "budget": TOTAL_BUDGET_INR},
                       offline=offline)
    plan = extract_json(raw)
    write_json(ctx.work / "plan.json", plan)
    say("planner", f"{plan['shot_count']['target']} shots, ~{plan['word_budget']['target']} words, "
                   f"budget Rs {plan['budget_inr']['total']:.0f}")
    return plan
