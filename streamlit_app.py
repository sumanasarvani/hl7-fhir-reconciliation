"""
app.py -- HL7/FHIR Interoperability Reconciliation Dashboard
Streamlit in Snowflake (SiS) app.

Three screens, selectable from the sidebar:
  1. Summary       -- overall discrepancy stats and breakdown by type
  2. Patient Lookup -- side-by-side FHIR vs HL7 view for one patient
  3. Ask a Question -- natural language -> SQL via Cortex Analyst

SETUP: update SEMANTIC_VIEW below to match the actual name Snowsight
gave your semantic view (check Snowsight -> AI & ML -> Cortex Analyst
-> Semantic views tab for the exact name).
"""

import streamlit as st
import pandas as pd
import requests
import json
import os
import re
from snowflake.snowpark.context import get_active_session

# CONFIG -- update this to match your actual semantic view name

DATABASE = "HEALTHCARE_INTEROP_SIMPLE"
SCHEMA = "PUBLIC"
STAGE = "SEMANTIC_STAGE"
SEMANTIC_MODEL_FILE = "semantic_model.yaml"

session = get_active_session()

# Container Runtime doesn't expose the _snowflake helper module, so we call
# the Cortex Analyst REST API directly using the container's OAuth session
# token (read from /snowflake/session/token) and the account host, which
# Snowflake injects as an environment variable in the container.
SNOWFLAKE_HOST = os.getenv("SNOWFLAKE_HOST")


def get_token() -> str:
    """Reads the OAuth token that Snowflake injects into the container."""
    with open("/snowflake/session/token", "r") as f:
        return f.read()

st.set_page_config(page_title="HL7/FHIR Reconciliation", layout="wide")


# Design system: tokens, fonts, and reusable HTML components
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
    --bg: #F5F7F8;
    --surface: #FFFFFF;
    --border: #DCE3E6;
    --text-primary: #16232B;
    --text-secondary: #5B6B74;
    --hl7: #A8712E;
    --hl7-soft: #F1E3CE;
    --fhir: #0E7C86;
    --fhir-soft: #D9EDEF;
    --danger: #C1443C;
    --danger-soft: #F8E1DF;
    --warning: #D98C2B;
    --warning-soft: #F5E4CB;
    --success: #3F8361;
    --success-soft: #DEEEE4;
    --sidebar-bg: #142129;
    --sidebar-text: #E7EDEF;
    --sidebar-muted: #8CA0A8;
}

html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background-color: var(--bg); }
code, .stCode, [data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace !important; }

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: var(--sidebar-bg);
}
[data-testid="stSidebar"] * { color: var(--sidebar-text) !important; }
[data-testid="stSidebar"] .stRadio label { color: var(--sidebar-text) !important; }

/* Masthead */
.masthead {
    display: flex; align-items: stretch; height: 40px; border-radius: 6px;
    overflow: hidden; margin-bottom: 28px; border: 1px solid var(--border);
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 0.06em;
}
.masthead-half {
    flex: 1; display: flex; align-items: center; font-weight: 600;
}
.masthead-hl7 { background: var(--hl7); color: #FFF9F0; justify-content: flex-end; padding-right: 16px; }
.masthead-fhir { background: var(--fhir); color: #F0FAFB; justify-content: flex-start; padding-left: 16px; }
.masthead-seam {
    width: 40px; background: var(--surface); display: flex; align-items: center;
    justify-content: center; font-size: 16px; color: var(--text-primary);
    border-left: 1px solid var(--border); border-right: 1px solid var(--border);
}

/* Page header */
.page-eyebrow {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--text-secondary); margin-bottom: 4px;
}
.page-title {
    font-size: 30px; font-weight: 700; color: var(--text-primary); margin: 0 0 6px 0;
}
.page-description { color: var(--text-secondary); font-size: 15px; margin-bottom: 24px; }

/* Metric cards */
.metric-row { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.metric-card {
    background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--accent-color, var(--text-secondary));
    border-radius: 6px; padding: 14px 18px; flex: 1; min-width: 160px;
}
.metric-label {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-secondary); margin-bottom: 6px;
}
.metric-value { font-family: 'IBM Plex Mono', monospace; font-size: 26px; font-weight: 600; color: var(--text-primary); }

