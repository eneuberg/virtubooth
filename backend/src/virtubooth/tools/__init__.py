"""Command line tools for the host, run before and after the party.

    python -m virtubooth.tools.qr          printable QR codes (token baked in)
    python -m virtubooth.tools.timelapse   Beer Cam timelapse video (ffmpeg)
    python -m virtubooth.tools.export      everything as one .tar.gz

They work inside the container (`docker compose exec app python -m
virtubooth.tools.<tool>`) and on a laptop against a copied data dir: they only
need the data dir (`--data-dir`, else $VB_DATA_DIR, else ./data), never the
full app configuration. Each module has `main(argv=None) -> int`.
"""
