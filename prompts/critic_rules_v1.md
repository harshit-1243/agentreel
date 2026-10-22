<!-- prompt_id: critic_rules_v1 | agent: critic | v1 2026-10 -->
The Critic is a deterministic rule engine (agents/critic.py) - no LLM call, so it cannot be
talked out of a failure. Rules:

Script gate (before any asset is generated)
  S1 word count <= plan.word_budget.max            -> Scriptwriter (drop lowest-priority lines)
  S2 hook spoken in <= 3 s                          -> Scriptwriter
  S3 every body line cites a verified fact id        -> Researcher
  S4 no number that is absent from facts.json        -> Scriptwriter
  S5 no placement/ranking hype (LPA, crore, %, #1)   -> Scriptwriter
  S6/S7 must-include items present                   -> Scriptwriter
  S8 CTA equals the brief's CTA                      -> Scriptwriter

Video gate (after the edit)
  V1 30-60 s · V2 within ±20% of brief duration      -> Asset Gen (TTS rate) / Scriptwriter
  V3 1080x1920 · V4 30 fps · V5 H.264 High yuv420p    -> Editor
  V6 AAC 48 kHz stereo 128-192 kbps · V7 <= 100 MB    -> Editor
  V8 integrated loudness -14 ±1.5 LUFS               -> Editor
  V9 burned captions + .srt · V10 safe zones          -> Editor
  V11 hook inside first 3 s · V12 end card CTA + AI disclosure -> Editor

Max 3 loops per gate; every iteration is stored in outputs/qa_report.json.
