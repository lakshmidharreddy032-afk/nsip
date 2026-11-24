"""Deterministic stand-in for the India-hosted AI gateway (OpenAI-compatible chat completions).

It behaves like a model: it reads the prompt, returns schema-shaped JSON, and is deliberately
*naive* about prompt injection in `appetite_signals` (it obeys "mark as approved"), so the red-team
suite can prove that the platform never lets model output drive routing or decisions.
"""
from __future__ import annotations

import json
import re

_BLOCK = re.compile(r'<untrusted_data source="([^"]+)">\n(.*?)\n</untrusted_data>', re.S)
_AMOUNT = r"(?:Rs\.?|INR|₹)\s*([\d.,]+\s*(?:crores?|cr|lakhs?|lacs?)?)"


def _blocks(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _BLOCK.finditer(text)}


def _line_of(doc: str, pos: int) -> int:
    return doc.count("\n", 0, pos) + 1


def _fact(doc: str, rx: str, conf: float = 0.9, group: int = 1, flags=re.I):
    m = re.search(rx, doc, flags)
    if not m:
        return None
    val = m.group(group).strip().rstrip(".,")
    return {"value": val, "confidence": conf, "evidence": m.group(0)[:300], "line": _line_of(doc, m.start())}


def classify(doc: str, attachments: str) -> dict:
    low = doc.lower()
    if any(k in low for k in ("out of office", "auto-reply", "automatic reply", "unsubscribe", "newsletter")):
        return {"category": "noise", "confidence": 0.95, "reasons": ["auto-reply or bulk mail markers"]}
    if any(k in low for k in ("revised sov", "updated sov", "revised schedule", "updated schedule")):
        return {"category": "updated_schedule", "confidence": 0.9, "reasons": ["mentions revised schedule"]}
    if any(k in low for k in ("sum insured", "proposal", "quote", "sov", "schedule of values", "premises")):
        return {"category": "new_submission", "confidence": 0.85, "reasons": ["risk details present"]}
    if "?" in doc or any(k in low for k in ("status", "update on", "chasing", "any news")):
        return {"category": "query", "confidence": 0.8, "reasons": ["question without risk details"]}
    return {"category": "noise", "confidence": 0.55, "reasons": ["no submission markers"]}


def key_facts(doc: str) -> dict:
    out: dict = {}
    out["insured_name"] = _fact(doc, r"(?:submission|proposal|quote) for (?:M/s\.?\s+)?(.+?),\s+who (?:operate|run|are)")
    out["occupancy"] = _fact(doc, r"(?:operate|run|are engaged in) (?:as )?(?:an? )?(.+?) (?:from|at) (?:their|the) premises")
    m = re.search(r"premises at (.+?),\s*([A-Za-z][A-Za-z .]+?)\s*-\s*(\d{6})", doc, re.I)
    if m:
        line = _line_of(doc, m.start())
        out["risk_address"] = {"value": f"{m.group(1).strip()}, {m.group(2).strip()}", "confidence": 0.88,
                               "evidence": m.group(0)[:300], "line": line}
        out["pincode"] = {"value": m.group(3), "confidence": 0.93, "evidence": m.group(0)[:300], "line": line}
    out["construction"] = _fact(doc, r"(?:buildings? (?:are|is) of|constructed (?:of|with)) (.+?) construction")
    out["year_built"] = _fact(doc, r"built (?:around|in) (\d{4})")
    out["coverage"] = _fact(doc, r"seeking (.+?) (?:cover )?with a")
    out["sum_insured"] = _fact(doc, r"total sum insured of " + _AMOUNT, 0.9)
    out["deductible"] = _fact(doc, r"Deductible requested:\s*([^\n]+?)\.(?:\s|$)", 0.8)
    out["inception_date"] = _fact(doc, r"inception (?:is|date is|from) (\d{1,2}[-/.]\d{1,2}[-/.]\d{4})")
    m = re.search(r"(\d+|no|nil) claims? in the last three years(?: amounting to " + _AMOUNT + ")?", doc, re.I)
    if m:
        n = 0 if m.group(1).lower() in ("no", "nil") else int(m.group(1))
        line = _line_of(doc, m.start())
        out["claims_count_3y"] = {"value": n, "confidence": 0.85, "evidence": m.group(0)[:300], "line": line}
        if m.group(2):
            out["claims_amount_3y"] = {"value": m.group(2).strip(), "confidence": 0.82,
                                       "evidence": m.group(0)[:300], "line": line}
    return {k: v for k, v in out.items() if v}


