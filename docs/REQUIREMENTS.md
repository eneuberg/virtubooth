I'm throwing a party and want to build three phone-friendly web activities that guests reach by scanning QR codes. Everything runs on my Raspberry Pi, which has a public domain pointing at it. Before writing code, explore the ideas, check my Pi's environment (OS, Pi model, installed tools like Python/Node/ffmpeg/Caddy, free disk space), and propose a plan with your recommended stack. Wait for my OK, then build it.

## The activities

1. **Beer Cam ("1 million beers" timelapse)**
   - Guests open a page, allow the camera (rear camera by default), and photograph their drink.
   - Show an overlay guide (a glass silhouette or circle) so every photo is framed the same way. Consistent alignment is what makes the final timelapse work.
   - Resize and compress the photo in the browser before uploading (~1080px, JPEG), then upload it to the Pi.
   - Show a fun confirmation like "Beer #127 logged 🍺" with a running count.

2. **Virtual Photo Booth**
   - Live camera preview with real-time filters guests can swipe or tap through, for example: black & white, sepia, color pop, pixelate/retro, a party frame, emoji/props overlays. Front camera by default, with a toggle to switch.
   - Optional 3-2-1 countdown, then capture. The saved image must include the filter exactly as previewed.
   - Let the guest download their photo to their phone and also upload it to the Pi.
   - Implement filters with canvas pixel ops or WebGL shaders, not CSS/ctx.filter, so they work on iOS Safari.

3. **Live Wall (for a TV/projector)**
   - A fullscreen page that shows new photos from both activities as they arrive (polling or SSE/WebSocket), with nice transitions. When nothing new comes in, cycle through older photos.
   - Show the beer counter prominently.
   - Show a QR code on screen so people can join.

## Requirements
- Must run over HTTPS (camera access requires it). Prefer Caddy for automatic certificates, unless you find a better fit for my setup.
- Must work well on recent iOS Safari and Android Chrome. Design mobile-first, with big buttons and a party vibe.
- Protect against randos: each QR code URL contains a secret party token, and the server rejects uploads without it. Add basic limits on file size, image type and upload rate.
- Store photos on disk in separate folders per activity, with timestamped filenames and a small metadata file or SQLite.
- The Pi must stay responsive with ~50 guests. Keep the server lightweight.
- Include a script that builds the timelapse from Beer Cam photos with ffmpeg, ordered by upload time, with configurable fps and optional crossfade.
- Include a script that generates the printable QR codes (with the token baked into the URLs).
- Run it as a systemd service so it survives reboots.
- Write a README with setup steps, how to start/stop, how to test locally, and how to export everything after the party.

## Process
- Start by proposing the architecture, file structure and any trade-offs or open questions. Don't build yet.
- After I approve, build it incrementally and test each piece as you go.
- Tell me how to test the camera pages on a real phone before party night.