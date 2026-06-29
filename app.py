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
:root {
  --brand-primary: #bc0031;
  --brand-primary-hover: #9e0028;
  --ink-900: #1B1918;
  --ink-600: #5C5C5C;
  --ink-400: #8A8A8A;
  --surface-0: #FFFFFF;
  --surface-1: #F4F5F7;
  --surface-2: #FAFBFC;
  --border: #E2E4E8;
  --pos: #66bb6a;
  --neg: #bc0031;
  --success-bg: #EAF6EC;
  --success-text: #2E7D3A;
  --radius-card: 12px;
  --radius-input: 8px;
  --shadow-card: 0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.06);
}

p, li, h1, h2, h3, h4, h5, h6, label,
input[type="text"], textarea,
[data-testid="stText"], [data-testid="stCaption"] {
    font-family: 'Source Sans 3', 'Source Sans Pro', Arial, sans-serif !important;
}

/* ── Container width ── */
main, [data-testid="stMain"] {
    max-width: 1200px !important; margin: 0 auto !important; padding: 0 32px !important;
}

/* ── Inputs ── */
[data-baseweb="select"] > div, [data-baseweb="input"], [data-baseweb="base-input"],
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
input[type="text"], textarea { border-radius: var(--radius-input) !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="base-input"]:focus-within {
    border-color: var(--brand-primary) !important;
    box-shadow: 0 0 0 2px rgba(188,0,49,0.12) !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background-color: var(--ink-900) !important;
    border-right: 4px solid var(--brand-primary) !important;
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
section[data-testid="stSidebar"] hr { border-color: var(--brand-primary) !important; opacity: 0.6 !important; }
section[data-testid="stSidebar"] .stFormSubmitButton > button,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    background-color: var(--brand-primary) !important; color: white !important; border: none !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background-color: #2c2827 !important; border-color: #A8A29F !important;
}

/* ── Headings ── */
h1 { color: var(--brand-primary) !important; border-bottom: 3px solid var(--brand-primary) !important;
     padding-bottom: 8px !important; font-weight: 700 !important; }
h2, h3 { color: var(--ink-900) !important; font-weight: 600 !important; }

/* ── Buttons ── */
.stButton > button { border: 2px solid var(--brand-primary) !important; color: var(--brand-primary) !important;
                     font-weight: 600 !important; background-color: var(--surface-0) !important;
                     border-radius: var(--radius-input) !important; }
.stButton > button:hover { background-color: var(--brand-primary) !important; color: white !important; }
.stDownloadButton > button, .stFormSubmitButton > button {
    background-color: var(--brand-primary) !important; color: white !important; border: none !important;
    font-weight: 600 !important; border-radius: var(--radius-input) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid var(--border) !important; }
.stTabs [data-baseweb="tab"] { font-weight: 600 !important; color: var(--ink-600) !important;
    border-bottom: 3px solid transparent !important; padding: 8px 16px !important; }
.stTabs [aria-selected="true"] { color: var(--brand-primary) !important;
    border-bottom: 3px solid var(--brand-primary) !important; }

/* ── Misc ── */
hr { border-color: var(--brand-primary) !important; opacity: 0.35 !important; }
.stAlert { border-left-width: 4px !important; }
.stDataFrame { border: 1px solid var(--border) !important; }

/* ── Cards ── */
.ui-card {
    border: 1px solid var(--border); border-radius: var(--radius-card); padding: 24px;
    background: var(--surface-2); min-height: 200px; box-shadow: var(--shadow-card);
}
.ui-card h3 { margin-top: 0 !important; color: var(--brand-primary) !important; }
.kpi-card {
    border: 1px solid var(--border); border-radius: var(--radius-card); padding: 20px;
    background: var(--surface-2); box-shadow: var(--shadow-card); text-align: center;
}
.kpi-card .kpi-label { font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
    color: var(--ink-400); letter-spacing: 0.05em; }
.kpi-card .kpi-value { font-size: 2.2rem; font-weight: 700; margin-top: 4px; }
.chart-card {
    border: 1px solid var(--border); border-radius: var(--radius-card); padding: 16px;
    background: var(--surface-2); box-shadow: var(--shadow-card); margin-bottom: 16px;
}

/* ── Expander headers ── */
details[data-testid="stExpander"] > summary > div > p {
    font-weight: 600 !important; font-size: 1rem !important;
}

/* ── Section caption inside expanders ── */
.section-caption {
    color: var(--ink-600); font-size: 0.85rem; line-height: 1.5;
    margin-bottom: 12px; padding-bottom: 10px;
    border-bottom: 1px solid var(--border);
}

