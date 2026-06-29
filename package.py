"""Export and import analysis packages.

An analysis package is a zip of one analysis folder (JSON Outputs, Markdown
Summaries, profile.json, meta.json, Executive_Summary.md). It is the only
persistence mechanism: no database, no local storage. Run produces a temp dir,
exports it as a zip; a recipient unpacks the zip into a fresh temp dir to view.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile

from profile import slugify


def export_analysis(analysis_dir: str) -> bytes:
    """Zip one analysis folder into in-memory bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(analysis_dir):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, analysis_dir)
                zf.write(full, arc)
    return buf.getvalue()


def unpack_analysis(zip_bytes: bytes, name_hint: str | None = None) -> str:
    """Unzip an analysis package into a fresh temp dir. Returns the dir path.

    The caller is responsible for cleaning up the temp dir when done
    (shutil.rmtree). No working directory or persistent storage is used.
    """
    target = tempfile.mkdtemp(prefix="fbpkg_")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(target)
    return target


if __name__ == "__main__":
    # Self-check: round-trip a fake analysis dir.
    import shutil
    src = tempfile.mkdtemp(prefix="fbsrc_")
    os.makedirs(os.path.join(src, "JSON Outputs"))
    with open(os.path.join(src, "meta.json"), "w") as f:
        json.dump({"id": "test_run", "filename": "x.csv", "date": "2026-01-01"}, f)
    with open(os.path.join(src, "JSON Outputs", "a.json"), "w") as f:
        json.dump({"aspect": {"aspect_key": "a", "display_name": "A"}}, f)
    z = export_analysis(src)
    out = unpack_analysis(z)
    assert os.path.exists(os.path.join(out, "meta.json"))
    assert os.path.exists(os.path.join(out, "JSON Outputs", "a.json"))
    shutil.rmtree(src); shutil.rmtree(out)
    print("package.py self-check OK")