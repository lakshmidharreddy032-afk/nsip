"""Object storage (originals, immutable) and the SharePoint document store adapter."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid object key")
        return p

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3ObjectStore:  # pragma: no cover - exercised against MinIO in compose
    """S3/MinIO with server-side encryption at rest. Streams large attachments via multipart upload."""

    def __init__(self) -> None:
        import boto3

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint, aws_access_key_id=s.s3_access_key,
                                   aws_secret_access_key=s.s3_secret_key, region_name="ap-south-1")

    def put(self, key: str, data: bytes) -> str:
        import io

        self.client.upload_fileobj(io.BytesIO(data), self.bucket, key,
                                   ExtraArgs={"ServerSideEncryption": "AES256"})
        return key

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"
    return name[:120]


def document_path(region: str, submission_ref: str, seq: int, sha256: str, filename: str,
                  when: datetime) -> str:
    """Consistent naming convention going forward. Legacy SharePoint naming is never parsed."""
    return f"NSIP/{region}/{when:%Y}/{when:%m}/{submission_ref}/{seq:02d}_{sha256[:8]}_{safe_filename(filename)}"


class DocumentStoreAdapter(Protocol):
    def store(self, path: str, data: bytes) -> str: ...


class LocalDocumentStore:
    def __init__(self, root: str) -> None:
        self.inner = LocalObjectStore(root)

    def store(self, path: str, data: bytes) -> str:
        return self.inner.put(path, data)


class SharePointDocumentStore:  # pragma: no cover - requires tenant
    """Uploads via Microsoft Graph drive API using app-only credentials from the secrets manager."""

    def __init__(self, drive_id: str, token_provider) -> None:
        self.drive_id, self.token_provider = drive_id, token_provider

    def store(self, path: str, data: bytes) -> str:
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{path}:/content"
        r = httpx.put(url, content=data, headers={"Authorization": f"Bearer {self.token_provider()}"}, timeout=60)
        r.raise_for_status()
        return r.json()["webUrl"]
