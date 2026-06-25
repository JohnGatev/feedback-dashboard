# Feedback Dashboard

A modular, profile-driven Streamlit app for analyzing "select-aspect + free-text"
feedback surveys (Qualtrics course evaluations, department meeting feedback, etc.).
Generalized from the [uva-course-evaluation-dashboard](https://github.com/JohnGatev/uva-course-evaluation-dashboard)
so a single config drives aspects, grouping, prompts, and output sections.

## What it does

- **Auto-detects** aspects, delimiter, and grouping variable from a Qualtrics CSV header.
- **Profile-driven**: one JSON profile describes the survey shape (aspects, polarity,
  grouping, prompts, output sections, model endpoint). No hardcoded aspect lists.
- **Local-first**: each user picks a working directory; all data stays on their machine.
- **Shareable packages**: export a completed analysis as a `.zip`; a colleague imports it
  and it appears in their analysis list. Profiles export/import as single JSON files.
- **Grouping optional**: when a survey has no grouping variable, group-level sections and
  charts are suppressed automatically. One flag in the profile, no branch sprawl.
- **Editable prompts**: the per-aspect and executive system prompts live in the profile
  and are editable in the dashboard. Structural section blocks are appended based on the
  `output_sections` list, so the house style (voice) is user-controlled while the
  document contract (what sections to produce) stays consistent.

## Install

```bash
pip install -r requirements.txt
streamlit run app.py
```

First launch: pick a working directory in the **Setup** tab. The app creates
`profiles/`, `analyses/`, and `kb/` under it.

## Profile schema

```json
{
  "name": "Department meeting feedback",
  "delimiter": "auto",
  "header_rows_to_skip": 2,
  "grouping": { "column": "Q1_Team", "display_name": "Team", "label_template": "Team {g}" },
  "grouping": null,
  "polarity": [
    { "key": "tip", "display": "Tips", "selection_column": "Q2_Tips",
      "color": "#bc0031", "explain_prefix": "Q3_Tips_explained" },
    { "key": "top", "display": "Tops", "selection_column": "Q4_Tops",
      "color": "#66bb6a", "explain_prefix": "Q5_Tops_explained" }
  ],
  "aspects": [
    { "display_label": "The location", "aspect_key": "the_location",
      "columns": { "tip": "Q3_Tips_explained_1", "top": "Q5_Tops_explained_1" } }
  ],
  "output_sections": ["counts", "group_counts_table", "group_differences",
                      "integrated_summary", "tensions", "representative_quotes"],
  "prompts": { "per_aspect_system": "...", "executive_system": "..." },
  "kb_files": ["kb/kb_input_contract_minimal.txt"],
  "model": { "endpoint": "...", "name": "gpt-oss-120b", "temperature": 0.3, "max_tokens": 32768 }
}
```

`grouping: null` → comments land in one `"all"` bucket; `group_counts_table` and
`group_differences` are dropped from `output_sections` and the prompts/UI adapt.

## Layout

```
profile.py     schema, validation, load/save
detect.py      auto-detect aspects/delimiter/grouping from a CSV
pipeline.py    csv_to_json + per-aspect summaries + executive summary
package.py     export/import analysis zips and profile JSON
app.py         Streamlit UI: Setup, Profiles, Run, Explore, Dashboard
kb/            knowledge-base files referenced by profiles (relative paths)
```

## Run flow

1. **Setup** — pick a working directory; import a shared package if you have one.
2. **Profiles** — edit or create a profile (aspects, grouping, prompts, sections).
3. **Run** — upload a CSV, review detected aspects, edit grouping, inherit prompts from a profile, run the pipeline.
4. **Explore** — filter by aspect/polarity/segment, read summaries, browse quotes.
5. **Dashboard** — executive summary, volume/positivity charts, PDF export, package export.

## Self-checks

```bash
python3 profile.py     # schema validation
python3 detect.py <csv_path>   # aspect detection on a real CSV
python3 pipeline.py <csv_path> <out_dir>   # CSV -> aspect JSON
python3 package.py     # profile export/import round-trip
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (already done if you cloned it).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub,
   pick this repo, branch `main`, file `app.py`.
3. Click **Deploy**. You get a public URL.

On Streamlit Cloud the app runs in **session mode**: each browser gets an
isolated scratch folder under `/tmp/feedback-dashboard-sessions/<key>/`. This
means:

- **Concurrent users don't collide** — each sees only their own analyses.
- **Nothing persists across container restarts** — the `/tmp` scratch is
  ephemeral. Export your analyses as **package (.zip)** from the Dashboard tab
  to keep results, or share them with colleagues who import via Setup.
- The bundled `kb/` files are auto-copied into each session on first load, so
  profiles that reference `kb/...` resolve out of the box.

To run locally with persistent storage instead, just `streamlit run app.py`
and pick a working directory in the Setup tab.