import json
from datetime import datetime

import requests
import streamlit as st

API_BASE = "http://localhost:8000/api"
RAG_BASE = "http://localhost:8000/rag"
AGENT_BASE = "http://localhost:8000/agent"

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


def agent_get(path, params=None, show_error=True):
    try:
        r = requests.get(f"{AGENT_BASE}{path}", params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if show_error:
            st.error(f"Agent API {r.status_code}: {r.text[:200]}")
        return None
    except requests.exceptions.ConnectionError:
        if show_error:
            st.error("Cannot connect to agent backend. Is the server running?")
        return None
    except Exception as e:
        if show_error:
            st.error(str(e))
        return None


def agent_post(path, body, show_error=True):
    try:
        r = requests.post(f"{AGENT_BASE}{path}", json=body, timeout=180)
        if r.status_code == 200:
            return r.json(), None
        err = r.text[:200]
        if show_error:
            st.error(f"Agent API {r.status_code}: {err}")
        return None, err
    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to agent backend"
    except Exception as e:
        return None, str(e)


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
    "_in_preview":       False,
    "_do_generate":      False,
    "_do_preview":       False,
    "_do_regen_section": None,
    "_regen_feedback":   "",
    "agent_session_id":  None,
    "agent_turns":       [],
    "agent_tickets":     None,
    "rag_evaluate_result": None,
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
# TABS
# ═══════════════════════════════════════════════════════

tab_generate, tab_library, tab_rag, tab_agent = st.tabs([
    "  Generate  ",
    "  Document Library  ",
    "  RAG Assistant  ",
    "  Agent  ",
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 — GENERATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_generate:

    # ── Department + Template selectors (moved inside tab) ──
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

    # ── Auto-load questions ──
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

    # ── Action handlers ──
    if st.session_state.get("_do_generate"):
        st.session_state["_do_generate"] = False
        st.session_state["_in_preview"]  = False
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

        if st.session_state.get("document"):
            st.session_state["_in_preview"] = True
            st.rerun()
        else:
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

    # ── Main generate UI ──
    doc        = st.session_state.get("document")
    preview    = st.session_state.get("preview_content")
    in_preview = st.session_state.get("_in_preview", False)

    if not st.session_state.get("sections") and not doc:
        st.info("Loading form fields… if this persists, check the backend is running.")

    else:
        form_col, doc_col = st.columns([1, 2], gap="large")

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

            elif in_preview:
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
                    render_plain(preview or "")

            elif doc:
                sections  = get_sections(doc)
                doc_title = doc.get("title", selected_template or "Document")
                company   = st.session_state.get("company")
                doc_id    = doc["document_id"]

                st.markdown(f"## {doc_title}")

                m1, m2 = st.columns(2)
                m1.metric("Version", f"v{doc.get('version', '1.0')}")
                m2.metric("Doc ID",  str(doc_id))

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
                    for sec_idx, section in enumerate(sections):
                        heading = section.get("heading", "")
                        if not heading:
                            continue

                        rkey = f"sec_{sec_idx}"

                        with st.container(border=True):
                            h_col, btn_col = st.columns([5, 1])

                            with h_col:
                                st.markdown(f"#### {heading}")

                            with btn_col:
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

        f1, f2 = st.columns(2)

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

            if not docs:
                st.info("No documents found. Generate your first document to see it here.")
            else:
                company = st.session_state.get("company")
                st.caption(f"{len(docs)} document(s)")
                st.write("")

                for doc in docs:
                    title   = doc.get("title", "Untitled")
                    version = doc.get("version", "1.0")
                    created = format_date(doc.get("created_at", ""))
                    doc_id  = doc["document_id"]

                    with st.container(border=True):
                        info_col, act_col = st.columns([2, 3])

                        with info_col:
                            st.markdown(f"**{title}**")
                            st.caption(f"v{version}  ·  {created}")

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 — RAG ASSISTANT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_rag:
    st.markdown("## 🔍 RAG Document Assistant")
    st.caption("Ask questions grounded in your Notion document library.")

    def render_sources(citations):
        if citations:
            st.markdown("**Sources:**")
            for c in citations:
                st.markdown(
                    f"- [{c['source_number']}] **{c['breadcrumb']}** "
                    f"— `{c.get('doc_type', '')}` | `{c.get('department', '')}`"
                )

    def render_retrieval_inspector(retrieved, key_prefix):
        if not retrieved:
            return

        st.markdown("**Retrieval inspector**")
        for chunk in retrieved:
            with st.expander(
                f"[{chunk['source_number']}] {chunk['breadcrumb'][:70]} "
                f"| score: {round(chunk['score'], 3)}",
                expanded=False,
            ):
                st.markdown(f"**Doc Type:** `{chunk['doc_type']}`")
                st.markdown(f"**Department:** `{chunk['department']}`")
                st.markdown(f"**Score:** `{chunk['score']}`")
                st.markdown("**Retrieved Text:**")
                st.markdown(chunk.get("preview", ""))

    with st.expander("🔧 Filters", expanded=False):
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            doc_type_filter = st.text_input(
                "Doc Type",
                placeholder="e.g. Policy, Contract",
            )
        with f_col2:
            dept_filter = st.text_input(
                "Department",
                placeholder="e.g. Human Resources",
            )

    mode = st.radio(
        "Mode",
        ["Query", "Compare", "Summarize", "Evaluate"],
        horizontal=True,
    )

    if "rag_query_turns" not in st.session_state:
        st.session_state.rag_query_turns = []
    if "rag_compare_result" not in st.session_state:
        st.session_state.rag_compare_result = None
    if "rag_summary_result" not in st.session_state:
        st.session_state.rag_summary_result = None
    if "rag_evaluate_result" not in st.session_state:
        st.session_state.rag_evaluate_result = None

    if mode == "Query":
        for idx, turn in enumerate(st.session_state.rag_query_turns):
            with st.chat_message("user"):
                st.markdown(turn["question"])

            with st.chat_message("assistant"):
                st.markdown(turn.get("answer", "No answer."))
                conf = turn.get("confidence", "").lower()
                badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                st.caption(f"{badge} Confidence: {turn.get('confidence', 'N/A')}")
                render_sources(turn.get("citations", []))
                render_retrieval_inspector(turn.get("retrieved_chunks", []), f"query_{idx}")

        question = st.chat_input("Ask a question about your documents...")
        if question:
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                with st.spinner("Searching documents..."):
                    try:
                        payload = {"question": question, "top_k": 8}
                        if doc_type_filter:
                            payload["doc_type"] = doc_type_filter
                        if dept_filter:
                            payload["department"] = dept_filter

                        r = requests.post(f"{RAG_BASE}/rag-query", json=payload, timeout=60)
                        result = r.json()

                        turn = {
                            "question": question,
                            "answer": result.get("answer", "No answer."),
                            "confidence": result.get("confidence", "N/A"),
                            "citations": result.get("citations", []),
                            "retrieved_chunks": result.get("retrieved_chunks", []),
                        }
                        st.session_state.rag_query_turns.append(turn)

                        st.markdown(turn["answer"])
                        conf = turn["confidence"].lower()
                        badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                        st.caption(f"{badge} Confidence: {turn['confidence']}")
                        render_sources(turn["citations"])
                        render_retrieval_inspector(turn["retrieved_chunks"], "query_new")

                    except Exception as e:
                        st.error(f"Error: {e}")

    elif mode == "Compare":
        st.markdown("### Compare Two Document Types")
        c1, c2 = st.columns(2)
        with c1:
            doc_a = st.text_input("Document Type A", placeholder="e.g. Employment Contract")
        with c2:
            doc_b = st.text_input("Document Type B", placeholder="e.g. Offer Letter")

        compare_q = st.text_input("What to compare?", placeholder="e.g. notice period clauses")

        if st.button("Compare", type="primary"):
            if doc_a and doc_b and compare_q:
                with st.spinner("Comparing documents..."):
                    try:
                        r = requests.post(
                            f"{RAG_BASE}/rag-compare",
                            json={"question": compare_q, "doc_type_a": doc_a, "doc_type_b": doc_b},
                            timeout=60,
                        )
                        result = r.json()
                        st.session_state.rag_compare_result = {
                            "question": compare_q,
                            "answer": result.get("answer", "No result."),
                            "citations": result.get("citations", []),
                        }
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Fill in both document types and the comparison question.")

        compare_result = st.session_state.get("rag_compare_result")
        if compare_result:
            st.markdown("### Comparison Result")
            st.markdown(f"**Q:** {compare_result['question']}")
            st.markdown(compare_result["answer"])
            render_sources(compare_result.get("citations", []))

    elif mode == "Summarize":
        st.markdown("### Summarize a Document")
        sum_doc_type = st.text_input("Document Type to Summarize", placeholder="e.g. Leave Policy")
        sum_dept = st.text_input("Department (optional)", placeholder="e.g. Human Resources")

        if st.button("Summarize", type="primary"):
            if sum_doc_type:
                with st.spinner("Summarizing..."):
                    try:
                        payload = {"doc_type": sum_doc_type}
                        if sum_dept:
                            payload["department"] = sum_dept

                        r = requests.post(f"{RAG_BASE}/rag-summarize", json=payload, timeout=60)
                        result = r.json()
                        st.session_state.rag_summary_result = {
                            "question": f"Summarize: {sum_doc_type}",
                            "answer": result.get("answer", "No summary."),
                            "citations": result.get("citations", []),
                        }
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Enter a document type to summarize.")

        summary_result = st.session_state.get("rag_summary_result")
        if summary_result:
            st.markdown("### Summary")
            st.markdown(f"**Q:** {summary_result['question']}")
            st.markdown(summary_result["answer"])
            render_sources(summary_result.get("citations", []))

    elif mode == "Evaluate":
        st.markdown("### Evaluate RAG Pipeline")
        questions_input = st.text_area(
            "Enter questions (one per line)",
            placeholder="what is the notice period?\nwhat are the leave policies?\n",
            height=150,
        )

        if st.button("Run Evaluation", type="primary"):
            questions = [q.strip() for q in questions_input.strip().split("\n") if q.strip()]
            if questions:
                st.session_state.rag_evaluate_result = None
                with st.spinner(f"Running {len(questions)} questions..."):
                    try:
                        r = requests.post(f"{RAG_BASE}/rag-evaluate", json={"questions": questions}, timeout=300)
                        if r.status_code == 200:
                            st.session_state.rag_evaluate_result = r.json()
                        else:
                            try:
                                detail = r.json().get("detail", r.text)
                            except Exception:
                                detail = r.text
                            st.error(f"Evaluation failed ({r.status_code}): {detail}")
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Enter at least one question.")

        evaluate_result = st.session_state.get("rag_evaluate_result")
        if evaluate_result:
            st.markdown(f"### Results — {evaluate_result.get('total', 0)} questions")

            if "aggregate" in evaluate_result:
                agg = evaluate_result["aggregate"]
                a1, a2 = st.columns(2)
                a1.metric("Faithfulness", str(agg.get("faithfulness", "N/A")))
                a2.metric("Answer Relevancy", str(agg.get("answer_relevancy", "N/A")))
                st.divider()

            for item in evaluate_result.get("results", []):
                with st.expander(f"Q: {item['question'][:60]}..."):
                    ragas = item.get("ragas", {})
                    if ragas:
                        r1, r2 = st.columns(2)
                        r1.metric("Faithfulness", str(ragas.get("faithfulness")))
                        r2.metric("Answer Relevancy", str(ragas.get("answer_relevancy")))
                    st.markdown(item.get("answer", ""))
                    render_sources(item.get("citations", []))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 — AGENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab_agent:
    st.markdown("## Agent Assistant")
    st.caption("Chat with the LangGraph agent and raise support tickets when needed.")

    a_col1, a_col2, a_col3 = st.columns([1, 1, 1])
    with a_col1:
        st.metric("Session", st.session_state.agent_session_id or "New")
    with a_col2:
        if st.button("New Session", use_container_width=True):
            st.session_state.agent_session_id = None
            st.session_state.agent_turns = []
            st.rerun()
    with a_col3:
        if st.button("Refresh Tickets", use_container_width=True):
            st.session_state.agent_tickets = agent_get("/tickets", show_error=True)

    st.divider()

    for idx, turn in enumerate(st.session_state.agent_turns):
        with st.chat_message("user"):
            st.markdown(turn["question"])

        with st.chat_message("assistant"):
            st.markdown(turn.get("response", "No response."))
            meta = []
            if turn.get("intent"):
                meta.append(f"Intent: {turn['intent']}")
            if turn.get("confidence"):
                meta.append(f"Confidence: {turn['confidence']}")
            if turn.get("trace_id"):
                meta.append(f"Trace: {turn['trace_id']}")
            if meta:
                st.caption(" | ".join(meta))

            citations = turn.get("citations", [])
            if citations:
                st.markdown("**Sources:**")
                for c in citations:
                    st.markdown(f"- **{c.get('breadcrumb', 'Source')}**")

            if turn.get("cannot_answer") and not turn.get("ticket_created"):
                if st.button("Create Ticket", key=f"agent_ticket_{idx}"):
                    sources = [
                        c.get("breadcrumb", "")
                        for c in citations
                        if c.get("breadcrumb")
                    ]
                    ticket_data, ticket_err = agent_post(
                        "/create-ticket",
                        {
                            "session_id": st.session_state.agent_session_id,
                            "question": turn["question"],
                            "sources": sources,
                        },
                    )
                    if ticket_data:
                        turn["ticket_created"] = True
                        turn["ticket_status"] = ticket_data.get("status")
                        turn["ticket_url"] = ticket_data.get("ticket_url")
                        st.success(ticket_data.get("message", "Ticket created."))
                        if ticket_data.get("ticket_url"):
                            st.markdown(f"[Open ticket]({ticket_data['ticket_url']})")
                    else:
                        st.error(ticket_err or "Could not create ticket.")

            if turn.get("ticket_created"):
                status = turn.get("ticket_status", "created")
                st.success(f"Ticket {status}.")
                if turn.get("ticket_url"):
                    st.markdown(f"[Open ticket]({turn['ticket_url']})")

    agent_question = st.chat_input("Ask the agent...", key="agent_chat_input")
    if agent_question:
        with st.chat_message("user"):
            st.markdown(agent_question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                payload = {
                    "message": agent_question,
                    "session_id": st.session_state.agent_session_id,
                }
                result, err = agent_post("/chat", payload)

            if result:
                st.session_state.agent_session_id = result.get("session_id")
                turn = {
                    "question": agent_question,
                    "response": result.get("response", ""),
                    "intent": result.get("intent"),
                    "confidence": result.get("confidence"),
                    "citations": result.get("citations", []),
                    "cannot_answer": result.get("cannot_answer", False),
                    "ticket_id": result.get("ticket_id"),
                    "ticket_url": result.get("ticket_url"),
                    "ticket_created": bool(result.get("ticket_url")),
                    "ticket_status": "created" if result.get("ticket_url") else None,
                    "trace_id": result.get("trace_id"),
                }
                st.session_state.agent_turns.append(turn)
                st.markdown(turn["response"] or "No response.")
                meta = []
                if turn.get("intent"):
                    meta.append(f"Intent: {turn['intent']}")
                if turn.get("confidence"):
                    meta.append(f"Confidence: {turn['confidence']}")
                if turn.get("trace_id"):
                    meta.append(f"Trace: {turn['trace_id']}")
                if meta:
                    st.caption(" | ".join(meta))
                st.rerun()
            else:
                st.error(err or "Agent request failed.")

    with st.expander("Tickets", expanded=False):
        tickets_data = st.session_state.agent_tickets
        if tickets_data is None:
            st.info("Click Refresh Tickets to load support tickets.")
        else:
            tickets = tickets_data.get("tickets", [])
            if not tickets:
                st.info("No tickets found.")
            for ticket in tickets:
                st.markdown(
                    f"**{ticket.get('title', 'Unknown')}**  \n"
                    f"Status: `{ticket.get('status', 'Unknown')}` | "
                    f"Priority: `{ticket.get('priority', 'Unknown')}` | "
                    f"Session: `{ticket.get('session_id', '')}`"
                )
                if ticket.get("url"):
                    st.markdown(f"[Open in Notion]({ticket['url']})")
                st.divider()


st.caption("DocForge Hub · Powered by AI")
