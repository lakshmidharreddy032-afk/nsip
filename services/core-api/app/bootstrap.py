"""Reference data bootstrap for core-api: flags, SOV layout library, appetite ruleset v1, brokers,
filed rating workbook allow-list. Demo users/authority are seeded by scripts/seed.py.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.rating import BUNDLED_WORKBOOK, workbook_sha256
from app.domain.analytics.flags import seed_flags
from app.domain.appetite.service import ensure_default_ruleset
from app.domain.extraction.sov import seed_library
from app.models import Broker, IntegrationConfig

BROKERS = [
    ("Meridian Insurance Brokers", "MIB001", "meridianbrokers.example", "west"),
    ("Coastal Risk Advisors", "CRA002", "coastalrisk.example", "south"),
    ("Pinnacle Insurance Broking", "PIB003", "pinnaclebroking.example", "west"),
    ("Sahyadri Insurance Services", "SIS004", "sahyadriins.example", "west"),
    ("Deccan Cover Brokers", "DCB005", "deccancover.example", "south"),
    ("Northgate Brokers", "NGB006", "northgatebrokers.example", "north"),
    ("Eastline Insurance Brokers", "EIB007", "eastline.example", "east"),
    ("Harbour Point Risk", "HPR008", "harbourpoint.example", "west"),
    ("Saffron Insurance Broking", "SIB009", "saffronbroking.example", "west"),
    ("Kaveri Risk Partners", "KRP010", "kaveririsk.example", "south"),
    ("Indus Shield Brokers", "ISB011", "indusshield.example", "north"),
    ("Lotus Commercial Brokers", "LCB012", "lotuscommercial.example", "west"),
]


def bootstrap(db: Session) -> None:
    seed_flags(db)
    seed_library(db)
    ensure_default_ruleset(db)
    for name, code, domain, region in BROKERS:
        if not db.scalar(select(Broker).where(Broker.code == code)):
            db.add(Broker(name=name, code=code, email_domain=domain, region=region))
    if BUNDLED_WORKBOOK.exists():
        row = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == "rating_workbooks"))
        digest = workbook_sha256(BUNDLED_WORKBOOK)
        entry = {"version": "NSG-PROP-2026.1", "filing_ref": "SAMPLE-FILING-PROP-2026-01",
                 "file": BUNDLED_WORKBOOK.name}
        if row is None:
            db.add(IntegrationConfig(key="rating_workbooks", config={digest: entry}))
        elif digest not in row.config:
            row.config = {**row.config, digest: entry}
    db.commit()


if __name__ == "__main__":
    from app.core.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        bootstrap(s)
    print("bootstrap complete")
