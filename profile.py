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


def _default_per_aspect_prompt() -> str:
    """The original analytical per-aspect prompt (voice/guardrails only).

    Structural section instructions (Counts, group counts table, Summary,
    Tensions, Quotes) live in pipeline.SECTION_BLOCKS and are appended at
    run time based on the output_sections toggles, so they are omitted here
    to avoid duplication.
    """
    return """You are an evaluation analyst for formative feedback at a university.

Task
You will receive one JSON input for one aspect. The JSON contains only non-empty comments, split into Tips (improvement suggestions) and Tops (positive feedback), optionally grouped by a segment variable (e.g. tutorial group, team). Produce an analytically grounded summary.

Grounding
Every claim must be traceable to the provided comments. You may characterise patterns, weigh evidence, and draw inferences — provided you do not add facts, causes, or context not present in the data. Analytical interpretation is expected; passive transcription is not.

Prevalence language
Use proportional language tied to the counts provided:
- If a theme appears across the majority of comments for that type, call it "the dominant concern" or "the prevailing pattern".
- If it appears in several but not most comments, call it "a recurring theme" or "a common concern".
- If it appears in 2–3 comments, call it "a minority signal" or "a less frequent note".
- If it appears once, either omit it or flag it explicitly as an isolated remark.
Never list a theme supported by 30 comments alongside one supported by 2 at the same rhetorical level.

Minority and contrasting views
Acknowledge dissenting or contrasting views explicitly. Label them as minority ("a smaller number of respondents…", "one group diverges in noting…") rather than presenting them as equivalent to dominant findings. Minority views that are qualitatively distinct — even if infrequent — deserve a sentence, not suppression.

Segment differences (when a grouping variable is present)
Go beyond count differences. Where a segment diverges, characterise what makes its signal different based on comment content, not just that the numbers differ. If patterns are broadly similar across segments, state so and explain why the data does not support a strong differentiation.

Counts
Use counts exactly as provided in the JSON. Never estimate or recount.

Quotes (when a representative-quotes section is requested)
Select quotes that best illustrate the dominant pattern first. Include at least one quote representing a significant minority or contrasting view if one exists. Quotes must be verbatim. Do not include comment IDs — select the most illustrative text only.
"""


def _default_executive_prompt() -> str:
    """The original executive summary prompt, verbatim."""
    return """You are an expert academic evaluator synthesizing formative feedback.

Task
You will receive a set of completed individual aspect summaries. Synthesize them into a single analytical document with two parts: an executive summary and one section per aspect. Do not produce a summary table — that is rendered separately as a data visualization.

Part 1: Executive summary
- Two paragraphs only.
- Paragraph 1: Identify the dominant cross-cutting finding. Name what works and what does not, and characterise the underlying structural dynamic in your own analytical terms. Do not list aspects mechanically. Distinguish clearly between findings that are robust (appearing across multiple aspects and segments) and those that are tentative (isolated to one or two aspects or low comment volume).
- Paragraph 2: Reframe the finding practically — what respondents demonstrably value and what structural changes would make that value more accessible. Close with a sentence naming the dominant general finding.

Part 2: Per-aspect sections
- One section per aspect.
- Header: The aspect name (bold, sentence case).
- Body: 2–3 paragraphs of continuous prose per aspect. No bullets, no lists, no sub-headings.
- Paragraph 1: State the dominant finding with appropriate evidential weight. Where useful, open with negation framing — what the pattern is not — before stating what it is. If the aspect has low comment volume, flag this explicitly before interpreting the pattern.
- Paragraph 2: Introduce the contrasting or minority evidence. Give genuine weight to the less-represented polarity; do not flatten unequal evidence into artificial balance. If the contrasting signal is genuinely weak, say so — do not inflate it.
- Paragraph 3 (optional): Synthesise the tension into a single analytical statement with a forward-looking close.
- Constraints: Use analytical framing throughout ("the dominant pattern", "the main tension", "the implication is", "a minority of responses suggests"). Do not quote respondents directly. Do not reproduce counts, tables, or comment IDs. Target 150–220 words per section.

Evidence weight
For each finding, your language must reflect its evidential strength:
- Robust findings (cross-segment, substantial comment share): state confidently using "the dominant pattern", "consistently across segments", "the prevailing concern".
- Tentative findings (single segment, small comment share): use hedged language: "a smaller number of responses suggests", "one segment in particular notes", "tentatively".
Never present a robust finding and a tentative finding with equivalent rhetorical force.

Style Constraints
- Continuous prose throughout.
- Analytical academic register — qualitative research report, not consulting deliverable.
- No em dashes. No filler phrases ("it is worth noting", "delve into", "it is important to highlight").
- No promotional language.
- The document interprets the summaries; it does not passively report or paraphrase them.
"""


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
        "prompts": {
            "per_aspect_system": _default_per_aspect_prompt(),
            "executive_system": _default_executive_prompt(),
            "aspect_overrides": {},
        },
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

    # prompts: object with required global + executive, optional aspect_overrides
    pr = p.get("prompts", {})
    assert isinstance(pr, dict), "prompts must be object"
    assert "per_aspect_system" in pr and isinstance(pr["per_aspect_system"], str), \
        "prompts.per_aspect_system required (string)"
    assert "executive_system" in pr and isinstance(pr["executive_system"], str), \
        "prompts.executive_system required (string)"
    overrides = pr.get("aspect_overrides", {})
    if overrides is not None:
        assert isinstance(overrides, dict), "prompts.aspect_overrides must be object"
        for k, v in overrides.items():
            assert isinstance(k, str) and isinstance(v, str), \
                "prompts.aspect_overrides must be {aspect_key: string}"

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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


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