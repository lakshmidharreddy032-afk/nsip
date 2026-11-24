"""DPDP Act 2023 personal-data detection and masking for logs and LLM prompts.

Detects: PAN, Aadhaar, Indian phone numbers, personal email addresses and names of individuals
introduced by honorifics or contact labels. Company names are not personal data and are kept.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "rediffmail.com", "icloud.com",
    "live.com", "protonmail.com", "aol.com",
}

_PAN = re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b")
_AADHAAR = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
_PHONE = re.compile(r"(?<![\d\w])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_NAME = re.compile(
    r"\b(?:(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Kumari)\.?\s+|"
    r"(?i:contact person|contact|attn|attention|proprietor|director|partner)\s*[:\-]\s*)"
    r"((?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+){0,3})"
)


@dataclass
class PiiHit:
    pii_type: str
    start: int
    end: int
    value: str

    @property
    def value_hash(self) -> str:
        return hashlib.sha256(self.value.strip().lower().encode()).hexdigest()

    @property
    def masked(self) -> str:
        v = self.value
        if self.pii_type == "email":
            local, _, dom = v.partition("@")
            return f"{local[:1]}***@{dom}"
        if self.pii_type == "person_name":
            return " ".join(p[:1] + "***" for p in v.split())
        return "*" * max(len(v) - 4, 0) + v[-4:]


def detect(text: str) -> list[PiiHit]:
    if not text:
        return []
    hits: list[PiiHit] = []
    for m in _PAN.finditer(text):
        hits.append(PiiHit("pan", m.start(), m.end(), m.group()))
    for m in _AADHAAR.finditer(text):
        hits.append(PiiHit("aadhaar", m.start(), m.end(), m.group()))
    for m in _PHONE.finditer(text):
        if not any(h.start <= m.start() < h.end for h in hits):
            hits.append(PiiHit("phone", m.start(), m.end(), m.group()))
    for m in _EMAIL.finditer(text):
        if m.group(1).lower() in PERSONAL_EMAIL_DOMAINS:
            hits.append(PiiHit("email", m.start(), m.end(), m.group()))
    for m in _NAME.finditer(text):
        hits.append(PiiHit("person_name", m.start(1), m.end(1), m.group(1)))
    hits.sort(key=lambda h: h.start)
    # drop overlaps, keep the earliest/longest
    out: list[PiiHit] = []
    for h in hits:
        if out and h.start < out[-1].end:
            continue
        out.append(h)
    return out


def mask(text: str, keep: set[str] | None = None) -> str:
    """Replace detected PII with typed placeholders. `keep` lists types needed for the task."""
    if not text:
        return text
    keep = keep or set()
    parts, last = [], 0
    for h in detect(text):
        if h.pii_type in keep:
            continue
        parts.append(text[last:h.start])
        parts.append(f"[{h.pii_type.upper()}:{h.masked}]")
        last = h.end
    parts.append(text[last:])
    return "".join(parts)


def mask_obj(obj):
    """Recursively mask strings inside dict/list payloads (for logs and stored AI call records)."""
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    return obj
