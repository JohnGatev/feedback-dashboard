from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import package as pkg
import pipeline
from detect import detect
from profile import (
    analyses_dir,
    default_profile,
    list_profiles,
    load as load_profile,
    load_storage_config,
    profiles_dir,
    save as save_profile,
    save_storage_config,
    slugify,
    validate,
)

st.set_page_config(page_title="Feedback Dashboard", layout="wide", page_icon="📋")

# --- Styling (generic, accent from profile) ---
_ACCENT = "#bc0031"
_ACCENT_DARK = "#1B1918"
_GREY1 = "#D7D6D4"
_GREY2 = "#F5F5F3"

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


# --- Storage helpers ---

def _is_cloud() -> bool:
    """True when running on Streamlit Community Cloud (or any container without
    a writable persistent home)."""
    return os.environ.get("STREAMLIT_CLOUD") == "1" or \
           os.path.isdir("/mount/src") or \
           "streamlit" in (os.environ.get("HOSTNAME", "") + os.environ.get("HOME", "")).lower()


def _session_working_dir() -> str:
    """Per-browser-session scratch dir on Streamlit Cloud.

    Each Streamlit browser session gets a unique key in session_state; we
    isolate analyses/profiles under /tmp so concurrent users don't collide.
    Nothing persists across container restarts, so users export packages to
    keep results.
    """
    root = "/tmp/feedback-dashboard-sessions"
    if "fb_session_key" not in st.session_state:
        import uuid
        st.session_state["fb_session_key"] = uuid.uuid4().hex[:8]
    sd = os.path.join(root, st.session_state["fb_session_key"])
    for sub in ("profiles", "analyses", "kb"):
        os.makedirs(os.path.join(sd, sub), exist_ok=True)
    return sd


def _seed_kb(session_dir: str) -> None:
    """Copy bundled KB files into a fresh session dir on cloud so profiles
    that reference `kb/...` resolve."""
    base_kb = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb")
    dest = os.path.join(session_dir, "kb")
    if os.path.isdir(base_kb) and not os.listdir(dest):
        for fn in os.listdir(base_kb):
            shutil.copy(os.path.join(base_kb, fn), os.path.join(dest, fn))


def get_working_dir() -> str | None:
    if _is_cloud():
        sd = _session_working_dir()
        _seed_kb(sd)
        return sd
    cfg = load_storage_config()
    wd = cfg.get("working_dir")
    if wd and os.path.isdir(wd):
        return wd
    return None


def set_working_dir(path: str) -> None:
    if _is_cloud():
        return  # ignored on cloud; session dir is fixed
    os.makedirs(path, exist_ok=True)
    for sub in ("profiles", "analyses", "kb"):
        os.makedirs(os.path.join(path, sub), exist_ok=True)
    save_storage_config({"working_dir": path})


def get_past_analyses(wd: str) -> list[dict]:
    out = []
    ad = analyses_dir(wd)
    if not os.path.isdir(ad):
        return out
    for d in os.listdir(ad):
        dp = os.path.join(ad, d)
        meta = os.path.join(dp, "meta.json")
        if os.path.exists(meta):
            with open(meta) as f:
                out.append(json.load(f))
    out.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return out


def analysis_path(wd: str, run_id: str) -> str:
    return os.path.join(analyses_dir(wd), run_id)


# --- Aspect/summary loading (generalized) ---

def load_aspect_data(analysis: str) -> tuple[dict, dict]:
    """Return (aspect_data, md_sections). aspect_data keyed by aspect_key."""
    import glob
    json_dir = os.path.join(analysis, "JSON Outputs")
    md_dir = os.path.join(analysis, "Markdown Summaries")
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
    return aspect_data, md_sections


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


def _profile_for_analysis(analysis: str) -> dict | None:
    p = os.path.join(analysis, "profile.json")
    if os.path.exists(p):
        try:
            return load_profile(p)
        except Exception:
            return None
    return None


# --- Sidebar nav ---

wd = get_working_dir()
st.sidebar.markdown(
    '<div style="font-size:1.1rem;font-weight:700;color:#fff;margin-bottom:4px;">Feedback Dashboard</div>',
    unsafe_allow_html=True)
