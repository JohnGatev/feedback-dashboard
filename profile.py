"""Survey profile: schema, validation, load/save.

A profile is a JSON dict describing one feedback-survey shape so the
pipeline and dashboard can run without hardcoded aspect lists, column
indices, prompts, or grouping labels.

Storage layout (under a user-chosen working directory):
    <dir>/profiles/<name>.json      profile files
    <dir>/analyses/<id>/            completed runs
    <dir>/kb/                       knowledge-base files (relative refs)
"""

import json
import os
import re

POLARITY_KEYS = ("tip", "top")
VALID_OUTPUT_SECTIONS = (
    "counts",
    "group_counts_table",
    "group_differences",
    "integrated_summary",
    "tensions",
    "representative_quotes",
)
DEFAULT_OUTPUT_SECTIONS = list(VALID_OUTPUT_SECTIONS)


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "aspect"


def default_profile() -> dict:
    """A minimal valid profile skeleton a user can fill in."""
    return {
        "name": "New survey",
        "delimiter": "auto",
        "header_rows_to_skip": 2,
        "grouping": None,
        "polarity": [
            {"key": "tip", "display": "Tips", "selection_column": "",
             "color": "#bc0031", "explain_prefix": ""},
            {"key": "top", "display": "Tops", "selection_column": "",
             "color": "#66bb6a", "explain_prefix": ""},
        ],
        "aspects": [],
        "output_sections": list(DEFAULT_OUTPUT_SECTIONS),
        "prompts": {"per_aspect_system": "", "executive_system": ""},
        "kb_files": [],
        "model": {
            "endpoint": "https://llmproxy.uva.nl/chat/completions",
            "name": "gpt-oss-120b",
            "temperature": 0.3,
            "max_tokens": 32768,
        },
    }


def validate(p: dict) -> None:
    """Assert-based validation. Raises AssertionError or ValueError on bad input."""
    assert isinstance(p, dict), "profile must be a JSON object"
    assert "name" in p and isinstance(p["name"], str) and p["name"].strip(), "name required"
    assert "delimiter" in p, "delimiter required ('auto', ',' or ';')"
    assert p["delimiter"] in ("auto", ",", ";"), f"bad delimiter: {p['delimiter']}"
    assert "header_rows_to_skip" in p, "header_rows_to_skip required"
    assert isinstance(p["header_rows_to_skip"], int) and p["header_rows_to_skip"] >= 0, \
        "header_rows_to_skip must be int >= 0"

    # grouping: null or object
    g = p.get("grouping")
    assert g is None or isinstance(g, dict), "grouping must be null or an object"
    if isinstance(g, dict):
        assert g.get("column"), "grouping.column required when grouping set"
        assert g.get("display_name"), "grouping.display_name required when grouping set"
        assert "label_template" in g, "grouping.label_template required when grouping set"

    # polarity: 1-2 entries
    pol = p.get("polarity")
    assert isinstance(pol, list) and 1 <= len(pol) <= 2, "polarity must be a list of 1-2 entries"
    keys = set()
    for entry in pol:
        assert isinstance(entry, dict), "polarity entry must be object"
        for f in ("key", "display", "selection_column", "color", "explain_prefix"):
            assert f in entry, f"polarity entry missing {f}"
        assert entry["key"] in POLARITY_KEYS, f"polarity.key must be one of {POLARITY_KEYS}"
        keys.add(entry["key"])
        assert entry["selection_column"], f"polarity {entry['key']} needs selection_column"
    assert len(keys) == len(pol), "polarity keys must be unique"

    # aspects: list, each with label/key/columns
    asp = p.get("aspects")
    assert isinstance(asp, list) and asp, "aspects must be a non-empty list"
    seen_keys = set()
    for a in asp:
        assert isinstance(a, dict), "aspect must be object"
        assert a.get("display_label"), "aspect.display_label required"
        assert a.get("aspect_key"), "aspect.aspect_key required"
        assert a["aspect_key"] not in seen_keys, f"duplicate aspect_key: {a['aspect_key']}"
        seen_keys.add(a["aspect_key"])
        cols = a.get("columns", {})
        assert isinstance(cols, dict), "aspect.columns must be object"
        for pol_key in keys:
            assert cols.get(pol_key), f"aspect {a['aspect_key']} missing column for {pol_key}"

    # output_sections: subset of valid
    secs = p.get("output_sections", [])
    assert isinstance(secs, list), "output_sections must be a list"
    for s in secs:
        assert s in VALID_OUTPUT_SECTIONS, f"unknown output_section: {s}"
    # group-only sections require grouping
    if g is None:
        for s in ("group_counts_table", "group_differences"):
            assert s not in secs, f"section {s} requires grouping to be set"

    # prompts: object with two string fields
    pr = p.get("prompts", {})
    assert isinstance(pr, dict), "prompts must be object"
    assert "per_aspect_system" in pr and isinstance(pr["per_aspect_system"], str), \
        "prompts.per_aspect_system required (string)"
    assert "executive_system" in pr and isinstance(pr["executive_system"], str), \
        "prompts.executive_system required (string)"

    # model
    m = p.get("model", {})
    assert isinstance(m, dict), "model must be object"
    assert m.get("endpoint"), "model.endpoint required"
    assert m.get("name"), "model.name required"


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    validate(p)
    return p


def save(p: dict, path: str) -> None:
    validate(p)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def profiles_dir(working_dir: str) -> str:
    return os.path.join(working_dir, "profiles")


def analyses_dir(working_dir: str) -> str:
    return os.path.join(working_dir, "analyses")


def list_profiles(working_dir: str) -> list[dict]:
    pd = profiles_dir(working_dir)
    out = []
    if not os.path.isdir(pd):
        return out
    for fn in sorted(os.listdir(pd)):
        if fn.endswith(".json"):
            try:
                out.append(load(os.path.join(pd, fn)))
            except Exception:
                continue
    return out


def storage_config_path() -> str:
    home = os.path.expanduser("~")
    cfg_dir = os.path.join(home, ".config", "feedback-dashboard")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "storage.json")


def load_storage_config() -> dict:
    p = storage_config_path()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_storage_config(cfg: dict) -> None:
    with open(storage_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


if __name__ == "__main__":
    # Self-check: default profile validates.
    p = default_profile()
    p["aspects"] = [
        {"display_label": "The location", "aspect_key": "the_location",
         "columns": {"tip": "Q3_Tips_explained_1", "top": "Q5_Tops_explained_1"}}
    ]
    p["polarity"][0]["selection_column"] = "Q2_Tips"
    p["polarity"][0]["explain_prefix"] = "Q3_Tips_explained"
    p["polarity"][1]["selection_column"] = "Q4_Tops"
    p["polarity"][1]["explain_prefix"] = "Q5_Tops_explained"
    p["grouping"] = {"column": "Q1_Team", "display_name": "Team", "label_template": "Team {g}"}
    p["prompts"]["per_aspect_system"] = "test"
    p["prompts"]["executive_system"] = "test"
    validate(p)
    print("profile.py self-check OK (with grouping)")

    # And a no-grouping variant with group sections suppressed.
    p2 = json.loads(json.dumps(p))
    p2["grouping"] = None
    p2["output_sections"] = [s for s in p2["output_sections"]
                             if s not in ("group_counts_table", "group_differences")]
    validate(p2)
    print("profile.py self-check OK (no grouping)")