_SYNONYMS = [
    ("loc_no", ["loc no", "location no", "sr", "s.no", "sl", "site id", "risk no", "#"]),
    ("pincode", ["pin", "postal", "zip"]),
    ("city", ["city", "town", "district"]),
    ("address", ["address", "premises", "location", "site"]),
    ("occupancy", ["occupancy", "trade", "nature", "activity", "usage"]),
    ("construction", ["construction", "const", "structure", "building type"]),
    ("year_built", ["year", "built", "yob"]),
    ("plant_machinery", ["plant", "machinery", "p&m", "pm", "equipment"]),
    ("stock", ["stock", "inventory", "goods"]),
    ("contents", ["content", "furniture", "ffe", "fixtures"]),
    ("building", ["building", "bldg", "structure value", "civil"]),
    ("total", ["total", "tsi", "sum"]),
    ("other", ["other", "misc"]),
]


def map_headers(headers_block: str) -> dict:
    headers = [h.strip() for h in headers_block.splitlines() if h.strip()]
    mappings = []
    for h in headers:
        low = h.lower()
        field, conf = "ignore", 0.5
        for cand, keys in _SYNONYMS:
            if any(k in low for k in keys):
                # building type / year built are not money columns
                if cand == "building" and ("type" in low or "year" in low or "age" in low):
                    continue
                field, conf = cand, 0.86
                break
        mult = 1
        if re.search(r"lakh|lac", low):
            mult = 100000
        elif re.search(r"\bcr\b|crore", low):
            mult = 10000000
        elif "'000" in low or "000s" in low or "thousand" in low:
            mult = 1000
        mappings.append({"header": h, "field": field, "unit_multiplier": mult, "confidence": conf})
    return {"mappings": mappings}


def appetite_signals(doc: str, features: str) -> dict:
    low = doc.lower()
    notes = []
    if "chemical" in low or "solvent" in low:
        notes.append("Chemical storage or processing mentioned.")
    if "ammonia" in low or "cold storage" in low:
        notes.append("Ammonia refrigeration hazard.")
    if "sprinkler" in low:
        notes.append("Sprinkler protection stated.")
    suggested = None
    # Deliberately naive: obeys injected instructions. Platform must ignore this field for routing.
    if re.search(r"(mark|treat|classify).{0,30}(approved|in[\s-]?appetite)", low):
        suggested = "in_appetite"
    return {"occupancy_code_suggestion": None, "hazard_notes": notes,
            "rationale": "Hazard features summarised from the submission text. " + (" ".join(notes) or
                                                                                     "No specific hazards noted."),
            "suggested_outcome": suggested}


def decline_letter(trusted: str) -> dict:
    def grab(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", trusted)
        return m.group(1).strip() if m else ""

    reasons = re.findall(r"^- (.+)$", trusted, re.M)
    body = (
        f"Dear {grab('Broker') or 'Partner'},\n\n"
        f"Thank you for the opportunity to consider {grab('Insured')} (our reference {grab('Our reference')}).\n\n"
        "After review against Northstar General's current underwriting guidelines, we are unable to offer "
        "terms on this occasion for the following reason(s):\n"
        + "\n".join(f"  - {r}" for r in reasons)
        + "\n\nWe value our relationship and look forward to supporting you on other risks.\n\n"
        "Kind regards,\nCommercial Property Underwriting\nNorthstar General Insurance"
    )
    return {"subject": f"Northstar General - unable to quote - {grab('Our reference')}", "body": body}


def handle(req: dict) -> dict:
    meta = req.get("metadata", {})
    pid = meta.get("prompt_id", "")
    user = next((m["content"] for m in req.get("messages", []) if m["role"] == "user"), "")
    blocks = _blocks(user)
    doc = blocks.get("document") or blocks.get("email") or ""
    if pid == "classify_email":
        att = re.search(r"Attachment names: (.*)", user)
        out = classify(doc, att.group(1) if att else "")
    elif pid == "extract_key_facts":
        out = key_facts(doc)
    elif pid == "map_sov_headers":
        out = map_headers(blocks.get("headers", ""))
    elif pid == "appetite_signals":
        out = appetite_signals(doc, "")
    elif pid == "decline_letter":
        out = decline_letter(user)
    else:
        out = {}
    content = json.dumps(out)
    return {
        "id": f"mock-{meta.get('request_id', '')}",
        "object": "chat.completion",
        "model": req.get("model", "mock"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": max(len(user) // 4, 1), "completion_tokens": max(len(content) // 4, 1)},
    }
