"""Adapter container built from configuration. Tests and eval override individual adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.adapters.crm_claims import MockClaimsData, MockCRM
from app.adapters.enrichment import MockCatModel, MockGeocoder
from app.adapters.mailbox import BrokerPortalAdapter, FolderMailbox
from app.adapters.ocr import MockOcr
from app.adapters.policy_admin import MockPolicyAdmin
from app.adapters.rating import ExcelModelRatingAdapter, MockPackageRatingApi
from app.adapters.scanning import ClamAVScanner, MockAntivirus
from app.adapters.storage import LocalDocumentStore, LocalObjectStore
from app.core.config import get_settings


@dataclass
class Adapters:
    object_store: object
    document_store: object
    mailbox: object
    portal: object
    antivirus: object
    ocr: object
    geocoder: object
    cat_model: object
    package_rating: object
    policy_admin: object
    crm: object
    claims: object
    workbook_allow_list: dict = field(default_factory=dict)

    def excel_rating(self) -> ExcelModelRatingAdapter:
        s = get_settings()
        return ExcelModelRatingAdapter(Path(s.rating_workbook_path) if s.rating_workbook_path else None,
                                       self.workbook_allow_list)


def build() -> Adapters:
    s = get_settings()
    if s.object_store == "s3":  # pragma: no cover
        from app.adapters.storage import S3ObjectStore

        store: object = S3ObjectStore()
    elif s.object_store == "gcs":  # pragma: no cover
        from app.adapters.storage import GCSObjectStore

        store = GCSObjectStore(s.s3_bucket)
    else:
        store = LocalObjectStore(s.object_store_dir)
    av = ClamAVScanner(s.clamav_host, s.clamav_port) if s.antivirus == "clamav" else MockAntivirus()
    if s.ocr == "tesseract":  # pragma: no cover
        from app.adapters.ocr import TesseractOcr

        ocr: object = TesseractOcr()
    else:
        ocr = MockOcr()
    return Adapters(
        object_store=store,
        document_store=LocalDocumentStore(str(Path(s.object_store_dir) / "sharepoint")),
        mailbox=FolderMailbox(),
        portal=BrokerPortalAdapter(),
        antivirus=av,
        ocr=ocr,
        geocoder=MockGeocoder(),
        cat_model=MockCatModel(),
        package_rating=MockPackageRatingApi(),
        policy_admin=MockPolicyAdmin(),
        crm=MockCRM(),
        claims=MockClaimsData(),
    )


_adapters: Adapters | None = None


def get_adapters() -> Adapters:
    global _adapters
    if _adapters is None:
        _adapters = build()
    return _adapters


def set_adapters(a: Adapters | None) -> None:
    global _adapters
    _adapters = a
