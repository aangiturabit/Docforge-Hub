import streamlit as st
import requests
from docx import Document
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO

API_BASE = "http://127.0.0.1:8000/api"

st.set_page_config(page_title="DocForge Hub", page_icon="📄", layout="wide")
st.title("📄 DocForge Hub")
st.subheader("AI-Powered Business Document Generator")
st.divider()

# ─────────────────────────────────────────
# FILE GENERATION FUNCTIONS
# ─────────────────────────────────────────

def generate_docx(title, content):
    doc = Document()
    doc.add_heading(title, 0)

    for line in content.split("\n"):
        doc.add_paragraph(line)

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_pdf(title, content):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)

    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{title}</b>", styles["Title"]))

    for line in content.split("\n"):
        story.append(Paragraph(line, styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ─────────────────────────────────────────
# SCREEN 1 — SELECT TEMPLATE
# ─────────────────────────────────────────

with st.container():
    st.markdown("### 🏢 Step 1: Choose Department & Document")

    dept_response = requests.get(f"{API_BASE}/departments")
    departments = dept_response.json()
    dept_names = [d["name"] for d in departments]
    dept_map = {d["name"]: d["id"] for d in departments}

    selected_dept = st.selectbox("Select Department", dept_names)

    if selected_dept:
        dept_id = dept_map[selected_dept]

        tmpl_response = requests.get(f"{API_BASE}/templates/{dept_id}")
        templates = tmpl_response.json()
        tmpl_names = [t["name"] for t in templates]
        tmpl_map = {t["name"]: t["id"] for t in templates}

        selected_template = st.selectbox("Select Document Type", tmpl_names)

        if selected_template:
            template_id = tmpl_map[selected_template]

            if st.button("🚀 Generate Questions", use_container_width=True):
                with st.spinner("Generating smart questions..."):
                    response = requests.post(
                        f"{API_BASE}/generate/questions",
                        json={"document_type_id": template_id}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        st.session_state.update({
                            "session_id": data["session_id"],
                            "sections": data["sections"],
                            "department_id": dept_id,
                            "template_id": template_id,
                            "template_name": selected_template
                        })
                        st.success("Questions ready!")
                    else:
                        st.error(f"Error: {response.text}")

# ─────────────────────────────────────────
# SCREEN 2 — FORM INPUT
# ─────────────────────────────────────────

if "sections" in st.session_state:
    st.divider()
    st.markdown(f"### 📝 Step 2: Fill Details for **{st.session_state['template_name']}**")

    answers = {}

    for section in st.session_state["sections"]:
        with st.expander(f"📌 {section['section_name']}", expanded=True):
            for field in section["fields"]:
                field_name = field["field_name"]
                label = field["field_label"]
                field_type = field["field_type"]
                required = field["is_required"]

                label_display = f"{label} *" if required else label

                if field_type == "textarea":
                    answers[field_name] = st.text_area(label_display, key=field_name)
                elif field_type == "date":
                    answers[field_name] = str(st.date_input(label_display, key=field_name))
                elif field_type == "number":
                    answers[field_name] = str(st.number_input(label_display, key=field_name))
                else:
                    answers[field_name] = st.text_input(label_display, key=field_name)

    st.session_state["answers"] = answers

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("👁️ Preview", use_container_width=True):
            with st.spinner("Generating preview..."):
                response = requests.post(
                    f"{API_BASE}/generate/preview",
                    json={
                        "department_id": st.session_state["department_id"],
                        "template_id": st.session_state["template_id"],
                        "answers": answers
                    }
                )
                if response.status_code == 200:
                    st.session_state["preview_content"] = response.json()["content"]
                else:
                    st.error(f"Error: {response.text}")

    with col2:
        if st.button("📄 Generate", use_container_width=True):
            with st.spinner("Generating document..."):
                response = requests.post(
                    f"{API_BASE}/generate/document",
                    json={
                        "session_id": st.session_state["session_id"],
                        "department_id": st.session_state["department_id"],
                        "template_id": st.session_state["template_id"],
                        "answers": answers
                    }
                )
                if response.status_code == 200:
                    st.session_state["document"] = response.json()
                    st.success("Document generated!")
                else:
                    st.error(f"Error: {response.text}")

# ─────────────────────────────────────────
# PREVIEW
# ─────────────────────────────────────────

if "preview_content" in st.session_state:
    st.divider()
    st.markdown("### 👁️ Preview")
    st.markdown(st.session_state["preview_content"])

# ─────────────────────────────────────────
# SCREEN 3 — OUTPUT
# ─────────────────────────────────────────

if "document" in st.session_state:
    doc = st.session_state["document"]

    st.divider()
    st.markdown(f"## 📄 {doc['title']}")
    st.markdown(doc["content"])

    st.divider()
    st.markdown("### 📥 Download Options")

    col1, col2, col3 = st.columns(3)

    with col1:
        pdf_file = generate_pdf(doc["title"], doc["content"])
        st.download_button("⬇️ PDF", pdf_file, f"{doc['title']}.pdf")

    with col2:
        docx_file = generate_docx(doc["title"], doc["content"])
        st.download_button("⬇️ DOCX", docx_file, f"{doc['title']}.docx")

    with col3:
        if "show_regen" not in st.session_state:
            st.session_state["show_regen"] = False

        if st.button("🔁 Regenerate"):
            st.session_state["show_regen"] = True

        if st.session_state["show_regen"]:
            feedback = st.text_input("Feedback (optional)")

            if st.button("Confirm"):
                with st.spinner("Regenerating..."):
                    response = requests.post(
                        f"{API_BASE}/generate/regenerate",
                        json={
                            "session_id": st.session_state["session_id"],
                            "answers": st.session_state["answers"],
                            "feedback": feedback
                        }
                    )

                    if response.status_code == 200:
                        st.session_state["document"] = response.json()
                        st.session_state["show_regen"] = False
                        st.rerun()
                    else:
                        st.error(f"Error: {response.text}")

st.divider()
st.caption("DocForge Hub — Powered by AI 🚀")