/* Section labels */
.section-label {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-secondary); margin: 20px 0 8px 0;
    border-bottom: 1px solid var(--border); padding-bottom: 6px;
}

/* Buttons */
.stButton button, .stDownloadButton button {
    border-radius: 5px; font-family: 'IBM Plex Sans', sans-serif; font-weight: 500;
}

/* Tabs */
[data-testid="stTabs"] button { font-family: 'IBM Plex Sans', sans-serif; font-weight: 500; }
</style>
""", unsafe_allow_html=True)


def render_masthead():
    st.markdown("""
    <div class="masthead">
        <div class="masthead-half masthead-hl7">HL7 v2 &middot; LEGACY</div>
        <div class="masthead-seam">&#8646;</div>
        <div class="masthead-half masthead-fhir">FHIR &middot; MODERN</div>
    </div>
    """, unsafe_allow_html=True)


def render_page_header(eyebrow, title, description):
    st.markdown(f"""
    <div class="page-eyebrow">{eyebrow}</div>
    <div class="page-title">{title}</div>
    <div class="page-description">{description}</div>
    """, unsafe_allow_html=True)


def render_metric_cards(cards):
    """cards: list of dicts with keys label, value, accent (hex color)"""
    html = '<div class="metric-row">'
    for c in cards:
        html += f"""
        <div class="metric-card" style="--accent-color: {c.get('accent', '#5B6B74')}">
            <div class="metric-label">{c['label']}</div>
            <div class="metric-value">{c['value']}</div>
        </div>
        """
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_section_label(text):
    st.markdown(f'<div class="section-label">{text}</div>', unsafe_allow_html=True)


DISCREPANCY_COLORS = {
    "MISSING_RECORD": "#C1443C",
    "TIMING_DRIFT": "#D98C2B",
    "CODING_MISMATCH": "#0E7C86",
    "VALUE_DISCREPANCY": "#A8712E",
}
DISCREPANCY_SOFT_COLORS = {
    "MISSING_RECORD": "#F8E1DF",
    "TIMING_DRIFT": "#F5E4CB",
    "CODING_MISMATCH": "#D9EDEF",
    "VALUE_DISCREPANCY": "#F1E3CE",
}

# Sidebar navigation
st.sidebar.markdown("""
<div style="font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em;
     text-transform: uppercase; color: #8CA0A8; margin-bottom: 2px;">HEALTHCARE INTEROPERABILITY</div>
<div style="font-family: 'IBM Plex Sans', sans-serif; font-weight: 700; font-size: 19px;
     color: #E7EDEF; margin-bottom: 20px;">HL7 &#8646; FHIR Reconciliation</div>
