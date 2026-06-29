from __future__ import annotations

import glob
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import package as pkg
import pipeline
from detect import detect
from profile import (
    default_profile,
    load as load_profile,
    save as save_profile,
    slugify,
    validate,
)

st.set_page_config(page_title="Feedback Dashboard", layout="wide", page_icon="📋")

# --- Styling ---
st.markdown("""
<style>
p, li, h1, h2, h3, h4, h5, h6, label,
input[type="text"], textarea,
[data-testid="stText"], [data-testid="stCaption"] {
    font-family: 'Source Sans 3', 'Source Sans Pro', Arial, sans-serif !important;
}
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"],
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
input[type="text"], textarea { border-radius: 4px !important; }
section[data-testid="stSidebar"] {
    background-color: #1B1918 !important;
    border-right: 4px solid #bc0031 !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] .stMarkdown * { color: #ffffff !important; }
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background-color: #2c2827 !important; border-color: #A8A29F !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #fff !important; }
section[data-testid="stSidebar"] hr { border-color: #bc0031 !important; opacity: 0.6 !important; }
section[data-testid="stSidebar"] .stFormSubmitButton > button,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    background-color: #bc0031 !important; color: white !important; border: none !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background-color: #2c2827 !important; border-color: #A8A29F !important;
}
h1 { color: #bc0031 !important; border-bottom: 3px solid #bc0031 !important;
     padding-bottom: 8px !important; font-weight: 700 !important; }
h2, h3 { color: #1B1918 !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { color: #bc0031 !important; font-weight: 700 !important; }
[data-testid="stMetric"] { border-left: 3px solid #bc0031 !important; padding-left: 10px !important; }
.stButton > button { border: 2px solid #bc0031 !important; color: #bc0031 !important;
                     font-weight: 600 !important; background-color: white !important; }
.stButton > button:hover { background-color: #bc0031 !important; color: white !important; }
.stDownloadButton > button, .stFormSubmitButton > button {
    background-color: #bc0031 !important; color: white !important; border: none !important;
    font-weight: 600 !important;
}
.stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #bc0031 !important; }
.stTabs [data-baseweb="tab"] { font-weight: 600 !important; color: #1B1918 !important;
    border-bottom: 3px solid transparent !important; padding: 8px 16px !important; }
.stTabs [aria-selected="true"] { color: #bc0031 !important;
    border-bottom: 3px solid #bc0031 !important; }
hr { border-color: #bc0031 !important; opacity: 0.35 !important; }
.stAlert { border-left-width: 4px !important; }
.stDataFrame { border: 1px solid #D7D6D4 !important; }
</style>
""", unsafe_allow_html=True)


# --- Session-state active analysis ---
# st.session_state["active"] = {
#   "meta": {id, filename, date, profile_name},
#   "profile": <profile dict>,
#   "aspect_data": {aspect_key: <JSON Outputs shape>},
#   "md_sections": {aspect_key: {section: text}},
#   "executive_md": <string>,
#   "run_dir": <temp dir path or None>,   # kept only for in-session export
# }

def _nonempty_aspects(aspect_data: dict, pol: list) -> dict:
    """Return only aspects with at least one non-empty comment across polarities."""
    return {k: d for k, d in aspect_data.items()
            if sum(d.get("counts", {}).get(x["key"] + "_comment_count", 0) for x in pol) > 0}


def _load_analysis_from_dir(analysis_dir: str) -> dict | None:
    """Read a temp analysis dir into the session-state shape."""
    json_dir = os.path.join(analysis_dir, "JSON Outputs")
    md_dir = os.path.join(analysis_dir, "Markdown Summaries")
    if not os.path.isdir(json_dir):
        return None
    aspect_data = {}
    for f in glob.glob(os.path.join(json_dir, "*.json")):
        with open(f) as fh:
            d = json.load(fh)
        aspect_data[d["aspect"]["aspect_key"]] = d
    md_sections = {}
    for f in glob.glob(os.path.join(md_dir, "*_summary.md")):
        k = os.path.basename(f).replace("_summary.md", "")
        with open(f, encoding="utf-8") as fh:
            md_sections[k] = parse_md_sections(fh.read())
    exe_path = os.path.join(analysis_dir, "Executive_Summary.md")
    exec_md = ""
    if os.path.exists(exe_path):
        with open(exe_path, encoding="utf-8") as fh:
            exec_md = fh.read()
    meta = {}
    mp = os.path.join(analysis_dir, "meta.json")
    if os.path.exists(mp):
        with open(mp) as fh:
            meta = json.load(fh)
    prof = None
    pp = os.path.join(analysis_dir, "profile.json")
    if os.path.exists(pp):
        try:
            prof = load_profile(pp)
        except Exception:
            prof = None
    prof = prof or default_profile()
    # Drop aspects with zero comments from the in-memory views.
    # The on-disk JSON files (and thus the exported zip) are untouched.
    filtered = _nonempty_aspects(aspect_data, prof["polarity"])
    md_sections = {k: v for k, v in md_sections.items() if k in filtered}
    return {
        "meta": meta,
        "profile": prof,
        "aspect_data": filtered,
        "md_sections": md_sections,
        "executive_md": exec_md,
        "run_dir": analysis_dir,
    }