if wd:
    st.sidebar.markdown(
        f'<div style="font-size:0.8rem;color:#D7D6D4;margin-bottom:6px;">'
        f'Storage: <code style="color:#fff;background:#2c2827;'
        f'padding:1px 5px;border-radius:3px;">{wd}</code></div>',
        unsafe_allow_html=True)
    page = st.sidebar.radio("Navigate", ["Setup", "Profiles", "Run", "Explore", "Dashboard"])
    analyses = get_past_analyses(wd)
    selected_analysis = None
    if analyses:
        st.sidebar.divider()
        st.sidebar.markdown("**Active analysis**")
        res_list = [f"{a['id']} — {a.get('filename','')}" for a in analyses]
        sel = st.sidebar.selectbox("Select", res_list, label_visibility="collapsed")
        sel_id = sel.split(" — ")[0]
        selected_analysis = analysis_path(wd, sel_id)
else:
    page = st.sidebar.radio("Navigate", ["Setup", "Profiles", "Run", "Explore", "Dashboard"])


# --- Profile editor (helper used by the Profiles page) ---

def _profile_editor(p: dict, pd_dir: str):
    with st.expander(f"Edit: {p['name']}", expanded=True):
        p["name"] = st.text_input("Profile name", p["name"])
        p["delimiter"] = st.selectbox("Delimiter", ["auto", ",", ";"], index=["auto", ",", ";"].index(p["delimiter"]))
        p["header_rows_to_skip"] = st.number_input("Header rows to skip", 0, 5, p["header_rows_to_skip"])

        st.markdown("**Grouping**")
        has_group = st.checkbox("Use a grouping/segment variable", value=p["grouping"] is not None)
        if has_group:
            g = p["grouping"] or {}
            g["column"] = st.text_input("Grouping column code (e.g. Q1_Team)", g.get("column", ""))
            g["display_name"] = st.text_input("Group display name", g.get("display_name", "Group"))
            g["label_template"] = st.text_input("Label template (use {g})", g.get("label_template", "Group {g}"))
            p["grouping"] = g
        else:
            p["grouping"] = None

        st.markdown("**Polarity**")
        for i, pol in enumerate(p["polarity"]):
            with st.container():
                pol["key"] = st.selectbox(f"Polarity {i+1} key", ["tip", "top"], index=["tip","top"].index(pol["key"]), key=f"polk{i}")
                pol["display"] = st.text_input(f"Display", pol["display"], key=f"pold{i}")
                pol["selection_column"] = st.text_input(f"Selection column", pol["selection_column"], key=f"pols{i}")
                pol["color"] = st.text_input(f"Color", pol["color"], key=f"polc{i}")
                pol["explain_prefix"] = st.text_input(f"Explain column prefix", pol["explain_prefix"], key=f"polp{i}")

        st.markdown("**Aspects**")
        for i, a in enumerate(p["aspects"]):
            with st.container():
                a["display_label"] = st.text_input(f"Aspect {i+1} label", a["display_label"], key=f"al{i}")
                a["aspect_key"] = st.text_input(f"Key", a["aspect_key"], key=f"ak{i}")
                for pk in [pol["key"] for pol in p["polarity"]]:
                    a["columns"][pk] = st.text_input(f"Column ({pk})", a["columns"].get(pk, ""), key=f"ac{i}_{pk}")

        st.markdown("**Output sections**")
        from profile import VALID_OUTPUT_SECTIONS
        group_only = {"group_counts_table", "group_differences"}
        if p["grouping"] is None:
            avail_secs = [s for s in VALID_OUTPUT_SECTIONS if s not in group_only]
            default_secs = [s for s in p.get("output_sections", []) if s not in group_only]
        else:
            avail_secs = list(VALID_OUTPUT_SECTIONS)
            default_secs = list(p.get("output_sections", []))
        secs = st.multiselect("Sections to include", avail_secs, default=default_secs)
        p["output_sections"] = secs

        st.markdown("**Prompts**")
        p["prompts"]["per_aspect_system"] = st.text_area(
            "Per-aspect system prompt (base; structural sections are appended automatically)",
            p["prompts"]["per_aspect_system"], height=180)
        p["prompts"]["executive_system"] = st.text_area(
            "Executive summary system prompt",
            p["prompts"]["executive_system"], height=180)

        st.markdown("**Model**")
        p["model"]["endpoint"] = st.text_input("LLM endpoint", p["model"]["endpoint"])
        p["model"]["name"] = st.text_input("Model name", p["model"]["name"])
        p["model"]["temperature"] = st.slider("Temperature", 0.0, 1.0, p["model"].get("temperature", 0.3))

        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("Save profile", type="primary"):
                try:
                    validate(p)
                    save_profile(p, os.path.join(pd_dir, f"{slugify(p['name'])}.json"))
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Validation error: {e}")
        with c2:
            if st.button("Delete profile"):
                fp = os.path.join(pd_dir, f"{slugify(p['name'])}.json")
                if os.path.exists(fp):
                    os.remove(fp)
                    st.success("Deleted.")
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 1) SETUP
# ─────────────────────────────────────────────────────────────────────────────
if page == "Setup":
    st.title("Setup")
    if _is_cloud():
        st.caption("Running on Streamlit Cloud. Each browser session gets an "
                   "isolated scratch folder. Nothing persists across restarts, "
                   "so **export your analyses as packages** to keep results.")
        st.success(f"Session storage: `{wd}`")
        st.info("Tip: use **Import a shared package** below to load a colleague's "
                "analysis, and **Export → package (.zip)** on the Dashboard tab "
                "to save or share your own.")
    else:
        st.caption("Choose a folder on your device where profiles, analyses, and "
                   "knowledge-base files will be stored. Nothing is uploaded; all "
                   "data stays local.")
        cur = wd
        if cur:
            st.success(f"Current working directory: `{cur}`")
        picked = st.text_input("Working directory path", value=cur or os.path.expanduser("~/feedback-dashboard"))
        if st.button("Set working directory", use_container_width=False):
            try:
                abs_p = os.path.abspath(os.path.expanduser(picked))
                set_working_dir(abs_p)
                st.success(f"Set: `{abs_p}`")
                st.rerun()
            except Exception as e:
                st.error(f"Could not set directory: {e}")
    st.divider()
    st.subheader("Import a shared package")
    up = st.file_uploader("Analysis package (.zip) or profile (.json)", type=["zip", "json"])
    if up and wd:
        if up.name.endswith(".zip"):
            target = pkg.import_analysis(up.getvalue(), wd, name_hint=up.name)
            st.success(f"Imported analysis → `{target}`")
        else:
            path = pkg.import_profile(up.getvalue(), wd)
            st.success(f"Imported profile → `{path}`")
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 2) PROFILES
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Profiles":
    st.title("Survey Profiles")
    st.caption("A profile describes one survey shape: aspects, grouping, prompts, "
               "and output sections. Edit one to customize the analysis.")
    if not wd:
        st.warning("Set a working directory in Setup first.")
        st.stop()

    pd_dir = profiles_dir(wd)
    pros = list_profiles(wd)
    st.subheader("Saved profiles")
    if pros:
        names = [p["name"] for p in pros]
        sel = st.selectbox("Open profile", ["— pick —"] + names)
        if sel != "— pick —":
            p = next(x for x in pros if x["name"] == sel)
            _profile_editor(p, pd_dir)
    else:
        st.info("No profiles yet. Create one from a CSV in the Run tab, or import one in Setup.")

    st.divider()
    st.subheader("Export current profile")
    if pros:
        exp = st.selectbox("Profile to export", names if pros else [])
        if st.button("Download profile JSON"):
            p = next(x for x in pros if x["name"] == exp)
            st.download_button("Download", pkg.export_profile(p),
                               file_name=f"{slugify(p['name'])}.json",
                               mime="application/json")
    else:
        st.caption("No profiles to export.")


