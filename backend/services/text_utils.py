import re
from datetime import date
from typing import Optional

_DEFAULTS = {
    "name": "the relevant party", "full name": "the relevant party",
    "candidate name": "the Candidate", "employee name": "the Employee",
    "authorized by": "the Authorised Signatory", "signatory": "the Authorised Signatory",
    "approver": "the Authorised Approver", "company name": "the Company",
    "organisation": "the Organisation", "department": "the Department",
    "designation": "the relevant designation", "job title": "the relevant position",
    "role": "the relevant role", "salary": "as per agreement",
    "ctc": "as per agreement", "amount": "as per agreement",
    "price": "as per agreement", "compensation": "as per agreement",
    "location": "the registered office", "address": "the registered address",
    "reference": "as referenced", "ref": "as referenced",
}

_INJECTION = re.compile(
    r"(ignore\s+(previous|all|above|prior)\s+instructions?|you\s+are\s+now\s+|"
    r"system\s*:|assistant\s*:|<\|.+?\|>|\\n\\n###|jailbreak)",
    re.IGNORECASE,
)


def _fill(token: str) -> str:
    t = token.strip().lower()
    for key, val in _DEFAULTS.items():
        if key in t:
            return val
    return f"the {t.replace('_', ' ').title()}"


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.*?)\*\*|\*(.*?)\*|`(.*?)`", lambda m: next(g for g in m.groups() if g is not None), text)
    text = re.sub(r"^[-=]{3,}$", "", text, flags=re.MULTILINE)
    for old, new in [("\u2019","'"),("\u2018","'"),("\u201c",'"'),("\u201d",'"'),("\u2013","-"),("\u2014","--")]:
        text = text.replace(old, new)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def replace_placeholders(text: str, answers: Optional[dict] = None, doc_context: Optional[dict] = None) -> str:
    today = date.today().strftime("%d %B %Y")

    if answers:
        fields = {
            r"\[COMPANY[_ ]NAME\]":   answers.get("company_name", ""),
            r"\[CANDIDATE[_ ]NAME\]": answers.get("candidate_name") or answers.get("employee_name", ""),
            r"\[EMPLOYEE[_ ]NAME\]":  answers.get("employee_name") or answers.get("candidate_name", ""),
            r"\[JOB[_ ]TITLE\]":      answers.get("job_title") or answers.get("designation", ""),
            r"\[DESIGNATION\]":       answers.get("designation") or answers.get("job_title", ""),
            r"\[DEPARTMENT\]":        answers.get("department", ""),
            r"\[JOINING[_ ]DATE\]":   answers.get("joining_date", today),
            r"\[SALARY\]":            answers.get("salary") or answers.get("ctc", ""),
            r"\[CTC\]":               answers.get("ctc") or answers.get("salary", ""),
            r"\[LOCATION\]":          answers.get("location", ""),
        }
        for pattern, value in fields.items():
            if value and str(value).strip():
                text = re.sub(pattern, str(value).strip(), text, flags=re.IGNORECASE)

    text = re.sub(r"\[DATE\]|\[date\]|\[Date\]|\[TODAY\]|\[today\]", today, text)
    text = re.sub(r"\[YEAR\]", str(date.today().year), text)
    text = re.sub(r"\[MONTH\]", date.today().strftime("%B"), text)
    text = re.sub(r"\[TBD\]|\bTBD\b", "to be confirmed", text)
    text = re.sub(r"\[INSERT[^\]]*\]", _fill("INSERT"), text)
    text = re.sub(r"\[ADD[^\]]*\]", "", text)
    text = re.sub(r"\[([A-Z][A-Z\s_]{2,})\]", lambda m: _fill(m.group(1)), text)
    return text


def sanitize_answer_value(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value[:12000])
    return _INJECTION.sub("[redacted]", value).strip()


def sanitize_answers(answers: dict) -> dict:
    return {k: sanitize_answer_value(str(v)) if v is not None else "" for k, v in answers.items()}