def parse_md_sections(md_text: str) -> dict:
    sections = {}
    current = None
    buf = []
    for line in md_text.split("\n"):
        m = re.match(r"^#{2,3}\s+(.+)", line)
        if m:
            if current:
                sections[current] = strip_ref_ids("\n".join(buf).strip())
            current = m.group(1).strip()
            buf = []
        elif current:
            buf.append(line)
    if current:
        sections[current] = strip_ref_ids("\n".join(buf).strip())
    return {k: v for k, v in sections.items()
            if not k.lower().startswith("aspect:") and k.lower() not in ("counts", "representative quotes")}


def strip_ref_ids(text: str) -> str:
    text = re.sub(r"\[r\d+_[a-z]+_[a-z_]+_\d+\]", "", text)
    text = re.sub(r"\br\d+_[a-z]+_[a-z_]+_\d+", "", text)
    text = re.sub(r"\(\s*;", "(", text)
    text = re.sub(r";\s*\)", ")", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def sort_segments(segs):
    def key(g):
        try:
            return (0, int(g))
        except ValueError:
            return (1, g)
    return sorted(segs, key=key)


# --- PDF builder (defined before page dispatch so it is bound at call time) ---

def build_pdf(active: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    Table, TableStyle, PageBreak)
    from reportlab.platypus.flowables import HRFlowable
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    profile = active["profile"]
    aspect_data = active["aspect_data"]
    md_sections = active.get("md_sections", {})
    meta = active.get("meta", {})
    exec_md = active.get("executive_md", "")
    pol = profile["polarity"]
    grouping = profile.get("grouping")
    seg_tmpl = grouping["label_template"] if grouping else "{g}"

    buf = io.BytesIO()
    page_w, _ = A4
    margin = 2.5 * cm
    content_w = page_w - 2 * margin
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=2 * cm, bottomMargin=2.5 * cm,
                            title="Feedback Analysis")
    ACCENT = colors.HexColor("#bc0031")
    BLACK = colors.HexColor("#1B1918")
    GREY1 = colors.HexColor("#D7D6D4")
    GREY2 = colors.HexColor("#F5F5F3")
    ss = getSampleStyleSheet()
    S = {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                             fontSize=20, spaceBefore=22, spaceAfter=10, textColor=ACCENT),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=13, spaceBefore=14, spaceAfter=6, textColor=BLACK),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                             fontSize=11, spaceBefore=10, spaceAfter=4, textColor=BLACK),
        "body": ParagraphStyle("body", parent=ss["Normal"], fontName="Times-Roman",
                               fontSize=10, leading=15, spaceAfter=6, textColor=BLACK),
        "bullet": ParagraphStyle("bul", parent=ss["Normal"], fontName="Times-Roman",
                                 fontSize=10, leading=14, leftIndent=14, spaceAfter=3, textColor=BLACK),
        "cover_title": ParagraphStyle("ct", parent=ss["Title"], fontName="Helvetica-Bold",
                                      fontSize=28, alignment=0, spaceAfter=10, textColor=BLACK),
    }

    def _esc(t):
        for src, dst in {"—": "--", "–": "-", "“": '"', "”": '"', "‘": "'", "’": "'",
                         "…": "...", "•": "-"}.items():
            t = t.replace(src, dst)
        t = "".join(c if ord(c) < 256 else "-" for c in t)
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _md(t):
        t = _esc(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        return t

    def _render(text, story):
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                story.append(Spacer(1, 0.1 * cm)); continue
            if s.startswith("- ") or s.startswith("* "):
                story.append(Paragraph("• " + _md(s[2:]), S["bullet"]))
            elif s.startswith("**") and s.endswith("**") and len(s) > 4:
                story.append(Paragraph(_md(s), S["h3"]))
            else:
                story.append(Paragraph(_md(s), S["body"]))

    def _img(fig, w, h):
        b = io.BytesIO()
        fig.savefig(b, format="png", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig); b.seek(0)
        return Image(b, width=w * cm, height=h * cm)

    story = []
    # Cover
    red = Table([["  "]], colWidths=[content_w], rowHeights=[0.6 * cm])
    red.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story += [red, Spacer(1, 4 * cm), Paragraph("Feedback Analysis", S["cover_title"])]
    if meta.get("filename"):
        story.append(Paragraph(_esc(meta.get("filename", "")),
                               ParagraphStyle("cs", parent=ss["Normal"], fontSize=13, textColor=BLACK)))
    if meta.get("date"):
        story.append(Paragraph(_esc(str(meta.get("date", ""))[:10]),
                               ParagraphStyle("cd", parent=ss["Normal"], fontSize=9, textColor=GREY1)))
    story.append(PageBreak())

    # Executive
    if exec_md:
        em = re.sub(r"\n\|[^\n]+", "", exec_md)
        story += [Paragraph("Executive Summary", S["h1"]),
                  HRFlowable(width=content_w, thickness=2, color=ACCENT), Spacer(1, 0.3 * cm)]
        for line in em.split("\n"):
            s = line.strip()
            if not s or s.startswith("|") or s.startswith("---"):
                continue
            if s.startswith("## "):
                story.append(Paragraph(_md(s[3:]), S["h2"]))
            elif s.startswith("### "):
                story.append(Paragraph(_md(s[4:]), S["h3"]))
            else:
                story.append(Paragraph(_md(s), S["body"]))
    story.append(PageBreak())

    # Per-aspect
    for k in sorted(aspect_data):
        d = aspect_data[k]
        display = d["aspect"]["display_name"]
        story += [PageBreak(), Paragraph(_esc(display), S["h1"]),
                  HRFlowable(width=content_w, thickness=2, color=ACCENT), Spacer(1, 0.3 * cm)]

        # Narrative sections (from md_sections, same lookup as Explore tab)
        secs = {sk.lower(): sv for sk, sv in md_sections.get(k, {}).items()}
        themes = next((secs[sk] for sk in ("summary", "integrated summary")
                       if sk in secs and secs[sk]), None)
        if themes:
            story.append(Paragraph("Summary", S["h2"]))
            _render(themes, story)

        gd = secs.get("segment differences", "") or secs.get("group differences", "")
        if gd and grouping:
            story.append(Paragraph("Segment differences", S["h2"]))
            _render(gd, story)

        ten = secs.get("key tensions / mixed signals", "")
        if ten:
            story.append(Paragraph("Key tensions", S["h2"]))
            _render(ten, story)

        # Counts by segment table
        if grouping:
            all_segs = sort_segments(set().union(*[d.get(f"{x['key']}_by_segment", {}).keys() for x in pol]))
            header = [grouping["display_name"]] + [x["display"] for x in pol] + ["Total"]
            rows_t = []
            for seg in all_segs:
                vals = [d.get(f"{x['key']}_by_segment", {}).get(seg, {}).get("comment_count", 0) for x in pol]
                rows_t.append([seg_tmpl.format(g=seg)] + [str(v) for v in vals] + [str(sum(vals))])
            tbl = Table([header] + rows_t, colWidths=[5 * cm] + [2.5 * cm] * (len(pol) + 1))
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY2]),
                ("GRID", (0, 0), (-1, -1), 0.5, GREY1),
            ]))
            story += [Spacer(1, 0.4 * cm), Paragraph("Counts by segment", S["h2"]),
                     Spacer(1, 0.15 * cm), tbl]

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# --- Run-tab constants ---