/* ── Stepper ── */
.stepper {
    display: flex; gap: 0; align-items: center; position: sticky; top: 0; z-index: 100;
    background: var(--surface-0); padding: 10px 0; margin-bottom: 16px;
    border-bottom: 1px solid var(--border);
}
.stepper-step {
    display: flex; align-items: center; gap: 6px; flex: 1; font-size: 0.78rem;
    color: var(--ink-400); font-weight: 600;
}
.stepper-dot {
    width: 24px; height: 24px; border-radius: 50%; display: inline-flex;
    align-items: center; justify-content: center; font-size: 0.72rem; font-weight: 700;
    border: 2px solid var(--border); color: var(--ink-400); background: var(--surface-0);
    flex-shrink: 0;
}
.stepper-dot.done { background: var(--brand-primary); border-color: var(--brand-primary); color: #fff; }
.stepper-dot.active { border-color: var(--brand-primary); color: var(--brand-primary); }
.stepper-line { flex: 0 0 16px; height: 2px; background: var(--border); }
.stepper-line.done { background: var(--brand-primary); }

/* ── Detected banner ── */
.detected-banner {
    background: var(--success-bg); color: var(--success-text); padding: 12px 16px;
    border-radius: var(--radius-input); border-left: 3px solid var(--pos);
    display: flex; align-items: center; gap: 10px; margin-bottom: 16px;
}
.detected-banner .det-chip {
    background: var(--surface-0); padding: 2px 10px; border-radius: 999px;
    font-size: 0.8rem; font-weight: 600; border: 1px solid var(--border);
}

/* ── Quote cards ── */
.quote-card {
    border: 1px solid var(--border); border-radius: var(--radius-card); padding: 14px 16px;
    background: var(--surface-2); box-shadow: var(--shadow-card); margin-bottom: 16px;
    border-left: 3px solid var(--neg);
}
.quote-tag {
    color: #fff; padding: 2px 8px; font-size: 0.7rem; font-weight: 700;
    border-radius: var(--radius-input); text-transform: uppercase;
}
.quote-seg {
    background: var(--surface-1); color: var(--ink-900); padding: 2px 8px;
    font-size: 0.7rem; font-weight: 600; border-radius: 999px; margin-left: 6px;
}
.quote-aspect { color: var(--ink-400); font-size: 0.7rem; margin-left: 8px; }
.quote-body { font-size: 0.9rem; color: var(--ink-900); line-height: 1.55; margin-top: 8px; }
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


def _stepper_html(steps):
    """Render a sticky horizontal stepper. steps = [(num, label, done_bool), ...]"""
    parts = ['<div class="stepper">']
    for i, (num, label, done) in enumerate(steps):
        cls = "done" if done else ""
        icon = "&#10003;" if done else str(num)
        parts.append(
            f'<div class="stepper-step">'
            f'<span class="stepper-dot {cls}">{icon}</span>'
            f'<span style="color:{("#bc0031" if done else "#8A8A8A")};'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{label}</span>'
            f'</div>')
        if i < len(steps) - 1:
            parts.append(f'<span class="stepper-line {"done" if done else ""}"></span>')
    parts.append('</div>')
    return "".join(parts)


def _detected_banner(det):
    """Render the detection result as a styled banner with chips."""
    chips = [f"delimiter <code>{det['delimiter']}</code>",
             f"{len(det['aspects'])} aspects"]
    if det["grouping"]:
        chips.append(f"grouping: <code>{det['grouping']['column']}</code>")
    chip_html = "".join(f'<span class="det-chip">{c}</span>' for c in chips)
    return (f'<div class="detected-banner">'
            f'<span style="font-size:1.1rem;">&#10003;</span>'
            f'<span style="font-weight:600;">Detected:</span>'
            f'{chip_html}</div>')


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
    seg_label = grouping["display_name"] if grouping else "All"

    buf = io.BytesIO()
    page_w, _ = A4
    margin = 2.5 * cm
    content_w = page_w - 2 * margin
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=2 * cm, bottomMargin=2.5 * cm,
                            title="Feedback Analysis")
    ACCENT = colors.HexColor("#bc0031")
    BLACK = colors.HexColor("#1B1918")
    GREY1 = colors.HexColor("#E2E4E8")
    GREY2 = colors.HexColor("#FAFBFC")
    POS_C = colors.HexColor("#66bb6a")
    NEG_C = colors.HexColor("#bc0031")
    ss = getSampleStyleSheet()
    S = {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                             fontSize=20, spaceBefore=22, spaceAfter=10, textColor=ACCENT),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=13, spaceBefore=14, spaceAfter=6, textColor=BLACK),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                             fontSize=11, spaceBefore=10, spaceAfter=4, textColor=BLACK),
        "body": ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=10, leading=15, spaceAfter=6, textColor=BLACK),
        "bullet": ParagraphStyle("bul", parent=ss["Normal"], fontName="Helvetica",
                                 fontSize=10, leading=14, leftIndent=14, spaceAfter=3, textColor=BLACK),
        "cover_title": ParagraphStyle("ct", parent=ss["Title"], fontName="Helvetica-Bold",
                                      fontSize=28, alignment=0, spaceAfter=10, textColor=BLACK),
        "kpi": ParagraphStyle("kpi", parent=ss["Normal"], fontName="Helvetica-Bold",
                              fontSize=24, alignment=1, spaceBefore=6, spaceAfter=2),
        "kpi_label": ParagraphStyle("kpil", parent=ss["Normal"], fontName="Helvetica",
                                    fontSize=9, alignment=1, textColor=GREY1),
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

    # ── Chart generation (matplotlib, matching on-screen Plotly styling) ──
    _pol_colors = {x["display"]: x["color"] for x in pol}

    def _chart_volume_by_aspect():
        aspects = sorted({d["aspect"]["display_name"] for d in aspect_data.values()})
        x = np.arange(len(aspects))
        w = 0.35
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for i, x_pol in enumerate(pol):
            vals = [d["counts"].get(x_pol["key"] + "_comment_count", 0)
                    for d in [aspect_data[k] for k in sorted(aspect_data)]]
            ax.bar(x + (i - 0.5) * w, vals, w, label=x_pol["display"],
                   color=_pol_colors[x_pol["display"]])
        ax.set_xticks(x)
        ax.set_xticklabels([a[:20] + "…" if len(a) > 20 else a for a in aspects],
                           rotation=30, ha="right", fontsize=9)
        ax.set_ylabel("Comments", fontsize=9)
        ax.set_title("By aspect", fontsize=12, fontweight="bold", color="#1B1918")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.legend(fontsize=9)
        fig.tight_layout()
        return _img(fig, 16, 7)

    def _chart_volume_by_segment():
        all_segs = sort_segments(set().union(*[d.get(f"{x['key']}_by_segment", {}).keys()
                                               for d in aspect_data.values() for x in pol]))
        x = np.arange(len(all_segs))
        w = 0.35
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for i, x_pol in enumerate(pol):
            vals = []
            for seg in all_segs:
                total = sum(d.get(f"{x_pol['key']}_by_segment", {}).get(seg, {})
                            .get("comment_count", 0) for d in aspect_data.values())
                vals.append(total)
            ax.bar(x + (i - 0.5) * w, vals, w, label=x_pol["display"],
                   color=_pol_colors[x_pol["display"]])
        ax.set_xticks(x)
        ax.set_xticklabels([seg_tmpl.format(g=s)[:15] for s in all_segs],
                           rotation=30, ha="right", fontsize=9)
        ax.set_ylabel("Comments", fontsize=9)
        ax.set_title(f"By {seg_label}", fontsize=12, fontweight="bold", color="#1B1918")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.legend(fontsize=9)
        fig.tight_layout()
        return _img(fig, 16, 7)

    def _chart_positivity_ranking():
        rows = []
        for k, d in aspect_data.items():
            display = d["aspect"]["display_name"]
            counts = {x["key"]: d["counts"].get(x["key"] + "_comment_count", 0) for x in pol}
            total = sum(counts.values())
            pos_key = next((x["key"] for x in pol if x["key"] == "top"), pol[-1]["key"])
            positivity = counts[pos_key] / total if total else 0
            rows.append((display, positivity))
        rows.sort(key=lambda r: r[1])
        labels = [r[0][:25] + "…" if len(r[0]) > 25 else r[0] for r in rows]
        vals = [r[1] for r in rows]
        fig, ax = plt.subplots(figsize=(10, max(4, len(rows) * 0.6)))
        colors_bar = []
        for v in vals:
            if v < 0.4:
                colors_bar.append("#bc0031")
            elif v < 0.6:
                colors_bar.append("#f0ad4e")
            else:
                colors_bar.append("#66bb6a")
        ax.barh(labels, vals, color=colors_bar)
        for i, v in enumerate(vals):
            ax.text(v + 0.01, i, f"{v:.0%}", va="center", fontsize=9, color="#1B1918")
        ax.set_xlim(0, 1.15)
        ax.set_xlabel("% Tops" if pol[1]["key"] == "top" else "% Positive", fontsize=9)
        ax.set_title("Aspect ranking", fontsize=12, fontweight="bold", color="#1B1918")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        fig.tight_layout()
        return _img(fig, 16, max(7, len(rows) * 0.9))

    def _chart_positivity_heatmap():
        all_segs = sort_segments(set().union(*[d.get(f"{x['key']}_by_segment", {}).keys()
                                               for d in aspect_data.values() for x in pol]))
        aspects = sorted({d["aspect"]["display_name"] for d in aspect_data.values()})
        pos_key = next((x["key"] for x in pol if x["key"] == "top"), pol[-1]["key"])
        data = np.full((len(aspects), len(all_segs)), np.nan)
        for ai, asp in enumerate(aspects):
            for si, seg in enumerate(all_segs):
                totals = {}
                for x in pol:
                    totals[x["key"]] = sum(
                        d.get(f"{x['key']}_by_segment", {}).get(seg, {}).get("comment_count", 0)
                        for d in aspect_data.values()
                        if d["aspect"]["display_name"] == asp)
                t = sum(totals.values())
                if t:
                    data[ai, si] = totals[pos_key] / t
        fig, ax = plt.subplots(figsize=(10, max(4, len(aspects) * 0.7)))
        from matplotlib.colors import LinearSegmentedColormap
        cmap = LinearSegmentedColormap.from_list("ryg", ["#bc0031", "#f5f5dc", "#66bb6a"])
        im = ax.imshow(data, cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(len(all_segs)))
        ax.set_xticklabels([seg_tmpl.format(g=s)[:12] for s in all_segs],
                           rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(aspects)))
        ax.set_yticklabels([a[:20] + "…" if len(a) > 20 else a for a in aspects], fontsize=9)
        for ai in range(len(aspects)):
            for si in range(len(all_segs)):
                if not np.isnan(data[ai, si]):
                    ax.text(si, ai, f"{data[ai, si]:.0%}", ha="center", va="center",
                            fontsize=8, color="#1B1918")
        ax.set_title("Positivity — Aspect × Segment", fontsize=12, fontweight="bold", color="#1B1918")
        fig.tight_layout()
        return _img(fig, 16, max(7, len(aspects) * 1.1))

    # ── Build KPI data for cover ──
    _totals = {}
    for x in pol:
        _totals[x["key"]] = sum(d["counts"].get(x["key"] + "_comment_count", 0)
                                for d in aspect_data.values())
    _grand_total = sum(_totals.values())

    story = []
    # Cover
    red = Table([["  "]], colWidths=[content_w], rowHeights=[0.6 * cm])
    red.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story += [red, Spacer(1, 3 * cm), Paragraph("Feedback Analysis", S["cover_title"])]
    if meta.get("filename"):
        story.append(Paragraph(_esc(meta.get("filename", "")),
                               ParagraphStyle("cs", parent=ss["Normal"], fontName="Helvetica",
                                              fontSize=13, textColor=BLACK)))
    if meta.get("date"):
        story.append(Paragraph(_esc(str(meta.get("date", ""))[:10]),
                               ParagraphStyle("cd", parent=ss["Normal"], fontName="Helvetica",
                                              fontSize=9, textColor=GREY1)))
    # KPIs on cover
    story.append(Spacer(1, 2 * cm))
    kpi_cells = []
    for x in pol:
        c = "#bc0031" if x["key"] == "tip" else "#66bb6a"
        kpi_cells.append(Paragraph(
            f'<para alignment="center"><font color="#8A8A8A" size="9">{x["display"].upper()}</font><br/>'
            f'<font color="{c}" size="24"><b>{_totals[x["key"]]}</b></font></para>',
            ParagraphStyle("kpi_cell", parent=ss["Normal"], fontName="Helvetica",
                           alignment=1, leading=30)))
    kpi_cells.append(Paragraph(
        f'<para alignment="center"><font color="#8A8A8A" size="9">TOTAL</font><br/>'
        f'<font color="#1B1918" size="24"><b>{_grand_total}</b></font></para>',
        ParagraphStyle("kpi_total", parent=ss["Normal"], fontName="Helvetica",
                       alignment=1, leading=30)))
    kpi_tbl = Table([kpi_cells], colWidths=[content_w / len(kpi_cells)] * len(kpi_cells))
    kpi_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, GREY1),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY1),
        ("BACKGROUND", (0, 0), (-1, -1), GREY2),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(kpi_tbl)
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
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY2]),
                ("GRID", (0, 0), (-1, -1), 0.5, GREY1),
            ]))
            story += [Spacer(1, 0.4 * cm), Paragraph("Counts by segment", S["h2"]),
                     Spacer(1, 0.15 * cm), tbl]

    # Charts section
    story += [PageBreak(), Paragraph("Charts", S["h1"]),
              HRFlowable(width=content_w, thickness=2, color=ACCENT), Spacer(1, 0.3 * cm)]
    story += [Paragraph("Volume", S["h2"]),
              Spacer(1, 0.2 * cm), _chart_volume_by_aspect()]
    if grouping:
        story += [Spacer(1, 0.3 * cm), _chart_volume_by_segment()]
    if len(pol) == 2:
        story += [Spacer(1, 0.5 * cm), Paragraph("Positivity", S["h2"]),
                  Spacer(1, 0.2 * cm), _chart_positivity_ranking()]
        if grouping:
            story += [Spacer(1, 0.3 * cm), _chart_positivity_heatmap()]

    # Representative quotes
    story += [PageBreak(), Paragraph("Representative Quotes", S["h1"]),
              HRFlowable(width=content_w, thickness=2, color=ACCENT), Spacer(1, 0.3 * cm)]
    for k in sorted(aspect_data):
        d = aspect_data[k]
        display = d["aspect"]["display_name"]
        for x in pol:
            seg_data = d.get(f"{x['key']}_by_segment", {})
            for seg, sd in seg_data.items():
                for c in sd.get("comments", [])[:3]:
                    tag = x["display"].upper()
                    tag_color = "#bc0031" if x["key"] == "tip" else "#66bb6a"
                    seg_str = seg_tmpl.format(g=seg) if grouping else ""
                    header_str = f'<font color="{tag_color}"><b>[{tag}]</b></font>'
                    if seg_str:
                        header_str += f' <font color="#8A8A8A">({seg_str})</font>'
                    header_str += f' <font color="#8A8A8A">— {display}</font>'
                    story.append(Paragraph(header_str,
                                           ParagraphStyle("qtag", parent=ss["Normal"],
                                                          fontName="Helvetica", fontSize=9,
                                                          spaceBefore=8, spaceAfter=2)))
                    story.append(Paragraph(f'"{_esc(c["text"])}"',
                                           ParagraphStyle("qbody", parent=ss["Normal"],
                                                          fontName="Helvetica", fontSize=10,
                                                          leading=14, leftIndent=14,
                                                          textColor=BLACK, spaceAfter=6)))

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
if "_nav" in st.session_state:
    _nav_target = st.session_state.pop("_nav")
    page = st.sidebar.radio("Navigate", ["Start", "Run", "Explore", "Dashboard"],
                            index=["Start", "Run", "Explore", "Dashboard"].index(_nav_target))
