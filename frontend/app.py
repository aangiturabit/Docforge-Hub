import json
from datetime import datetime

import requests
import streamlit as st

API_BASE = "http://localhost:8000/api"

st.set_page_config(
    page_title="DocForge Hub",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ═══════════════════════════════════════════════════════
# API HELPERS
# ═══════════════════════════════════════════════════════

def api_get(path, params=None, show_error=True):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if show_error:
            st.error(f"API {r.status_code}: {r.text[:200]}")
        return None
    except requests.exceptions.ConnectionError:
        if show_error:
            st.error("Cannot connect to backend. Is the server running?")
        return None
    except Exception as e:
        if show_error:
            st.error(str(e))
        return None


def api_post(path, body, show_error=True):
    try:
        r = requests.post(f"{API_BASE}{path}", json=body, timeout=180)
        if r.status_code == 200:
            return r.json(), None
        err = r.text[:200]
        if show_error:
            st.error(f"API {r.status_code}: {err}")
        return None, err
    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to backend"
    except Exception as e:
        return None, str(e)


def api_delete(path, show_error=True):
    try:
        r = requests.delete(f"{API_BASE}{path}", timeout=30)
        if r.status_code == 200:
            return True
        if show_error:
            st.error(f"API {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        if show_error:
            st.error(str(e))
        return False


def fetch_pdf(document_id: int, company: dict = None):
    try:
        params = {}
        if company:
            params["company_json"] = json.dumps(company)
        r = requests.get(f"{API_BASE}/documents/{document_id}/pdf", params=params, timeout=60)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


def fetch_docx(document_id: int, company: dict = None):
    try:
        params = {}
        if company:
            params["company_json"] = json.dumps(company)
        r = requests.get(f"{API_BASE}/documents/{document_id}/docx", params=params, timeout=60)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════

def short_name(name, max_len=45):
    if len(name) <= max_len:
        return name
    cut        = name[:max_len]
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 20 else cut) + "…"


def format_date(dt_str):
    try:
        return datetime.fromisoformat(dt_str).strftime("%d %b %Y")
    except Exception:
        return dt_str or "—"


STATUS_ICON  = {"validated": "🟢", "pending": "🟡", "needs_review": "🟠", "failed": "🔴", "draft": "🔵"}
STATUS_LABEL = {"validated": "Validated", "pending": "Pending", "needs_review": "Needs Review", "failed": "Failed", "draft": "Draft"}


def status_display(status):
    icon  = STATUS_ICON.get(status, "⚪")
    label = STATUS_LABEL.get(status, status.replace("_", " ").title() if status else "Pending")
    return f"{icon} {label}"


def company_sig(company):
    return json.dumps(company or {}, sort_keys=True)


def get_sections(doc):
    if not doc:
        return []
    raw = doc.get("structured_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return parsed.get("sections", [])
    except Exception:
        pass
    return []


def escape_pipe(text):
    return str(text).replace("|", "\\|")


# ═══════════════════════════════════════════════════════
# RENDERERS
# ═══════════════════════════════════════════════════════

def render_section_content(section):
    ctype   = section.get("content_type", "text")
    content = section.get("content", "")

    if ctype == "text" and isinstance(content, str):
        for para in content.split("\n\n"):
            p = para.strip()
            if p:
                st.write(p)

    elif ctype == "table" and isinstance(content, list) and content:
        headers   = [escape_pipe(c) for c in content[0].get("cells", [])]
        rows      = [[escape_pipe(c) for c in r.get("cells", [])] for r in content[1:]]
        if headers:
            sep       = " | ".join(["---"] * len(headers))
            data_rows = "\n".join("| " + " | ".join(r) + " |" for r in rows)
            st.markdown(f"| {' | '.join(headers)} |\n| {sep} |\n{data_rows}")

    elif ctype == "list" and isinstance(content, list):
        for item in content:
            st.markdown(f"- {item}")


def render_plain(content):
    if not content:
        st.info("No content to display.")
        return
    for line in content.split("\n"):
        s = line.strip()
        if not s:
            continue
        if len(s) < 65 and not s.startswith("-") and len(s.split()) <= 9:
            st.markdown(f"**{s}**")
        elif s.startswith("- "):
            st.markdown(s)
        else:
            st.write(s)


# ═══════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════

_defaults = {
    "session_id":        None,
    "sections":          None,
    "department_id":     None,
    "template_id":       None,
    "template_name":     None,
    "department_name":   None,
    "document":          None,
    "preview_content":   None,
    "answers":           {},
    "library_doc":       None,
    "_loaded_combo":     None,
    "_loaded_company":   None,
    # FIX: track whether we are in preview mode without destroying the document
    "_in_preview":       False,
    # Action flags — survive st.rerun()
    "_do_generate":      False,
    "_do_preview":       False,
    "_do_regen_section": None,
    "_regen_feedback":   "",
    "company": {
        "name": "", "industry": "", "size": "",
        "location": "", "tone": "Professional",
    },
}

for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### Company Context")
    st.caption("Optional — improves document quality")
    st.divider()

    co             = st.session_state["company"]
    co["name"]     = st.text_input("Company Name",  value=co["name"],     placeholder="Acme Corp")
    co["industry"] = st.text_input("Industry",      value=co["industry"], placeholder="Technology")

    _sizes = ["", "1–10", "11–50", "51–200", "201–500", "500+"]
    co["size"] = st.selectbox(
        "Company Size", _sizes,
        index=_sizes.index(co.get("size", "")) if co.get("size", "") in _sizes else 0,
    )
    co["location"] = st.text_input("Location", value=co["location"], placeholder="Mumbai, India")

    _tones = ["Professional", "Formal", "Friendly", "Technical", "Empathetic"]
    co["tone"] = st.selectbox(
        "Tone", _tones,
        index=_tones.index(co.get("tone", "Professional")),
    )
    st.divider()
    st.caption("DocForge Hub · v1.0")


# ═══════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════

st.markdown("# DocForge Hub")
st.caption("AI-powered document generation")
st.divider()


# ═══════════════════════════════════════════════════════
# DEPARTMENT + TEMPLATE SELECTORS
# ═══════════════════════════════════════════════════════

dept_data  = api_get("/departments", show_error=False) or []
dept_names = [d["name"] for d in dept_data]
dept_map   = {d["name"]: d["id"] for d in dept_data}

if not dept_names:
    st.warning("No departments found. Check the backend is running.")
    st.stop()

sel_col1, sel_col2 = st.columns([1, 2])

with sel_col1:
    dept_idx      = st.selectbox(
        "Department",
        options=range(len(dept_names)),
        format_func=lambda i: dept_names[i],
        key="sb_dept_idx",
    )
    selected_dept = dept_names[dept_idx]

dept_id   = dept_map[selected_dept]
tmpl_data = api_get(f"/templates/{dept_id}", show_error=False) or []

tmpl_display_map   = {short_name(t["name"]): t["name"] for t in tmpl_data}
tmpl_map           = {t["name"]: t["id"] for t in tmpl_data}
tmpl_display_names = [short_name(t["name"]) for t in tmpl_data]
selected_template  = None

with sel_col2:
    if tmpl_display_names:
        tmpl_idx = st.selectbox(
            "Document Type",
            options=range(len(tmpl_display_names)),
            format_func=lambda i: tmpl_display_names[i],
            key="sb_tmpl_idx",
        )
        selected_template = tmpl_display_map.get(tmpl_display_names[tmpl_idx])
    else:
        st.selectbox("Document Type", ["No templates found"], disabled=True)

st.divider()


# ═══════════════════════════════════════════════════════
# AUTO-LOAD QUESTIONS
# ═══════════════════════════════════════════════════════

def auto_load_questions():
    if not selected_dept or not selected_template:
        return

    current_combo   = f"{selected_dept}||{selected_template}"
    current_company = company_sig(st.session_state.get("company"))
    combo_changed   = st.session_state.get("_loaded_combo") != current_combo
    company_changed = (
        st.session_state.get("_loaded_company") != current_company
        and st.session_state.get("sections") is not None
    )

    if not combo_changed and not company_changed:
        return

    with st.spinner("Loading form…"):
        data, _err = api_post(
            "/generate/questions",
            {
                "document_type_id": tmpl_map.get(selected_template),
                "company":          st.session_state.get("company"),
            },
            show_error=True,
        )

    if data:
        st.session_state.update({
            "sections":        data["sections"],
            "department_id":   dept_map[selected_dept],
            "template_id":     tmpl_map[selected_template],
            "template_name":   selected_template,
            "department_name": selected_dept,
            "document":        None,
            "preview_content": None,
            "_in_preview":     False,
            "answers":         {},
            "_loaded_combo":   current_combo,
            "_loaded_company": current_company,
            "_do_generate":    False,
            "_do_preview":     False,
        })
        st.rerun()


auto_load_questions()


# ═══════════════════════════════════════════════════════
# ACTION HANDLERS
# ═══════════════════════════════════════════════════════

if st.session_state.get("_do_generate"):
    st.session_state["_do_generate"] = False
    st.session_state["_in_preview"]  = False   # exit preview when generating fresh
    with st.spinner("Generating document…"):
        data, err = api_post(
            "/generate/document",
            {
                "department_id": st.session_state["department_id"],
                "template_id":   st.session_state["template_id"],
                "answers":       st.session_state["answers"],
                "company":       st.session_state["company"],
            },
        )
    if data:
        st.session_state["document"]        = data
        st.session_state["preview_content"] = None
        if data.get("session_id"):
            st.session_state["session_id"] = data["session_id"]
        st.rerun()
    else:
        st.error(f"Generation failed: {err}")

if st.session_state.get("_do_preview"):
    st.session_state["_do_preview"] = False

    # FIX: If a document is already generated, preview IS that document —
    # no LLM call needed. Just flip the _in_preview flag so the right panel
    # switches to read-only mode with a Back button.
    if st.session_state.get("document"):
        st.session_state["_in_preview"] = True
        st.rerun()
    else:
        # No document yet — call the lightweight preview endpoint so the user
        # can see something before committing to a full generate.
        with st.spinner("Generating preview…"):
            pdata, perr = api_post(
                "/generate/preview",
                {
                    "department_id": st.session_state["department_id"],
                    "template_id":   st.session_state["template_id"],
                    "answers":       st.session_state["answers"],
                    "company":       st.session_state["company"],
                },
            )
        if pdata:
            st.session_state["preview_content"] = pdata.get("content", "")
            st.session_state["_in_preview"]     = True
            st.rerun()
        else:
            st.error(f"Preview failed: {perr}")

if st.session_state.get("_do_regen_section"):
    heading  = st.session_state["_do_regen_section"]
    feedback = st.session_state.get("_regen_feedback", "")
    doc      = st.session_state.get("document")
    st.session_state["_do_regen_section"] = None
    st.session_state["_regen_feedback"]   = ""

    if doc:
        with st.spinner(f"Rewriting '{heading}'…"):
            result, err = api_post(
                "/generate/section",
                {
                    "document_id":  doc["document_id"],
                    "section_name": heading,
                    "answers":      st.session_state.get("answers", {}),
                    "feedback":     feedback or None,
                    "company":      st.session_state.get("company"),
                },
            )
        if result:
            updated = api_get(f"/documents/{doc['document_id']}", show_error=False)
            if updated:
                st.session_state["document"] = updated
                st.rerun()
        else:
            st.error(f"Rewrite failed: {err}")


# ═══════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════

tab_generate, tab_library = st.tabs(["  Generate  ", "  Document Library  "])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 — GENERATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_generate:

    doc        = st.session_state.get("document")
    preview    = st.session_state.get("preview_content")
    in_preview = st.session_state.get("_in_preview", False)

    if not st.session_state.get("sections") and not doc:
        st.info("Loading form fields… if this persists, check the backend is running.")

    else:
        form_col, doc_col = st.columns([1, 2], gap="large")

        # ════════════════════════════════════════
        # LEFT — Intake Form
        # ════════════════════════════════════════
        with form_col:
            st.markdown(f"### {selected_template or 'Document'}")
            st.caption(selected_dept or "")
            st.write("")

            if st.session_state.get("sections"):
                answers = {}

                top1, top2 = st.columns(2)
                with top1:
                    if st.button("Generate Document", type="primary",
                                 use_container_width=True, key="gen_top"):
                        st.session_state["answers"]      = answers
                        st.session_state["_do_generate"] = True
                        st.rerun()
                with top2:
                    if st.button("Preview", use_container_width=True, key="prev_top"):
                        st.session_state["answers"]     = answers
                        st.session_state["_do_preview"] = True
                        st.rerun()

                st.divider()

                for section in st.session_state["sections"]:
                    fields = section.get("fields", [])
                    if not fields:
                        continue

                    with st.container(border=True):
                        st.markdown(f"**{section['section_name']}**")
                        st.write("")

                        for field in fields:
                            fn    = field["field_name"]
                            label = field["field_label"]
                            ftype = field["field_type"]

                            if ftype == "textarea":
                                answers[fn] = st.text_area(label, key=f"f_{fn}", height=80)
                            elif ftype == "date":
                                answers[fn] = str(st.date_input(label, key=f"f_{fn}"))
                            elif ftype == "number":
                                answers[fn] = str(st.number_input(label, key=f"f_{fn}", step=1))
                            else:
                                answers[fn] = st.text_input(label, key=f"f_{fn}")

                st.session_state["answers"] = answers

                st.divider()
                bot1, bot2 = st.columns(2)
                with bot1:
                    if st.button("Generate Document", type="primary",
                                 use_container_width=True, key="gen_bot"):
                        st.session_state["answers"]      = answers
                        st.session_state["_do_generate"] = True
                        st.rerun()
                with bot2:
                    if st.button("Preview", use_container_width=True, key="prev_bot"):
                        st.session_state["answers"]     = answers
                        st.session_state["_do_preview"] = True
                        st.rerun()

        # ════════════════════════════════════════
        # RIGHT — Document Output
        # ════════════════════════════════════════
        with doc_col:

            if not doc and not preview and not in_preview:
                with st.container(border=True):
                    st.markdown("#### Your document will appear here")
                    st.caption("Fill in the form and click **Generate Document**.")
                    st.write("")
                    st.markdown(
                        "- AI generates all sections from your inputs\n"
                        "- Rewrite any section individually\n"
                        "- Download as PDF or DOCX\n"
                        "- Publish to Notion"
                    )

            # ── PREVIEW MODE ──────────────────────────────────────────────────
            # FIX: Show existing document in read-only view, with a Back button.
            # Never calls the LLM when a document already exists.
            elif in_preview:
                # Back button — always visible at the top
                back_col, label_col = st.columns([1, 5])
                with back_col:
                    if st.button("← Back", use_container_width=True, key="preview_back"):
                        st.session_state["_in_preview"]     = False
                        st.session_state["preview_content"] = None
                        st.rerun()
                with label_col:
                    st.info("Preview mode — not saved to library." if not doc else "Preview of your generated document.")

                st.markdown(f"## {st.session_state.get('template_name', 'Preview')}")
                st.divider()

                # If we have the full structured doc, render it section by section
                if doc:
                    sections = get_sections(doc)
                    if sections:
                        for section in sections:
                            heading = section.get("heading", "")
                            with st.container(border=True):
                                if heading:
                                    st.markdown(f"#### {heading}")
                                render_section_content(section)
                    else:
                        render_plain(doc.get("content", ""))
                else:
                    # No generated doc — show the lightweight preview text
                    render_plain(preview or "")

            # ── FULL GENERATED DOCUMENT (editable) ───────────────────────────
            elif doc:
                sections   = get_sections(doc)
                doc_title  = doc.get("title", selected_template or "Document")
                company    = st.session_state.get("company")
                doc_id     = doc["document_id"]
                val_status = doc.get("validation_status", "pending")

                st.markdown(f"## {doc_title}")

                m1, m2, m3 = st.columns(3)
                m1.metric("Status",  status_display(val_status))
                m2.metric("Version", f"v{doc.get('version', '1.0')}")
                m3.metric("Doc ID",  str(doc_id))

                st.divider()

                act1, act2, act3 = st.columns(3)

                with act1:
                    pdf_b = fetch_pdf(doc_id, company)
                    if pdf_b:
                        st.download_button(
                            "Download PDF", data=pdf_b,
                            file_name=f"{doc_title}.pdf",
                            mime="application/pdf",
                            use_container_width=True, key="gen_dl_pdf",
                        )
                    else:
                        st.button("Download PDF", disabled=True,
                                  use_container_width=True, key="gen_dl_pdf_d")

                with act2:
                    docx_b = fetch_docx(doc_id, company)
                    if docx_b:
                        st.download_button(
                            "Download DOCX", data=docx_b,
                            file_name=f"{doc_title}.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True, key="gen_dl_docx",
                        )
                    else:
                        st.button("Download DOCX", disabled=True,
                                  use_container_width=True, key="gen_dl_docx_d")

                with act3:
                    if st.button("Publish to Notion", use_container_width=True, key="notion_gen"):
                        with st.spinner("Publishing…"):
                            ndata, nerr = api_post("/notion/publish", {"document_id": doc_id})
                            if ndata:
                                st.success(f"Published — [Open in Notion]({ndata.get('notion_url', '')})")
                            else:
                                st.error(f"Notion error: {nerr}")

                st.divider()

                if sections:
                    for section in sections:
                        heading = section.get("heading", "")
                        if not heading:
                            continue

                        with st.container(border=True):
                            h_col, btn_col = st.columns([5, 1])

                            with h_col:
                                st.markdown(f"#### {heading}")

                            with btn_col:
                                rkey = (
                                    heading[:28]
                                    .replace(" ", "_")
                                    .replace("/", "_")
                                    .replace("(", "")
                                    .replace(")", "")
                                )
                                with st.popover("Rewrite", use_container_width=True):
                                    st.markdown(f"**{heading}**")
                                    feedback_val = st.text_area(
                                        "Instructions (optional)",
                                        placeholder="e.g. More formal, add more detail…",
                                        key=f"fb_{rkey}",
                                        height=80,
                                    )
                                    if st.button(
                                        "Regenerate",
                                        key=f"regen_{rkey}",
                                        type="primary",
                                        use_container_width=True,
                                    ):
                                        st.session_state["_do_regen_section"] = heading
                                        st.session_state["_regen_feedback"]   = feedback_val
                                        st.rerun()

                            render_section_content(section)
                else:
                    render_plain(doc.get("content", ""))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 — DOCUMENT LIBRARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_library:

    if st.session_state.get("library_doc"):
        lib_doc   = st.session_state["library_doc"]
        lib_title = lib_doc.get("title", "Document")
        sections  = get_sections(lib_doc)

        back_col, title_col = st.columns([1, 7])
        with back_col:
            if st.button("← Back", use_container_width=True, key="lib_back"):
                st.session_state["library_doc"] = None
                st.rerun()
        with title_col:
            st.markdown(f"## {lib_title}")
            st.caption(
                f"v{lib_doc.get('version', '1.0')}  ·  "
                f"{status_display(lib_doc.get('validation_status', ''))}  ·  "
                f"Created {format_date(lib_doc.get('created_at', ''))}"
            )

        st.divider()

        if sections:
            for section in sections:
                heading = section.get("heading", "")
                with st.container(border=True):
                    if heading:
                        st.markdown(f"#### {heading}")
                    render_section_content(section)
        else:
            render_plain(lib_doc.get("content", ""))

    else:
        st.markdown("### Document Library")
        st.divider()

        f1, f2, f3 = st.columns(3)

        with f1:
            dept_data_lib   = api_get("/departments", show_error=False) or []
            dept_filter_map = {d["name"]: d["id"] for d in dept_data_lib}
            filter_dept     = st.selectbox(
                "Department",
                ["All Departments"] + [d["name"] for d in dept_data_lib],
                key="lib_dept_f",
            )

        with f2:
            tmpl_lib = []
            if filter_dept != "All Departments":
                tmpl_lib = api_get(f"/templates/{dept_filter_map[filter_dept]}", show_error=False) or []
            else:
                for d in dept_data_lib:
                    tmpl_lib.extend(api_get(f"/templates/{d['id']}", show_error=False) or [])
            tmpl_lib_disp = {short_name(t["name"]): t["id"] for t in tmpl_lib}
            filter_tmpl   = st.selectbox(
                "Document Type",
                ["All Document Types"] + list(tmpl_lib_disp.keys()),
                key="lib_tmpl_f",
            )

        with f3:
            filter_status = st.selectbox(
                "Status",
                ["All", "validated", "pending", "needs_review", "failed"],
                key="lib_status_f",
            )

        st.divider()

        params = {}
        if filter_dept != "All Departments":
            params["department_id"] = dept_filter_map[filter_dept]
        if filter_tmpl != "All Document Types":
            params["template_id"] = tmpl_lib_disp.get(filter_tmpl)

        raw_docs = api_get("/documents", params=params, show_error=True)

        if raw_docs is None:
            st.warning("Could not load documents.")
        else:
            docs = raw_docs or []
            if filter_status != "All":
                docs = [d for d in docs if d.get("validation_status") == filter_status]

            if not docs:
                st.info("No documents found. Generate your first document to see it here.")
            else:
                company = st.session_state.get("company")
                st.caption(f"{len(docs)} document(s)")
                st.write("")

                for doc in docs:
                    title   = doc.get("title", "Untitled")
                    val     = doc.get("validation_status", "pending")
                    version = doc.get("version", "1.0")
                    created = format_date(doc.get("created_at", ""))
                    doc_id  = doc["document_id"]

                    with st.container(border=True):
                        info_col, act_col = st.columns([2, 3])

                        with info_col:
                            st.markdown(f"**{title}**")
                            st.caption(f"v{version}  ·  {created}  ·  {status_display(val)}")

                        with act_col:
                            b_view, b_pdf, b_docx, b_del = st.columns(4)

                            with b_view:
                                if st.button("View", key=f"v_{doc_id}", use_container_width=True):
                                    st.session_state["library_doc"] = doc
                                    st.rerun()

                            with b_pdf:
                                pdf_b = fetch_pdf(doc_id, company)
                                if pdf_b:
                                    st.download_button(
                                        "PDF", data=pdf_b,
                                        file_name=f"{title}.pdf",
                                        mime="application/pdf",
                                        use_container_width=True,
                                        key=f"pdf_{doc_id}",
                                    )
                                else:
                                    st.button("PDF", disabled=True,
                                              use_container_width=True, key=f"pdf_d_{doc_id}")

                            with b_docx:
                                docx_b = fetch_docx(doc_id, company)
                                if docx_b:
                                    st.download_button(
                                        "DOCX", data=docx_b,
                                        file_name=f"{title}.docx",
                                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                        use_container_width=True,
                                        key=f"docx_{doc_id}",
                                    )
                                else:
                                    st.button("DOCX", disabled=True,
                                              use_container_width=True, key=f"docx_d_{doc_id}")

                            with b_del:
                                if st.button("Delete", key=f"del_{doc_id}", use_container_width=True):
                                    if api_delete(f"/documents/{doc_id}"):
                                        st.success("Deleted.")
                                        st.rerun()

                        with st.expander("Publish to Notion"):
                            if st.button("Publish", key=f"notion_{doc_id}"):
                                with st.spinner("Publishing…"):
                                    ndata, nerr = api_post("/notion/publish", {"document_id": doc_id})
                                    if ndata:
                                        st.success(f"Published — [Open in Notion]({ndata.get('notion_url', '')})")
                                    else:
                                        st.error(f"Error: {nerr}")

st.caption("DocForge Hub · Powered by AI")



# import json
# from datetime import datetime
# import requests
# import streamlit as st

# API_BASE = "http://localhost:8000/api"

# st.set_page_config(
#     page_title="DocForge Hub",
#     page_icon="🗂️",
#     layout="wide",
#     initial_sidebar_state="collapsed",
# )


# # ═══════════════════════════════════════════════════════
# # API HELPERS
# # ═══════════════════════════════════════════════════════

# def api_get(path, params=None, show_error=True):
#     try:
#         r = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
#         if r.status_code == 200:
#             return r.json()
#         if show_error:
#             st.error(f"API {r.status_code}: {r.text[:200]}")
#         return None
#     except requests.exceptions.ConnectionError:
#         if show_error:
#             st.error("Cannot connect to backend. Is the server running?")
#         return None
#     except Exception as e:
#         if show_error:
#             st.error(str(e))
#         return None


# def api_post(path, body, show_error=True):
#     try:
#         r = requests.post(f"{API_BASE}{path}", json=body, timeout=180)
#         if r.status_code == 200:
#             return r.json(), None
#         err = r.text[:200]
#         if show_error:
#             st.error(f"API {r.status_code}: {err}")
#         return None, err
#     except requests.exceptions.ConnectionError:
#         return None, "Cannot connect to backend"
#     except Exception as e:
#         return None, str(e)


# def api_delete(path, show_error=True):
#     try:
#         r = requests.delete(f"{API_BASE}{path}", timeout=30)
#         if r.status_code == 200:
#             return True
#         if show_error:
#             st.error(f"API {r.status_code}: {r.text[:200]}")
#         return False
#     except Exception as e:
#         if show_error:
#             st.error(str(e))
#         return False


# def fetch_pdf(document_id: int, company: dict = None):
#     try:
#         params = {}
#         if company:
#             params["company_json"] = json.dumps(company)
#         r = requests.get(f"{API_BASE}/documents/{document_id}/pdf", params=params, timeout=60)
#         return r.content if r.status_code == 200 else None
#     except Exception:
#         return None


# def fetch_docx(document_id: int, company: dict = None):
#     try:
#         params = {}
#         if company:
#             params["company_json"] = json.dumps(company)
#         r = requests.get(f"{API_BASE}/documents/{document_id}/docx", params=params, timeout=60)
#         return r.content if r.status_code == 200 else None
#     except Exception:
#         return None


# # ═══════════════════════════════════════════════════════
# # UTILITIES
# # ═══════════════════════════════════════════════════════

# def short_name(name, max_len=45):
#     if len(name) <= max_len:
#         return name
#     cut        = name[:max_len]
#     last_space = cut.rfind(" ")
#     return (cut[:last_space] if last_space > 20 else cut) + "…"


# def format_date(dt_str):
#     try:
#         return datetime.fromisoformat(dt_str).strftime("%d %b %Y")
#     except Exception:
#         return dt_str or "—"


# STATUS_ICON  = {"validated": "🟢", "pending": "🟡", "needs_review": "🟠", "failed": "🔴", "draft": "🔵"}
# STATUS_LABEL = {"validated": "Validated", "pending": "Pending", "needs_review": "Needs Review", "failed": "Failed", "draft": "Draft"}


# def status_display(status):
#     icon  = STATUS_ICON.get(status, "⚪")
#     label = STATUS_LABEL.get(status, status.replace("_", " ").title() if status else "Pending")
#     return f"{icon} {label}"


# def company_sig(company):
#     return json.dumps(company or {}, sort_keys=True)


# def get_sections(doc):
#     if not doc:
#         return []
#     raw = doc.get("structured_json")
#     if not raw:
#         return []
#     try:
#         parsed = json.loads(raw) if isinstance(raw, str) else raw
#         if isinstance(parsed, list):
#             return parsed
#         if isinstance(parsed, dict):
#             return parsed.get("sections", [])
#     except Exception:
#         pass
#     return []


# def escape_pipe(text):
#     return str(text).replace("|", "\\|")


# # ═══════════════════════════════════════════════════════
# # RENDERERS
# # ═══════════════════════════════════════════════════════

# def render_section_content(section):
#     ctype   = section.get("content_type", "text")
#     content = section.get("content", "")

#     if ctype == "text" and isinstance(content, str):
#         for para in content.split("\n\n"):
#             p = para.strip()
#             if p:
#                 st.write(p)

#     elif ctype == "table" and isinstance(content, list) and content:
#         headers   = [escape_pipe(c) for c in content[0].get("cells", [])]
#         rows      = [[escape_pipe(c) for c in r.get("cells", [])] for r in content[1:]]
#         if headers:
#             sep       = " | ".join(["---"] * len(headers))
#             data_rows = "\n".join("| " + " | ".join(r) + " |" for r in rows)
#             st.markdown(f"| {' | '.join(headers)} |\n| {sep} |\n{data_rows}")

#     elif ctype == "list" and isinstance(content, list):
#         for item in content:
#             st.markdown(f"- {item}")


# def render_plain(content):
#     if not content:
#         st.info("No content to display.")
#         return
#     for line in content.split("\n"):
#         s = line.strip()
#         if not s:
#             continue
#         if len(s) < 65 and not s.startswith("-") and len(s.split()) <= 9:
#             st.markdown(f"**{s}**")
#         elif s.startswith("- "):
#             st.markdown(s)
#         else:
#             st.write(s)


# # ═══════════════════════════════════════════════════════
# # SESSION STATE
# # ═══════════════════════════════════════════════════════

# _defaults = {
#     "session_id":        None,
#     "sections":          None,
#     "department_id":     None,
#     "template_id":       None,
#     "template_name":     None,
#     "department_name":   None,
#     "document":          None,
#     "preview_content":   None,
#     "answers":           {},
#     "library_doc":       None,
#     "_loaded_combo":     None,
#     "_loaded_company":   None,
#     # Action flags — survive st.rerun()
#     "_do_generate":      False,
#     "_do_preview":       False,
#     "_do_regen_section": None,   
#     "company": {
#         "name": "", "industry": "", "size": "",
#         "location": "", "tone": "Professional",
#     },
# }

# for k, v in _defaults.items():
#     if k not in st.session_state:
#         st.session_state[k] = v


# # ═══════════════════════════════════════════════════════
# # SIDEBAR
# # ═══════════════════════════════════════════════════════

# with st.sidebar:
#     st.markdown("### Company Context")
#     st.caption("Optional — improves document quality")
#     st.divider()

#     co             = st.session_state["company"]
#     co["name"]     = st.text_input("Company Name",  value=co["name"],     placeholder="Acme Corp")
#     co["industry"] = st.text_input("Industry",      value=co["industry"], placeholder="Technology")

#     _sizes = ["", "1–10", "11–50", "51–200", "201–500", "500+"]
#     co["size"] = st.selectbox(
#         "Company Size", _sizes,
#         index=_sizes.index(co.get("size", "")) if co.get("size", "") in _sizes else 0,
#     )
#     co["location"] = st.text_input("Location", value=co["location"], placeholder="Mumbai, India")

#     _tones = ["Professional", "Formal", "Friendly", "Technical", "Empathetic"]
#     co["tone"] = st.selectbox(
#         "Tone", _tones,
#         index=_tones.index(co.get("tone", "Professional")),
#     )
#     st.divider()
#     st.caption("DocForge Hub · v1.0")


# # ═══════════════════════════════════════════════════════
# # HEADER
# # ═══════════════════════════════════════════════════════

# st.markdown("# DocForge Hub")
# st.caption("AI-powered document generation")
# st.divider()


# # ═══════════════════════════════════════════════════════
# # DEPARTMENT + TEMPLATE SELECTORS
# # ═══════════════════════════════════════════════════════

# dept_data  = api_get("/departments", show_error=False) or []
# dept_names = [d["name"] for d in dept_data]
# dept_map   = {d["name"]: d["id"] for d in dept_data}

# if not dept_names:
#     st.warning("No departments found. Check the backend is running.")
#     st.stop()

# sel_col1, sel_col2 = st.columns([1, 2])

# with sel_col1:
#     dept_idx      = st.selectbox(
#         "Department",
#         options=range(len(dept_names)),
#         format_func=lambda i: dept_names[i],
#         key="sb_dept_idx",
#     )
#     selected_dept = dept_names[dept_idx]

# dept_id   = dept_map[selected_dept]
# tmpl_data = api_get(f"/templates/{dept_id}", show_error=False) or []

# tmpl_display_map   = {short_name(t["name"]): t["name"] for t in tmpl_data}
# tmpl_map           = {t["name"]: t["id"] for t in tmpl_data}
# tmpl_display_names = [short_name(t["name"]) for t in tmpl_data]
# selected_template  = None

# with sel_col2:
#     if tmpl_display_names:
#         tmpl_idx = st.selectbox(
#             "Document Type",
#             options=range(len(tmpl_display_names)),
#             format_func=lambda i: tmpl_display_names[i],
#             key="sb_tmpl_idx",
#         )
#         selected_template = tmpl_display_map.get(tmpl_display_names[tmpl_idx])
#     else:
#         st.selectbox("Document Type", ["No templates found"], disabled=True)

# st.divider()


# # ═══════════════════════════════════════════════════════
# # AUTO-LOAD QUESTIONS
# # ═══════════════════════════════════════════════════════

# def auto_load_questions():
#     if not selected_dept or not selected_template:
#         return

#     current_combo   = f"{selected_dept}||{selected_template}"
#     current_company = company_sig(st.session_state.get("company"))
#     combo_changed   = st.session_state.get("_loaded_combo") != current_combo
#     company_changed = (
#         st.session_state.get("_loaded_company") != current_company
#         and st.session_state.get("sections") is not None
#     )

#     if not combo_changed and not company_changed:
#         return

#     with st.spinner("Loading form…"):
#         data, _err = api_post(
#             "/generate/questions",
#             {
#                 "document_type_id": tmpl_map.get(selected_template),
#                 "company":          st.session_state.get("company"),
#             },
#             show_error=True,
#         )

#     if data:
#         st.session_state.update({
#             "sections":        data["sections"],
#             "department_id":   dept_map[selected_dept],
#             "template_id":     tmpl_map[selected_template],
#             "template_name":   selected_template,
#             "department_name": selected_dept,
#             "document":        None,
#             "preview_content": None,
#             "answers":         {},
#             "_loaded_combo":   current_combo,
#             "_loaded_company": current_company,
#             "_do_generate":    False,
#             "_do_preview":     False,
#         })
#         st.rerun()


# auto_load_questions()


# # ═══════════════════════════════════════════════════════
# # ACTION HANDLERS — run before rendering, use flags
# # These fire on the rerun AFTER a button sets a flag,
# # so the API call happens with valid state, not in a
# # half-rendered widget tree.
# # ═══════════════════════════════════════════════════════

# if st.session_state.get("_do_generate"):
#     st.session_state["_do_generate"] = False
#     with st.spinner("Generating document…"):
#         data, err = api_post(
#             "/generate/document",
#             {
#                 "department_id": st.session_state["department_id"],
#                 "template_id":   st.session_state["template_id"],
#                 "answers":       st.session_state["answers"],
#                 "company":       st.session_state["company"],
#             },
#         )
#     if data:
#         st.session_state["document"]        = data
#         st.session_state["preview_content"] = None
#         if data.get("session_id"):
#             st.session_state["session_id"] = data["session_id"]
#         st.rerun()
#     else:
#         st.error(f"Generation failed: {err}")

# if st.session_state.get("_do_preview"):
#     st.session_state["_do_preview"] = False
#     with st.spinner("Generating preview…"):
#         pdata, perr = api_post(
#             "/generate/preview",
#             {
#                 "department_id": st.session_state["department_id"],
#                 "template_id":   st.session_state["template_id"],
#                 "answers":       st.session_state["answers"],
#                 "company":       st.session_state["company"],
#             },
#         )
#     if pdata:
#         st.session_state["preview_content"] = pdata.get("content", "")
#         st.session_state["document"]        = None
#         st.rerun()
#     else:
#         st.error(f"Preview failed: {perr}")

# if st.session_state.get("_do_regen_section"):
#     heading  = st.session_state["_do_regen_section"]
#     feedback = st.session_state.get("_regen_feedback", "")
#     doc      = st.session_state.get("document")
#     st.session_state["_do_regen_section"] = None
#     st.session_state["_regen_feedback"]   = ""

#     if doc:
#         with st.spinner(f"Rewriting '{heading}'…"):
#             result, err = api_post(
#                 "/generate/section",
#                 {
#                     "document_id":  doc["document_id"],
#                     "section_name": heading,
#                     "answers":      st.session_state.get("answers", {}),
#                     "feedback":     feedback or None,
#                     "company":      st.session_state.get("company"),
#                 },
#             )
#         if result:
#             updated = api_get(f"/documents/{doc['document_id']}", show_error=False)
#             if updated:
#                 st.session_state["document"] = updated
#                 st.rerun()
#         else:
#             st.error(f"Rewrite failed: {err}")


# # ═══════════════════════════════════════════════════════
# # TABS
# # ═══════════════════════════════════════════════════════

# tab_generate, tab_library = st.tabs(["  Generate  ", "  Document Library  "])


# # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# # TAB 1 — GENERATE
# # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# with tab_generate:

#     doc     = st.session_state.get("document")
#     preview = st.session_state.get("preview_content")

#     if not st.session_state.get("sections") and not doc:
#         st.info("Loading form fields… if this persists, check the backend is running.")

#     else:
#         form_col, doc_col = st.columns([1, 2], gap="large")

#         # ════════════════════════════════════════
#         # LEFT — Intake Form
#         # ════════════════════════════════════════
#         with form_col:
#             st.markdown(f"### {selected_template or 'Document'}")
#             st.caption(selected_dept or "")
#             st.write("")

#             if st.session_state.get("sections"):
#                 answers = {}

#                 top1, top2 = st.columns(2)
#                 with top1:
#                     if st.button("Generate Document", type="primary",
#                                  use_container_width=True, key="gen_top"):
#                         st.session_state["answers"]      = answers
#                         st.session_state["_do_generate"] = True
#                         st.rerun()
#                 with top2:
#                     if st.button("Preview", use_container_width=True, key="prev_top"):
#                         st.session_state["answers"]    = answers
#                         st.session_state["_do_preview"] = True
#                         st.rerun()

#                 st.divider()

#                 for section in st.session_state["sections"]:
#                     fields = section.get("fields", [])
#                     if not fields:
#                         continue

#                     with st.container(border=True):
#                         st.markdown(f"**{section['section_name']}**")
#                         st.write("")

#                         for field in fields:
#                             fn    = field["field_name"]
#                             label = field["field_label"]
#                             ftype = field["field_type"]

#                             if ftype == "textarea":
#                                 answers[fn] = st.text_area(label, key=f"f_{fn}", height=80)
#                             elif ftype == "date":
#                                 answers[fn] = str(st.date_input(label, key=f"f_{fn}"))
#                             elif ftype == "number":
#                                 answers[fn] = str(st.number_input(label, key=f"f_{fn}", step=1))
#                             else:
#                                 answers[fn] = st.text_input(label, key=f"f_{fn}")

#                 # Update answers in session after all fields rendered
#                 st.session_state["answers"] = answers

#                 st.divider()
#                 bot1, bot2 = st.columns(2)
#                 with bot1:
#                     if st.button("Generate Document", type="primary",
#                                  use_container_width=True, key="gen_bot"):
#                         st.session_state["answers"]      = answers
#                         st.session_state["_do_generate"] = True
#                         st.rerun()
#                 with bot2:
#                     if st.button("Preview", use_container_width=True, key="prev_bot"):
#                         st.session_state["answers"]    = answers
#                         st.session_state["_do_preview"] = True
#                         st.rerun()

#         # ════════════════════════════════════════
#         # RIGHT — Document Output
#         # ════════════════════════════════════════
#         with doc_col:

#             if not doc and not preview:
#                 with st.container(border=True):
#                     st.markdown("#### Your document will appear here")
#                     st.caption("Fill in the form and click **Generate Document**.")
#                     st.write("")
#                     st.markdown(
#                         "- AI generates all sections from your inputs\n"
#                         "- Rewrite any section individually\n"
#                         "- Download as PDF or DOCX\n"
#                         "- Publish to Notion"
#                     )

#             elif preview:
#                 st.info("Preview mode — not saved to library.")
#                 st.markdown(f"## {st.session_state.get('template_name', 'Preview')}")
#                 st.divider()
#                 render_plain(preview)

#             elif doc:
#                 sections   = get_sections(doc)
#                 doc_title  = doc.get("title", selected_template or "Document")
#                 company    = st.session_state.get("company")
#                 doc_id     = doc["document_id"]
#                 val_status = doc.get("validation_status", "pending")

#                 st.markdown(f"## {doc_title}")

#                 m1, m2, m3 = st.columns(3)
#                 m1.metric("Status",  status_display(val_status))
#                 m2.metric("Version", f"v{doc.get('version', '1.0')}")
#                 m3.metric("Doc ID",  str(doc_id))

#                 st.divider()

#                 act1, act2, act3 = st.columns(3)

#                 with act1:
#                     pdf_b = fetch_pdf(doc_id, company)
#                     if pdf_b:
#                         st.download_button(
#                             "Download PDF", data=pdf_b,
#                             file_name=f"{doc_title}.pdf",
#                             mime="application/pdf",
#                             use_container_width=True, key="gen_dl_pdf",
#                         )
#                     else:
#                         st.button("Download PDF", disabled=True,
#                                   use_container_width=True, key="gen_dl_pdf_d")

#                 with act2:
#                     docx_b = fetch_docx(doc_id, company)
#                     if docx_b:
#                         st.download_button(
#                             "Download DOCX", data=docx_b,
#                             file_name=f"{doc_title}.docx",
#                             mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#                             use_container_width=True, key="gen_dl_docx",
#                         )
#                     else:
#                         st.button("Download DOCX", disabled=True,
#                                   use_container_width=True, key="gen_dl_docx_d")

#                 with act3:
#                     if st.button("Publish to Notion", use_container_width=True, key="notion_gen"):
#                         with st.spinner("Publishing…"):
#                             ndata, nerr = api_post("/notion/publish", {"document_id": doc_id})
#                             if ndata:
#                                 st.success(f"Published — [Open in Notion]({ndata.get('notion_url', '')})")
#                             else:
#                                 st.error(f"Notion error: {nerr}")

#                 st.divider()

#                 if sections:
#                     for section in sections:
#                         heading = section.get("heading", "")
#                         if not heading:
#                             continue

#                         with st.container(border=True):
#                             h_col, btn_col = st.columns([5, 1])

#                             with h_col:
#                                 st.markdown(f"#### {heading}")

#                             with btn_col:
#                                 rkey = (
#                                     heading[:28]
#                                     .replace(" ", "_")
#                                     .replace("/", "_")
#                                     .replace("(", "")
#                                     .replace(")", "")
#                                 )
#                                 with st.popover("Rewrite", use_container_width=True):
#                                     st.markdown(f"**{heading}**")
#                                     feedback_val = st.text_area(
#                                         "Instructions (optional)",
#                                         placeholder="e.g. More formal, add more detail…",
#                                         key=f"fb_{rkey}",
#                                         height=80,
#                                     )
#                                     if st.button(
#                                         "Regenerate",
#                                         key=f"regen_{rkey}",
#                                         type="primary",
#                                         use_container_width=True,
#                                     ):
#                                         # Set flags — actual API call happens at top of script
#                                         st.session_state["_do_regen_section"] = heading
#                                         st.session_state["_regen_feedback"]   = feedback_val
#                                         st.rerun()

#                             render_section_content(section)
#                 else:
#                     render_plain(doc.get("content", ""))


# # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# # TAB 2 — DOCUMENT LIBRARY
# # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# with tab_library:

#     if st.session_state.get("library_doc"):
#         lib_doc   = st.session_state["library_doc"]
#         lib_title = lib_doc.get("title", "Document")
#         sections  = get_sections(lib_doc)

#         back_col, title_col = st.columns([1, 7])
#         with back_col:
#             if st.button("← Back", use_container_width=True, key="lib_back"):
#                 st.session_state["library_doc"] = None
#                 st.rerun()
#         with title_col:
#             st.markdown(f"## {lib_title}")
#             st.caption(
#                 f"v{lib_doc.get('version', '1.0')}  ·  "
#                 f"{status_display(lib_doc.get('validation_status', ''))}  ·  "
#                 f"Created {format_date(lib_doc.get('created_at', ''))}"
#             )

#         st.divider()

#         if sections:
#             for section in sections:
#                 heading = section.get("heading", "")
#                 with st.container(border=True):
#                     if heading:
#                         st.markdown(f"#### {heading}")
#                     render_section_content(section)
#         else:
#             render_plain(lib_doc.get("content", ""))

#     else:
#         st.markdown("### Document Library")
#         st.divider()

#         f1, f2, f3 = st.columns(3)

#         with f1:
#             dept_data_lib   = api_get("/departments", show_error=False) or []
#             dept_filter_map = {d["name"]: d["id"] for d in dept_data_lib}
#             filter_dept     = st.selectbox(
#                 "Department",
#                 ["All Departments"] + [d["name"] for d in dept_data_lib],
#                 key="lib_dept_f",
#             )

#         with f2:
#             tmpl_lib = []
#             if filter_dept != "All Departments":
#                 tmpl_lib = api_get(f"/templates/{dept_filter_map[filter_dept]}", show_error=False) or []
#             else:
#                 for d in dept_data_lib:
#                     tmpl_lib.extend(api_get(f"/templates/{d['id']}", show_error=False) or [])
#             tmpl_lib_disp = {short_name(t["name"]): t["id"] for t in tmpl_lib}
#             filter_tmpl   = st.selectbox(
#                 "Document Type",
#                 ["All Document Types"] + list(tmpl_lib_disp.keys()),
#                 key="lib_tmpl_f",
#             )

#         with f3:
#             filter_status = st.selectbox(
#                 "Status",
#                 ["All", "validated", "pending", "needs_review", "failed"],
#                 key="lib_status_f",
#             )

#         st.divider()

#         params = {}
#         if filter_dept != "All Departments":
#             params["department_id"] = dept_filter_map[filter_dept]
#         if filter_tmpl != "All Document Types":
#             params["template_id"] = tmpl_lib_disp.get(filter_tmpl)

#         raw_docs = api_get("/documents", params=params, show_error=True)

#         if raw_docs is None:
#             st.warning("Could not load documents.")
#         else:
#             docs = raw_docs or []
#             if filter_status != "All":
#                 docs = [d for d in docs if d.get("validation_status") == filter_status]

#             if not docs:
#                 st.info("No documents found. Generate your first document to see it here.")
#             else:
#                 company = st.session_state.get("company")
#                 st.caption(f"{len(docs)} document(s)")
#                 st.write("")

#                 for doc in docs:
#                     title   = doc.get("title", "Untitled")
#                     val     = doc.get("validation_status", "pending")
#                     version = doc.get("version", "1.0")
#                     created = format_date(doc.get("created_at", ""))
#                     doc_id  = doc["document_id"]

#                     with st.container(border=True):
#                         info_col, act_col = st.columns([2, 3])

#                         with info_col:
#                             st.markdown(f"**{title}**")
#                             st.caption(f"v{version}  ·  {created}  ·  {status_display(val)}")

#                         with act_col:
#                             b_view, b_pdf, b_docx, b_del = st.columns(4)

#                             with b_view:
#                                 if st.button("View", key=f"v_{doc_id}", use_container_width=True):
#                                     st.session_state["library_doc"] = doc
#                                     st.rerun()

#                             with b_pdf:
#                                 pdf_b = fetch_pdf(doc_id, company)
#                                 if pdf_b:
#                                     st.download_button(
#                                         "PDF", data=pdf_b,
#                                         file_name=f"{title}.pdf",
#                                         mime="application/pdf",
#                                         use_container_width=True,
#                                         key=f"pdf_{doc_id}",
#                                     )
#                                 else:
#                                     st.button("PDF", disabled=True,
#                                               use_container_width=True, key=f"pdf_d_{doc_id}")

#                             with b_docx:
#                                 docx_b = fetch_docx(doc_id, company)
#                                 if docx_b:
#                                     st.download_button(
#                                         "DOCX", data=docx_b,
#                                         file_name=f"{title}.docx",
#                                         mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#                                         use_container_width=True,
#                                         key=f"docx_{doc_id}",
#                                     )
#                                 else:
#                                     st.button("DOCX", disabled=True,
#                                               use_container_width=True, key=f"docx_d_{doc_id}")

#                             with b_del:
#                                 if st.button("Delete", key=f"del_{doc_id}", use_container_width=True):
#                                     if api_delete(f"/documents/{doc_id}"):
#                                         st.success("Deleted.")
#                                         st.rerun()

#                         with st.expander("Publish to Notion"):
#                             if st.button("Publish", key=f"notion_{doc_id}"):
#                                 with st.spinner("Publishing…"):
#                                     ndata, nerr = api_post("/notion/publish", {"document_id": doc_id})
#                                     if ndata:
#                                         st.success(f"Published — [Open in Notion]({ndata.get('notion_url', '')})")
#                                     else:
#                                         st.error(f"Error: {nerr}")

# st.caption("DocForge Hub · Powered by AI")