_SECTION_TOGGLES = [
    {"key": "counts", "label": "Comment counts",
     "help": "Show total Tips and Tops counts at the top of each aspect "
             "summary. Drop this if you only want narrative."},
    {"key": "group_counts_table", "label": "Per-segment counts table",
     "help": "A markdown table breaking down comment counts by segment "
             "(team/group). Only available when grouping is on."},
    {"key": "group_differences", "label": "Segment differences",
     "help": "A section characterising how segments differ in their comment "
             "content, beyond just counts. Only when grouping is on."},
    {"key": "integrated_summary", "label": "Integrated narrative summary",
     "help": "The core 4-7 theme narrative, weighted by prevalence, "
             "integrating Tips and Tops. The analytical heart of each aspect."},
    {"key": "tensions", "label": "Key tensions / mixed signals",
     "help": "Name the main within-aspect splits and which side has more "
             "evidential support. Drop if you don't want conflict framing."},
    {"key": "representative_quotes", "label": "Representative quotes",
     "help": "Up to 6 verbatim quotes per polarity, leading with the dominant "
             "pattern and including a minority voice. Drop for pure narrative."},
]
_GROUP_ONLY_KEYS = {"group_counts_table", "group_differences"}


# --- Sidebar nav ---

st.sidebar.markdown(
    '<div style="font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:4px;">Feedback Dashboard</div>',
    unsafe_allow_html=True)
page = st.sidebar.radio("Navigate", ["Start", "Run", "Explore", "Dashboard"])

active = st.session_state.get("active")
if active:
    st.sidebar.divider()
    st.sidebar.markdown("**Active analysis**")
    m = active.get("meta", {})
    st.sidebar.caption(f"{m.get('filename', '—')} · {str(m.get('date', ''))[:10]}")
    if st.sidebar.button("Clear", use_container_width=True):
        rd = active.get("run_dir")
        if rd and os.path.isdir(rd) and rd.startswith(tempfile.gettempdir()):
            shutil.rmtree(rd, ignore_errors=True)
        st.session_state.pop("active", None)
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 1) START
# ─────────────────────────────────────────────────────────────────────────────
if page == "Start":
    st.title("Start")
    st.caption("Import a previously exported analysis package (.zip) to view it, "
               "or go to Run to create a new analysis from a CSV.")
    st.markdown("""
**How it works**

1. **Run** — upload a Qualtrics CSV, detect aspects, define your comparison, run the pipeline.
2. **Explore** — filter summaries and quotes by aspect, polarity, and segment.
3. **Dashboard** — charts, executive summary, PDF export.
4. **Export** — download the finished analysis as a `.zip` package.
5. **Share** — send the package to a colleague. They open this app, come here, and import it.

Nothing is stored on a server. Each session lives in your browser; the only
persistence is the `.zip` you export.
""")
    st.divider()
    st.subheader("Import a package")
    with st.form("import_form"):
        up = st.file_uploader("Analysis package (.zip)", type=["zip"])
        submitted = st.form_submit_button("Import package")
    if submitted and up is not None:
        with st.spinner("Unpacking…"):
            tmp = pkg.unpack_analysis(up.getvalue())
            loaded = _load_analysis_from_dir(tmp)
        if loaded and loaded["aspect_data"]:
            st.session_state["active"] = loaded
            st.success(f"Imported: {loaded['meta'].get('filename', up.name)}")
            st.rerun()
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            st.error("No aspect data found in this package. Check the file.")


