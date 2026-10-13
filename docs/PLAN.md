# virtubooth: pre-overhaul decisions

> **Historical.** These are the decisions taken before the October 2026
> overhaul. Most still hold (Docker hosting, the token gate, the join flow,
> the Beer Cam framing, the admin split, the postponed Live Wall), but the
> stack line does not: the frontend is now React + TypeScript + Vite, and the
> backend is restructured under `backend/`. The overhaul's brief, plan,
> contracts and design are in [overhaul/](overhaul/) (start with
> [overhaul/PLAN.md](overhaul/PLAN.md)); the current state is described in
> [ARCHITECTURE.md](ARCHITECTURE.md).

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
