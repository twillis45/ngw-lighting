"""Filesystem locations, defined once.

Created 2026-09-03. The upload directory was previously defined in two places
that disagreed:

    api/routes/shoot_match.py:74   Path(os.environ.get("NGW_UPLOAD_DIR", "static/uploads"))
    api/routes/health.py:144       Path("static/uploads")          # hardcoded

So /health/system reported free space and writability for a directory the
uploader would stop using the moment NGW_UPLOAD_DIR was set -- a storage alarm
watching the wrong filesystem, which is the failure mode where the alarm is
worse than no alarm because it reads green.

Two facts make the default dangerous rather than merely awkward:

  * `static/uploads/` is gitignored and recreated empty at boot (main.py:167),
    so on Render it lives on the EPHEMERAL container filesystem and is
    destroyed by every deploy.
  * The database lives on the mounted disk at /data and persists `image_path`
    in four tables (db/database.py:129, 141, 166, 316).

Rows survive a deploy; the files they name do not. The 2026-08-31 data-loss fix
pointed NGW_DATA_DIR at the mounted disk and stopped there, so it repaired the
database and left the images behind.

Pointing NGW_UPLOAD_DIR at /data alone would NOT have worked before today: the
app serves uploads only because they happen to sit under `static/`, which is
mounted at /static. main.py now mounts /static/uploads at whatever this resolves
to, BEFORE the general /static mount, so storage location and public URL are
independent and stored `/static/uploads/...` references keep resolving.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

#: Where uploaded reference images are written. Absolute on Render (the mounted
#: disk), repo-relative in local dev. Read this; never re-derive it.
UPLOAD_DIR: Path = (
    Path(os.environ["NGW_UPLOAD_DIR"]).resolve()
    if os.environ.get("NGW_UPLOAD_DIR")
    else REPO_ROOT / "static" / "uploads"
)

#: The public URL prefix those files are served under. Kept stable even when
#: UPLOAD_DIR moves, because it is written into database rows.
UPLOAD_URL_PREFIX = "/static/uploads"
