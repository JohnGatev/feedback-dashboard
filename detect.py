"""Auto-detect survey structure from a Qualtrics-style CSV export.

Qualtrics 3-row header layout:
    row 0: internal column codes (QID*, ImportId...)
    row 1: human-readable question text; multi-answer "explained" columns
           end with " - <aspect label>"
    row 2+: respondent data

Detection heuristics:
    delimiter  : count ';' vs ',' in row 0; pick the more frequent.
    polarity   : find "Select one or two aspects ... (Tips)"-style headers
                 for keys tip/top, plus their matching "explained_*" columns.
    aspects    : for each explained column, strip the " - <label>" suffix
                 from the row-1 header; pair tip/top by trailing _N suffix.
    grouping   : a Q* column whose row-1 text contains "what team"/"which
                 group"/"which tutorial" (case-insensitive); else None.
"""

import csv
import io
import os
import re
from profile import slugify


def _read_raw(path: str) -> list[str]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.readlines()


def detect_delimiter(first_line: str) -> str:
    semi = first_line.count(";")
    comma = first_line.count(",")
    if semi > comma:
        return ";"
    return ","


def _parse_row(line: str, delimiter: str) -> list[str]:
    rdr = csv.reader(io.StringIO(line), delimiter=delimiter)
    return next(rdr)


def _parse_header_rows(path: str, delimiter: str, skip: int) -> list[list[str]]:
    lines = _read_raw(path)
    return [_parse_row(lines[i], delimiter) for i in range(min(skip, len(lines)))]


_EXPLAINED_RE = re.compile(r"^(Q\d+)_(Tips|Tops)_explained_(\d+)$", re.IGNORECASE)
_SELECTION_RE = re.compile(r"select one or two aspects.*?\b(tips|tops)\b", re.IGNORECASE)
_GROUP_HINT_RE = re.compile(
    r"\b(what team|which team|what group|which group|which tutorial|"
    r"what tutorial|team do you support|tutorial group)\b",
    re.IGNORECASE,
)


def _norm_pol_key(k: str) -> str:
    """tips/tops -> tip/top (singular)."""
    k = k.lower()
    return k[:-1] if k.endswith("s") else k


def _column_codes(row0: list[str]) -> list[tuple[str, str]]:
    """Return (normalized_code, original) for each column from row 0."""
    out = []
    for cell in row0:
        m = re.search(r'"ImportId":"([^"]+)"', cell)
        code = m.group(1) if m else cell.strip()
        out.append((code, cell))
    return out


def detect(path: str, header_rows_to_skip: int = 2) -> dict:
    """Detect survey structure. Returns a partial profile dict.

    The caller fills in prompts, kb_files, model, and may edit aspects.
    """
    lines = _read_raw(path)
    if not lines:
        raise ValueError("Empty CSV")
    delim = detect_delimiter(lines[0])
    header = _parse_header_rows(path, delim, header_rows_to_skip)
    if len(header) < 2:
        raise ValueError("Not enough header rows for detection")
    row0 = header[0]   # codes
    row1 = header[1]   # human labels

    codes = [c for c, _ in _column_codes(row0)]

    # --- Polarity: find selection columns (Q2_Tips / Q4_Tops style) ---
    polarity = []
    for idx, code in enumerate(codes):
        m = _SELECTION_RE.search(row1[idx] if idx < len(row1) else "")
        if m:
            key = _norm_pol_key(m.group(1))
            polarity.append({
                "key": key,
                "display": "Tips" if key == "tip" else "Tops",
                "selection_column": code,
                "color": "#bc0031" if key == "tip" else "#66bb6a",
                "explain_prefix": None,  # filled below
            })
    # Deduplicate by key, keep first
    seen = set()
    polarity = [p for p in polarity if not (p["key"] in seen or seen.add(p["key"]))]

    # --- Aspect columns: pair explained_* by trailing _N ---
    # Map: suffix_N -> {polarity_key: column_code, label}
    pairs: dict[str, dict] = {}
    for idx, code in enumerate(codes):
        m = _EXPLAINED_RE.match(code)
        if not m:
            continue
        _qid, kind, suf = m.group(1), m.group(2).lower(), m.group(3)
        pol_key = _norm_pol_key(kind)
        # Label from row1: text after final " - "
        label_txt = row1[idx] if idx < len(row1) else ""
        label = label_txt.rsplit(" - ", 1)[-1].strip().rstrip("\U0001f517").strip() \
            if " - " in label_txt else label_txt.strip()
        if not label:
            label = f"Aspect {suf}"
        entry = pairs.setdefault(suf, {"label": None, "cols": {}})
        if entry["label"] is None or (label and not label.startswith("Aspect ")):
            entry["label"] = label
        entry["cols"][pol_key] = code

    aspects = []
    for suf in sorted(pairs.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        e = pairs[suf]
        label = e["label"] or f"Aspect {suf}"
        cols = e["cols"]
        if not all(pk in cols for pk in ("tip", "top")):
            continue  # incomplete pair; skip
        aspects.append({
            "display_label": label,
            "aspect_key": slugify(label),
            "columns": {"tip": cols["tip"], "top": cols["top"]},
        })

    # Fill explain_prefix on each polarity entry from the first aspect column.
    for p in polarity:
        for a in aspects:
            col = a["columns"].get(p["key"])
            if col:
                p["explain_prefix"] = re.sub(r"_\d+$", "", col)
                break

    # --- Grouping: scan Q* columns for a "team/group/tutorial" hint ---
    grouping = None
    for idx, code in enumerate(codes):
        if not re.match(r"^Q\d+", code):
            continue
        hint_txt = row1[idx] if idx < len(row1) else ""
        if _GROUP_HINT_RE.search(hint_txt):
            display = hint_txt.split("?")[0].strip().rstrip(",") or "Group"
            grouping = {
                "column": code,
                "display_name": display,
                "label_template": (display.split()[-1].title() or "Group") + " {g}",
            }
            break

    return {
        "delimiter": delim,
        "header_rows_to_skip": header_rows_to_skip,
        "polarity": polarity,
        "aspects": aspects,
        "grouping": grouping,
    }


def demo():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: detect.py <csv_path>")
        return
    d = detect(path)
    print("delimiter:", d["delimiter"])
    print("grouping:", d["grouping"])
    print("polarity:")
    for p in d["polarity"]:
        print(" ", p)
    print(f"aspects ({len(d['aspects'])}):")
    for a in d["aspects"]:
        print(f"  {a['aspect_key']:<40} tip={a['columns']['tip']}  top={a['columns']['top']}  ({a['display_label']})")


if __name__ == "__main__":
    demo()