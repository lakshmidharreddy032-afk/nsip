"""Attachment antivirus (ClamAV) and Office macro stripping."""
from __future__ import annotations

import io
import socket
import struct
import zipfile
from typing import Protocol

EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


class AntivirusAdapter(Protocol):
    def scan(self, data: bytes) -> str: ...  # clean | infected | error


class MockAntivirus:
    def scan(self, data: bytes) -> str:
        return "infected" if EICAR_MARKER in data else "clean"


class ClamAVScanner:  # pragma: no cover - requires clamd container
    def __init__(self, host: str, port: int) -> None:
        self.host, self.port = host, port

    def scan(self, data: bytes) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=30) as s:
                s.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), 8192):
                    chunk = data[i:i + 8192]
                    s.sendall(struct.pack("!L", len(chunk)) + chunk)
                s.sendall(struct.pack("!L", 0))
                resp = s.recv(4096)
            return "clean" if resp.rstrip(b"\0").endswith(b"OK") else "infected"
        except OSError:
            return "error"


MACRO_EXTS = (".xlsm", ".xlsb", ".docm", ".pptm", ".xltm")


def strip_macros(filename: str, data: bytes) -> tuple[bytes, bool]:
    """Remove VBA projects from OOXML packages. Returns (data, stripped?). Legacy .xls is parsed read-only."""
    low = filename.lower()
    if not (low.endswith(MACRO_EXTS) or low.endswith((".xlsx", ".docx"))):
        return data, False
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return data, False
    names = zin.namelist()
    bad = [n for n in names if "vbaProject" in n or n.lower().endswith(".bin") and "vba" in n.lower()]
    if not bad:
        return data, False
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            if n in bad:
                continue
            content = zin.read(n)
            if n == "[Content_Types].xml":
                content = content.replace(b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
                                          b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
            zout.writestr(n, content)
    return out.getvalue(), True
