"""Parse security-team removal emails into a structured, validated request.

Supported shapes, tried in order and merged:
1. Structured body lines ("Software: ...", "Version: ...", "Reason: ...").
2. Subject line fallback: "[UNAUTHORIZED-SOFTWARE] <name> <version> ...".
3. CSV / JSON attachments (device_id, software_name, software_version columns/keys).
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from email.utils import parseaddr

TAGS = {"UNAUTHORIZED-SOFTWARE": "unauthorized", "EOL-SOFTWARE": "end_of_life", "SECURITY-PATCH": "vulnerable"}
TAG_RE = re.compile(r"\[(UNAUTHORIZED-SOFTWARE|EOL-SOFTWARE|SECURITY-PATCH)\]", re.I)
DEVICE_RE = re.compile(r"\bDEV-\d{3,6}\b", re.I)
VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,3}\b")
FLEET_RE = re.compile(r"affected devices\s*:\s*(all|entire fleet|fleet[- ]wide|all devices)", re.I)
URGENCY = (  # checked in priority order, whole words only
    ("critical", ("CRITICAL", "IMMEDIATE", "URGENT", "24 HOURS")),
    ("high", ("HIGH", "ASAP", "1 WEEK")),
    ("medium", ("MEDIUM", "2 WEEKS")),
    ("low", ("LOW", "30 DAYS")),
)


@dataclass
class RemovalRequest:
    message_id: str
    sender: str
    subject: str
    request_type: str | None = None
    software_name: str | None = None
    software_version: str | None = None
    device_ids: list[str] = field(default_factory=list)
    scope: str = "listed_devices"  # listed_devices | fleet
    removal_reason: str | None = None
    replacement: str | None = None
    urgency: str = "medium"
    sender_authorized: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {**asdict(self), "valid": self.valid}


def sender_address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def is_authorized(sender: str, allowed: list[str]) -> bool:
    """Exact address match; 'security-team@company.com.evil.io' is not 'security-team@company.com'."""
    addr = sender_address(sender)
    return bool(addr) and addr in {a.strip().lower() for a in allowed}


def _field(body: str, *names: str) -> str | None:
    for n in names:
        m = re.search(rf"^\s*{n}\s*:\s*(.+?)\s*$", body, re.I | re.M)
        if m:
            return m.group(1)
    return None


def _urgency(explicit: str | None, subject: str, body: str) -> str:
    for text in (explicit or "", f"{subject}\n{body}"):
        up = text.upper()
        for level, words in URGENCY:
            if any(re.search(rf"\b{re.escape(w)}\b", up) for w in words):
                return level
    return "medium"


def _from_subject(subject: str) -> tuple[str | None, str | None]:
    rest = TAG_RE.sub("", subject).strip()
    m = VERSION_RE.search(rest)
    if not m:
        return (rest or None), None
    name = rest[:m.start()].strip(" -:")
    return (name or None), m.group()


def _attachments(req: RemovalRequest, attachments: list[dict]) -> None:
    for a in attachments or []:
        name, content = (a.get("filename") or "").lower(), a.get("content") or ""
        try:
            if name.endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(content)))
                req.device_ids += [r["device_id"].strip() for r in rows if (r.get("device_id") or "").strip()]
                first = rows[0] if rows else {}
                req.software_name = req.software_name or (first.get("software_name") or None)
                req.software_version = req.software_version or (first.get("software_version") or None)
            elif name.endswith(".json"):
                data = json.loads(content)
                req.device_ids += [str(d) for d in data.get("device_ids", [])]
                req.software_name = req.software_name or data.get("software_name")
                req.software_version = req.software_version or data.get("software_version")
        except (ValueError, KeyError, AttributeError) as e:
            req.errors.append(f"could not read attachment {a.get('filename')}: {e}")


def parse_email(message_id: str, sender: str, subject: str, body: str, attachments: list[dict] | None,
                allowed_senders: list[str]) -> RemovalRequest:
    req = RemovalRequest(message_id=message_id, sender=sender, subject=subject)
    req.sender_authorized = is_authorized(sender, allowed_senders)
    if not req.sender_authorized:
        req.errors.append(f"sender {sender_address(sender) or sender!r} is not on the authorized sender list")
    tag = TAG_RE.search(subject or "")
    req.request_type = TAGS[tag.group(1).upper()] if tag else None
    if not tag:
        req.errors.append("subject has no [UNAUTHORIZED-SOFTWARE], [EOL-SOFTWARE] or [SECURITY-PATCH] tag")

    req.software_name = _field(body, "Software", "Application", "Product")
    version_line = _field(body, "Version")
    if version_line:
        m = VERSION_RE.search(version_line)
        req.software_version = m.group() if m else version_line
    subj_name, subj_version = _from_subject(subject or "")
    req.software_name = req.software_name or subj_name
    req.software_version = req.software_version or subj_version
    req.removal_reason = _field(body, "Reason", "Removal Reason")
    req.replacement = _field(body, "Replace with", "Replacement")
    req.urgency = _urgency(_field(body, "Urgency", "Risk Level"), subject or "", body or "")
    req.device_ids = [d.upper() for d in DEVICE_RE.findall(body or "")]
    _attachments(req, attachments or [])
    req.device_ids = list(dict.fromkeys(d.upper() for d in req.device_ids))  # dedupe, keep order
    if FLEET_RE.search(body or "") and not req.device_ids:
        req.scope = "fleet"

    if not req.software_name:
        req.errors.append("missing software name (expected a 'Software:' line)")
    if not req.software_version or not VERSION_RE.fullmatch(req.software_version):
        req.errors.append("missing or invalid version (expected e.g. 'Version: 6.0.36'); "
                          "removal is version-specific, so a version is required")
    if not req.device_ids and req.scope != "fleet":
        req.errors.append("no target devices (list DEV-xxxxx IDs or write 'Affected Devices: all')")
    return req
