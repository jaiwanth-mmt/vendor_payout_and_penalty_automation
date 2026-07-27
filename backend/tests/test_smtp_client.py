from __future__ import annotations

import pytest

from backend.app.integrations.smtp import (
    InMemoryMailTransport,
    OutboundMail,
    SmtpError,
    mailer_recipients_from_env,
    normalize_email,
    parse_recipient_list,
    smtp_config_from_env,
)


def test_parse_recipient_list_dedupes_and_trims() -> None:
    recipients = parse_recipient_list(" a@go-mmt.com, B@go-mmt.com; a@go-mmt.com ")
    assert recipients == ["a@go-mmt.com", "B@go-mmt.com"]


def test_normalize_email_rejects_invalid() -> None:
    assert normalize_email("not-an-email") == ""
    assert normalize_email("ok@go-mmt.com") == "ok@go-mmt.com"


def test_smtp_config_from_env_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    with pytest.raises(SmtpError, match="SMTP_PASSWORD"):
        smtp_config_from_env()


def test_smtp_config_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "noreply@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.setenv("SMTP_TLS_VERIFY", "false")
    config = smtp_config_from_env()
    assert config.host == "smtp.example.com"
    assert config.user == "noreply@example.com"
    assert config.password == "secret"
    assert config.starttls is True
    assert config.tls_verify is False


def test_build_ssl_context_respects_tls_verify() -> None:
    from backend.app.integrations.smtp import build_ssl_context

    verified = build_ssl_context(tls_verify=True)
    unverified = build_ssl_context(tls_verify=False)
    assert verified.check_hostname is True
    assert unverified.check_hostname is False


def test_mailer_recipients_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAILER_RECIPIENTS", raising=False)
    defaults = mailer_recipients_from_env()
    assert "Deepak.Kumar2@go-mmt.com" in defaults
    assert len(defaults) == 3

    monkeypatch.setenv("MAILER_RECIPIENTS", "one@go-mmt.com,two@go-mmt.com")
    assert mailer_recipients_from_env() == ["one@go-mmt.com", "two@go-mmt.com"]


def test_in_memory_transport_captures_mail() -> None:
    transport = InMemoryMailTransport()
    result = transport.send(
        OutboundMail(
            to="ops@go-mmt.com",
            subject="Penalty complaint details - B1",
            text_body="hi",
            html_body="<p>hi</p>",
        )
    )
    assert result.to == "ops@go-mmt.com"
    assert len(transport.sent) == 1
