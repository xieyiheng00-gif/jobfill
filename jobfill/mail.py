"""Optional mail connector: find a job portal's verification email (code or link) over IMAP.

Used only inside ``jobfill login``, which the candidate runs. Configure it in ``data/secret.env``
(JOBFILL_IMAP_HOST / USER / PASSWORD; for Gmail an app password). Mail is read-only (the inbox is
opened read-only), only recent messages that look like a verification from this portal are looked at,
and a link is followed only when it points at the portal's own domain.
"""

from __future__ import annotations

import email
import email.header
import imaplib
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

VERIFY = re.compile(r"verif|confirm|activat|validat|one[- ]?time|passcode|security code|sign[- ]?in code|"
                    r"\bcode\b|welcome", re.I)
LINK_HINT = re.compile(r"verif|confirm|activat|validat|token|magic|signin|sign-in|login|account", re.I)
CODE_NEAR = re.compile(r"(?:code|passcode|pin|otp)\b\D{0,40}?(?<!\d)(\d{4,8})(?!\d)", re.I)
CODE_ALONE = re.compile(r"(?<![\d/.-])(\d{6})(?![\d/.-])")
URL = re.compile(r"https?://[^\s\"'<>()]+")


def registrable(host: str) -> str:
    """'nvidia.wd5.myworkdayjobs.com' -> 'myworkdayjobs.com' (good enough for portal domains)."""
    parts = host.lower().split(":")[0].split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "ac", "org", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _text_and_links(msg: Message) -> tuple[str, list[str]]:
    texts, links = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            links += [unescape(h) for h in re.findall(r'href=["\']([^"\']+)["\']', body, re.I)]
            body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body)
            body = unescape(re.sub(r"<[^>]+>", " ", body))
        links += [u.rstrip(".,;") for u in URL.findall(body)]
        texts.append(body)
    return " ".join(" ".join(texts).split()), list(dict.fromkeys(links))


def extract(msg: Message, hosts: list[str], company: str) -> dict | None:
    """Code and/or link from a message, if it looks like this portal's verification email."""
    allowed = {registrable(h) for h in hosts if h}
    sender = parseaddr(msg.get("From", ""))[1].lower()
    subject = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
    text, links = _text_and_links(msg)
    portal_links = [u for u in links if registrable(urlparse(u).netloc) in allowed]
    related = (registrable(sender.split("@")[-1]) in allowed or bool(portal_links)
               or (company and company.lower() in f"{sender} {subject} {text[:2000]}".lower()))
    if not related or not VERIFY.search(f"{subject} {text[:3000]}"):
        return None
    clean = URL.sub(" ", text)   # digits inside links are not codes
    code = CODE_NEAR.search(clean) or CODE_ALONE.search(clean)
    link = next((u for u in portal_links if LINK_HINT.search(urlparse(u).path + "?" + urlparse(u).query)), None)
    if not code and not link:
        return None
    return {"code": code.group(1) if code else None, "link": link, "subject": subject, "from": sender}


class ImapMail:
    def __init__(self, host: str, user: str, password: str, port: int = 993, folder: str = "INBOX"):
        self.host, self.user, self.password, self.port, self.folder = host, user, password, port, folder

    @classmethod
    def from_env(cls, env: dict) -> "ImapMail | None":
        if not all(env.get(k) for k in ("JOBFILL_IMAP_HOST", "JOBFILL_IMAP_USER", "JOBFILL_IMAP_PASSWORD")):
            return None
        return cls(env["JOBFILL_IMAP_HOST"], env["JOBFILL_IMAP_USER"], env["JOBFILL_IMAP_PASSWORD"],
                   int(env.get("JOBFILL_IMAP_PORT", "993")), env.get("JOBFILL_IMAP_FOLDER", "INBOX"))

    def _recent(self, since: datetime, limit: int = 30) -> list[Message]:
        with imaplib.IMAP4_SSL(self.host, self.port) as box:
            box.login(self.user, self.password)
            box.select(self.folder, readonly=True)
            _, data = box.search(None, f'(SINCE "{(since - timedelta(days=1)):%d-%b-%Y}")')
            out = []
            for num in reversed(data[0].split()[-limit:]):
                _, parts = box.fetch(num, "(BODY.PEEK[])")   # PEEK: leave messages unread
                msg = email.message_from_bytes(parts[0][1])
                try:
                    when = parsedate_to_datetime(msg.get("Date"))
                except (TypeError, ValueError):
                    continue
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when >= since - timedelta(minutes=2):
                    out.append(msg)
            return out

    def test(self) -> dict:
        n = len(self._recent(datetime.now(timezone.utc) - timedelta(days=1)))
        return {"connected": True, "account": self.user, "messages_last_day": n}

    def wait_for_verification(self, since: datetime, hosts: list[str], company: str, timeout: int = 180,
                              poll: int = 10) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            for msg in self._recent(since):
                found = extract(msg, hosts, company)
                if found:
                    return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll)
