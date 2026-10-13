# Overhaul brief (from the host, 2026-10-13, translated)

> "The current design looks very sloppy. I want a UI/UX overhaul of the whole
> site and to rebuild everything. Use proper frameworks and a proper tech
> stack, above all for the frontend, which is almost entirely raw
> HTML/CSS/JS: at least TypeScript level, a modern framework (and
> frameworks). FastAPI is fine for the backend, but refactor everything:
> the code, where things live and how it is structured architecturally
> (it's all over the place), and the folder structure (everything is just
> in one folder). Use subagents. First analysis, then planning, then
> implementation. Weigh whether the work of the agents that were running
> collides fundamentally with the plan. Refactor and rework frontend,
> backend and repo structure. Install and use these skills: Test skill,
> Web design guidelines, Awesome design, image-to-code, playwright cli,
> frontend-design. Work through the night, no follow-up questions,
> remember everything until the end, build it. Don't push the result.
> Give me a report about everything at the end. A complete overhaul of
> everything."

## Ground rules for this overhaul

- Branch `overhaul` (worktree `.worktrees/overhaul`). Never pushed. `main`
  (commit 1d6b5eb, pushed) is the pre-overhaul baseline. The host's dev
  server runs from the main checkout on :8000; leave it alone.
- No questions to the host: decide, document the decision, move on.
- Skills (installed in ~/.claude/skills, reviewed):
  - **frontend-design** (Anthropic): distinctive visual direction
  - **web-design-guidelines** (Vercel): fetches
    https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
  - **awesome-design**: 68 style references under `styles/`
  - **image-to-code**: image-first design. There is no image model here,
    so "images" are rendered mockups (HTML → Playwright screenshots) that
    are analysed before the real implementation.
  - **playwright-cli** (Microsoft; the `playwright-cli` binary is in
    ~/.local/bin)
  - **webapp-testing** (Anthropic): the "Test skill"
- Keep every product behaviour that exists today unless the plan explicitly
  changes it (see analysis/ for the inventory). Above all, keep these
  invariants:
  - The security model: party-token gate, signed cookies, CSRF origin
    check, strict CSP for scripts, rate limits, upload validation.
  - Content-blocker-safe names.
  - The join flow (consent without a "no" option), pseudonyms, the
    fingerprint used only as a hint.
  - Moderation:
    - live screen can only hide photos
    - manage screen: delete, bans, device bans, auto-ban release
    - upload pause per guest, new-guest pause, stop all uploads
  - Camera rules:
    - exact 1080×1440 capture
    - preview == saved photo
    - mirroring rules
  - Tools: timelapse, qr, export.
  - Deployment: Docker and Coolify.
  - German UI.
  - Browsers: iOS Safari, Android Chrome, Firefox and desktop.
  - Cross-browser e2e coverage.

## Phases

1. **Analysis** (subagents, read-only): architecture + API inventory; UX/UI
   audit; stack research. → `docs/overhaul/analysis/`
2. **Plan**: target architecture, repo layout, design direction, work
   breakdown with file ownership, test strategy. → `docs/overhaul/PLAN.md`
3. **Implementation**, in waves of subagents in worktrees off `overhaul`,
   merged by the orchestrator.
4. **Verification**: QA, a11y, content blockers, security, Docker,
   cross-browser.
5. **Report** to the host. → `docs/overhaul/REPORT.md` plus a summary in
   chat.