else:
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
    st.caption("Import a previously exported analysis package to view it, "
               "or create a new analysis from a Qualtrics CSV.")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("""
        <div class="ui-card">
            <h3>Create a new analysis</h3>
            <p style="color:#6b6b6b;font-size:0.9rem;line-height:1.6;">
            Upload a Qualtrics CSV, auto-detect aspects and grouping,
            define your comparison, and run the analysis pipeline.
            Nothing is saved — export the result as a .zip when done.
            </p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Go to Run →", use_container_width=True, key="goto_run"):
            st.session_state["_nav"] = "Run"
            st.rerun()
    with col_r:
        st.markdown("""
        <div class="ui-card">
            <h3>Import a package</h3>
            <p style="color:#6b6b6b;font-size:0.9rem;line-height:1.6;">
            Open a .zip exported from a previous analysis to view it
            in Explore and Dashboard immediately.
            </p>
        </div>
        """, unsafe_allow_html=True)
        up = st.file_uploader("Analysis package (.zip)", type=["zip"],
                              help="Select a .zip file exported from this app. "
                                   "It contains all aspect JSONs, markdown summaries, "
                                   "and the profile used to generate them.")
        if up is not None:
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

    st.divider()
    st.markdown("""
    <div style="color:#6b6b6b;font-size:0.85rem;line-height:1.7;">
    <strong style="color:#1B1918;">How it works</strong><br>
    1. <strong>Run</strong> — upload a Qualtrics CSV, detect aspects, define your comparison, run the pipeline.<br>
    2. <strong>Explore</strong> — filter summaries and quotes by aspect, polarity, and segment.<br>
    3. <strong>Dashboard</strong> — charts, executive summary, PDF export.<br>
    4. <strong>Export</strong> — download the finished analysis as a .zip package.<br>
    5. <strong>Share</strong> — send the package to a colleague. They open this app, come here, and import it.<br><br>
    Nothing is stored on a server. Each session lives in your browser; the only persistence
    is the .zip you export.
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# 2) RUN
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Run":
    st.title("Run an analysis")
    st.caption("Upload a Qualtrics CSV, review the auto-detected structure, "
               "configure the model and prompts, then run. Nothing is saved — "
               "export the result as a .zip when done.")

    _dp = default_profile()
    _default_aspect_prompt = _dp["prompts"]["per_aspect_system"]
    _default_exec_prompt = _dp["prompts"]["executive_system"]

    # ── Step 1: Upload ──
    with st.expander('1 · Upload CSV', expanded=True):
        st.markdown('<div class="section-caption">Select a Qualtrics CSV export. '
                    'The app auto-detects the delimiter, aspects, polarity, and '
                    'grouping variable from the 3-row header.</div>',
                    unsafe_allow_html=True)
        up = st.file_uploader("Qualtrics CSV", type=["csv"],
                              help="A Qualtrics CSV export with a 3-row header "
                                   "(ImportId codes, question text, import labels). "
                                   "Aspects, polarity, and grouping are detected "
                                   "automatically from the header structure.")
    if up is None:
        st.info("Select a CSV file above to begin.")
        st.stop()

    csv_bytes = up.getvalue()
    det = detect(csv_bytes)
    st.markdown(_detected_banner(det), unsafe_allow_html=True)

    # ── Stepper (completion tracked via session_state for cross-rerun persistence) ──
    _s = st.session_state
    _stepper_steps = [
        (1, "Upload",      up is not None),
        (2, "Aspects",     len(det["aspects"]) > 0),
        (3, "Grouping",    True),
        (4, "Model",       bool(_s.get("fb_models"))),
        (5, "Sections",    True),
        (6, "Comparison",  True),
        (7, "Executive",   True),
        (8, "Run",         bool(_s.get("active"))),
    ]
    st.markdown(_stepper_html(_stepper_steps), unsafe_allow_html=True)

    # ── Step 2: Detected Aspects ──
    with st.expander('2 · Detected Aspects', expanded=True):
        st.markdown('<div class="section-caption">Each row is one aspect auto-detected '
                    'from the CSV. Untick to exclude an aspect; edit the label to '
                    'change how it appears in summaries, charts, and the PDF.</div>',
                    unsafe_allow_html=True)
        keep = []
        for i, a in enumerate(det["aspects"]):
            cols = st.columns([1, 9])
            with cols[0]:
                inc = st.checkbox("", value=True, key=f"inc{i}",
                                  help="Include this aspect in the analysis.")
            with cols[1]:
                a["display_label"] = st.text_input(
                    "Label", value=a["display_label"].capitalize(), key=f"dl{i}",
                    label_visibility="collapsed",
                    help="The human-readable name shown in summaries, charts, "
                         "and the PDF report.")
            if inc:
                keep.append(a)
        det["aspects"] = keep
        if not det["aspects"]:
            st.warning("No aspects selected. Tick at least one to run.")

    # ── Step 3: Grouping ──
    with st.expander('3 · Grouping', expanded=False):
        st.markdown('<div class="section-caption">Grouping splits comments by a '
                    'survey variable (e.g. team, tutorial group). When enabled, '
                    'the analysis shows per-segment counts, differences, and a '
                    'heatmap. Leave disabled if your survey has no such variable.</div>',
                    unsafe_allow_html=True)
        has_g = st.checkbox("Use grouping/segment variable",
                            value=det["grouping"] is not None,
                            help="Enable to split comments by a survey variable. "
                                 "Adds per-segment counts, differences, and a "
                                 "positivity heatmap to the output.")
        g = det["grouping"] or {}
        g["column"] = st.text_input(
            "Grouping column code", g.get("column", ""),
            disabled=not has_g,
            help="The Qualtrics column ID (e.g. Q1_Team) that holds each "
                 "respondent's segment value. Must match the CSV header code exactly.")
        g["display_name"] = st.text_input(
            "Display name", g.get("display_name", "Group"),
            disabled=not has_g,
            help="Human-readable label shown in charts, tables, and filters "
                 "(e.g. 'Team').")
        g["label_template"] = st.text_input(
            "Label template", g.get("label_template", "Group {g}"),
            disabled=not has_g,
            help="How individual segment labels appear in the UI. {g} is replaced "
                 "by each segment value, e.g. 'Team {g}' becomes 'Team PC&J'.")
        if has_g:
            det["grouping"] = g
        else:
            det["grouping"] = None

    # ── Step 4: Model & API Key ──
    with st.expander('4 · Model & API Key', expanded=True):
        st.markdown('<div class="section-caption">Enter your LLM proxy credentials, '
                    'fetch the available models, and select one. The API key is '
                    'used for both model discovery and the analysis run.</div>',
                    unsafe_allow_html=True)
        api_key = st.text_input("API key", type="password",
                                help="Your LLM proxy API key. Used to fetch "
                                     "available models and to run the analysis.")
        KNOWN_ENDPOINTS = [
            "https://llmproxy.uva.nl/chat/completions",
            "https://ai-research-proxy.azurewebsites.net/v1/chat/completions",
            "Custom…",
        ]
        endpoint_sel = st.selectbox("Endpoint", KNOWN_ENDPOINTS,
                                    help="The chat-completions URL of your LLM proxy. "
                                         "Choose 'Custom…' to enter a different URL.")
        if endpoint_sel == "Custom…":
            endpoint = st.text_input("Custom endpoint URL", "",
                                     help="Full URL of the chat-completions endpoint, "
                                          "e.g. https://my-proxy.example.com/v1/chat/completions")
        else:
            endpoint = endpoint_sel

        if "fb_models" not in st.session_state:
            st.session_state["fb_models"] = []
        c_fetch, _ = st.columns([1, 4])
        with c_fetch:
            if st.button("Fetch available models",
                         disabled=not (api_key and endpoint),
                         help="Query the endpoint for all models accessible "
                              "with your API key. Disabled until both API key "
                              "and endpoint are provided."):
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
            model_name = st.selectbox("Model", model_ids,
                                      help="The model to use for generating aspect "
                                           "and executive summaries.")
        else:
            model_name = None
            st.caption("No models loaded yet. Enter your API key and click "
                       "“Fetch available models”.")

    # ── Step 5: Output Sections ──
    with st.expander('5 · Output Sections', expanded=True):
        st.markdown('<div class="section-caption">Toggle which structural sections '
                    'each aspect summary contains. Group-only sections are disabled '
                    'when grouping is off.</div>',
                    unsafe_allow_html=True)
        if "fb_sections" not in st.session_state:
            st.session_state["fb_sections"] = {}
        secs = []
        for t in _SECTION_TOGGLES:
            is_group_only = t["key"] in _GROUP_ONLY_KEYS
            is_disabled = is_group_only and det["grouping"] is None
            default_on = t["key"] in _dp["output_sections"] and not is_disabled
            cur = st.session_state["fb_sections"].get(t["key"], default_on)
            label = t["label"] + (" (requires grouping)" if is_disabled else "")
            on = st.toggle(label, value=cur and not is_disabled,
                           help=t["help"], key=f"tog_{t['key']}",
                           disabled=is_disabled)
            st.session_state["fb_sections"][t["key"]] = on
            if on:
                secs.append(t["key"])

    # ── Step 6: Aspect Comparison ──
    with st.expander('6 · Aspect Comparison', expanded=True):
        st.markdown('<div class="section-caption">Choose how aspects are analysed. '
                    'Broad narrative uses the shipped analytical prompt. Custom '
                    'focus lets you add a comparison lens in natural language, '
                    'appended to the default.</div>',
                    unsafe_allow_html=True)
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
                           "of the meeting and whether it feels relevant to their role.",
                help="Describe your comparison goal in plain language. The LLM "
                     "turns this into a structured focus directive.")
            if "fb_focus" not in st.session_state:
                st.session_state["fb_focus"] = ""
            c_gen, _ = st.columns([1, 4])
            with c_gen:
                if st.button("Generate focus directive",
                             help="Send your description to the LLM to produce "
                                  "a structured focus directive appended to the "
                                  "default prompt."):
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
                     "toggles in Step 5.")

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
                    format_func=lambda k: aspect_labels[k],
                    help="Aspects not selected here will use the default broad "
                         "prompt instead of your custom focus.")
                if "fb_overrides" not in st.session_state:
                    st.session_state["fb_overrides"] = {}
                st.session_state["fb_overrides"] = {}
                for a in det["aspects"]:
                    if a["aspect_key"] not in scoped_keys:
                        st.session_state["fb_overrides"][a["aspect_key"]] = _default_aspect_prompt

    # ── Step 7: Executive Summary ──
    with st.expander('7 · Executive Summary', expanded=False):
        st.markdown('<div class="section-caption">Configure the executive summary '
                    'that synthesises all aspect summaries. Default produces a '
                    'two-paragraph synthesis plus per-aspect narrative. Custom '
                    'focus lets you steer the emphasis.</div>',
                    unsafe_allow_html=True)
        with st.expander("View default executive prompt", expanded=False):
            st.text(_default_exec_prompt)
        exec_mode = st.radio(
            "Executive mode",
            ["Default (two-part synthesis)", "Custom focus"],
            horizontal=True,
            help="Default produces a two-paragraph executive summary plus "
                 "per-aspect narrative prose in an analytical register. "
                 "Custom lets you add a focus directive appended to the default.",
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
                           "which aspects are robust vs tentative.",
                help="Describe the executive summary emphasis in plain language. "
                     "The LLM turns this into a structured directive.")
            if "fb_exec_focus" not in st.session_state:
                st.session_state["fb_exec_focus"] = ""
            c_gen_e, _ = st.columns([1, 4])
            with c_gen_e:
                if st.button("Generate executive focus",
                             help="Send your description to the LLM to produce "
                                  "a structured executive focus directive."):
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
                              value=ex, height=200,
                              help="The default executive prompt with your focus "
                                   "directive appended. Edit freely.")

    # ── Step 8: Run ──
    with st.expander('8 · Run Analysis', expanded=True):
        st.markdown('<div class="section-caption">Name your analysis and run the '
                    'pipeline. This converts the CSV to per-aspect JSONs, generates '
                    'summaries via the LLM, and produces an executive summary. '
                    'Export the result as a .zip when done.</div>',
                    unsafe_allow_html=True)
        run_name = st.text_input("Name this analysis", value=up.name.replace(".csv", ""),
                                 help="A descriptive name for this run. Used in "
                                      "the exported file name and meta data.")
        can_run = bool(det["aspects"] and api_key and model_name and endpoint
                       and pa.strip() and ex.strip())
        if not can_run:
            st.caption("Complete the steps above (aspects, model, prompts) before running.")
        if st.button("Run pipeline", type="primary", disabled=not can_run,
                     help="Run the full 3-stage pipeline: CSV → aspect JSONs → "
                          "LLM summaries → executive summary."):
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
                                  format_func=lambda k: _key_to_name.get(k, k),
                                  help="Filter to a single aspect, or show all.")
        sel_pol = st.selectbox("Polarity", ["All"] + [x["display"] for x in pol],
                               help="Filter to Tips or Tops only, or show both.")
        if grouping:
            sel_seg = st.selectbox(seg_label, ["All"] + sort_segments(all_segs),
                                   help=f"Filter to a single {seg_label.lower()}, or show all.")
        else:
            sel_seg = "All"
        active_aspects = [sel_aspect] if sel_aspect != "All" else sorted(aspect_data.keys())
        active_segs = [sel_seg] if sel_seg != "All" else list(all_segs)

    # Metrics — three KPI cards
    totals = {x["key"]: 0 for x in pol}
    for k in active_aspects:
        d = aspect_data[k]
        for seg in active_segs:
            for x in pol:
                totals[x["key"]] += d.get(f"{x['key']}_by_segment", {}).get(seg, {}).get("comment_count", 0)
    total = sum(totals.values())
    _kpi_colors = {}
    for x in pol:
        _kpi_colors[x["key"]] = "#bc0031" if x["key"] == "tip" else "#66bb6a"
    mcols = st.columns(len(pol) + 1)
    for i, x in enumerate(pol):
        with mcols[i]:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">{x["display"]}</div>'
                f'<div class="kpi-value" style="color:{_kpi_colors[x["key"]]};">'
                f'{totals[x["key"]]}</div></div>',
                unsafe_allow_html=True)
    with mcols[len(pol)]:
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-label">Total</div>'
            f'<div class="kpi-value" style="color:#1B1918;">{total}</div></div>',
            unsafe_allow_html=True)

    st.divider()
    st.subheader("Aspect summaries")
    st.caption("Narrative summaries for each aspect, tabbed by theme, segment "
               "differences, and key tensions where available.")
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
    st.caption("Verbatim quotes from the survey, filtered by aspect, polarity, "
               "and segment. Coloured by polarity, tagged by segment.")
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
                    seg_badge = (f'<span class="quote-seg">'
                                 f'{seg_tmpl.format(g=q["segment"])}</span>') if grouping else ""
                    border_color = q["color"]
                    card = (
                        f'<div class="quote-card" style="border-left:3px solid {border_color};">'
                        f'<div><span class="quote-tag" style="background:{border_color};">'
                        f'{q["polarity"].upper()}</span>'
                        f'{seg_badge}'
                        f'<span class="quote-aspect">{q["aspect"]}</span>'
                        f'</div><div class="quote-body">'
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
    st.caption("Comment counts by aspect and polarity. When grouping is enabled, "
               "a second chart breaks counts down by segment.")
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
    _PLOTLY_CFG = {"displayModeBar": "reduce"}
    c1, c2 = st.columns(2)
    with c1:
        if not df.empty:
            with st.container():
                st.markdown('<div class="chart-card">', unsafe_allow_html=True)
                fig = px.bar(df, x="Aspect", y="Count", color="Polarity", barmode="group",
                             color_discrete_map=cmap, title="By aspect",
                             labels={"Count": "Comments", "Aspect": ""})
                fig.update_layout(xaxis_tickangle=-30, legend_title="", margin=dict(t=40, b=100),
                                  showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config=_PLOTLY_CFG)
                st.markdown('</div>', unsafe_allow_html=True)
    with c2:
        if grouping and ga_rows:
            with st.container():
                st.markdown('<div class="chart-card">', unsafe_allow_html=True)
                df_g = pd.DataFrame(ga_rows)
                df_g_long = df_g.melt(id_vars="Segment", value_vars=[x["display"] for x in pol],
                                      var_name="Polarity", value_name="Count")
                fig2 = px.bar(df_g_long, x="Segment", y="Count", color="Polarity", barmode="group",
                              color_discrete_map=cmap, title=f"By {seg_label}",
                              labels={"Count": "Comments", "Segment": ""})
                fig2.update_layout(legend_title="", margin=dict(t=40), showlegend=False)
                st.plotly_chart(fig2, use_container_width=True, config=_PLOTLY_CFG)
                st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    st.subheader("Positivity")
    st.caption("Positive-comment share per aspect, ranked lowest to highest. "
               "When grouping is enabled, a heatmap shows positivity by aspect "
               "and segment.")
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
            with st.container():
                st.markdown('<div class="chart-card">', unsafe_allow_html=True)
                fig3 = px.bar(piv, x="Positivity", y="Aspect", orientation="h", color="Positivity",
                              color_continuous_scale="RdYlGn", range_color=[0, 1],
                              title="Aspect ranking", labels={"Positivity": f"% {pos_key}", "Aspect": ""},
                              text=piv["Positivity"])
                fig3.update_traces(texttemplate="%{text:.2%}", textposition="outside")
                fig3.update_xaxes(tickformat=".2%")
                fig3.update_layout(coloraxis_showscale=False, margin=dict(t=40, b=20),
                                   showlegend=False)
                st.plotly_chart(fig3, use_container_width=True, config=_PLOTLY_CFG)
                st.markdown('</div>', unsafe_allow_html=True)
        with col4:
            if grouping and ga_rows:
                with st.container():
                    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
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
                    st.plotly_chart(fig4, use_container_width=True, config=_PLOTLY_CFG)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.caption("Grouping not enabled for this analysis; heatmap skipped.")

    st.divider()
    st.subheader("Export")
    st.caption("Download a PDF report with charts and narrative, or export the "
               "full analysis as a .zip package for sharing.")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        if st.button("Generate PDF report",
                     help="Build a PDF with volume charts, positivity ranking, "
                          "and per-aspect narrative sections."):
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
        if st.button("Export analysis package (.zip)",
                     help="Export all aspect JSONs, markdown summaries, profile, "
                          "and meta as a .zip for sharing or archival."):
            rd = active.get("run_dir")
            if rd and os.path.isdir(rd):
                z = pkg.export_analysis(rd)
                fn = active.get("meta", {}).get("filename", "analysis").replace(".csv", "")
                st.download_button("Download package", z,
                                   file_name=f"{slugify(fn)}.zip",
                                   mime="application/zip")
            else:
                st.error("No run directory available for export.")