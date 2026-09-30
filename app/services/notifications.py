"""Automated results email via Resend.

After each generation (each matching run, and each re-run after review decisions or profile
overrides) a summary built from the document template's sections — deal profile, qualified counts,
top contacts per category, gaps and limitations — is emailed with the one-page PDF and the Excel
workbook attached. Recipients come only from configuration (default Info@tencapital.group), never
from the UI or uploaded files; no investor or founder is ever emailed.

* On when RESEND_API_KEY is set (IM_NOTIFY_ENABLED=false turns it off).
* Sending never raises and never fails an analysis; the outcome is recorded on the run.
* The API key travels only in the Authorization header and is never logged.
* A retried request cannot deliver a second copy (Resend idempotency key per generated state).

Uses Resend's REST API through the standard library, so tests can swap the transport.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import Any

from app.config import Settings
from app.extraction.deal_profile import profile_bullets
from app.models import CATEGORY_ORDER, RunResult
from app.reports.frames import summary_counts
from app.reports.template import load_template
from app.utils.logging import get_logger

LOGGER = get_logger(__name__)

PROVIDER = "Resend"
RESEND_EMAILS_URL = "https://api.resend.com/emails"
#: Resend sits behind Cloudflare, which rejects the default Python-urllib user agent.
USER_AGENT = "ten-capital-investor-match/1.0"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_RETRIES = 2

#: (method, url, headers, body, timeout) -> (status, response body)
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


@dataclass
class NotificationOutcome:
    provider: str
    to: list[str]
    sender: str
    generation: str
    attempted: bool = False
    sent: bool = False
    subject: str = ""
    attachments: list[str] = field(default_factory=list)
    message_id: str | None = None
    error: str | None = None
    skipped_reason: str | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    @property
    def status_text(self) -> str:
        if self.sent:
            return f"Results emailed to {', '.join(self.to)}"
        if self.skipped_reason:
            return f"Results email not sent: {self.skipped_reason}"
        return f"Results email failed: {self.error}"


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None,
                     timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def generation_key(result: RunResult) -> str:
    """Identifies one generated state: inputs, overrides, review decisions and report date."""
    parts = [result.deal.deck_file, result.report_date.isoformat()]
    parts += [f"{f['File']}:{f['Sheet']}:{f['SHA-256']}:{f['Company-specific']}" for f in result.input_files]
    parts += [f"{k}={o.display}@{o.entered_at}" for k, o in sorted(result.deal.overrides.items())]
    parts += [f"{e.code}:{e.email}" for e in result.log if e.code == "INTRO_REVIEW_CLEARED"]
    parts += [f"{r['Email']}:{r['Match Basis']}" for r in result.already_introduced]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


# ------------------------------------------------------------------------------ render

_NAVY = "#1F3864"
_GREY = "#4A5360"
_CELL = "padding:5px 7px;border-bottom:1px solid #D9DDE3;vertical-align:top;font-size:13px;"
_HEAD = f"padding:5px 7px;background:{_NAVY};color:#FFFFFF;text-align:left;font-size:12px;"


def _h(title: str) -> str:
    return (f'<h3 style="color:{_NAVY};font-size:15px;margin:22px 0 6px;border-bottom:1px solid {_NAVY};'
            f'padding-bottom:3px">{escape(title)}</h3>')


def render_email(result: RunResult, *, subject_prefix: str, workbook_name: str,
                 app_url: str | None = None) -> tuple[str, str, str]:
    """(subject, html, text), following the document template's sections and labels."""
    t = load_template()
    sec = {s.id: s for s in t.sections}
    top_x = sec["top_contacts"].model_extra or {}
    deal = result.deal
    company = result.context.company_name or t.header["company_empty_text"]
    counts = summary_counts(result)
    raise_line = " · ".join(v for v in (deal.effective_display("raise_amount"), deal.effective_display("stage"),
                                        deal.effective_display("instrument")) if v != "not stated in deck") \
        or "not stated in deck"
    date_text = f"{result.report_date:%B} {result.report_date.day}, {result.report_date.year}"
    claude = next((line for line in deal.extraction_log if line.startswith("Claude analysis")),
                  "Rule-based extraction only (Claude not used)")
    subject = (f"{subject_prefix} {t.document_title} — {company} · {counts['qualified_total']} qualified · "
               f"{counts['already_introduced']} already introduced · {counts['review']} for review")
    bullets = profile_bullets(deal, result.context)

    html = ['<div style="font-family:Arial,Helvetica,sans-serif;color:#1F2328;max-width:860px">',
            f'<p style="color:{_GREY};font-size:11px;letter-spacing:.08em;margin:0">{escape(t.header["eyebrow"])}</p>',
            f'<h2 style="color:{_NAVY};margin:2px 0 4px;font-size:20px">'
            f'{escape(t.header["title_pattern"].format(company_name=company, document_title=t.document_title))}</h2>',
            f'<p style="color:{_GREY};margin:0 0 4px"><b>Raise:</b> {escape(raise_line)} &nbsp; <b>Report date:</b> '
            f'{escape(date_text)} &nbsp; <b>Deck date:</b> {escape(deal.effective_display("deck_date"))}</p>',
            f'<p style="color:{_GREY};font-size:12px;margin:0">Deck: {escape(deal.deck_file)} · {escape(claude)}</p>',
            _h(sec["deal_profile"].title), "<ul>" + "".join(f"<li>{escape(b)}</li>" for b in bullets) + "</ul>",
            _h(sec["qualified_contacts"].title), '<table style="border-collapse:collapse"><tr>']
    tiles = list(counts["qualified"].items()) + [("Total qualified", counts["qualified_total"]),
                                                   ("Already introduced", counts["already_introduced"]),
                                                   ("Held for review", counts["review"])]
    html += [f'<td style="{_CELL}text-align:center"><b style="font-size:18px">{n}</b><br>'
             f'<span style="color:{_GREY};font-size:11px">{escape(label)}</span></td>' for label, n in tiles]
    html += ["</tr></table>", _h(sec["top_contacts"].title)]
    text = [f"{t.document_title} — {company}", f"Raise: {raise_line} · Report date: {date_text} · "
            f"Deck date: {deal.effective_display('deck_date')}", f"Deck: {deal.deck_file} · {claude}", "",
            sec["deal_profile"].title.upper()] + [f"  - {b}" for b in bullets]
    text += ["", sec["qualified_contacts"].title.upper()] + [f"  {label}: {n}" for label, n in tiles]
    text += ["", sec["top_contacts"].title.upper()]
    for cat in CATEGORY_ORDER:
        members = [s for s in result.ranked if s.category == cat]
        header = top_x["group_header_pattern"].format(category=cat.value, count=len(members))
        html.append(f'<p style="margin:10px 0 4px"><b>{escape(header)}</b></p>')
        text.append(f"  {header}")
        if not members:
            html.append(f'<p style="color:{_GREY};font-size:13px;margin:0">{escape(top_x["empty_group_text"])}</p>')
            text.append(f"    {top_x['empty_group_text']}")
            continue
        html.append('<table style="border-collapse:collapse;width:100%"><tr>' + "".join(
            f'<th style="{_HEAD}">{escape(c.label)}</th>' for c in sec["top_contacts"].columns) + "</tr>")
        for s in members[: top_x["max_rows_per_group"]]:
            c = s.contact
            name = c.full_name or "(generic inbox — no named contact)"
            html.append(f'<tr><td style="{_CELL}">{s.rank}</td><td style="{_CELL}"><b>{escape(name)}</b></td>'
                        f'<td style="{_CELL}">{escape(c.organization or "—")}</td>'
                        f'<td style="{_CELL}"><b>{s.fit_score:.1f}</b></td><td style="{_CELL}">{escape(s.why)}</td></tr>')
            text.append(f"    {s.rank}. {name} — {c.organization or '—'} · {s.fit_score:.1f} · {s.why}")
        html.append("</table>")
    gaps = sec["gaps_and_limitations"]
    html += [_h(gaps.title), "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in result.limitations) + "</ul>"]
    text += ["", gaps.title.upper()] + [f"  - {x}" for x in result.limitations]
    link = f' Open the app: <a href="{escape(app_url)}">{escape(app_url)}</a>.' if app_url else ""
    html.append(f'<p style="color:{_GREY};font-size:12px;margin-top:22px">Attached: the one-page PDF and '
                f'{escape(workbook_name)} (Ranked Investors with contact details, Already Introduced, Deal Profile, '
                f'Exclusions and Review, Scoring Evidence).{link} No investor or founder has been contacted.</p>'
                f'<p style="color:{_GREY};font-size:12px">Compiled on {escape(date_text)} by TEN Capital Network · '
                f'{escape(t.footer["confidential_text"])}</p></div>')
    text += ["", f"Attached: one-page PDF and {workbook_name}." + (f" App: {app_url}" if app_url else ""),
             "No investor or founder has been contacted.", t.footer["confidential_text"]]
    return subject, "".join(html), "\n".join(text)


# ------------------------------------------------------------------------------ send


def _json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _error_text(status: int, raw: bytes) -> str:
    detail = str(_json(raw).get("message") or raw[:200].decode("utf-8", "replace")).strip()
    if status == 401:
        return "Resend rejected the API key (401). Check RESEND_API_KEY."
    if status == 403:
        return f"Resend refused the request (403): {detail}. The sender domain must be verified in Resend."
    if status == 422:
        return f"Resend rejected the message (422): {detail}."
    if status == 429:
        return "Resend rate limit reached (429)."
    return f"Resend returned {status}: {detail[:200]}"


def send_results_email(result: RunResult, files: dict[str, bytes], *, settings: Settings,
                       transport: Transport | None = None,
                       sleep: Callable[[float], None] = time.sleep) -> NotificationOutcome:
    """Email the results with the given attachments ({filename: bytes}). Never raises."""
    recipients = settings.notify_recipients()
    base = NotificationOutcome(PROVIDER, recipients, settings.im_notify_from, generation_key(result))
    key = settings.resend_api_key.get_secret_value().strip() if settings.resend_api_key else ""
    if not settings.im_notify_enabled:
        base.skipped_reason = "email notifications are disabled (IM_NOTIFY_ENABLED=false)"
    elif not key:
        base.skipped_reason = "no RESEND_API_KEY configured"
    elif not recipients:
        base.skipped_reason = "no recipients configured (IM_NOTIFY_TO)"
    else:
        _send(result, files, settings, key, base, transport or urllib_transport, sleep)
    result.notifications.append(base)
    return base


def _send(result: RunResult, files: dict[str, bytes], settings: Settings, key: str, out: NotificationOutcome,
          send: Transport, sleep: Callable[[float], None]) -> None:
    workbook = next((n for n in files if n.endswith(".xlsx")), "the Excel workbook")
    try:
        subject, html_body, text_body = render_email(result, subject_prefix=settings.im_notify_subject_prefix,
                                                     workbook_name=workbook, app_url=settings.public_url)
    except Exception as exc:  # noqa: BLE001 - a rendering bug must not fail the analysis
        LOGGER.exception("Results email could not be rendered")
        out.error = f"email could not be rendered ({exc.__class__.__name__})"
        return
    attachments, total, omitted = [], 0, []
    for name, data in files.items():
        if total + len(data) > MAX_ATTACHMENT_BYTES:
            omitted.append(name)
            continue
        attachments.append((name, data))
        total += len(data)
    if omitted:
        text_body += f"\n\nNot attached (size limit): {', '.join(omitted)}. Download them from the app."
        html_body += f'<p style="color:#8C1D18;font-size:12px">Not attached (size limit): {escape(", ".join(omitted))}.</p>'
    payload: dict[str, Any] = {
        "from": settings.im_notify_from, "to": out.to, "subject": subject, "html": html_body, "text": text_body,
        "tags": [{"name": "app", "value": "investor-match"}, {"name": "generation", "value": out.generation}],
        "attachments": [{"filename": n, "content": base64.b64encode(d).decode("ascii")} for n, d in attachments],
    }
    reply_to = [p.strip() for p in settings.im_notify_reply_to.split(",") if p.strip()]
    if reply_to:
        payload["reply_to"] = reply_to
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT,
               "Idempotency-Key": f"investor-match/{out.generation}"}
    body = json.dumps(payload).encode("utf-8")
    out.attempted, out.subject, out.attachments = True, subject, [n for n, _d in attachments]
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        try:
            status, raw = send("POST", RESEND_EMAILS_URL, headers, body, settings.im_notify_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - network failures must not fail an analysis
            last_error = f"could not reach Resend ({exc.__class__.__name__})"
        else:
            if 200 <= status < 300:
                out.sent, out.message_id = True, _json(raw).get("id")
                LOGGER.info("Results email sent to %d recipient(s)", len(out.to))
                return
            last_error = _error_text(status, raw)
            if status != 429 and 400 <= status < 500:
                break  # a client error will not succeed on retry
        if attempt < MAX_RETRIES:
            sleep(1.5 * (attempt + 1))
    out.error = last_error
    LOGGER.warning("Results email not sent: %s", last_error)
