"""Everything the app WRITES must live under DATA_DIR, not in image storage.

Found 2026-08-31, and it explains a lot of this project's history.

Render mounts the persistent disk at /data. The app wrote to /app/data —
WORKDIR is /app, so the repo's data/ directory sits there. That is IMAGE
storage, rebuilt on every deploy. So every write was destroyed by the next
deploy: the SQLite DB, waitlist signups, lab uploads, benchmark cases,
baselines.

That is why production had zero benchmark cases and zero baselines however
long the code existed. Nothing was broken about creating them; nothing
survived.

Proven rather than assumed: a thumbnail committed 2026-08-30 was served by
production immediately, which a disk mounted at /app/data would have shadowed.
Render's own disk-usage graph read ~0 GB.

The fix is NGW_DATA_DIR=/data, which the code already supported. These tests
assert the split it creates: writable state follows DATA_DIR, shipped
read-only content does not.
"""
import importlib
import os
from pathlib import Path

import pytest


def _reload_with(tmp, monkeypatch):
    monkeypatch.setenv("NGW_DATA_DIR", str(tmp))
    import db.database
    importlib.reload(db.database)
    import api.routes.waitlist as wl
    import api.routes.lab as lab
    importlib.reload(wl)
    importlib.reload(lab)
    return db.database, wl, lab


def test_writable_paths_follow_data_dir(tmp_path, monkeypatch):
    dbm, wl, lab = _reload_with(tmp_path, monkeypatch)
    for name, p in (("DB_PATH", dbm.DB_PATH),
                    ("WAITLIST_PATH", wl.WAITLIST_PATH),
                    ("UPLOAD_DIR", lab.UPLOAD_DIR)):
        assert str(p).startswith(str(tmp_path)), (
            f"{name} is {p} — not under DATA_DIR, so on Render it would write to "
            "image storage and be destroyed on the next deploy")


def test_shipped_read_only_content_does_not_follow_data_dir(tmp_path, monkeypatch):
    """The other half. Moving DATA_DIR must not orphan the reference dataset,
    which ships in the image and is never written."""
    _, _, lab = _reload_with(tmp_path, monkeypatch)
    repo_data = Path(lab.__file__).resolve().parent.parent.parent / "data"
    bases = [str(b) for b in lab._SAFE_IMAGE_BASES]
    assert any(str(repo_data / "reference_dataset") == b for b in bases), (
        "the shipped reference_dataset is no longer an approved image base — "
        "lab image serving would 404 for every dataset entry")


def test_the_waitlist_is_not_a_bare_relative_path():
    """It was Path('data/waitlist.json'), which resolves against the CWD and
    silently lands in image storage."""
    src = (Path(__file__).resolve().parent.parent /
           "api" / "routes" / "waitlist.py").read_text()
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert 'Path("data/waitlist.json")' not in code


def test_render_yaml_mountpath_and_data_dir_agree():
    """The config error itself: the blueprint said /app/data while the live
    service used /data, and nothing compared them."""
    import re
    y = (Path(__file__).resolve().parent.parent / "render.yaml").read_text()
    code = "\n".join(l.split("#", 1)[0] for l in y.splitlines())
    mount = re.search(r"mountPath:\s*(\S+)", code)
    datadir = re.search(r'key:\s*NGW_DATA_DIR\s*\n\s*value:\s*"?([^"\s]+)', code)
    assert mount, "no disk mountPath in render.yaml"
    assert datadir, "NGW_DATA_DIR not declared in render.yaml"
    assert mount.group(1) == datadir.group(1), (
        f"disk is mounted at {mount.group(1)} but NGW_DATA_DIR is "
        f"{datadir.group(1)} — writes would go to image storage")