# ─────────────────────────────────────────────────────────────────────────────
# 3) RUN
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Run":
    st.title("Run an analysis")
    st.caption("Upload a Qualtrics CSV. Aspects and grouping are auto-detected; "
               "review and edit before running. A profile supplies the prompts "
               "and output sections.")
    if not wd:
        st.warning("Set a working directory in Setup first.")
        st.stop()

    up = st.file_uploader("Qualtrics CSV", type=["csv"])
    if up is None:
        st.stop()

    # Persist upload to a temp path for detection
    tmp_csv = os.path.join(wd, "_upload.csv")
    with open(tmp_csv, "wb") as f:
        f.write(up.getvalue())

    det = detect(tmp_csv)
    st.success(f"Detected: delimiter `{det['delimiter']}`, "
               f"{len(det['aspects'])} aspects, "
               f"grouping: {det['grouping']['column'] if det['grouping'] else 'none'}")

    with st.expander("Detected aspects (edit before run)", expanded=True):
        keep = []
        for i, a in enumerate(det["aspects"]):
            cols = st.columns([1, 3, 3, 1])
            with cols[0]:
                inc = st.checkbox("include", value=True, key=f"inc{i}")
            with cols[1]:
                a["display_label"] = st.text_input("label", a["display_label"], key=f"dl{i}")
            with cols[2]:
                a["aspect_key"] = st.text_input("key", a["aspect_key"], key=f"dk{i}")
            with cols[3]:
                st.caption(f"tip={a['columns']['tip']}\ntop={a['columns']['top']}")
            if inc:
                keep.append(a)
        det["aspects"] = keep

    with st.expander("Grouping", expanded=False):
        has_g = st.checkbox("Use grouping/segment variable",
                            value=det["grouping"] is not None)
        if has_g:
            g = det["grouping"] or {}
            g["column"] = st.text_input("Grouping column code", g.get("column", ""))
            g["display_name"] = st.text_input("Display name", g.get("display_name", "Group"))
            g["label_template"] = st.text_input("Label template ({g})", g.get("label_template", "Group {g}"))
            det["grouping"] = g
        else:
            det["grouping"] = None

    # Inherit prompts/sections/model from an existing profile or defaults
    pros = list_profiles(wd)
    inherit = st.selectbox(
        "Inherit prompts/sections/model from profile",
        ["— defaults —"] + [p["name"] for p in pros])
    base = default_profile()
    if inherit != "— defaults —":
        base = next(p for p in pros if p["name"] == inherit)

    with st.expander("Prompts & sections (inherited, edit for this run)", expanded=False):
        from profile import VALID_OUTPUT_SECTIONS
        group_only = {"group_counts_table", "group_differences"}
        if det["grouping"] is None:
            avail_secs = [s for s in VALID_OUTPUT_SECTIONS if s not in group_only]
            default_secs = [s for s in base["output_sections"] if s not in group_only]
        else:
            avail_secs = list(VALID_OUTPUT_SECTIONS)
            default_secs = list(base["output_sections"])
        secs = st.multiselect("Output sections", avail_secs, default=default_secs)
        pa = st.text_area("Per-aspect system prompt (base)", base["prompts"]["per_aspect_system"], height=180)
        ex = st.text_area("Executive summary system prompt", base["prompts"]["executive_system"], height=180)
        endpoint = st.text_input("LLM endpoint", base["model"]["endpoint"])
        model_name = st.text_input("Model name", base["model"]["name"])

    run_name = st.text_input("Name this analysis", value=up.name.replace(".csv", ""))
    api_key = st.text_input("API key", type="password")
    if st.button("Run pipeline", type="primary"):
        if not api_key:
            st.error("API key required.")
            st.stop()
        # Build profile
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
        p["model"]["endpoint"] = endpoint
        p["model"]["name"] = model_name
        try:
            validate(p)
        except Exception as e:
            st.error(f"Profile invalid: {e}")
            st.stop()

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + slugify(run_name)
        run_dir = os.path.join(analyses_dir(wd), run_id)
        os.makedirs(run_dir, exist_ok=True)
        json_out = os.path.join(run_dir, "JSON Outputs")
        md_out = os.path.join(run_dir, "Markdown Summaries")

        msg = st.empty()
        msg.info("Step 1/3: Converting CSV to aspect JSONs...")
        pipeline.csv_to_json(p, tmp_csv, json_out)

        msg.info("Step 2/3: Generating aspect summaries (this can take a few minutes)...")
        pipeline.generate_aspect_summaries(p, json_out, md_out, api_key, base_dir=wd)

        msg.info("Step 3/3: Generating executive summary...")
        exe = os.path.join(run_dir, "Executive_Summary.md")
        pipeline.generate_executive_summary(p, md_out, exe, api_key)

        save_profile(p, os.path.join(run_dir, "profile.json"))
        # Copy the input CSV into the run for reproducibility
        shutil.copy(tmp_csv, os.path.join(run_dir, up.name))
        with open(os.path.join(run_dir, "meta.json"), "w") as f:
            json.dump({"id": run_id, "filename": up.name,
                       "timestamp": run_id, "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "profile_name": p["name"]}, f, indent=2)
        msg.success("Done.")
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 4) EXPLORE
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Explore":
    st.title("Feedback Explorer")
    if not selected_analysis:
        st.warning("No analysis selected. Run one or pick one in the sidebar.")
        st.stop()
    p = _profile_for_analysis(selected_analysis) or default_profile()
    aspect_data, md_sections = load_aspect_data(selected_analysis)
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

    with st.sidebar:
        st.subheader("Filters")
        sel_aspect = st.selectbox("Aspect", ["All"] + sorted(aspect_data.keys()))
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
# 5) DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Dashboard":
    st.title("Dashboard")
    if not selected_analysis:
        st.warning("No analysis selected.")
        st.stop()
    p = _profile_for_analysis(selected_analysis) or default_profile()
    aspect_data, _ = load_aspect_data(selected_analysis)
    pol = p["polarity"]
    grouping = p.get("grouping")
    seg_tmpl = grouping["label_template"] if grouping else "{g}"
    seg_label = grouping["display_name"] if grouping else "All"

    # Executive summary
    exe = os.path.join(selected_analysis, "Executive_Summary.md")
    if os.path.exists(exe):
        with open(exe, encoding="utf-8") as f:
            txt = f.read()
        txt = re.sub(r"(\n\|[^\n]+)+", "", txt)
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
            fig.update_layout(xaxis_tickangle=-30, legend_title="", margin=dict(t=40, b=100))
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        if grouping and ga_rows:
            df_g = pd.DataFrame(ga_rows)
            df_g_long = df_g.melt(id_vars="Segment", value_vars=[x["display"] for x in pol],
                                  var_name="Polarity", value_name="Count")
            fig2 = px.bar(df_g_long, x="Segment", y="Count", color="Polarity", barmode="group",
                          color_discrete_map=cmap, title=f"By {seg_label}",
                          labels={"Count": "Comments", "Segment": ""})
            fig2.update_layout(legend_title="", margin=dict(t=40))
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
                          title="Aspect ranking", labels={"Positivity": f"% {pos_key}", "Aspect": ""})
            fig3.update_xaxes(tickformat=".0%")
            fig3.update_layout(coloraxis_showscale=False, margin=dict(t=40))
            st.plotly_chart(fig3, use_container_width=True)
        with col4:
            if grouping and ga_rows:
                df_g = pd.DataFrame(ga_rows)
                df_g["Total"] = df_g[pol[0]["display"]] + df_g[pol[1]["display"]]
                df_g["Positivity"] = df_g[pos_key] / df_g["Total"].replace(0, pd.NA)
                heat = df_g.pivot_table(index="Aspect", columns="Segment", values="Positivity")
                n = len(heat)
                fig4 = px.imshow(heat, color_continuous_scale="RdYlGn", zmin=0, zmax=1,
                                 text_auto=".0%", title="Positivity — Aspect × Segment")
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
                    pdf_bytes = build_pdf(selected_analysis, aspect_data, p)
                    st.download_button("Download PDF", pdf_bytes,
                                       file_name=f"feedback_{os.path.basename(selected_analysis)}.pdf",
                                       mime="application/pdf")
                except Exception as e:
                    st.error(f"PDF failed: {e}")
    with col_e2:
        if st.button("Export analysis package (.zip)"):
            z = pkg.export_analysis(selected_analysis)
            st.download_button("Download package", z,
                               file_name=f"{os.path.basename(selected_analysis)}.zip",
                               mime="application/zip")


# ── PDF builder (generalized) ────────────────────────────────────────────────

def build_pdf(analysis: str, aspect_data: dict, profile: dict) -> bytes:
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
    meta = os.path.join(analysis, "meta.json")
    if os.path.exists(meta):
        with open(meta) as f:
            m = json.load(f)
        story.append(Paragraph(_esc(m.get("filename", "")),
                               ParagraphStyle("cs", parent=ss["Normal"], fontSize=13, textColor=BLACK)))
    story.append(PageBreak())

    # Executive
    exe = os.path.join(analysis, "Executive_Summary.md")
    if os.path.exists(exe):
        with open(exe, encoding="utf-8") as f:
            em = f.read()
        em = re.sub(r"\n\|[^\n]+", "", em)
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
        # Segment table
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
            story += [Paragraph("Counts by segment", S["h2"]), Spacer(1, 0.15 * cm), tbl]

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()