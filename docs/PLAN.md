# virtubooth: pre-overhaul decisions

> **Historical.** The decisions taken before the October 2026 overhaul. Still
> true: Docker hosting, the token gate (now several QR codes), the join flow,
> the Beer Cam framing, the admin split. Changed since: the stack (React +
> TypeScript + Vite, the backend under `backend/`) and the Live Wall, which is
> no longer postponed but the `wall` extension. The overhaul's records are in
> [overhaul/](overhaul/); the current state is in
> [ARCHITECTURE.md](ARCHITECTURE.md) and [FEATURES.md](FEATURES.md).

The original spec is in [REQUIREMENTS.md](REQUIREMENTS.md). These decisions
change or extend it (agreed 2026-10-12):

- **Hosting:** an external server via Docker (exposes a port), not a Raspberry
  Pi. TLS/domain comes from a reverse proxy in front, set up later.
- **Live Wall:** postponed. The platform is extension-based
  ([ARCHITECTURE.md](ARCHITECTURE.md)), so the wall can come back as an
  extension that uses the event bus.
- **No token, no entry:** without a valid party QR scan every page shows
  "Scan den QR-Code" (HTTP 404).
- **Beer Cam:** beer bottle outline by default, switchable to a cup of about
  the same size. Output 1080×1440 (3:4).
- **Guest identity:** no registration. First visit → consent banner (store
  photos + post on Instagram, device recognition), with no "no" option, plus
  an optional Instagram handle. Guests get a pseudonym; a fingerprint is kept
  as a moderation hint.
- **Admin:** password from env. Live screen: hide only. Management screen:
  hide, delete, users, bans (user and, separately, fingerprint).
- **Stack:** Python/FastAPI, SQLite, vanilla JS (no build, no CDN), WebGL
  filters. *(Superseded by the overhaul: React 19 + TypeScript + Vite, still
  no CDN and the same WebGL filters.)*
