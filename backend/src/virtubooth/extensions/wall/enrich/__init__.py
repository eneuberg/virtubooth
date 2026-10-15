"""Live-Wall photo analysis ("enrichment"): facts per photo for the wall's fun
categories and the admin's „Analyse“ panel.

- `service.EnrichmentService`  the port the wall uses (PLAN §4.5), owns the worker
- `supervisor` / `worker`      the separate analysis process and its keeper
- `jobs`                       `wall_analysis` / `wall_facts` rows (migration 9)
- `pipeline` + `analyzers/`    the analyzer plugins (basic always; ML with the
                               `ml` extra and downloaded models)
- `models`                     model registry, download with SHA256 pins
- `engine`, `values`, `presets` rule-based wall categories (specs in `wall_categories`)
- `objects`                    the frozen object list (`photo_objects`)
- `testjobs`                   test images through the worker, nothing stored
- `admin_api`                  `/admin/analysis…` under the wall router

CLI: `python -m virtubooth.extensions.wall.enrich --help`.

Privacy: no recognition model; face crops, landmarks and CLIP vectors stay in
the worker's memory for one photo. Stored are counts, scores and boxes only.
"""