""", unsafe_allow_html=True)
page = st.sidebar.radio("View", ["Summary", "Patient Lookup", "Ask a Question", "Convert FHIR \u2192 HL7"])


# Shared helper: run a SQL query and return a pandas DataFrame
def run_query(sql):
    return session.sql(sql).to_pandas()


def clean_name(name):
    """Strips Synthea's trailing uniqueness digits from each name part.
    e.g. 'Alfonzo975 Brad867 Barton704' -> 'Alfonzo Brad Barton'"""
    if not isinstance(name, str):
        return name
    return re.sub(r"\d+", "", name).strip()


def clean_name_column(df, col="PATIENT_NAME"):
    """Applies clean_name to a column if it exists in the dataframe."""
    if col in df.columns:
        df[col] = df[col].apply(clean_name)
    return df


# FHIR -> HL7 conversion logic
import random
from datetime import datetime, timedelta


def _extract_patient(by_type):
    patients = by_type.get("Patient", [])
    if not patients:
        return None
    p = patients[0]
    name_entry = (p.get("name") or [{}])[0]
    given = name_entry.get("given", [])
    family = name_entry.get("family", "")
    address_entry = (p.get("address") or [{}])[0]
    mrn, ssn = None, None
    for ident in p.get("identifier", []):
        code = (ident.get("type", {}).get("coding") or [{}])[0].get("code")
        if code == "MR":
            mrn = ident.get("value")
        elif code == "SS":
            ssn = ident.get("value")
    return {
        "patient_id": p.get("id"), "mrn": mrn, "ssn": ssn,
        "family_name": family, "given_names": given,
        "gender": p.get("gender"), "birth_date": p.get("birthDate"),
        "address_line": (address_entry.get("line") or [""])[0],
        "city": address_entry.get("city"), "state": address_entry.get("state"),
        "postal_code": address_entry.get("postalCode"),
        "phone": next((t.get("value") for t in p.get("telecom", []) if t.get("system") == "phone"), None),
    }


def _within_window(period_start_str, cutoff_dt):
    if not period_start_str:
        return False
    try:
        dt = datetime.fromisoformat(period_start_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt >= cutoff_dt


def _extract_encounters(by_type, cutoff_dt):
    encounters = []
    for enc in by_type.get("Encounter", []):
        period = enc.get("period", {})
        start = period.get("start")
        if not _within_window(start, cutoff_dt):
            continue
        participant = (enc.get("participant") or [{}])[0]
        provider_display = participant.get("individual", {}).get("display")
        reason_coding = (enc.get("reasonCode") or [{}])
        reason_text = None
        if reason_coding:
            codings = reason_coding[0].get("coding") or [{}]
            reason_text = codings[0].get("display")
        location_entry = (enc.get("location") or [{}])[0]
        location_display = location_entry.get("location", {}).get("display")
        encounters.append({
            "encounter_id": enc.get("id"), "period_start": start,
            "provider": provider_display, "location": location_display,
        })
    return encounters


def _extract_lab_observations(by_type, encounter_ids):
    observations = []
    for obs in by_type.get("Observation", []):
        category_codes = [c.get("code") for cat in obs.get("category", []) for c in cat.get("coding", [])]
        if "laboratory" not in category_codes:
            continue
        enc_ref = obs.get("encounter", {}).get("reference", "")
        enc_id = enc_ref.split(":")[-1] if enc_ref else None
        if enc_id not in encounter_ids:
            continue
        code_entry = (obs.get("code", {}).get("coding") or [{}])[0]
        value_qty = obs.get("valueQuantity", {})
        observations.append({
            "observation_id": obs.get("id"), "encounter_id": enc_id,
            "loinc_code": code_entry.get("code"), "display": code_entry.get("display"),
            "value": value_qty.get("value"), "unit": value_qty.get("unit"),
        })
    return observations


def extract_fhir_bundle(bundle_json, years_back=3, reference_date=None):
    """Parses one Synthea-style FHIR Bundle JSON into patient/encounters/observations."""
    by_type = {}
    for entry in bundle_json.get("entry", []):
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType")
        if rtype:
            by_type.setdefault(rtype, []).append(resource)

    if "Patient" not in by_type:
        return None

    ref_dt = datetime.fromisoformat(reference_date) if reference_date else datetime.utcnow()
    cutoff_dt = ref_dt - timedelta(days=365 * years_back)

    patient = _extract_patient(by_type)
    encounters = _extract_encounters(by_type, cutoff_dt)
    encounter_ids = {e["encounter_id"] for e in encounters}
    observations = _extract_lab_observations(by_type, encounter_ids)

    return {"patient": patient, "encounters": encounters, "observations": observations}


def flatten_to_fhir_rows(patient_json):
    """One row per lab observation -- the flat FHIR table shape."""
    rows = []
    patient = patient_json["patient"]
    encounters_by_id = {e["encounter_id"]: e for e in patient_json["encounters"]}
    for obs in patient_json["observations"]:
        enc = encounters_by_id.get(obs["encounter_id"], {})
        given = " ".join(patient.get("given_names", []) or [])
        rows.append({
            "observation_id": obs["observation_id"], "patient_id": patient["patient_id"],
            "patient_name": f"{given} {patient['family_name']}".strip(),
            "dob": patient["birth_date"], "gender": patient["gender"],
            "encounter_id": obs["encounter_id"], "encounter_date": enc.get("period_start", ""),
            "provider": enc.get("provider", ""), "lab_code": obs["loinc_code"],
            "lab_name": obs["display"], "lab_value": obs["value"], "lab_unit": obs["unit"],
        })
    return rows


def _shift_date(date_str, hours_range=(1, 4)):
    if not date_str:
        return date_str
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        return date_str
    shift = random.choice([1, -1]) * random.randint(*hours_range)
    return (dt + timedelta(hours=shift)).isoformat()


def build_hl7_rows(fhir_rows, mutation_rate=0.15, seed=42):
    """Copies FHIR rows, deliberately corrupts ~mutation_rate of them, logs ground truth."""
    random.seed(seed)
    hl7_rows, ground_truth = [], []
    for row in fhir_rows:
        hl7_row = dict(row)
        if random.random() < mutation_rate:
            mutation = random.choice(["timing", "coding", "value", "drop"])
            if mutation == "drop":
                ground_truth.append({**row, "mutation_type": "DROPPED_RECORD"})
                continue
            elif mutation == "timing":
                original = row["encounter_date"]
                hl7_row["encounter_date"] = _shift_date(original)
                ground_truth.append({**row, "mutation_type": "TIMING_DRIFT",
                                      "original_value": original, "mutated_value": hl7_row["encounter_date"]})
            elif mutation == "coding":
                original = row["lab_code"]
                hl7_row["lab_code"] = "LOCAL_" + original
                ground_truth.append({**row, "mutation_type": "CODING_MISMATCH",
                                      "original_value": original, "mutated_value": hl7_row["lab_code"]})
            elif mutation == "value":
                try:
                    original = float(row["lab_value"])
                    pct = random.uniform(0.05, 0.15) * random.choice([1, -1])
                    hl7_row["lab_value"] = round(original * (1 + pct), 2)
                    ground_truth.append({**row, "mutation_type": "VALUE_DISCREPANCY",
                                          "original_value": str(original), "mutated_value": str(hl7_row["lab_value"])})
                except (ValueError, TypeError):
                    pass
        hl7_rows.append(hl7_row)
    return hl7_rows, ground_truth


# PAGE 1: Summary
if page == "Summary":
    render_masthead()
    render_page_header(
        "OVERVIEW",
        "Reconciliation Summary",
        "Comparing FHIR (modern) vs HL7 v2 (legacy) lab result data for the same patients.",
    )

    total_fhir = run_query(f"SELECT COUNT(*) AS n FROM {DATABASE}.{SCHEMA}.PATIENTS_FHIR").iloc[0]["N"]
    total_discrepancies = run_query(f"SELECT COUNT(*) AS n FROM {DATABASE}.{SCHEMA}.DISCREPANCIES").iloc[0]["N"]
    match_rate = 100 * (1 - total_discrepancies / total_fhir) if total_fhir else 0
    match_color = "#3F8361" if match_rate >= 90 else ("#D98C2B" if match_rate >= 75 else "#C1443C")

    render_metric_cards([
        {"label": "Total FHIR Lab Records", "value": f"{total_fhir:,}", "accent": "#5B6B74"},
        {"label": "Total Discrepancies", "value": f"{total_discrepancies:,}", "accent": "#D98C2B"},
        {"label": "Match Rate", "value": f"{match_rate:.1f}%", "accent": match_color},
    ])

    render_section_label("DISCREPANCIES BY TYPE")
    type_counts = run_query(f"""
        SELECT DISCREPANCY_TYPE, COUNT(*) AS COUNT
        FROM {DATABASE}.{SCHEMA}.DISCREPANCIES
        GROUP BY DISCREPANCY_TYPE
        ORDER BY COUNT DESC
    """)
    st.bar_chart(type_counts.set_index("DISCREPANCY_TYPE"), color="#0E7C86")

    render_section_label("ALL DETECTED DISCREPANCIES")
    st.caption("Filter and explore every mismatch found between the two data sources.")

    type_filter = st.multiselect(
        "Filter by discrepancy type",
        options=type_counts["DISCREPANCY_TYPE"].tolist(),
        default=type_counts["DISCREPANCY_TYPE"].tolist(),
    )

    if type_filter:
        filter_clause = "', '".join(type_filter)
        detail_df = run_query(f"""
            SELECT PATIENT_NAME, ENCOUNTER_ID, LAB_NAME, DISCREPANCY_TYPE, FHIR_VALUE, HL7_VALUE
            FROM {DATABASE}.{SCHEMA}.DISCREPANCIES
            WHERE DISCREPANCY_TYPE IN ('{filter_clause}')
            ORDER BY PATIENT_NAME
            LIMIT 500
        """)
        detail_df = clean_name_column(detail_df)

        def highlight_type(row):
            color = DISCREPANCY_SOFT_COLORS.get(row["DISCREPANCY_TYPE"], "")
            return [f"background-color: {color}" if col == "DISCREPANCY_TYPE" else "" for col in row.index]

        styled_detail = detail_df.style.apply(highlight_type, axis=1)
        st.dataframe(styled_detail, use_container_width=True)
    else:
        st.info("Select at least one discrepancy type above to see details.")


# PAGE 2: Patient Lookup
elif page == "Patient Lookup":
    render_masthead()
    render_page_header(
        "PATIENT-LEVEL COMPARISON",
        "Patient Lookup",
        "Compare the FHIR and HL7 versions of a single patient's lab results, side by side.",
    )

    patients = run_query(f"""
        SELECT DISTINCT PATIENT_ID, PATIENT_NAME
        FROM {DATABASE}.{SCHEMA}.PATIENTS_FHIR
        ORDER BY PATIENT_NAME
    """)
    patients["DISPLAY_NAME"] = patients["PATIENT_NAME"].apply(clean_name)

    patient_choice = st.selectbox(
        "Select a patient",
        options=patients["PATIENT_ID"].tolist(),
        format_func=lambda pid: patients.loc[patients["PATIENT_ID"] == pid, "DISPLAY_NAME"].values[0],
    )

    if patient_choice:
        fhir_df = run_query(f"""
            SELECT OBSERVATION_ID, ENCOUNTER_DATE, LAB_NAME, LAB_CODE, LAB_VALUE, LAB_UNIT
            FROM {DATABASE}.{SCHEMA}.PATIENTS_FHIR
            WHERE PATIENT_ID = '{patient_choice}'
            ORDER BY ENCOUNTER_DATE
        """)
        hl7_df = run_query(f"""
            SELECT OBSERVATION_ID, ENCOUNTER_DATE, LAB_NAME, LAB_CODE, LAB_VALUE, LAB_UNIT
            FROM {DATABASE}.{SCHEMA}.PATIENTS_HL7
            WHERE PATIENT_ID = '{patient_choice}'
            ORDER BY ENCOUNTER_DATE
        """)

        st.markdown(f"""
        <div class="page-title" style="font-size: 22px; margin-top: 8px;">{patients.loc[patients['PATIENT_ID'] == patient_choice, 'DISPLAY_NAME'].values[0]}</div>
        """, unsafe_allow_html=True)

        missing_count = len(fhir_df) - len(hl7_df)
        render_metric_cards([
            {"label": "FHIR Records", "value": len(fhir_df), "accent": "#0E7C86"},
            {"label": "HL7 Records", "value": len(hl7_df), "accent": "#A8712E"},
            {"label": "Missing from HL7", "value": missing_count, "accent": "#C1443C" if missing_count else "#3F8361"},
        ])

        # Merge on observation_id to highlight mismatches
        merged = fhir_df.merge(
            hl7_df, on="OBSERVATION_ID", how="left", suffixes=("_FHIR", "_HL7")
        )

        def highlight_mismatch(row):
            styles = [""] * len(row)
            if pd.isna(row.get("LAB_VALUE_HL7")):
                return [f"background-color: {DISCREPANCY_SOFT_COLORS['MISSING_RECORD']}"] * len(row)
            if row.get("LAB_CODE_FHIR") != row.get("LAB_CODE_HL7"):
                styles = [f"background-color: {DISCREPANCY_SOFT_COLORS['CODING_MISMATCH']}" if "LAB_CODE" in col else s for col, s in zip(row.index, styles)]
            if str(row.get("LAB_VALUE_FHIR")) != str(row.get("LAB_VALUE_HL7")):
                styles = [f"background-color: {DISCREPANCY_SOFT_COLORS['VALUE_DISCREPANCY']}" if "LAB_VALUE" in col else s for col, s in zip(row.index, styles)]
            if str(row.get("ENCOUNTER_DATE_FHIR")) != str(row.get("ENCOUNTER_DATE_HL7")):
                styles = [f"background-color: {DISCREPANCY_SOFT_COLORS['TIMING_DRIFT']}" if "ENCOUNTER_DATE" in col else s for col, s in zip(row.index, styles)]
            return styles

        render_section_label("SIDE-BY-SIDE COMPARISON")
        st.markdown(f"""
        <div style="display: flex; gap: 16px; font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;">
            <span><span style="display:inline-block;width:10px;height:10px;background:{DISCREPANCY_SOFT_COLORS['MISSING_RECORD']};border:1px solid {DISCREPANCY_COLORS['MISSING_RECORD']};margin-right:5px;"></span>Missing from HL7</span>
            <span><span style="display:inline-block;width:10px;height:10px;background:{DISCREPANCY_SOFT_COLORS['CODING_MISMATCH']};border:1px solid {DISCREPANCY_COLORS['CODING_MISMATCH']};margin-right:5px;"></span>Coding mismatch</span>
            <span><span style="display:inline-block;width:10px;height:10px;background:{DISCREPANCY_SOFT_COLORS['VALUE_DISCREPANCY']};border:1px solid {DISCREPANCY_COLORS['VALUE_DISCREPANCY']};margin-right:5px;"></span>Value mismatch</span>
            <span><span style="display:inline-block;width:10px;height:10px;background:{DISCREPANCY_SOFT_COLORS['TIMING_DRIFT']};border:1px solid {DISCREPANCY_COLORS['TIMING_DRIFT']};margin-right:5px;"></span>Timing drift</span>
        </div>
        """, unsafe_allow_html=True)

        display_cols = [
            "LAB_NAME_FHIR", "LAB_CODE_FHIR", "LAB_CODE_HL7",
            "LAB_VALUE_FHIR", "LAB_VALUE_HL7",
            "ENCOUNTER_DATE_FHIR", "ENCOUNTER_DATE_HL7",
        ]
        styled = merged[display_cols].style.apply(highlight_mismatch, axis=1)
        st.dataframe(styled, use_container_width=True)


# PAGE 3: Ask a Question (Cortex Analyst)
elif page == "Ask a Question":
    render_masthead()
    render_page_header(
        "NATURAL LANGUAGE QUERY",
        "Ask a Question",
        "Ask a plain-English question about the reconciliation data. Powered by Cortex Analyst.",
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    def send_message(prompt: str) -> dict:
        """Calls the Cortex Analyst REST API with the given question."""
        request_body = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "semantic_model_file": f"@{DATABASE}.{SCHEMA}.{STAGE}/{SEMANTIC_MODEL_FILE}",
        }
        resp = requests.post(
            url=f"https://{SNOWFLAKE_HOST}/api/v2/cortex/analyst/message",
            json=request_body,
            headers={
                "Authorization": f"Bearer {get_token()}",
                "X-Snowflake-Authorization-Token-Type": "OAUTH",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code < 400:
            return resp.json()
        else:
            raise Exception(f"Cortex Analyst error ({resp.status_code}): {resp.text}")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "sql" in msg:
                with st.expander("View generated SQL"):
                    st.code(msg["sql"], language="sql")
            if "df" in msg:
                st.dataframe(msg["df"], use_container_width=True)

    if question := st.chat_input("e.g. How many discrepancies are there of each type?"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = send_message(question)
                    content_items = response["message"]["content"]

                    answer_text = ""
                    sql = None
                    for item in content_items:
                        if item["type"] == "text":
                            answer_text += item["text"]
                        elif item["type"] == "sql":
                            sql = item["statement"]

                    st.write(answer_text if answer_text else "Here's what I found:")

                    result_df = None
                    if sql:
                        with st.expander("View generated SQL"):
                            st.code(sql, language="sql")
                        result_df = run_query(sql)
                        result_df = clean_name_column(result_df)
                        st.dataframe(result_df, use_container_width=True)

                    assistant_msg = {"role": "assistant", "content": answer_text}
                    if sql:
                        assistant_msg["sql"] = sql
                    if result_df is not None:
                        assistant_msg["df"] = result_df
                    st.session_state.messages.append(assistant_msg)

                except Exception as e:
                    st.error(f"Something went wrong: {e}")


# PAGE 4: Convert FHIR -> HL7
elif page == "Convert FHIR \u2192 HL7":
    render_masthead()
    render_page_header(
        "DATA PIPELINE UTILITY",
        "Convert FHIR \u2192 HL7",
        "Upload a Synthea-style FHIR Bundle JSON file for a single patient. This tool extracts "
        "their recent lab data, then generates a matching HL7-style version with realistic "
        "data-quality issues deliberately injected \u2014 the same logic used to build this project's dataset.",
    )

    col1, col2, col3 = st.columns(3)
    years_back = col1.number_input("Years of history to keep", min_value=1, max_value=20, value=3)
    mutation_rate = col2.slider("Mutation rate (simulated errors)", 0.0, 1.0, 0.15)
    seed = col3.number_input("Random seed (for reproducibility)", value=42)

    uploaded_file = st.file_uploader("Upload a FHIR Bundle (.json)", type=["json"])

    if uploaded_file is not None:
        try:
            bundle_json = json.load(uploaded_file)
        except json.JSONDecodeError:
            st.error("That file isn't valid JSON. Please upload a FHIR Bundle JSON file.")
            st.stop()

        extracted = extract_fhir_bundle(bundle_json, years_back=years_back)

        if extracted is None:
            st.error("No Patient resource found in this file. This tool expects a single-patient FHIR Bundle (Synthea's per-patient export format).")
        elif not extracted["encounters"]:
            st.warning(f"This patient has no encounters within the last {years_back} year(s). Try increasing the years window.")
        else:
            fhir_rows = flatten_to_fhir_rows(extracted)
            hl7_rows, ground_truth = build_hl7_rows(fhir_rows, mutation_rate=mutation_rate, seed=seed)

            fhir_df = pd.DataFrame(fhir_rows)
            hl7_df = pd.DataFrame(hl7_rows)
            gt_df = pd.DataFrame(ground_truth)

            st.success(
                f"Converted {len(fhir_rows)} FHIR lab records \u2192 {len(hl7_rows)} HL7 records "
                f"({len(fhir_rows) - len(hl7_rows)} dropped, {len(ground_truth)} discrepancies injected)."
            )

            tab1, tab2, tab3 = st.tabs(["FHIR (source)", "HL7 (converted)", "Injected discrepancies"])
            with tab1:
                st.dataframe(fhir_df, use_container_width=True)
                st.download_button("Download FHIR CSV", fhir_df.to_csv(index=False), "patient_fhir.csv", "text/csv")
            with tab2:
                st.dataframe(hl7_df, use_container_width=True)
                st.download_button("Download HL7 CSV", hl7_df.to_csv(index=False), "patient_hl7.csv", "text/csv")
            with tab3:
                if len(gt_df):
                    st.dataframe(gt_df, use_container_width=True)
                    st.download_button("Download discrepancy log CSV", gt_df.to_csv(index=False), "patient_discrepancies.csv", "text/csv")
                else:
                    st.info("No discrepancies were injected for this patient at the current mutation rate/seed.")