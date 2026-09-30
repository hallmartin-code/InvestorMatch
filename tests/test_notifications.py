"""Results email via Resend, with a fake transport (no network)."""

from __future__ import annotations

import base64
import copy
import json

from app.config import Settings
from app.pipeline import deliver_results, output_names
from app.services.notifications import RESEND_EMAILS_URL, send_results_email

KEY = "re_test_key_do_not_use"


def settings(**kw) -> Settings:
    base = dict(resend_api_key=KEY, im_notify_enabled=True, im_notify_to="Info@tencapital.group",
                railway_public_domain="example.up.railway.app")
    base.update(kw)
    return Settings(**base)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses) or [(200, b'{"id": "msg_123"}')]
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, json.loads(body)))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def files(result):
    pdf, xlsx = output_names(result.context.company_name, result.report_date)
    return {pdf: b"%PDF-fake", xlsx: b"PK-fake"}


def test_email_is_sent_to_info_with_both_attachments(sample_result):
    result = copy.copy(sample_result)
    result.notifications = []
    transport = FakeTransport()
    out = send_results_email(result, files(result), settings=settings(), transport=transport)
    assert out.sent and out.message_id == "msg_123" and out.to == ["Info@tencapital.group"]
    method, url, headers, payload = transport.calls[0]
    assert (method, url) == ("POST", RESEND_EMAILS_URL)
    assert headers["Authorization"] == f"Bearer {KEY}" and headers["Idempotency-Key"].startswith("investor-match/")
    assert payload["to"] == ["Info@tencapital.group"]
    assert payload["from"].endswith("<reports@tencapital.group>")
    assert "Investor Contact Shortlist — Cardiolyte Health" in payload["subject"]
    assert [a["filename"] for a in payload["attachments"]] == list(files(result))
    assert base64.b64decode(payload["attachments"][0]["content"]) == b"%PDF-fake"
    for title in ("Deal profile", "Qualified contacts", "Material gaps and screening limitations"):
        assert title in payload["html"]
    assert "Avery Holt" in payload["html"] and "https://example.up.railway.app" in payload["text"]
    assert KEY not in payload["html"] + payload["text"]


def test_failures_never_raise_and_client_errors_are_not_retried(sample_result):
    result = copy.copy(sample_result)
    result.notifications = []
    rejected = FakeTransport((401, b'{"message": "bad key"}'))
    out = send_results_email(result, files(result), settings=settings(), transport=rejected, sleep=lambda s: None)
    assert not out.sent and "401" in out.error and len(rejected.calls) == 1
    flaky = FakeTransport((500, b"oops"), (200, b'{"id": "ok"}'))
    out = send_results_email(result, files(result), settings=settings(), transport=flaky, sleep=lambda s: None)
    assert out.sent and len(flaky.calls) == 2

    def boom(*a):
        raise OSError("network down")

    out = send_results_email(result, files(result), settings=settings(), transport=boom, sleep=lambda s: None)
    assert not out.sent and "could not reach Resend" in out.error


def test_skipped_without_key_or_when_disabled(sample_result):
    result = copy.copy(sample_result)
    result.notifications = []
    assert "no RESEND_API_KEY" in send_results_email(result, {}, settings=settings(resend_api_key=None)).skipped_reason
    assert "disabled" in send_results_email(result, {}, settings=settings(im_notify_enabled=False)).skipped_reason


def test_same_generation_is_emailed_once(sample_result, monkeypatch):
    result = copy.copy(sample_result)
    result.notifications = []
    transport = FakeTransport()
    import app.services.notifications as n

    monkeypatch.setattr(n, "urllib_transport", transport)
    first = deliver_results(result, files(result), settings())
    second = deliver_results(result, files(result), settings())
    assert first.sent and second is first and len(transport.calls) == 1
