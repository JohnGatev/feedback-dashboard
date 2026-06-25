"""Feedback analysis pipeline, generalized over a survey profile.

Three stages, each taking a profile dict:
    csv_to_json(profile, csv_path, out_dir)   -> one JSON per aspect
    generate_aspect_summaries(profile, json_dir, md_dir, api_key)
    generate_executive_summary(profile, md_dir, out_file, api_key)

No hardcoded aspect lists, column indices, prompts, or grouping labels.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from profile import slugify, VALID_OUTPUT_SECTIONS


# ── CSV parsing ──────────────────────────────────────────────────────────────

def _open_csv(path: str, delimiter: str) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f, delimiter=delimiter))


def _col_index_by_code(row0: list[str], code: str) -> int:
    """Find a column index by matching its ImportId code in row 0."""
    for i, cell in enumerate(row0):
        m = re.search(r'"ImportId":"([^"]+)"', cell)
        if m and m.group(1) == code:
            return i
        if cell.strip() == code:
            return i
    raise KeyError(f"column code not found in header: {code}")


def _build_code_index(row0: list[str]) -> dict[str, int]:
    idx = {}
    for i, cell in enumerate(row0):
        m = re.search(r'"ImportId":"([^"]+)"', cell)
        code = m.group(1) if m else cell.strip()
        if code and code not in idx:
            idx[code] = i
    return idx


def _parse_selection_cell(cell: str) -> list[str]:
    """Parse a comma-separated selection cell into labels."""
    if not cell or not cell.strip():
        return []
    return [c.strip() for c in cell.split(",") if c.strip()]


def _segment_value(row: list[str], grouping: dict | None, code_idx: dict[str, int]) -> str:
    if grouping is None:
        return "all"
    col = grouping["column"]
    i = code_idx.get(col)
    if i is None or i >= len(row):
        return "unknown"
    v = row[i].strip()
    return v or "unknown"


# ── Stage 1: CSV -> per-aspect JSON ──────────────────────────────────────────

def csv_to_json(profile: dict, csv_path: str, out_dir: str) -> list[str]:
    """Convert a survey CSV into one JSON file per aspect.

    Returns list of written file paths.
    """
    delim = profile["delimiter"]
    if delim == "auto":
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            first = f.readline()
        delim = ";" if first.count(";") > first.count(",") else ","

    rows = _open_csv(csv_path, delim)
    skip = profile["header_rows_to_skip"]
    if len(rows) <= skip:
        raise ValueError("CSV has no data rows after header skip")
    row0 = rows[0]
    data_rows = rows[skip:]

    code_idx = _build_code_index(row0)

    polarity = profile["polarity"]
    pol_by_key = {p["key"]: p for p in polarity}
    aspects = profile["aspects"]
    grouping = profile.get("grouping")
    seg_label = grouping["display_name"] if grouping else "All"
    seg_field = "by_segment"  # generalized bucket key

    # Validate columns exist
    for p in polarity:
        if p["selection_column"] not in code_idx:
            raise KeyError(f"polarity {p['key']} selection_column not found: {p['selection_column']}")
    for a in aspects:
        for pk, col in a["columns"].items():
            if col not in code_idx:
                raise KeyError(f"aspect {a['aspect_key']} column not found: {col}")

    # Initialise store
    store = {}
    for a in aspects:
        key = a["aspect_key"]
        store[key] = {
            "aspect": {
                "aspect_key": key,
                "display_name": a["display_label"],
                "display_labels_observed": [],
            },
            "counts": {p["key"] + "_comment_count": 0 for p in polarity},
            "by_segment": {},
            "_labels_seen": set(),
        }

    def _bucket(entry, seg, pol_key):
        segs = entry[seg_field]
        if seg not in segs:
            segs[seg] = {p["key"] + "_comment_count": 0 for p in polarity}
            for p in polarity:
                segs[seg][p["key"] + "_s"] = {"comment_count": 0, "comments": []}
        return segs[seg][pol_key + "_s"]

    for row_idx, row in enumerate(data_rows):
        while len(row) < len(row0):
            row.append("")
        seg = _segment_value(row, grouping, code_idx)

        for p in polarity:
            sel_col = code_idx[p["selection_column"]]
            sel_cell = row[sel_col] if sel_col < len(row) else ""
            selections = _parse_selection_cell(sel_cell)
            if not selections:
                continue
            # Match each selected label to an aspect by display_label
            for label in selections:
                aspect = next((a for a in aspects if a["display_label"].strip().lower() == label.lower()), None)
                if aspect is None:
                    continue
                text_col = code_idx.get(aspect["columns"][p["key"]])
                if text_col is None or text_col >= len(row):
                    continue
                text = row[text_col].strip()
                if not text:
                    continue
                entry = store[aspect["aspect_key"]]
                entry["_labels_seen"].add(label)
                b = _bucket(entry, seg, p["key"])
                cid = f"r{row_idx:04d}_{p['key']}_{aspect['aspect_key']}_{len(b['comments'])+1}"
                b["comments"].append({"id": cid, "segment": seg, "text": text})
                b["comment_count"] += 1
                entry["counts"][p["key"] + "_comment_count"] += 1
                entry["by_segment"][seg][p["key"] + "_comment_count"] += 1

    # Finalise: drop internal sets, sort labels, normalise segment structure
    out_files = []
    os.makedirs(out_dir, exist_ok=True)
    for key, entry in store.items():
        entry["aspect"]["display_labels_observed"] = sorted(entry.pop("_labels_seen"))
        # Reorganize by_segment into per-polarity sub-dicts matching old shape
        segs_out = {}
        for seg, segd in entry["by_segment"].items():
            segs_out[seg] = {p["key"] + "_by_segment": {} for p in polarity}
            for p in polarity:
                segs_out[seg][p["key"] + "_by_segment"] = segd[p["key"] + "_s"]
            # keep aggregate counts at seg level for convenience
            for p in polarity:
                segs_out[seg][p["key"] + "_comment_count"] = segd[p["key"] + "_comment_count"]
        entry["by_segment"] = segs_out
        # Also expose per-polarity top-level buckets keyed by segment, mirroring
        # the original tips_by_tutorial_group / tops_by_tutorial_group shape so
        # dashboards can iterate by polarity generically.
        for p in polarity:
            pk = p["key"]
            by_seg = {}
            for seg, segd in segs_out.items():
                by_seg[seg] = segd[pk + "_by_segment"]
            entry[f"{pk}_by_segment"] = by_seg
        # remove the combined by_segment now that per-polarity views exist
        entry.pop("by_segment", None)

        fp = os.path.join(out_dir, f"{key}.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        out_files.append(fp)
        print(f"  written: {fp}  ({entry['counts']})")

    return out_files


# ── Stage 2: per-aspect summaries ────────────────────────────────────────────

SECTION_BLOCKS = {
    "counts": (
        "### Counts\n"
        "Report exact counts from the input for each polarity (non-empty comments only).\n"
        "Provide a balance label per polarity pair if two polarities are present."
    ),
    "group_counts_table": (
        "### Segment counts table\n"
        "Markdown table: rows = union of segment keys; columns: Segment | "
        "per-polarity comment counts | Balance. Use provided per-segment "
        "comment_count fields only; do not recount."
    ),
    "group_differences": (
        "### Segment differences\n"
        "Characterise notable between-segment differences supported by counts "
        "and/or distinct themes in segment comments. If patterns are broadly "
        "similar given available comments, state so explicitly."
    ),
    "integrated_summary": (
        "### Summary\n"
        "ONE integrated narrative with 4-7 theme labels, each followed by 1-3 "
        "bullets. Weight themes by prevalence: lead with the dominant theme, "
        "progress to less frequent ones, label minority signals clearly. "
        "Integrate positive and negative signals under the same label when they "
        "address the same subtopic."
    ),
    "tensions": (
        "### Key tensions / mixed signals\n"
        "Identify the main within-aspect splits. For each, name which position "
        "has more evidential support and which is the minority view. If none: "
        "'No clear split observed in the comments.'"
    ),
    "representative_quotes": (
        "### Representative quotes\n"
        "Up to 6 quotes per polarity, verbatim, no comment IDs. Lead with the "
        "most illustrative of the dominant pattern; include at least one "
        "minority or contrasting voice if present."
    ),
}


def _build_aspect_system_prompt(profile: dict) -> str:
    base = profile["prompts"]["per_aspect_system"]
    secs = profile.get("output_sections", [])
    blocks = [SECTION_BLOCKS[s] for s in secs if s in SECTION_BLOCKS]
    structure = "\n\n".join(blocks)
    polarity = profile["polarity"]
    pol_desc = "; ".join(f"{p['key']} = {p['display']}" for p in polarity)
    grouping = profile.get("grouping")
    seg_desc = (f"Segments are '{grouping['display_name']}' values."
                if grouping else "There is a single segment 'all' (no grouping variable).")
    header = (
        f"You are an evaluation analyst for formative feedback.\n\n"
        f"Polarities: {pol_desc}\n{seg_desc}\n\n"
        f"Grounding: every claim must be traceable to the provided comments. "
        f"Do not add facts, causes, or context not present in the data. "
        f"Analytical interpretation is expected; passive transcription is not.\n\n"
        f"Counts: use counts exactly as provided in the JSON; never estimate or recount.\n\n"
        f"Output format (markdown):\n\n## Aspect: <aspect.display_name>\n\n{structure}\n"
    )
    return f"{header}\n\n=== USER-PROVIDED BASE PROMPT ===\n{base}".strip()


def _aspect_user_message(aspect_data: dict) -> str:
    return ("Here is the feedback JSON for one aspect. Summarize it according to "
            "the instructions.\n\n" + json.dumps(aspect_data, indent=2))


def _call_llm(profile: dict, system: str, user: str, api_key: str, timeout: int = 180) -> str:
    m = profile["model"]
    payload = {
        "model": m["name"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": m.get("temperature", 0.3),
        "max_tokens": m.get("max_tokens", 32768),
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    r = requests.post(m["endpoint"], headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _load_kb(profile: dict, base_dir: str) -> str:
    parts = []
    for rel in profile.get("kb_files", []):
        p = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                parts.append(f"--- START KB: {os.path.basename(p)} ---\n{f.read()}\n--- END KB ---\n")
        else:
            print(f"  warn: KB file not found: {p}")
    return "\n".join(parts)


def generate_aspect_summaries(profile: dict, json_dir: str, md_dir: str,
                              api_key: str, base_dir: str = ".") -> list[str]:
    os.makedirs(md_dir, exist_ok=True)
    system = _build_aspect_system_prompt(profile)
    kb = _load_kb(profile, base_dir)
    if kb:
        system = f"{system}\n\n=== KNOWLEDGE BASE ===\n{kb}"
    import glob
    json_files = sorted(glob.glob(os.path.join(json_dir, "*.json")))
    if not json_files:
        raise ValueError(f"No aspect JSON files in {json_dir}")

    def _one(jf):
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
        key = data["aspect"]["aspect_key"]
        try:
            text = _call_llm(profile, system, _aspect_user_message(data), api_key)
            return key, text
        except Exception as e:
            print(f"  ERROR {key}: {type(e).__name__}: {e}", flush=True)
            return key, None

    saved = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_one, jf): jf for jf in json_files}
        for fut in as_completed(futs):
            key, text = fut.result()
            if text:
                fp = os.path.join(md_dir, f"{key}_summary.md")
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(text)
                saved.append(fp)
                print(f"  -> summary: {key}")
            else:
                print(f"  -> FAILED: {key}")
    if not saved:
        raise RuntimeError("All aspect LLM calls failed")
    return saved


# ── Stage 3: executive summary ───────────────────────────────────────────────

def generate_executive_summary(profile: dict, md_dir: str, out_file: str,
                               api_key: str) -> str:
    import glob
    md_files = sorted(glob.glob(os.path.join(md_dir, "*_summary.md")))
    if not md_files:
        raise ValueError(f"No aspect summaries in {md_dir}")
    combined = ""
    for mf in md_files:
        name = os.path.basename(mf).replace("_summary.md", "").replace("_", " ").title()
        with open(mf, encoding="utf-8") as f:
            combined += f"\n\n--- ASPECT: {name} ---\n{f.read()}\n"
    system = profile["prompts"]["executive_system"]
    user = f"Here are the individual aspect summaries to synthesize:\n\n{combined}"
    text = _call_llm(profile, system, user, api_key, timeout=300)
    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  executive summary -> {out_file}")
    return out_file


# ── Self-check ───────────────────────────────────────────────────────────────

def _demo():
    import sys
    if len(sys.argv) < 3:
        print("usage: pipeline.py <csv_path> <out_dir>")
        return
    csv_path, out_dir = sys.argv[1], sys.argv[2]
    from detect import detect
    from profile import default_profile
    d = detect(csv_path)
    p = default_profile()
    p["name"] = "demo"
    p["delimiter"] = d["delimiter"]
    p["polarity"] = d["polarity"]
    p["aspects"] = d["aspects"]
    p["grouping"] = d["grouping"]
    if p["grouping"] is None:
        p["output_sections"] = [s for s in p["output_sections"]
                                if s not in ("group_counts_table", "group_differences")]
    p["prompts"]["per_aspect_system"] = "Analytical academic register; no em dashes."
    p["prompts"]["executive_system"] = "Synthesize the aspect summaries into one document."
    files = csv_to_json(p, csv_path, out_dir)
    print(f"\nWrote {len(files)} aspect JSON files to {out_dir}")
    # Show one
    if files:
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        print(f"\nFirst aspect: {data['aspect']['aspect_key']}")
        print(f"  counts: {data['counts']}")
        for pk in [pol["key"] for pol in p["polarity"]]:
            segs = data.get(f"{pk}_by_segment", {})
            print(f"  {pk} segments: {list(segs.keys())}")


if __name__ == "__main__":
    _demo()