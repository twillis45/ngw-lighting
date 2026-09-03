"""Uploads must be written, served, and monitored from ONE directory.

Before 2026-09-03 there were two definitions:
    api/routes/shoot_match.py  read NGW_UPLOAD_DIR
    api/routes/health.py       hardcoded "static/uploads"
so setting the env var pointed the uploader at the disk while the storage
health check kept reporting on a directory nothing wrote to -- an alarm that
reads green because it is watching the wrong filesystem.

And the app served uploads only because they happened to sit under static/, so
moving them to the persistent disk would have made every image 404 while the
database kept its "/static/uploads/..." rows.
"""
import importlib
import os
from pathlib import Path

import pytest


def _fresh_paths(monkeypatch, value=None):
    if value is None:
        monkeypatch.delenv("NGW_UPLOAD_DIR", raising=False)
    else:
        monkeypatch.setenv("NGW_UPLOAD_DIR", str(value))
    import paths
    return importlib.reload(paths)


class TestOneDefinition:
    def test_uploader_and_health_check_read_the_same_object(self):
        """Not 'the same string' -- the same imported object, so they cannot
        drift apart again by someone editing one of them."""
        import paths
        from api.routes import shoot_match
        assert shoot_match.UPLOAD_DIR is paths.UPLOAD_DIR

    def test_health_system_reports_on_the_upload_dir(self):
        """health.py imports UPLOAD_DIR rather than naming a literal path."""
        src = Path("api/routes/health.py").read_text()
        assert 'Path("static/uploads")' not in src, (
            "health.py hardcodes the upload path again; it will report on a "
            "directory the uploader may not be using"
        )
        assert "from paths import UPLOAD_DIR" in src

    def test_env_var_moves_the_directory(self, monkeypatch, tmp_path):
        target = tmp_path / "disk" / "uploads"
        p = _fresh_paths(monkeypatch, target)
        assert p.UPLOAD_DIR == target.resolve()
        _fresh_paths(monkeypatch, None)

    def test_default_is_repo_relative_not_cwd_relative(self, monkeypatch):
        """A bare relative path breaks the moment anything changes directory --
        which happens in this repo's own tooling."""
        p = _fresh_paths(monkeypatch, None)
        assert p.UPLOAD_DIR.is_absolute()
        assert p.UPLOAD_DIR.name == "uploads"


class TestFilesStayServableWhereverTheyLive:
    def test_static_uploads_is_mounted_at_the_resolved_dir(self):
        src = Path("main.py").read_text()
        assert 'app.mount("/static/uploads"' in src, (
            "uploads are served only by sitting under static/; move UPLOAD_DIR "
            "to the persistent disk and every stored image 404s"
        )

    def test_the_specific_mount_comes_first(self):
        """Starlette matches mounts in order. If /static is mounted first it
        swallows /static/uploads and the specific mount never runs."""
        src = Path("main.py").read_text()
        assert src.index('app.mount("/static/uploads"') < src.index('app.mount("/static"'), \
            "/static is mounted before /static/uploads, so the general mount wins"

    def test_url_prefix_matches_what_is_stored_in_the_database(self):
        import paths
        assert paths.UPLOAD_URL_PREFIX == "/static/uploads", (
            "db rows carry this prefix (see api/routes/blueprint.py normalisation); "
            "changing it orphans every existing row"
        )
