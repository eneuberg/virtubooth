"""External AI (LLM) for the Live-Wall: the host's own API key, a provider
(Anthropic by default, optionally Mistral in the EU), object detection at
upload, the property poll, category verdicts, a usage budget and the test image.

Settings keys: `x.llm.config` (config.py), `x.llm.key` (crypto.py, encrypted),
`x.llm.poll` (poller.py: the last poll's input hash).
Tables (migration 11): `llm_properties`, `llm_polls`, `property_scores`,
`wall_category_verdicts`, `llm_usage`; detection stores the AI's own list
(`photo_source_objects`) and merges it into D1's `photo_objects` (enrich/merge.py).

Privacy: a guest with `users.ai_opt_out` or `users.analysis_opt_out` set never
has a photo, label or name sent; the flags are read live before every send.
"""
