"""Investor list → validated, deduplicated contacts, with an exclusion/merge log.

* Only syntactically valid emails are kept (syntax ≠ deliverability).
* Duplicates are merged by case-insensitive email; conflicting values are noted, list-like fields
  are unioned, and suppression on any duplicate suppresses the merged contact.
* Generic inboxes (info@, invest@ …) are kept but flagged.
"""

from __future__ import annotations

import re
from typing import Any

from app.ingestion.mapping import INVESTOR_FIELDS, apply_mapping
from app.ingestion.tables import ImportedTable
from app.models import Contact, ContactRecord, LogEntry, LogStatus, SourceRef
from app.utils.text import (
    email_local_part,
    fold,
    is_truthy,
    is_valid_email,
    normalize_email,
    normalize_org,
    normalize_person,
    split_name,
)

LIST_KEYS = {"sector_focus", "thesis", "geo_focus", "ten_events", "ten_similar_intros", "notes", "stage_focus",
             "alt_emails"}


def alternative_emails(values: dict[str, str]) -> list[str]:
    """Valid addresses from the 'Alternative emails' field (normalized)."""
    return [normalize_email(p) for p in re.split(r"[;,\s]+", values.get("alt_emails", "") or "")
            if is_valid_email(normalize_email(p))]


def suppression_emails(table: ImportedTable, mapping: dict[str, str | None]) -> dict[str, SourceRef]:
    """Emails on an unsubscribe / suppression sheet → the row that lists them."""
    from app.ingestion.mapping import email_column_by_content

    column = mapping.get("email") or email_column_by_content(table)
    out: dict[str, SourceRef] = {}
    if not column:
        return out
    for row, number in zip(table.rows, table.row_numbers, strict=True):
        for part in re.split(r"[;,\s]+", row.get(column, "") or ""):
            email = normalize_email(part)
            if is_valid_email(email):
                out.setdefault(email, SourceRef(table.filename, f"row {number}", table.sheet))
    return out


LABELS = {f.key: f.label for f in INVESTOR_FIELDS}
_SUPPRESSION_HEADER = re.compile(r"unsub|suppress|opt.?out|\bdnc\b|do.?not|blacklist|block.?list|bounce", re.I)
# Values that mean "do not email" in any status-like column (e.g. Latest Status = "UNSUB").
_SUPPRESSION_STATUS = re.compile(r"^\s*(?:unsub\w*|opted.?out|opt.?out|do not (?:contact|email)|dnc|bounced?|"
                                 r"suppressed|hard bounce)\b", re.I)


def _extra_suppression_columns(table: ImportedTable, mapped: str | None) -> tuple[list[str], list[str]]:
    """(flag columns, status columns) beyond the mapped suppression column."""
    flags = [c for c in table.columns if c != mapped and _SUPPRESSION_HEADER.search(c)]
    statuses = [c for c in table.columns if c != mapped and c not in flags and re.search(r"status", c, re.I)]
    return flags, statuses


def _extra_suppression(row: dict[str, str], flags: list[str], statuses: list[str]) -> str | None:
    for col in flags:
        value = (row.get(col) or "").strip()
        if value and (is_truthy(value) or _SUPPRESSION_STATUS.match(value)):
            return f"{col}: {value}"
    for col in statuses:
        value = (row.get(col) or "").strip()
        if value and (_SUPPRESSION_STATUS.match(value) or re.search(r"unsubscribed|do not contact", value, re.I)):
            return f"{col}: {value}"
    return None


def build_records(table: ImportedTable, mapping: dict[str, str | None], cfg: dict[str, Any]) -> list[ContactRecord]:
    terms = [t.lower() for t in cfg["screening"]["suppression_terms"]]
    header = mapping.get("suppression") or ""
    flag_cols, status_cols = _extra_suppression_columns(table, mapping.get("suppression"))
    raw_rows = dict(zip(table.row_numbers, table.rows, strict=True))
    records = []
    for values, row in apply_mapping(table, mapping):
        if not values.get("first_name") and not values.get("last_name") and values.get("full_name"):
            values["first_name"], values["last_name"] = split_name(values["full_name"])
        status = fold(values.get("suppression", ""))
        reason = None
        if status:
            term = next((t for t in terms if t in status), None)
            if term and not re.search(r"\bnot\s+" + re.escape(term), status):
                reason = f"{mapping['suppression']}: {values['suppression']}"
            elif is_truthy(status) and _SUPPRESSION_HEADER.search(header):
                reason = f"{header}: {values['suppression']}"
        if reason is None and (flag_cols or status_cols):
            reason = _extra_suppression(raw_rows[row], flag_cols, status_cols)
        values["_suppressed"] = reason or ""
        values["_participation_header"] = mapping.get("participation") or ""
        records.append(ContactRecord(values=values, source=SourceRef(table.filename, f"row {row}", table.sheet)))
    return records


