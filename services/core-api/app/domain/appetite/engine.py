"""Pure, deterministic appetite rules engine. Inputs are validated features computed by code.

No model output is ever an input to this engine; `llm_signals` are stored alongside for monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field

OUTCOME_PRECEDENCE = ["out_of_appetite", "needs_info", "refer_risk_engineering", "in_appetite"]
VALID_OPS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "missing", "present"}


class RuleError(ValueError):
    pass


@dataclass
class Rule:
    id: str
    name: str
    outcome: str
    condition: dict
    priority: int = 100
    decline_reason: str = ""
    enabled: bool = True


@dataclass
class Evaluation:
    outcome: str
    fired: list[dict] = field(default_factory=list)


def validate_condition(cond: dict) -> None:
    if "all" in cond or "any" in cond:
        items = cond.get("all") or cond.get("any")
        if not isinstance(items, list) or not items:
            raise RuleError("all/any must be a non-empty list")
        for c in items:
            validate_condition(c)
        return
    if cond.get("op") not in VALID_OPS or "field" not in cond:
        raise RuleError(f"invalid leaf condition: {cond}")
    if cond["op"] not in ("missing", "present") and "value" not in cond:
        raise RuleError(f"condition needs a value: {cond}")


def validate_rule(r: Rule) -> None:
    if r.outcome not in OUTCOME_PRECEDENCE[:3]:
        raise RuleError(f"{r.id}: invalid outcome {r.outcome}")
    validate_condition(r.condition)


def _leaf(cond: dict, f: dict) -> bool:
    v = f.get(cond["field"])
    op, target = cond["op"], cond.get("value")
    if op == "missing":
        return v is None or v == ""
    if op == "present":
        return v is not None and v != ""
    if op == "eq":
        return v == target
    if op == "ne":
        return v != target
    if v is None:
        return False
    if op == "in":
        return v in (target or [])
    if op == "not_in":
        return v not in (target or [])
    try:
        if op == "gt":
            return v > target
        if op == "gte":
            return v >= target
        if op == "lt":
            return v < target
        if op == "lte":
            return v <= target
    except TypeError:
        return False
    return False  # pragma: no cover


def matches(cond: dict, features: dict) -> bool:
    if "all" in cond:
        return all(matches(c, features) for c in cond["all"])
    if "any" in cond:
        return any(matches(c, features) for c in cond["any"])
    return _leaf(cond, features)


def evaluate(rules: list[Rule], features: dict) -> Evaluation:
    fired = []
    for r in sorted(rules, key=lambda x: x.priority):
        if r.enabled and matches(r.condition, features):
            fired.append({"rule_id": r.id, "name": r.name, "outcome": r.outcome, "decline_reason": r.decline_reason})
    outcome = "in_appetite"
    for candidate in OUTCOME_PRECEDENCE:
        if any(x["outcome"] == candidate for x in fired):
            outcome = candidate
            break
    return Evaluation(outcome, fired)