# ─────────────────────────────────────────────────────────────────────────────
# 2) RUN
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Run":
    st.title("Run an analysis")
    st.caption("Upload a Qualtrics CSV. Aspects and grouping are auto-detected; "
               "review them, define what you want to compare in natural language, "
               "generate prompts, and run. Nothing is saved — export the result as "
               "a package when done.")

    with st.form("csv_upload_form"):
        up = st.file_uploader("Qualtrics CSV", type=["csv"])
        submitted = st.form_submit_button("Upload CSV")
    if up is None:
        st.info("Select a CSV file and click **Upload CSV** to begin.")
        st.stop()

    # Read uploaded bytes once; pass in-memory to detect + pipeline.
    csv_bytes = up.getvalue()

    det = detect(csv_bytes)
    st.success(f"Detected: delimiter `{det['delimiter']}`, "
               f"{len(det['aspects'])} aspects, "
               f"grouping: {det['grouping']['column'] if det['grouping'] else 'none'}")

    # ── Detected Aspects ──
    with st.expander("Detected Aspects", expanded=True):
        keep = []
        for i, a in enumerate(det["aspects"]):
            cols = st.columns([1, 9])
            with cols[0]:
                inc = st.checkbox("", value=True, key=f"inc{i}")
            with cols[1]:
                a["display_label"] = st.text_input(
                    "Label", value=a["display_label"].capitalize(), key=f"dl{i}",
                    label_visibility="collapsed")
            if inc:
                keep.append(a)
        det["aspects"] = keep
        if not det["aspects"]:
            st.warning("No aspects selected. Tick at least one to run.")

    # ── Grouping ──
    with st.expander("Grouping", expanded=False):
        st.caption("Grouping splits comments by a survey variable (e.g. team, "
                   "tutorial group). When enabled, the analysis shows per-segment "
                   "counts, differences, and a heatmap. Leave disabled if your "
                   "survey has no such variable.")
        has_g = st.checkbox("Use grouping/segment variable",
                            value=det["grouping"] is not None)
        if has_g:
            g = det["grouping"] or {}
            g["column"] = st.text_input(
                "Grouping column code", g.get("column", ""),
                help="The Qualtrics column ID (e.g. Q1_Team) that holds each "
                     "respondent's segment value. Must match the CSV header code exactly.")
            g["display_name"] = st.text_input(
                "Display name", g.get("display_name", "Group"),
                help="Human-readable label shown in charts, tables, and filters "
                     "(e.g. 'Team').")
            g["label_template"] = st.text_input(
                "Label template", g.get("label_template", "Group {g}"),
                help="How individual segment labels appear in the UI. Use {g} for "
                     "the value, e.g. 'Team {g}' becomes 'Team PC&J'.")
            det["grouping"] = g
        else:
            det["grouping"] = None

    # ── Model & API key ──
    with st.expander("Model", expanded=True):
        api_key = st.text_input("API key", type="password",
                                help="Your LLM proxy API key. Used to fetch "
                                     "available models and to run the analysis.")
        KNOWN_ENDPOINTS = [
            "https://llmproxy.uva.nl/chat/completions",
            "https://ai-research-proxy.azurewebsites.net/v1/chat/completions",
            "Custom…",
        ]
        endpoint_sel = st.selectbox("Endpoint", KNOWN_ENDPOINTS,
                                    help="The chat-completions URL of your LLM proxy.")
        if endpoint_sel == "Custom…":
            endpoint = st.text_input("Custom endpoint URL", "")
        else:
            endpoint = endpoint_sel

        if "fb_models" not in st.session_state:
            st.session_state["fb_models"] = []
        c_fetch, _ = st.columns([1, 4])
        with c_fetch:
            if st.button("Fetch available models"):
                if not api_key or not endpoint:
                    st.error("Enter an API key and endpoint first.")
                else:
                    try:
                        with st.spinner("Fetching models…"):
                            st.session_state["fb_models"] = pipeline.fetch_models(endpoint, api_key)
                        st.success(f"Found {len(st.session_state['fb_models'])} models.")
                    except Exception as e:
                        st.session_state["fb_models"] = []
                        st.error(f"API key error: could not retrieve models. "
                                 f"Check your key and endpoint. ({e})")
        model_ids = st.session_state.get("fb_models", [])
        if model_ids:
            model_name = st.selectbox("Model", model_ids)
        else:
            model_name = None
            st.caption("No models loaded yet. Enter your API key and click "
                       "“Fetch available models”.")

    # ── Analysis Instructions ──
    _dp = default_profile()
    _default_aspect_prompt = _dp["prompts"]["per_aspect_system"]
    _default_exec_prompt = _dp["prompts"]["executive_system"]

    with st.expander("Analysis Instructions", expanded=True):
        # --- Output sections as toggles ---
        st.subheader("Sections to include in each aspect summary")
        st.caption("Toggle which structural sections each aspect summary contains. "
                   "Group-only sections are hidden when grouping is disabled.")
        if "fb_sections" not in st.session_state:
            st.session_state["fb_sections"] = {}
        secs = []
        for t in _SECTION_TOGGLES:
            if t["key"] in _GROUP_ONLY_KEYS and det["grouping"] is None:
                continue
            default_on = t["key"] in _dp["output_sections"]
            cur = st.session_state["fb_sections"].get(t["key"], default_on)
            on = st.toggle(t["label"], value=cur, help=t["help"], key=f"tog_{t['key']}")
            st.session_state["fb_sections"][t["key"]] = on
            if on:
                secs.append(t["key"])

        # --- Aspect comparison mode ---
        st.markdown("---")
        st.subheader("How should aspects be compared?")
        mode = st.radio(
            "Comparison mode",
            ["Broad narrative (default)", "Custom focus"],
            horizontal=True,
            help="Broad uses the shipped analytical prompt (prevalence language, "
                 "minority-view handling, grounding rules). Custom lets you add a "
                 "focus directive in natural language that is appended to the default.",
            label_visibility="collapsed")

        with st.expander("View default aspect prompt", expanded=False):
            st.text(_default_aspect_prompt)

        if mode == "Broad narrative (default)":
            pa = _default_aspect_prompt
            st.caption("Using the default analytical prompt. Switch to Custom focus "
                       "to add a specific comparison lens.")
        else:
            st.caption("Describe what you want to compare in natural language. "
                       "Click Generate to turn it into a focus directive that is "
                       "appended to the default prompt. Edit the combined text below.")
            focus_intent = st.text_area(
                "What do you want to compare or analyze?", height=80,
                placeholder="e.g. Compare how different teams perceive the formality "
                           "of the meeting and whether it feels relevant to their role.")
            if "fb_focus" not in st.session_state:
                st.session_state["fb_focus"] = ""
            c_gen, _ = st.columns([1, 4])
            with c_gen:
                if st.button("Generate focus directive"):
                    if not api_key or not model_name:
                        st.error("Enter an API key and select a model first.")
                    elif not focus_intent.strip():
                        st.error("Describe what you want to analyze first.")
                    else:
                        try:
                            with st.spinner("Generating focus directive…"):
                                tmp_prof = default_profile()
                                tmp_prof["model"]["endpoint"] = endpoint
                                tmp_prof["model"]["name"] = model_name
                                st.session_state["fb_focus"] = \
                                    pipeline.generate_prompt_from_description(
                                        tmp_prof, focus_intent, api_key)
                            st.success("Focus directive generated. Review below.")
                        except Exception as e:
                            st.error(f"Generation failed: {e}")
            focus_text = st.session_state["fb_focus"]
            if focus_text.strip():
                pa = f"{_default_aspect_prompt}\n\n=== FOCUS FOR THIS ANALYSIS ===\n{focus_text}"
            else:
                pa = _default_aspect_prompt
            pa = st.text_area(
                "Per-aspect system prompt (default + focus, editable)",
                value=pa, height=220,
                help="The default analytical prompt with your focus directive "
                     "appended. Edit freely. Structural sections (counts, tables, "
                     "quotes) are appended automatically at run time based on the "
                     "toggles above.")

            # --- Scope the custom focus to specific aspects (optional) ---
            if det["aspects"]:
                st.markdown("**Apply custom focus to which aspects?**")
                st.caption("Selected aspects use the prompt above. Unselected "
                           "aspects fall back to the broad default. Leave all "
                           "selected to apply it everywhere.")
                aspect_labels = {a["aspect_key"]: a["display_label"] for a in det["aspects"]}
                scoped_keys = st.multiselect(
                    "Aspects with custom focus",
                    options=list(aspect_labels.keys()),
                    default=list(aspect_labels.keys()),
                    format_func=lambda k: aspect_labels[k])
                if "fb_overrides" not in st.session_state:
                    st.session_state["fb_overrides"] = {}
                st.session_state["fb_overrides"] = {}
                for a in det["aspects"]:
                    if a["aspect_key"] not in scoped_keys:
                        st.session_state["fb_overrides"][a["aspect_key"]] = _default_aspect_prompt

        st.markdown("---")
        st.subheader("Executive summary")
        with st.expander("View default executive prompt", expanded=False):
            st.text(_default_exec_prompt)
        exec_mode = st.radio(
            "Executive mode",
            ["Default (two-part synthesis)", "Custom focus"],
            horizontal=True,
            label_visibility="collapsed")
        if exec_mode == "Default (two-part synthesis)":
            ex = _default_exec_prompt
            st.caption("Using the default executive prompt: two-paragraph executive "
                       "summary + per-aspect narrative prose, analytical register, "
                       "no em dashes.")
        else:
            st.caption("Describe what the executive summary should focus on. "
                       "The generated directive is appended to the default.")
            exec_intent = st.text_area(
                "What should the executive summary focus on?", height=70,
                placeholder="e.g. Highlight cross-cutting findings and identify "
                           "which aspects are robust vs tentative.")
            if "fb_exec_focus" not in st.session_state:
                st.session_state["fb_exec_focus"] = ""
            c_gen_e, _ = st.columns([1, 4])
            with c_gen_e:
                if st.button("Generate executive focus"):
                    if not api_key or not model_name:
                        st.error("Enter an API key and select a model first.")
                    elif not exec_intent.strip():
                        st.error("Describe the executive summary focus first.")
                    else:
                        try:
                            with st.spinner("Generating…"):
                                tmp_prof = default_profile()
                                tmp_prof["model"]["endpoint"] = endpoint
                                tmp_prof["model"]["name"] = model_name
                                st.session_state["fb_exec_focus"] = \
                                    pipeline.generate_prompt_from_description(
                                        tmp_prof, exec_intent, api_key)
                            st.success("Executive focus generated. Review below.")
                        except Exception as e:
                            st.error(f"Generation failed: {e}")
            exec_focus = st.session_state["fb_exec_focus"]
            if exec_focus.strip():
                ex = f"{_default_exec_prompt}\n\n=== FOCUS FOR THIS ANALYSIS ===\n{exec_focus}"
            else:
                ex = _default_exec_prompt
            ex = st.text_area("Executive summary instructions (default + focus, editable)",
                              value=ex, height=200)

    # ── Run ──
    st.divider()
    run_name = st.text_input("Name this analysis", value=up.name.replace(".csv", ""))
    can_run = bool(det["aspects"] and api_key and model_name and endpoint
                   and pa.strip() and ex.strip())
    if not can_run:
        st.caption("Complete the steps above (aspects, model, prompts) before running.")
    if st.button("Run pipeline", type="primary", disabled=not can_run):
        p = default_profile()
        p["name"] = run_name
        p["delimiter"] = det["delimiter"]
        p["header_rows_to_skip"] = 2
        p["grouping"] = det["grouping"]
        p["polarity"] = det["polarity"]
        p["aspects"] = det["aspects"]
        p["output_sections"] = secs
        p["prompts"]["per_aspect_system"] = pa
        p["prompts"]["executive_system"] = ex
        p["prompts"]["aspect_overrides"] = dict(st.session_state.get("fb_overrides", {}))
        p["model"]["endpoint"] = endpoint
        p["model"]["name"] = model_name
        try:
            validate(p)
        except Exception as e:
            st.error(f"Profile invalid: {e}")
            st.stop()

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + slugify(run_name)
        run_dir = tempfile.mkdtemp(prefix="fbrun_")
        json_out = os.path.join(run_dir, "JSON Outputs")
        md_out = os.path.join(run_dir, "Markdown Summaries")

        msg = st.empty()
        msg.info("Step 1/3: Converting CSV to aspect JSONs...")
        try:
            pipeline.csv_to_json(p, csv_bytes, json_out)
        except Exception as e:
            st.error(f"Step 1 failed (CSV conversion): {e}")
            shutil.rmtree(run_dir, ignore_errors=True)
            st.stop()

        msg.info("Step 2/3: Generating aspect summaries (this can take a few minutes)...")
        try:
            pipeline.generate_aspect_summaries(p, json_out, md_out, api_key,
                                                base_dir=os.path.dirname(os.path.abspath(__file__)))
        except Exception as e:
            st.error(f"Step 2 failed (aspect summaries). Network or API error: {e}")
            shutil.rmtree(run_dir, ignore_errors=True)
            st.stop()

        msg.info("Step 3/3: Generating executive summary...")
        try:
            exe = os.path.join(run_dir, "Executive_Summary.md")
            pipeline.generate_executive_summary(p, md_out, exe, api_key)
        except Exception as e:
            st.error(f"Step 3 failed (executive summary). Network or API error: {e}")
            shutil.rmtree(run_dir, ignore_errors=True)
            st.stop()

        save_profile(p, os.path.join(run_dir, "profile.json"))
        with open(os.path.join(run_dir, up.name), "wb") as f:
            f.write(csv_bytes)
        with open(os.path.join(run_dir, "meta.json"), "w") as f:
            json.dump({"id": run_id, "filename": up.name,
                       "timestamp": run_id, "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "profile_name": p["name"]}, f, indent=2)

        st.session_state["active"] = _load_analysis_from_dir(run_dir)
        msg.success("Done. Go to Explore or Dashboard to view, or export the package below.")
        st.rerun()

    # Export after a run
    if active and active.get("run_dir"):
        st.divider()
        st.subheader("Export")
        if st.button("Export analysis package (.zip)"):
            z = pkg.export_analysis(active["run_dir"])
            fn = active.get("meta", {}).get("filename", "analysis").replace(".csv", "")
            st.download_button("Download package", z,
                               file_name=f"{slugify(fn)}.zip",
                               mime="application/zip")


# ─────────────────────────────────────────────────────────────────────────────
# 3) EXPLORE
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Explore":
    st.title("Feedback Explorer")
    if not active:
        st.warning("No analysis loaded. Run one or import a package on the Start page.")
        st.stop()
    p = active["profile"]
    aspect_data = active["aspect_data"]
    md_sections = active["md_sections"]
    if not aspect_data:
        st.info("No aspect data in this analysis.")
        st.stop()

    pol = p["polarity"]
    grouping = p.get("grouping")
    seg_label = grouping["display_name"] if grouping else "All"
    seg_tmpl = grouping["label_template"] if grouping else "{g}"

    all_segs = set()
    for d in aspect_data.values():
        for pk in [x["key"] for x in pol]:
            all_segs.update(d.get(f"{pk}_by_segment", {}).keys())

    _key_to_name = {k: d["aspect"]["display_name"] for k, d in aspect_data.items()}

    with st.sidebar:
        st.subheader("Filters")
        sel_aspect = st.selectbox("Aspect", ["All"] + sorted(aspect_data.keys()),
                                  format_func=lambda k: _key_to_name.get(k, k))
        sel_pol = st.selectbox("Polarity", ["All"] + [x["display"] for x in pol])
        if grouping:
            sel_seg = st.selectbox(seg_label, ["All"] + sort_segments(all_segs))
        else:
            sel_seg = "All"
        active_aspects = [sel_aspect] if sel_aspect != "All" else sorted(aspect_data.keys())
        active_segs = [sel_seg] if sel_seg != "All" else list(all_segs)

    # Metrics
    totals = {x["key"]: 0 for x in pol}
    for k in active_aspects:
        d = aspect_data[k]
        for seg in active_segs:
            for x in pol:
                totals[x["key"]] += d.get(f"{x['key']}_by_segment", {}).get(seg, {}).get("comment_count", 0)
    mcols = st.columns(len(pol) + 1)
    for i, x in enumerate(pol):
        mcols[i].metric(x["display"], totals[x["key"]])
    total = sum(totals.values())
    mcols[len(pol)].metric("Total comments", total)

    st.divider()
    st.subheader("Aspect summaries")
    TAB_LOOKUP = {
        "Themes": None,
        "Segment differences": "segment differences",
        "Group differences": "group differences",
        "Tensions": "key tensions / mixed signals",
    }
    for asp_key in active_aspects:
        display = aspect_data[asp_key]["aspect"]["display_name"]
        with st.expander(display, expanded=True):
            sections = md_sections.get(asp_key, {})
            lookup = {k.lower(): v for k, v in sections.items()}
            available = []
            for label, key in TAB_LOOKUP.items():
                if label == "Themes":
                    content = next((lookup[k] for k in ("summary", "integrated summary") if k in lookup and lookup[k]), None)
                else:
                    content = lookup.get(key, "")
                if content:
                    available.append((label, content))
            if available:
                tabs = st.tabs([t[0] for t in available])
                for tab, (_, content) in zip(tabs, available):
                    with tab:
                        st.markdown(content)
            else:
                st.info("No summary for this aspect.")

    st.divider()
    st.subheader("Quote explorer")
    quotes = []
    for k in active_aspects:
        d = aspect_data[k]
        display = d["aspect"]["display_name"]
        for x in pol:
            if sel_pol != "All" and sel_pol != x["display"]:
                continue
            for seg, sd in d.get(f"{x['key']}_by_segment", {}).items():
                if sel_seg != "All" and seg != sel_seg:
                    continue
                for c in sd["comments"]:
                    quotes.append({"aspect": display, "polarity": x["display"],
                                   "color": x["color"], "segment": seg, "text": c["text"]})
    if not quotes:
        st.info("No quotes match the current filters.")
    else:
        st.caption(f"{len(quotes)} quotes")
        for i in range(0, len(quotes), 2):
            cols = st.columns(2)
            for j, col in enumerate(cols):
                if i + j >= len(quotes):
                    break
                q = quotes[i + j]
                with col:
                    seg_badge = (f'<span style="background:#F5F5F3;color:#1B1918;padding:2px 8px;'
                                 f'font-size:0.7rem;font-weight:600;margin-left:5px;">'
                                 f'{seg_tmpl.format(g=q["segment"])}</span>') if grouping else ""
                    card = (
                        f'<div style="border-left:3px solid {q["color"]};'
                        f'border:1px solid #D7D6D4;padding:12px 14px;margin-bottom:8px;'
                        f'background:#fff;min-height:110px;">'
                        f'<div style="margin-bottom:8px;">'
                        f'<span style="background:{q["color"]};color:#fff;padding:2px 8px;'
                        f'font-size:0.7rem;font-weight:700;">{q["polarity"].upper()}</span>'
                        f'{seg_badge}'
                        f'<span style="color:#A8A29F;font-size:0.7rem;margin-left:8px;">{q["aspect"]}</span>'
                        f'</div><div style="font-size:0.9rem;color:#1B1918;line-height:1.55;">'
                        f'&ldquo;{q["text"]}&rdquo;</div></div>'
                    )
                    st.markdown(card, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 4) DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Dashboard":
    st.title("Dashboard")
    if not active:
        st.warning("No analysis loaded. Run one or import a package on the Start page.")
        st.stop()
    p = active["profile"]
    aspect_data = active["aspect_data"]
    pol = p["polarity"]
    grouping = p.get("grouping")
    seg_tmpl = grouping["label_template"] if grouping else "{g}"
    seg_label = grouping["display_name"] if grouping else "All"

    # Executive summary
    exec_md = active.get("executive_md", "")
    if exec_md:
        txt = re.sub(r"(\n\|[^\n]+)+", "", exec_md)
        st.markdown(txt)
    else:
        st.info("No executive summary.")

    st.divider()
    st.subheader("Volume")
    rows = []
    ga_rows = []
    for k, d in aspect_data.items():
        display = d["aspect"]["display_name"]
        for x in pol:
            cnt = d["counts"].get(x["key"] + "_comment_count", 0)
            rows.append({"Aspect": display, "Polarity": x["display"], "Count": cnt})
        if grouping:
            all_segs = set()
            for x in pol:
                all_segs.update(d.get(f"{x['key']}_by_segment", {}).keys())
            for seg in all_segs:
                rec = {"Segment": seg_tmpl.format(g=seg), "Aspect": display}
                for x in pol:
                    rec[x["display"]] = d.get(f"{x['key']}_by_segment", {}).get(seg, {}).get("comment_count", 0)
                ga_rows.append(rec)

    df = pd.DataFrame(rows)
    cmap = {x["display"]: x["color"] for x in pol}
    c1, c2 = st.columns(2)
    with c1:
        if not df.empty:
            fig = px.bar(df, x="Aspect", y="Count", color="Polarity", barmode="group",
                         color_discrete_map=cmap, title="By aspect",
                         labels={"Count": "Comments", "Aspect": ""})
            fig.update_layout(xaxis_tickangle=-30, legend_title="", margin=dict(t=40, b=100),
                              showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        if grouping and ga_rows:
            df_g = pd.DataFrame(ga_rows)
            df_g_long = df_g.melt(id_vars="Segment", value_vars=[x["display"] for x in pol],
                                  var_name="Polarity", value_name="Count")
            fig2 = px.bar(df_g_long, x="Segment", y="Count", color="Polarity", barmode="group",
                          color_discrete_map=cmap, title=f"By {seg_label}",
                          labels={"Count": "Comments", "Segment": ""})
            fig2.update_layout(legend_title="", margin=dict(t=40), showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Positivity")
    if len(pol) == 2:
        piv = df.pivot_table(index="Aspect", columns="Polarity", values="Count", fill_value=0).reset_index()
        for x in pol:
            if x["display"] not in piv.columns:
                piv[x["display"]] = 0
        piv["Total"] = piv[pol[0]["display"]] + piv[pol[1]["display"]]
        pos_key = next((x["display"] for x in pol if x["key"] == "top"), pol[1]["display"])
        piv["Positivity"] = piv[pos_key] / piv["Total"].replace(0, pd.NA)
        piv = piv.sort_values("Positivity")
        col3, col4 = st.columns(2)
        with col3:
            fig3 = px.bar(piv, x="Positivity", y="Aspect", orientation="h", color="Positivity",
                          color_continuous_scale="RdYlGn", range_color=[0, 1],
                          title="Aspect ranking", labels={"Positivity": f"% {pos_key}", "Aspect": ""},
                          text=piv["Positivity"])
            fig3.update_traces(texttemplate="%{text:.2%}", textposition="outside")
            fig3.update_xaxes(tickformat=".2%")
            fig3.update_layout(coloraxis_showscale=False, margin=dict(t=40, b=20),
                               showlegend=False)
            st.plotly_chart(fig3, use_container_width=True)
        with col4:
            if grouping and ga_rows:
                df_g = pd.DataFrame(ga_rows)
                df_g["Total"] = df_g[pol[0]["display"]] + df_g[pol[1]["display"]]
                df_g["Positivity"] = df_g[pos_key] / df_g["Total"].replace(0, pd.NA)
                heat = df_g.pivot_table(index="Aspect", columns="Segment", values="Positivity")
                n = len(heat)
                fig4 = px.imshow(heat, color_continuous_scale="RdYlGn", zmin=0, zmax=1,
                                 text_auto=".2%", title="Positivity — Aspect × Segment")
                fig4.update_layout(height=max(320, n * 55 + 80),
                                   margin=dict(t=50, b=20, l=10, r=10),
                                   coloraxis_showscale=False, xaxis=dict(side="bottom"))
                fig4.update_xaxes(tickangle=-30)
                st.plotly_chart(fig4, use_container_width=True)
            else:
                st.caption("Grouping not enabled for this analysis; heatmap skipped.")

    st.divider()
    st.subheader("Export")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        if st.button("Generate PDF report"):
            with st.spinner("Building PDF..."):
                try:
                    pdf_bytes = build_pdf(active)
                    fn = active.get("meta", {}).get("filename", "analysis").replace(".csv", "")
                    st.download_button("Download PDF", pdf_bytes,
                                       file_name=f"{slugify(fn)}.pdf",
                                       mime="application/pdf")
                except Exception as e:
                    st.error(f"PDF failed: {e}")
    with col_e2:
        if st.button("Export analysis package (.zip)"):
            rd = active.get("run_dir")
            if rd and os.path.isdir(rd):
                z = pkg.export_analysis(rd)
                fn = active.get("meta", {}).get("filename", "analysis").replace(".csv", "")
                st.download_button("Download package", z,
                                   file_name=f"{slugify(fn)}.zip",
                                   mime="application/zip")
            else:
                st.error("No run directory available for export.")