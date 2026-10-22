"""Scriptwriter: turn verified facts into a timed VO script (hook -> body -> CTA).

Every body line is bound to the fact tags it needs; a line is only written when
facts.json actually holds a verified fact for each tag, and the fact ids travel
with the line so the Critic can trace every sentence back to a PDF page.
Hooks are generated as A/B/C variants and scored; the best one that fits the
3-second rule wins. Critic feedback (e.g. over word budget) arrives via
`feedback` and the writer drops the lowest-priority lines first."""
from __future__ import annotations

import json
import random

from .common import Fact, RunContext, ScriptLine, say, write_json
from .llm import LLM, extract_json
from .planner import HOOK_WPS, WORDS_PER_SECOND

# (id, tags required, priority 1=keep .. 5=drop first, text)
BODY_BANK = [
    ("lab",        ["lab"],                1, "In the final-year Agentic AI Lab at K J Somaiya, students don't just study AI. They ship it."),
    ("multiagent", ["multi_agent"],        1, "Multi-agent pipelines, with clear roles, hand-offs and a critic loop."),
    ("rag",        ["rag"],                3, "Retrieval that grounds every claim in verified source documents."),
    ("orchestr",   ["orchestration"],      4, "Text, image, speech and video tools, orchestrated on a deadline."),
    ("constraint", ["timebox", "budget"],  2, "A sealed brief. A three-hour hard stop. A five-hundred-rupee API budget."),
    ("logging",    ["logging"],            2, "Every call logged, every rupee tracked, one command to reproduce the run."),
    ("deploy",     ["deploy"],             1, "Then they deploy, live on GitHub Pages, Hugging Face Spaces or Streamlit Cloud."),
    ("responsible", ["responsible"],       2, "Responsible AI built in: grounding, consent, disclosure, licensing."),
    ("portfolio",  ["portfolio"],          5, "Every graduate leaves with a reproducible agentic system on GitHub."),
    ("proof",      ["SELF"],               1, "The proof? This reel was planned, scripted and edited by agents built in that lab."),
]

HOOKS = [
    "What does an AI-ready graduate actually build?",
    "What does an AI-ready graduate build?",
    "Recruiters, meet the AI-ready graduate.",
]


def score_hook(h: str, topic: str) -> dict:
    words = len(h.split())
    secs = round(words / HOOK_WPS, 2)
    topic_hit = sum(w.lower().strip(":,.?") in h.lower() for w in topic.split()[:3])
    s = (2.0 if h.endswith("?") else 0) + topic_hit + (1.5 if secs <= 3.0 else -5) - 0.1 * words
    return {"text": h, "words": words, "est_s": secs, "score": round(s, 2), "fits_3s": secs <= 3.0}


def _facts_for(tags, facts: list[Fact]):
    ids = []
    for tag in tags:
        if tag == "SELF":  # claim about this very run - verified against logs/run_log.jsonl
            ids.append("SELF:run_log")
            continue
        hit = next((f for f in facts if tag in f.tags and f.verified), None)
        if hit is None:
            return None
        ids.append(hit.id)
    return ids


def run(ctx: RunContext, llm: LLM, plan: dict, facts: list[Fact], feedback: dict | None = None,
        version: int = 1) -> list[ScriptLine]:
    b = ctx.brief
    rng = random.Random(ctx.seed)
    word_cap = plan["word_budget"]["max"]
    must_tags = {"deploy", "lab"}  # brief.must_include -> real lab infrastructure / deployment

    def offline() -> str:
        hooks = sorted((score_hook(h, b.topic) for h in HOOKS), key=lambda x: (-x["score"], rng.random()))
        lines = [ScriptLine(id="L01", key="hook", role="hook", text=hooks[0]["text"], priority=0)]
        for key, tags, prio, text in BODY_BANK:
            ids = _facts_for(tags, facts)
            if ids is None:
                continue
            if key in must_tags:
                prio = 0
            lines.append(ScriptLine(id=key, key=key, role="body", text=text, fact_ids=ids, priority=prio))
        lines.append(ScriptLine(id="cta", key="cta", role="cta", text=b.cta, priority=0))

        if feedback and feedback.get("over_words"):
            # drop lowest-priority lines until the script fits the word budget
            while sum(len(l.text.split()) for l in lines) > word_cap:
                droppable = [l for l in lines if l.priority > 0]
                if not droppable:
                    break
                lines.remove(max(droppable, key=lambda l: (l.priority, len(l.text))))
        return json.dumps({"hooks": hooks, "lines": [l.model_dump() for l in lines]}, indent=2)

    raw = llm.complete(ctx, agent="scriptwriter", prompt_id="scriptwriter_v2",
                       variables={"brief": b.model_dump_json(), "facts": json.dumps(
                           [f.model_dump() for f in facts if f.verified], ensure_ascii=False),
                                  "word_budget": word_cap, "feedback": json.dumps(feedback or {})},
                       offline=offline)
    data = extract_json(raw)
    lines = [ScriptLine(**l) for l in data["lines"]]

    t = 0.0
    for i, l in enumerate(lines, 1):
        l.id = f"L{i:02d}"
        l.est_start = round(t, 2)
        t += len(l.text.split()) / WORDS_PER_SECOND + 0.25
        l.est_end = round(t, 2)

    write_json(ctx.work / "script.json", {"version": version, "hooks": data.get("hooks", []),
                                          "lines": [l.model_dump() for l in lines]})
    md = [f"# Script - {b.id} (v{version})", "",
          f"**Topic:** {b.topic}  ", f"**Audience:** {b.audience}  ", f"**Tone:** {b.tone}  ",
          f"**Words:** {sum(len(l.text.split()) for l in lines)} / budget {word_cap}", "",
          "| Time | Role | Line | Facts |", "|---|---|---|---|"]
    for l in lines:
        md.append(f"| {l.est_start:05.2f}-{l.est_end:05.2f} | {l.role} | {l.text} | {', '.join(l.fact_ids) or '-'} |")
    md += ["", f"_End card (4 s):_ {b.cta} / Created with AI agents — LY Agentic AI Lab"]
    (ctx.work / "script.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    say("scriptwriter", f"v{version}: {len(lines)} lines, {sum(len(l.text.split()) for l in lines)} words, "
                        f"hook = \"{lines[0].text}\"")
    return lines
