import streamlit as st
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.database.connection import SessionLocal
from backend.database.models import Department, DocumentTemplate, TemplateSection, SectionField

st.set_page_config(page_title="DocForge Hub", page_icon="📄", layout="wide")

st.title("📄 DocForge Hub")
st.subheader("AI-Powered Business Document Generator")
st.divider()

db = SessionLocal()

# --- Dropdown 1: Department ---
departments = db.query(Department).all()
dept_names = [d.name for d in departments]
dept_map = {d.name: d.id for d in departments}

selected_dept = st.selectbox("🏢 Select Department", dept_names)

# --- Dropdown 2: Document Type ---
if selected_dept:
    dept_id = dept_map[selected_dept]
    templates = db.query(DocumentTemplate).filter(
        DocumentTemplate.department_id == dept_id
    ).all()
    template_names = [t.name for t in templates]
    template_map = {t.name: t.id for t in templates}

    selected_template = st.selectbox("📋 Select Document Type", template_names)

    # --- Show Sections ---
    if selected_template:
        template_id = template_map[selected_template]
        sections = db.query(TemplateSection).filter(
            TemplateSection.template_id == template_id
        ).order_by(TemplateSection.section_order).all()

        st.divider()
        st.markdown(f"### 📑 Sections for **{selected_template}**")

        for section in sections:
            with st.expander(f"📌 {section.section_name}"):
                fields = db.query(SectionField).filter(
                    SectionField.section_id == section.id
                ).all()
                for field in fields:
                    required = "\\*" if field.is_required else ""
                    st.markdown(f"- **{field.field_label}** {required} `{field.field_type}`")

st.divider()
st.caption("DocForge Hub — Powered by AI")

db.close()