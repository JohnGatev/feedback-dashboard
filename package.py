"""Export and import analysis packages and profiles.

An analysis package is a zip of one analysis folder under <working>/analyses/<id>/.
A profile is a single JSON file under <working>/profiles/.
Both are shareable: a recipient imports them into their own working dir.
"""

from __future__ import annotations

import io
import json
import os
import zipfile

from profile import load as load_profile, save as save_profile, slugify


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


def import_analysis(zip_bytes: bytes, working_dir: str, name_hint: str | None = None) -> str:
    """Unzip an analysis package into <working>/analyses/<id>/.

    The meta.json inside (if present) supplies the id; otherwise name_hint is slugified.
    Returns the analysis dir path.
    """
    analyses = os.path.join(working_dir, "analyses")
    os.makedirs(analyses, exist_ok=True)

    # Peek at meta.json to get the id
    run_id = None
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if "meta.json" in names:
            meta = json.loads(zf.read("meta.json"))
            run_id = slugify(meta.get("id") or meta.get("name") or "")
        # Fallback: scan for meta.json at any depth
        if run_id is None:
            for n in names:
                if n.endswith("meta.json"):
                    try:
                        meta = json.loads(zf.read(n))
                        run_id = slugify(meta.get("id") or meta.get("name") or "")
                        break
                    except Exception:
                        pass
    if not run_id:
        run_id = slugify(name_hint or "imported")

    # Avoid clobbering an existing dir
    target = os.path.join(analyses, run_id)
    i = 1
    while os.path.exists(target):
        target = os.path.join(analyses, f"{run_id}_{i}")
        i += 1
    os.makedirs(target, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(target)
    return target


def export_profile(profile: dict) -> bytes:
    """Serialize a profile to JSON bytes."""
    return json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8")


def import_profile(json_bytes: bytes, working_dir: str) -> str:
    """Save a profile JSON into <working>/profiles/. Returns the path."""
    p = json.loads(json_bytes)
    pd = os.path.join(working_dir, "profiles")
    os.makedirs(pd, exist_ok=True)
    name = slugify(p.get("name") or "imported")
    path = os.path.join(pd, f"{name}.json")
    i = 1
    while os.path.exists(path):
        path = os.path.join(pd, f"{name}_{i}.json")
        i += 1
    save_profile(p, path)
    return path


if __name__ == "__main__":
    # Self-check: round-trip a profile dict.
    from profile import default_profile
    p = default_profile()
    p["name"] = "Self check survey"
    p["aspects"] = [{"display_label": "X", "aspect_key": "x",
                     "columns": {"tip": "Q3_1", "top": "Q5_1"}}]
    p["polarity"][0]["selection_column"] = "Q2"
    p["polarity"][1]["selection_column"] = "Q4"
    p["grouping"] = None
    p["output_sections"] = [s for s in p["output_sections"]
                            if s not in ("group_counts_table", "group_differences")]
    p["prompts"]["per_aspect_system"] = "test"
    p["prompts"]["executive_system"] = "test"
    b = export_profile(p)
    path = import_profile(b, "/tmp/_pkg_test")
    reloaded = load_profile(path)
    assert reloaded["name"] == p["name"]
    print("package.py self-check OK:", path)