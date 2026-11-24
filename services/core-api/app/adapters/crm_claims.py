"""CRM (broker activity) and claims data platform (monthly snapshot) adapters."""
from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class CRMAdapter(Protocol):
    def log_activity(self, broker_code: str, activity: str, detail: dict) -> None: ...


class MockCRM:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or Path(get_settings().outbox_dir) / "crm_activity.jsonl")

    def log_activity(self, broker_code: str, activity: str, detail: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "broker": broker_code,
                                "activity": activity, "detail": detail}, default=str) + "\n")


class ClaimsDataAdapter(Protocol):
    def monthly_snapshot(self) -> dict: ...


class MockClaimsData:
    """Monthly snapshot of earned premium and incurred losses by cohort (AI-assisted vs baseline)."""

    def monthly_snapshot(self) -> dict:
        rng = random.Random(2026)  # noqa: S311 - synthetic data
        months = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
        rows = []
        for m in months:
            for cohort, base in (("baseline", 0.68), ("ai_assisted", 0.665)):
                earned = rng.randint(380, 420) * 1_00_000
                rows.append({"month": m, "cohort": cohort, "earned_premium": earned,
                             "incurred": int(earned * (base + rng.uniform(-0.03, 0.03)))})
        return {"snapshot_date": "2026-11-01", "refresh": "monthly", "rows": rows}
