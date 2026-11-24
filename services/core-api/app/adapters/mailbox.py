"""Regional shared-mailbox adapters: MS Graph, IMAP fallback, and a folder mock (.eml files)."""
from __future__ import annotations

import imaplib
import json
import shutil
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings


@dataclass
class RawMessage:
    ref: str  # adapter-specific handle used to mark processed
    region: str
    mailbox: str
    raw: bytes
    channel: str = "email"


class MailboxAdapter(Protocol):
    def fetch(self, region: str) -> list[RawMessage]: ...
    def mark_processed(self, msg: RawMessage) -> None: ...
    def send(self, region: str, to: str, subject: str, body: str, in_reply_to: str | None = None) -> str: ...


class FolderMailbox:
    """Mock: reads <dir>/<region>/inbox/*.eml, moves to processed/, writes sent mail to the outbox."""

    def __init__(self, root: str | None = None, outbox: str | None = None) -> None:
        s = get_settings()
        self.root = Path(root or s.mailbox_dir)
        self.outbox = Path(outbox or s.outbox_dir)

    def fetch(self, region: str) -> list[RawMessage]:
        inbox = self.root / region / "inbox"
        if not inbox.exists():
            return []
        return [RawMessage(ref=str(p), region=region, mailbox=f"submissions.{region}@northstar.example",
                           raw=p.read_bytes()) for p in sorted(inbox.glob("*.eml"))]

    def mark_processed(self, msg: RawMessage) -> None:
        src = Path(msg.ref)
        dest = self.root / msg.region / "processed"
        dest.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.move(str(src), dest / src.name)

    def send(self, region: str, to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
        self.outbox.mkdir(parents=True, exist_ok=True)
        mid = f"<{uuid.uuid4()}@nsip.northstar.example>"
        (self.outbox / f"{region}-{uuid.uuid4().hex[:12]}.json").write_text(json.dumps(
            {"message_id": mid, "to": to, "subject": subject, "body": body, "in_reply_to": in_reply_to}))
        return mid


class GraphMailbox:  # pragma: no cover - requires tenant
    """Microsoft Graph shared mailbox per region. Polling plus change-notification webhooks."""

    def __init__(self, mailboxes: dict[str, str], token_provider) -> None:
        self.mailboxes, self.token_provider = mailboxes, token_provider

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token_provider()}"}

    def fetch(self, region: str) -> list[RawMessage]:
        box = self.mailboxes[region]
        url = f"https://graph.microsoft.com/v1.0/users/{box}/mailFolders/inbox/messages?$filter=isRead eq false&$top=50"
        r = httpx.get(url, headers=self._h(), timeout=30)
        r.raise_for_status()
        out = []
        for m in r.json().get("value", []):
            raw = httpx.get(f"https://graph.microsoft.com/v1.0/users/{box}/messages/{m['id']}/$value",
                            headers=self._h(), timeout=120)
            raw.raise_for_status()
            out.append(RawMessage(ref=m["id"], region=region, mailbox=box, raw=raw.content))
        return out

    def mark_processed(self, msg: RawMessage) -> None:
        httpx.patch(f"https://graph.microsoft.com/v1.0/users/{msg.mailbox}/messages/{msg.ref}",
                    json={"isRead": True}, headers=self._h(), timeout=30).raise_for_status()

    def subscribe(self, region: str, notification_url: str, client_state: str) -> dict:
        body = {"changeType": "created", "notificationUrl": notification_url,
                "resource": f"users/{self.mailboxes[region]}/mailFolders('inbox')/messages",
                "expirationDateTime": "", "clientState": client_state}
        r = httpx.post("https://graph.microsoft.com/v1.0/subscriptions", json=body, headers=self._h(), timeout=30)
        r.raise_for_status()
        return r.json()

    def send(self, region: str, to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
        msg = {"message": {"subject": subject, "body": {"contentType": "Text", "content": body},
                           "toRecipients": [{"emailAddress": {"address": to}}]}, "saveToSentItems": True}
        httpx.post(f"https://graph.microsoft.com/v1.0/users/{self.mailboxes[region]}/sendMail", json=msg,
                   headers=self._h(), timeout=30).raise_for_status()
        return ""


class ImapMailbox:  # pragma: no cover - requires server
    def __init__(self, host: str, user: str, password: str, smtp_host: str, region_folders: dict[str, str]):
        self.host, self.user, self.password, self.smtp_host = host, user, password, smtp_host
        self.folders = region_folders

    def fetch(self, region: str) -> list[RawMessage]:
        with imaplib.IMAP4_SSL(self.host) as imap:
            imap.login(self.user, self.password)
            imap.select(self.folders[region])
            _, data = imap.search(None, "UNSEEN")
            out = []
            for num in data[0].split():
                _, msg = imap.fetch(num, "(BODY.PEEK[])")
                out.append(RawMessage(ref=num.decode(), region=region, mailbox=self.folders[region],
                                      raw=msg[0][1]))  # type: ignore[index,arg-type]
            return out

    def mark_processed(self, msg: RawMessage) -> None:
        with imaplib.IMAP4_SSL(self.host) as imap:
            imap.login(self.user, self.password)
            imap.select(msg.mailbox)
            imap.store(msg.ref, "+FLAGS", "\\Seen")

    def send(self, region: str, to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = self.user, to, subject
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        m.set_content(body)
        with smtplib.SMTP_SSL(self.smtp_host) as smtp:
            smtp.login(self.user, self.password)
            smtp.send_message(m)
        return m.get("Message-ID", "")


class BrokerPortalAdapter:
    """Secondary channel: reads submissions from the existing 2023 broker portal (read-only)."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or get_settings().mailbox_dir) / "portal"

    def fetch(self, region: str) -> list[RawMessage]:
        folder = self.root / region
        if not folder.exists():
            return []
        return [RawMessage(ref=str(p), region=region, mailbox="broker-portal-2023", raw=p.read_bytes(),
                           channel="portal") for p in sorted(folder.glob("*.eml"))]

    def mark_processed(self, msg: RawMessage) -> None:
        p = Path(msg.ref)
        if p.exists():
            p.rename(p.with_suffix(".done"))
