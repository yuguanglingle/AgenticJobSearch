"""Streamlit UI for candidate profile management."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
AGENTS_DIR = BASE_DIR.parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from src.agent import generate_candidate_profile
from src.models import CandidateProfileRequest, CandidatePreferences
from src import db

load_dotenv(BASE_DIR / ".env")
load_dotenv(AGENTS_DIR / ".env")

st.set_page_config(page_title="Candidate Profile Agent", layout="wide")

st.title("Candidate Profile Agent")

if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""

if "preferences" not in st.session_state:
    st.session_state.preferences = {
        "locations": "",
        "remote_preference": "any",
        "role_targets": "",
        "industries": "",
        "dealbreakers": "",
        "comp_min": None,
        "work_auth": "",
    }

if "usage_summary" not in st.session_state:
    st.session_state.usage_summary = None

if "usage_raw" not in st.session_state:
    st.session_state.usage_raw = None

if "generated_envelope" not in st.session_state:
    st.session_state.generated_envelope = None


with st.sidebar:
    st.header("Saved Candidates")
    candidates = db.list_candidates()
    options = ["(new)"] + [c.id for c in candidates]
    labels = {"(new)": "(new)"}
    for c in candidates:
        try:
            profile = json.loads(c.candidate_profile_json)
            headline = profile.get("result", {}).get("candidate_profile", {}).get("headline", "(no headline)")
        except Exception:
            headline = "(invalid JSON)"
        labels[c.id] = f"{headline} - {c.updated_at}"

    selected = st.selectbox(
        "Select", options, format_func=lambda x: labels.get(x, x)
    )

    if selected != "(new)":
        record = db.get_candidate(selected)
        prefs = db.get_candidate_preferences(selected)
        if record:
            st.session_state.resume_text = record.resume_raw
        if prefs:
            st.session_state.preferences = {
                "locations": ", ".join(json.loads(prefs.locations or "[]")),
                "remote_preference": prefs.remote_preference or "any",
                "role_targets": ", ".join(json.loads(prefs.role_targets or "[]")),
                "industries": ", ".join(json.loads(prefs.industries or "[]")),
                "dealbreakers": ", ".join(json.loads(prefs.dealbreakers or "[]")),
                "comp_min": prefs.comp_min,
                "work_auth": prefs.work_auth or "",
            }


col1, col2, col3 = st.columns([2, 1, 1], gap="large")


with col1:
    st.subheader("📄 Resume")
    
    # Upload resume file
    uploaded_file = st.file_uploader(
        "Upload Resume",
        type=["pdf", "txt", "doc", "docx"],
        key="resume_uploader"
    )
    
    if uploaded_file is not None:
        try:
            if uploaded_file.type == "text/plain":
                resume_text = uploaded_file.getvalue().decode("utf-8")
            elif uploaded_file.type in ["application/pdf"]:
                st.info("PDF files require pdf2image and pytesseract. Please upload TXT or DOCX.")
                resume_text = st.session_state.resume_text
            elif uploaded_file.type in ["application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
                st.info("DOCX files require python-docx. Please upload TXT for now.")
                resume_text = st.session_state.resume_text
            else:
                resume_text = uploaded_file.getvalue().decode("utf-8")
            
            st.session_state.resume_text = resume_text
            st.success(f"✓ Loaded: {uploaded_file.name}")
        except Exception as e:
            st.error(f"Error reading file: {str(e)}")
            resume_text = st.session_state.resume_text
    else:
        resume_text = st.session_state.resume_text
    
    # Alternative: paste resume text
    with st.expander("Or paste resume text"):
        resume_text = st.text_area(
            "Resume Text",
            value=resume_text,
            height=300,
            key="resume_paste"
        )
        st.session_state.resume_text = resume_text


# ============= OLD COL1 CODE (COMMENTED OUT FOR LATER) =============
# with col1:
#     st.subheader("Input")
#     if st.button("Load Sample Resume"):
#         sample_path = BASE_DIR / "samples" / "resume.txt"
#         with open(sample_path, "r", encoding="utf-8") as f:
#             st.session_state.resume_text = f.read()
#
#     resume_text = st.text_area(
#         "Resume Text",
#         value=st.session_state.resume_text,
#         height=300,
#     )
# ============= END OLD COL1 CODE =============

with col2:
    st.subheader("Preferences")
    locations = st.text_input("Locations (comma-separated)", value=st.session_state.preferences["locations"])
    remote_preference = st.selectbox(
        "Remote Preference",
        options=["remote", "hybrid", "onsite", "any"],
        index=["remote", "hybrid", "onsite", "any"].index(st.session_state.preferences["remote_preference"]),
    )
    role_targets = st.text_input("Role Targets (comma-separated)", value=st.session_state.preferences["role_targets"])
    industries = st.text_input("Industries (comma-separated)", value=st.session_state.preferences["industries"])
    dealbreakers = st.text_input("Dealbreakers (comma-separated)", value=st.session_state.preferences["dealbreakers"])
    comp_min = st.number_input("Minimum Compensation", min_value=0, value=st.session_state.preferences["comp_min"] or 0)
    work_auth = st.text_input("Work Authorization", value=st.session_state.preferences["work_auth"])

with col3:
    st.subheader("🚀 Actions")
    
    if st.button("Generate Profile", use_container_width=True, type="primary"):
        try:
            prefs = CandidatePreferences(
                locations=[s.strip() for s in locations.split(",") if s.strip()],
                remote_preference=remote_preference,
                role_targets=[s.strip() for s in role_targets.split(",") if s.strip()],
                industries=[s.strip() for s in industries.split(",") if s.strip()],
                dealbreakers=[s.strip() for s in dealbreakers.split(",") if s.strip()],
                comp_min=int(comp_min) if comp_min else None,
                work_auth=work_auth.strip() or None,
            )
            request = CandidateProfileRequest(
                resume_text=resume_text,
                preferences=prefs,
            )
            envelope, usage_summary, usage_raw = generate_candidate_profile(request)
            st.session_state.generated_envelope = envelope
            st.session_state.usage_summary = usage_summary
            st.session_state.usage_raw = usage_raw
            st.success("✓ Profile generated!")
        except Exception as exc:
            st.error(f"Error: {str(exc)}")
            print(f"Candidate profile generation failed: {exc}")
    
    st.divider()
    
    if st.session_state.generated_envelope:
        envelope = st.session_state.generated_envelope
        profile = envelope.result.candidate_profile
        
        st.subheader("📊 Results")
        st.caption(profile.headline)
        st.metric("Seniority", profile.seniority_estimate)
        st.write(f"**Skills:** {', '.join(profile.core_skills[:5])}")
        st.write(f"**Domains:** {', '.join(profile.domains[:3])}")
        
        with st.expander("View JSON"):
            st.code(envelope.model_dump_json(indent=2), language="json")
        
        if st.session_state.usage_summary:
            st.info(st.session_state.usage_summary)
    
    elif selected != "(new)":
        record = db.get_candidate(selected)
        if record:
            st.subheader("📋 Saved Profile")
            try:
                saved = json.loads(record.candidate_profile_json)
                profile = saved.get("result", {}).get("candidate_profile", {})
                st.caption(profile.get("headline", "N/A"))
                st.metric("Seniority", profile.get("seniority_estimate", "N/A"))
                with st.expander("View JSON"):
                    st.code(json.dumps(saved, indent=2), language="json")
            except Exception as e:
                st.error(f"Invalid JSON: {str(e)}")
    else:
        st.info("👈 Generate a profile or select a saved candidate")

