"""Prompt-injection detection and untrusted-content isolation.

Detection only flags content for the reviewer. It never changes routing: routing and appetite
decisions are made by deterministic code from validated fields (see domain/appetite).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

_PATTERNS: list[tuple[str, str]] = [
    ("override_instructions", r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b.{0,30}\b(instruction|prompt|rule|direction)s?"),
    ("role_hijack", r"\b(you are now|act as|pretend to be|from now on you)\b"),
    ("approval_command", r"\b(mark|set|flag|classify|treat|route)\b.{0,40}\b(as\s+)?(approved|in[\s-]?appetite|accepted|bound|pre[\s-]?approved|cleared|priority|urgent)\b"),
    ("decision_command", r"\b(approve|auto[\s-]?approve|issue|bind|accept)\b.{0,30}\b(this|the)?\s*(quote|policy|risk|submission|cover)\b.{0,30}\b(immediately|now|automatically|without)"),
    ("skip_controls", r"\b(skip|bypass|disable|no need for)\b.{0,30}\b(review|referral|triage|check|survey|underwriter|validation|clearance)"),
    ("permission_escalation", r"\b(grant|give|elevate|assign)\b.{0,30}\b(admin|authority|permission|access|role)\b"),
    ("system_prompt_probe", r"\b(system prompt|reveal your|print your instructions|developer mode|jailbreak)\b"),
    ("delimiter_spoof", r"(</?\s*(system|assistant|untrusted_data|instructions)\s*>|\[/?INST\]|<\|im_start\|>)"),
    ("premium_injection", r"\b(premium|rate)\b.{0,20}\b(should be|must be|set to|is fixed at)\b"),
]
_COMPILED = [(name, re.compile(p, re.IGNORECASE | re.DOTALL)) for name, p in _PATTERNS]
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")


@dataclass
class InjectionFlag:
    pattern: str
    excerpt: str
    location: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return _ZERO_WIDTH.sub("", text)


def detect(text: str, location: str) -> list[InjectionFlag]:
    norm = normalise(text)
    flags = []
    for name, rx in _COMPILED:
        for m in rx.finditer(norm):
            s, e = max(m.start() - 20, 0), min(m.end() + 20, len(norm))
            flags.append(InjectionFlag(name, norm[s:e].replace("\n", " ").strip()[:240], location))
            break
    return flags


def wrap_untrusted(text: str, label: str) -> str:
    """Delimit untrusted broker content as data. Neutralise any attempt to close the data block."""
    safe = normalise(text).replace("<untrusted_data", "&lt;untrusted_data").replace("</untrusted_data", "&lt;/untrusted_data")
    return f'<untrusted_data source="{label}">\n{safe}\n</untrusted_data>'
