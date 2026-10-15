"""The analysis pipeline with fake analyzers: dependency order, skip chains,
failures → retry → failed, scratch never stored."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from PIL import Image

from virtubooth.core.clock import now_iso
from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.pipeline import (
    AnalyzerInfo,
    Box,
    Frame,
    PhotoInfo,
    Pipeline,
    Result,
    merge,
    topological,
)
from virtubooth.extensions.wall.enrich.worker import Worker
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user


class Fake:
    def __init__(self, name: str, needs: tuple[str, ...] = (), *, models: tuple[str, ...] = (),
                 fail: bool = False, kind: str = "basic") -> None:  # fmt: skip
        self.info = AnalyzerInfo(name=name, title=name.title(), version="7", kind=kind,  # type: ignore[arg-type]
                                 needs=needs, models=models, facts=(name,))  # fmt: skip
        self.fail = fail
        self.loads = 0
        self.seen: list[list[str]] = []

    def load(self, models: Mapping[str, Path]) -> None:
        self.loads += 1

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        self.seen.append(sorted(prior))
        if self.fail:
            raise ValueError("boom")
        secret = {"embedding": [0.1] * 4, "crop": "pixels"}
        return Result(
            facts={self.info.name: 1.0},
            boxes=[Box("face", 0.1, 0.2, 0.3, 0.4, f"by {self.info.name}", 0.9)],
            details=[(self.info.title, "ja")],
            scratch=secret,
        )


def frame() -> Frame:
    info = PhotoInfo(
        1, "pub", "booth", "x.jpg", "2026-10-13T18:00:00.000+00:00", 64, 64, {}, "Gast"
    )
    return Frame(Image.new("RGB", (64, 64), (10, 20, 30)), 64, 64, info)


def pipeline(*analyzers: Fake, gate=lambda info: None, resolve=lambda name: Path("/m")) -> Pipeline:
    return Pipeline(list(analyzers), gate=gate, resolve=resolve)


def test_order_follows_needs_then_registry_order():
    infos = [Fake("c", ("b",)).info, Fake("a").info, Fake("b", ("a",)).info, Fake("d").info]
    assert topological(infos) == ["a", "b", "c", "d"]
    with pytest.raises(ValueError, match="cycle"):
        topological([Fake("x", ("y",)).info, Fake("y", ("x",)).info])


def test_dependents_see_prior_results_and_scratch_is_dropped():
    a, b, c = Fake("a"), Fake("b", ("a",)), Fake("c", ("b",))
    p = pipeline(c, b, a)
    out = p.run(frame())
    assert p.order == ["a", "b", "c"]
    assert b.seen == [["a"]] and c.seen == [["a", "b"]]
    assert out.facts == {"a": 1.0, "b": 1.0, "c": 1.0}
    assert out.versions == {"a": "7", "b": "7", "c": "7"}
    assert out.details == [("A", "ja"), ("B", "ja"), ("C", "ja")]
    # the same box from three analyzers: one box, labels joined
    assert [b.label for b in out.boxes] == ["by a · by b · by c"]
    stored = json.dumps(out.data())
    assert "embedding" not in stored and "pixels" not in stored
    # loaded once per process
    p.run(frame())
    assert (a.loads, b.loads, c.loads) == (1, 1, 1)


def test_disabled_skips_the_chain():
    a, b, c, d = Fake("a"), Fake("b", ("a",)), Fake("c", ("b",)), Fake("d")
    out = pipeline(a, b, c, d).run(frame(), disabled={"a"})
    assert out.facts == {"d": 1.0}
    assert out.skipped == {"a": "ausgeschaltet", "b": "braucht a", "c": "braucht b"}
    assert not b.seen and not c.seen


def test_unavailable_analyzers_and_missing_models_skip():
    ml = Fake("ml", kind="ml")
    dep = Fake("dep", ("ml",))
    model = Fake("model", models=("big",))
    p = pipeline(ml, dep, model, Fake("ok"),
                 gate=lambda info: "KI-Paket fehlt" if info.kind == "ml" else None,
                 resolve=lambda name: None)  # fmt: skip
    out = p.run(frame())
    assert out.facts == {"ok": 1.0}
    assert out.skipped == {"ml": "KI-Paket fehlt", "dep": "braucht ml", "model": "Modell big fehlt"}
    assert ml.loads == model.loads == 0


def test_load_errors_make_an_analyzer_unavailable():
    class Broken(Fake):
        def load(self, models: Mapping[str, Path]) -> None:
            raise RuntimeError("no libEGL")

    p = pipeline(Broken("x"), Fake("y", ("x",)))
    out = p.run(frame())
    assert out.facts == {}
    assert out.skipped["x"].startswith("Laden fehlgeschlagen") and p.load_errors == {
        "x": out.skipped["x"]
    }


def test_expected_versions_static_and_loaded():
    class Broken(Fake):
        def load(self, models: Mapping[str, Path]) -> None:
            raise RuntimeError("no libEGL")

    broken = Broken("x")
    p = pipeline(Fake("a"), Fake("b", ("a",)), broken, Fake("y", ("x",)),
                 Fake("m", models=("big",)),
                 resolve=lambda name: None if name == "big" else Path("/m"))  # fmt: skip
    # static: nothing is loaded, the broken one still looks fine
    assert p.expected() == {"a": "7", "b": "7", "x": "7", "y": "7"}
    assert p.expected({"a"}) == {"x": "7", "y": "7"}
    assert broken.loads == 0
    # loaded: exact, and the load error sticks for the static answer too
    assert p.expected(load=True) == {"a": "7", "b": "7"}
    assert p.expected() == {"a": "7", "b": "7"}


def test_people_falls_back_to_faces():
    out = merge({"faces": Result(facts={"faces": 3})}, ["faces"], {}, {}, {})
    assert out.facts == {"faces": 3.0, "people": 3.0}
    out = merge({"o": Result(facts={"people": 5, "faces": 3})}, ["o"], {}, {}, {})
    assert out.facts["people"] == 5.0


# ------------------------------------------------- through the worker + jobs


@pytest.fixture
def data_dir(tmp_path: Path) -> Iterator[tuple[Path, Repositories, int]]:
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    repos = Repositories.create(db, data)
    user = create_user(db, repos, consent_version="1", instagram=None, fp_hash=None,
                       fp_components={}, ip="10.0.0.1", user_agent="pytest")  # fmt: skip
    (data / "booth").mkdir()
    Image.new("RGB", (120, 90), (200, 30, 30)).save(data / "booth" / "p.jpg")
    public_id = new_public_id()
    repos.photos.insert(public_id=public_id, extension="booth", user_id=user.id,
                        filename="p.jpg", thumb_filename="p.jpg", width=120, height=90, size=1,
                        meta={}, created_at=now_iso())  # fmt: skip
    yield data, repos, repos.photos.internal_id(public_id) or 0
    db.close()


def test_a_failing_analyzer_fails_the_photo_after_two_attempts(data_dir):
    data, repos, photo_id = data_dir
    worker = Worker(data, analyzers=[Fake("a"), Fake("b", ("a",), fail=True)])
    worker.run(once=True)
    row = jobs.get(repos.db, photo_id)
    assert (row.state, row.attempts) == ("failed", 2)
    assert row.error == "Analyse fehlgeschlagen (ValueError)"
    assert jobs.facts(repos.db, photo_id) == {}


def test_the_worker_stores_facts_boxes_details_but_no_scratch(data_dir):
    data, repos, photo_id = data_dir
    worker = Worker(data, analyzers=[Fake("a"), Fake("b", ("a",))])
    assert worker.run(once=True) == 0
    row = jobs.get(repos.db, photo_id)
    assert row.state == "done" and row.versions == {"a": "7", "b": "7"}
    assert jobs.facts(repos.db, photo_id) == {"a": 1.0, "b": 1.0}
    assert row.data["details"] == [{"label": "A", "value": "ja"}, {"label": "B", "value": "ja"}]
    raw = repos.db.one("SELECT data FROM wall_analysis WHERE photo_id=?", (photo_id,))[0]
    assert "embedding" not in raw and "pixels" not in raw
    beat = repos.app_settings.get(jobs.WORKER_KEY)
    assert beat["pid"] > 0 and beat["beat_at"] and "models_missing" in beat


def test_a_missing_file_is_skipped(data_dir):
    data, repos, photo_id = data_dir
    (data / "booth" / "p.jpg").unlink()
    Worker(data, analyzers=[Fake("a")]).run(once=True)
    row = jobs.get(repos.db, photo_id)
    assert (row.state, row.error) == ("skipped", "Fotodatei fehlt")


def test_the_worker_recycles_after_max_photos(data_dir):
    data, repos, photo_id = data_dir
    worker = Worker(data, analyzers=[Fake("a")], max_photos=1, idle_s=0.01, watch_parent=False)
    assert worker.run() == 75
    assert jobs.get(repos.db, photo_id).state == "done"


def test_an_opted_out_guest_gets_only_the_basic_values(data_dir):
    """„Meine Fotos nicht automatisch auswerten“: the ML analyzers (by their
    registry names) are skipped. Switching back only flips the flag: the
    analysis is frozen (PLAN-NIGHT N4), nothing is requeued."""
    data, repos, photo_id = data_dir
    user_id = repos.db.one("SELECT user_id FROM photos WHERE id=?", (photo_id,))[0]

    def analyzers() -> list[Fake]:
        return [Fake("basic"), Fake("faces"), Fake("emotion", ("faces",))]

    assert repos.users.set_analysis_opt_out(user_id, True)
    Worker(data, analyzers=analyzers()).run(once=True)
    assert jobs.facts(repos.db, photo_id) == {"basic": 1.0}

    row = jobs.get(repos.db, photo_id)
    assert repos.users.set_analysis_opt_out(user_id, False)
    assert not repos.users.set_analysis_opt_out(user_id, False)  # unchanged
    assert jobs.get(repos.db, photo_id) == row
    assert jobs.facts(repos.db, photo_id) == {"basic": 1.0}


def _versions(repos: Repositories, photo_id: int) -> tuple[str, dict[str, str]]:
    row = jobs.get(repos.db, photo_id)
    assert row is not None
    return row.state, row.versions


def test_the_sweep_requeues_on_a_new_version_or_a_newly_enabled_analyzer(data_dir):
    data, repos, photo_id = data_dir
    worker = Worker(data, analyzers=[Fake("basic"), Fake("faces")])
    worker.run(once=True)
    assert _versions(repos, photo_id) == ("done", {"basic": "7", "faces": "7"})
    # nothing changed: a sweep (also a forced one) queues nothing
    assert worker.sweep(repos, force=True) == 0
    # a new version of one analyzer (new code, so a new worker)
    bumped = Fake("faces")
    object.__setattr__(bumped, "info", AnalyzerInfo(
        name="faces", title="F", version="8", kind="basic", facts=("faces",)))  # fmt: skip
    worker = Worker(data, analyzers=[Fake("basic"), bumped])
    assert worker.run(once=True) == 0
    assert _versions(repos, photo_id) == ("done", {"basic": "7", "faces": "8"})
    # switched off: no new work (its old facts are just ignored) ...
    jobs.save_disabled(repos.app_settings, {"faces"}, by="pytest")
    assert worker.sweep(repos) == 0
    # ... switched on (here: a registry analyzer that was not running): queued again
    jobs.save_disabled(repos.app_settings, set(), by="pytest")
    worker = Worker(data, analyzers=[Fake("basic"), bumped, Fake("tags")])
    assert worker.sweep(repos) == 1
    assert _versions(repos, photo_id)[0] == "pending"
    worker.run(once=True)
    assert _versions(repos, photo_id) == ("done", {"basic": "7", "faces": "8", "tags": "7"})


def test_a_model_that_fails_to_load_does_not_requeue_forever(data_dir):
    data, repos, photo_id = data_dir

    class Broken(Fake):
        def load(self, models: Mapping[str, Path]) -> None:
            self.loads += 1
            raise RuntimeError("no libEGL")

    for _ in range(3):  # three recycled workers
        broken = Broken("faces")
        worker = Worker(data, analyzers=[Fake("basic"), broken])
        worker.run(once=True)
        assert _versions(repos, photo_id) == ("done", {"basic": "7"})
        assert worker.sweep(repos, force=True) == 0
    # the sweep loaded it to find out (once per worker), but queued nothing
    assert broken.loads == 1 and not broken.seen


def test_switching_the_opt_out_keeps_the_frozen_analysis(data_dir):
    data, repos, photo_id = data_dir
    user_id = repos.db.one("SELECT user_id FROM photos WHERE id=?", (photo_id,))[0]
    Worker(data, analyzers=[Fake("basic"), Fake("faces")]).run(once=True)
    before = (jobs.get(repos.db, photo_id), jobs.facts(repos.db, photo_id))
    for flag in (True, False, True, False):
        assert repos.users.set_analysis_opt_out(user_id, flag)
        assert (jobs.get(repos.db, photo_id), jobs.facts(repos.db, photo_id)) == before


def test_an_opt_out_during_an_analysis_only_flips_the_flag(data_dir):
    """The result is stored (frozen); the live flag keeps it out of every use."""
    _data, repos, photo_id = data_dir
    user_id = repos.db.one("SELECT user_id FROM photos WHERE id=?", (photo_id,))[0]
    claimed = jobs.claim(repos.db)
    assert claimed is not None and not claimed.opt_out
    assert repos.users.set_analysis_opt_out(user_id, True)
    assert jobs.get(repos.db, photo_id).state == "running"
    assert repos.users.get(user_id).analysis_opt_out is True


def test_the_worker_names_the_source_from_the_stored_labels(data_dir):
    from virtubooth.extensions.wall.enrich.analyzers.basic import BasicAnalyzer
    from virtubooth.extensions.wall.enrich.pipeline import SourceLabels

    data, repos, photo_id = data_dir
    jobs.save_source_labels(repos.app_settings, {"booth": SourceLabels(title="Fotobox")})
    Worker(data, analyzers=[BasicAnalyzer()]).run(once=True)
    details = {d["label"]: d["value"] for d in jobs.get(repos.db, photo_id).data["details"]}
    assert details["Quelle"] == "Fotobox"