def _log(status: LogStatus, code: str, reason: str, rec: ContactRecord | Contact, detail: str = "") -> LogEntry:
    if isinstance(rec, Contact):
        return LogEntry(status, code, reason, rec.first_name, rec.last_name, rec.organization, rec.email_display,
                        rec.get("investor_type"), list(rec.sources), detail)
    return LogEntry(status, code, reason, rec.get("first_name"), rec.get("last_name"), rec.get("organization"),
                    rec.get("email"), rec.get("investor_type"), [rec.source], detail)


def _pick_email(raw: str) -> tuple[str, str]:
    """First syntactically valid address in a cell (cells sometimes hold several)."""
    parts = [p for p in re.split(r"[;,\s]+", raw) if p]
    for part in parts:
        if is_valid_email(normalize_email(part)):
            return normalize_email(part), part.strip("<>")
    return "", raw


def consolidate(records: list[ContactRecord], cfg: dict[str, Any],
                suppression_list: dict[str, SourceRef] | None = None) -> tuple[list[Contact], list[LogEntry]]:
    generic = {p.lower() for p in cfg["screening"]["generic_inbox_prefixes"]}
    log: list[LogEntry] = []
    groups: dict[str, list[tuple[ContactRecord, str]]] = {}
    for rec in records:
        raw = rec.get("email")
        if not raw:
            log.append(_log(LogStatus.EXCLUDED, "NO_EMAIL", "No email address", rec))
            continue
        email, display = _pick_email(raw)
        if not email:
            log.append(_log(LogStatus.EXCLUDED, "INVALID_EMAIL", "Email is not syntactically valid", rec,
                            f"value: {raw}"))
            continue
        if len([p for p in re.split(r"[;,\s]+", raw) if p]) > 1:
            log.append(_log(LogStatus.FLAG, "MULTIPLE_EMAILS", "Cell held several addresses; used the first valid one",
                            rec, f"value: {raw}"))
        groups.setdefault(email, []).append((rec, display))

    contacts: list[Contact] = []
    for email, members in groups.items():
        recs = [r for r, _d in members]
        merged: dict[str, str] = {}
        notes: list[str] = []
        filled: list[str] = []
        keys = [k for k in recs[0].values if not k.startswith("_")]
        for key in keys:
            values = list(dict.fromkeys(r.get(key) for r in recs if r.get(key)))
            if not values:
                merged[key] = ""
            elif key in LIST_KEYS:
                merged[key] = "; ".join(values)
            else:
                merged[key] = values[0]
                if not recs[0].get(key):
                    filled.append(LABELS.get(key, key))
                if len(values) > 1 and key not in {"email", "full_name", "suppression"}:
                    notes.append(f"Conflicting {LABELS.get(key, key)}: " + " | ".join(values) + " (kept first)")
                    if key == "investor_type":
                        merged["_type_conflict"] = " | ".join(values)
        merged["_participation_header"] = recs[0].values.get("_participation_header", "")
        suppressed = [r.values["_suppressed"] for r in recs if r.values.get("_suppressed")]
        if suppression_list:
            listed = next((suppression_list[e] for e in [email, *alternative_emails(merged)] if e in suppression_list),
                          None)
            if listed is not None:
                suppressed.append(f"listed on unsubscribe list {listed.label}")
        contact = Contact(
            email=email, email_display=members[0][1], first_name=merged.get("first_name", ""),
            last_name=merged.get("last_name", ""), organization=merged.get("organization", ""), values=merged,
            sources=[r.source for r in recs], merged_count=len(recs), consolidation_notes=notes,
            suppressed_reason=suppressed[0] if suppressed else None,
            generic_inbox=email_local_part(email) in generic,
        )
        if len(recs) > 1:
            filled_note = [f"filled from duplicates: {', '.join(filled)}"] if filled else []
            detail = "; ".join(notes + filled_note) or "identical values"
            if suppressed and len(suppressed) < len(recs):
                detail += "; suppression on one record applied to all duplicates"
            log.append(_log(LogStatus.MERGED, "DUPLICATE_MERGED", f"Consolidated {len(recs)} records with the same email",
                            contact, detail))
        contacts.append(contact)

    by_person: dict[tuple[str, str], list[Contact]] = {}
    for c in contacts:
        name = normalize_person(c.full_name)
        if name:
            by_person.setdefault((name, normalize_org(c.organization)), []).append(c)
    for (_name, _org), group in by_person.items():
        if len(group) > 1:
            emails = ", ".join(c.email_display for c in group)
            for c in group:
                log.append(_log(LogStatus.FLAG, "POSSIBLE_DUPLICATE_PERSON",
                                "Same name and organization under different emails — check before outreach", c,
                                f"emails: {emails}"))
    return contacts, log


def contact_log(status: LogStatus, code: str, reason: str, contact: Contact, detail: str = "") -> LogEntry:
    return _log(status, code, reason, contact, detail)
