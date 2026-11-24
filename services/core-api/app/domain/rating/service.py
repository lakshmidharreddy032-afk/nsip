"""Rating runs. The premium always comes from a filed source adapter; nothing else may produce one."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.rating import RatingError, RatingRequest
from app.adapters.registry import Adapters, get_adapters
from app.core.security import UNDERWRITING_ROLES, Principal
from app.domain.appetite.occupancy import HAZARD_BY_CODE
from app.domain.audit import service as audit
from app.domain.extraction import service as ext
from app.domain.submissions import service as subs
from app.models import IntegrationConfig, RatingRun, Submission

FILED_SOURCES = ("rating_api", "excel_model")
RATEABLE_STATUSES = ("ready_for_rating", "rated")


class RatingServiceError(Exception):
    pass


def workbook_allow_list(db: Session) -> dict:
    row = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key == "rating_workbooks"))
    return row.config if row else {}


def build_request(db: Session, sub: Submission) -> RatingRequest:
    vals = subs.current_values(db, sub.id)
    f = ext.build_features(vals, sub.region)
    if not f["sum_insured"] or not f["occupancy_code"]:
        raise RatingServiceError("Sum insured and a recognised occupancy are required for rating.")
    hazard = HAZARD_BY_CODE.get(f["occupancy_code"])
    if hazard not in ("low", "medium", "high"):
        raise RatingServiceError("Occupancy is not rateable under the filed tables.")
    ded = vals.get("cover.deductible")
    return RatingRequest(line=sub.line, sum_insured=int(f["sum_insured"]), hazard_class=hazard,
                         construction=f["construction"] or "rcc", cat_zone=f["cat_zone"] or "medium",
                         claims_count_3y=int(f["claims_count_3y"] or 0),
                         deductible=int(ded) if isinstance(ded, int) else 0, occupancy_code=f["occupancy_code"])


def run_rating(db: Session, p: Principal, sub: Submission, adapters: Adapters | None = None) -> RatingRun:
    adapters = adapters or get_adapters()
    if not p.has(*UNDERWRITING_ROLES):
        raise RatingServiceError("Only underwriters can run rating.")
    if not p.can_see_region(sub.region):
        raise RatingServiceError("Submission is outside your region.")
    if sub.status not in RATEABLE_STATUSES:
        raise RatingServiceError("Submission must be marked ready (reviewed) before rating.")
    if sub.referral_status == "open":
        raise RatingServiceError("Risk-engineering referral must be completed before pricing.")
    if sub.triage_outcome == "out_of_appetite":
        raise RatingServiceError("Out-of-appetite submissions cannot be rated.")
    req = build_request(db, sub)
    if sub.line == "package":
        adapter = adapters.package_rating
    else:
        adapters.workbook_allow_list = workbook_allow_list(db)
        adapter = adapters.excel_rating()
    try:
        result = adapter.rate(req)  # type: ignore[attr-defined]
    except RatingError as e:
        raise RatingServiceError(str(e)) from e
    if result.source not in FILED_SOURCES:
        raise RatingServiceError("Rating source is not a filed source.")
    run = RatingRun(submission_id=sub.id, source=result.source, source_version=result.source_version,
                    filing_ref=result.filing_ref, workbook_hash=result.workbook_hash, inputs_hash=req.inputs_hash(),
                    inputs=req.canonical(), outputs={"premium": str(result.premium), **result.breakdown},
                    premium=result.premium, run_by=p.user_id)
    db.add(run)
    sub.status = "rated"
    db.flush()
    audit.record(db, action="rating.run", entity_type="submission", entity_id=sub.id, actor_id=p.user_id,
                 actor_type="human", region=sub.region,
                 data={"rating_run": str(run.id), "source": run.source, "version": run.source_version,
                       "filing_ref": run.filing_ref, "workbook_hash": run.workbook_hash,
                       "inputs_hash": run.inputs_hash, "premium": str(run.premium)})
    db.commit()
    return run


def is_current(db: Session, sub: Submission, run: RatingRun) -> bool:
    try:
        return build_request(db, sub).inputs_hash() == run.inputs_hash
    except RatingServiceError:
        return False
