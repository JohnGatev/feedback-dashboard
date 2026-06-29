# Feedback Dashboard

A Streamlit app for analyzing "select-aspect + free-text" feedback surveys
(Qualtrics course evaluations, department meeting feedback, etc.). Upload a
CSV, auto-detect aspects, run LLM-powered summaries, and export the result
as a PDF or shareable .zip package.

Generalized from the
[uva-course-evaluation-dashboard](https://github.com/JohnGatev/uva-course-evaluation-dashboard).

## What it does

- **Auto-detects** aspects, delimiter, polarity, and grouping variable from a
  Qualtrics 3-row CSV header.
- **Session-only**: no database, no local storage, no setup page. Each browser
  session is isolated; the only persistence is the .zip you export.
- **Shareable packages**: export a completed analysis as a `.zip`; a colleague
  imports it on the Start page to view it immediately.
- **Grouping optional**: when a survey has no grouping variable, group-level
  sections and charts are suppressed automatically.
- **Editable prompts**: the default analytical and executive prompts ship with
  the app and can be extended with a natural-language "focus directive" that is
  appended (never replacing) to the defaults.
- **PDF export**: generates a PDF with KPIs, executive summary, per-aspect
  narratives, embedded charts, and representative quotes.

## Install

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Pages

| Page | Purpose |
|------|---------|
| **Start** | Import a previously exported .zip package to view it. |
| **Run** | Upload a Qualtrics CSV, review detected aspects, configure model and prompts, run the pipeline. Export the result as .zip. |
| **Explore** | Filter summaries and quotes by aspect, polarity, and segment. KPI tiles, aspect summaries, quote explorer. |
| **Dashboard** | Executive summary, volume and positivity charts, PDF and .zip export. |

## File layout

```
app.py         Streamlit UI: Start, Run, Explore, Dashboard
profile.py     profile schema, validation, default prompts
detect.py      auto-detect aspects/delimiter/grouping from a CSV
pipeline.py    csv_to_json + per-aspect summaries + executive summary
package.py     export/import analysis .zip packages
kb/            knowledge-base files (optional, referenced by profiles)
.streamlit/    Streamlit config
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub,
   pick this repo, branch `main`, file `app.py`.
3. Click **Deploy**.

Nothing persists across container restarts. Export your analyses as .zip from
the Run or Dashboard page to keep results.

## Self-checks

```bash
python3 profile.py     # schema validation
python3 package.py     # zip round-trip
```