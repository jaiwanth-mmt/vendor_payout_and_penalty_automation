"""SMTP transport for vendor penalty mailer (stdlib only)."""

from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any, Protocol


DEFAULT_SMTP_HOST = "smtpmail.mmt.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_FROM = "noreply-depot@makemytrip.com"
DEFAULT_SMTP_TIMEOUT_SECONDS = 30
DEFAULT_MAILER_RECIPIENTS = [
    "Deepak.Kumar2@go-mmt.com",
    "jaiwanth.t@go-mmt.com",
    "Manoj.Kumar@go-mmt.com",
]


class SmtpError(RuntimeError):
    """Raised when SMTP configuration or delivery fails."""


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().casefold() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    from_address: str
    starttls: bool = True
    tls_verify: bool = True
    timeout_seconds: int = DEFAULT_SMTP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class OutboundMail:
    to: str
    subject: str
    text_body: str
    html_body: str
    from_address: str | None = None


@dataclass(frozen=True)
class SendResult:
    to: str
    message_id: str
    smtp_response: str = ""


class MailTransport(Protocol):
    def send(self, mail: OutboundMail) -> SendResult: ...


def parse_recipient_list(raw: str | None) -> list[str]:
    if raw is None:
        return []
    recipients: list[str] = []
    seen: set[str] = set()
    for part in str(raw).replace(";", ",").split(","):
        address = normalize_email(part)
        if not address:
            continue
        key = address.casefold()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(address)
    return recipients


def normalize_email(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    _name, address = parseaddr(raw)
    address = (address or raw).strip()
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        return ""
    local, _, domain = address.partition("@")
    if not local.strip() or not domain.strip() or " " in address or "\n" in address or "\r" in address:
        return ""
    return address


def validate_email(value: str, *, field_name: str = "email") -> str:
    address = normalize_email(value)
    if not address:
        raise SmtpError(f"Invalid {field_name}: {value!r}")
    return address


def smtp_config_from_env() -> SmtpConfig:
    password = os.getenv("SMTP_PASSWORD", "").strip()
    if not password:
        raise SmtpError("SMTP_PASSWORD is required for vendor mailer. Set it in the environment or .env.")

    user = os.getenv("SMTP_USER", DEFAULT_SMTP_FROM).strip() or DEFAULT_SMTP_FROM
    from_address = os.getenv("SMTP_FROM", user).strip() or user
    validate_email(from_address, field_name="SMTP_FROM")
    validate_email(user, field_name="SMTP_USER")

    starttls = _env_flag("SMTP_STARTTLS", default=True)
    # Corporate smtpmail.mmt.com uses an internal CA; Node nodemailer samples
    # set NODE_TLS_REJECT_UNAUTHORIZED=0. Prefer SMTP_TLS_VERIFY=false only for that host.
    tls_verify = _env_flag("SMTP_TLS_VERIFY", default=True)
    try:
        port = int(os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)) or DEFAULT_SMTP_PORT)
        timeout_seconds = int(
            os.getenv("SMTP_TIMEOUT_SECONDS", str(DEFAULT_SMTP_TIMEOUT_SECONDS)) or DEFAULT_SMTP_TIMEOUT_SECONDS
        )
    except ValueError as error:
        raise SmtpError("SMTP_PORT and SMTP_TIMEOUT_SECONDS must be integers") from error

    return SmtpConfig(
        host=os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST).strip() or DEFAULT_SMTP_HOST,
        port=port,
        user=user,
        password=password,
        from_address=from_address,
        starttls=starttls,
        tls_verify=tls_verify,
        timeout_seconds=max(1, timeout_seconds),
    )


def build_ssl_context(*, tls_verify: bool) -> ssl.SSLContext:
    if tls_verify:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def mailer_recipients_from_env() -> list[str]:
    raw = os.getenv("MAILER_RECIPIENTS")
    if raw is None or not str(raw).strip():
        recipients = list(DEFAULT_MAILER_RECIPIENTS)
    else:
        recipients = parse_recipient_list(raw)
    if not recipients:
        raise SmtpError("MAILER_RECIPIENTS must include at least one valid email address")
    for recipient in recipients:
        validate_email(recipient, field_name="MAILER_RECIPIENTS")
    return recipients


def build_mime_message(mail: OutboundMail, *, from_address: str) -> MIMEMultipart:
    to_address = validate_email(mail.to, field_name="to")
    sender = validate_email(mail.from_address or from_address, field_name="from")
    subject = " ".join(str(mail.subject or "").split())
    if not subject:
        raise SmtpError("Email subject is required")
    if "\n" in subject or "\r" in subject:
        raise SmtpError("Email subject must be a single line")

    message = MIMEMultipart("alternative")
    message["From"] = formataddr(("Cabs Team", sender))
    message["To"] = to_address
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain="makemytrip.com")
    message.attach(MIMEText(mail.text_body or "", "plain", "utf-8"))
    if mail.html_body:
        message.attach(MIMEText(mail.html_body, "html", "utf-8"))
    return message


class SmtpMailTransport:
    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def send(self, mail: OutboundMail) -> SendResult:
        message = build_mime_message(mail, from_address=self.config.from_address)
        to_address = validate_email(mail.to, field_name="to")
        try:
            with smtplib.SMTP(self.config.host, self.config.port, timeout=self.config.timeout_seconds) as client:
                client.ehlo()
                if self.config.starttls:
                    context = build_ssl_context(tls_verify=self.config.tls_verify)
                    client.starttls(context=context)
                    client.ehlo()
                if self.config.user and self.config.password:
                    client.login(self.config.user, self.config.password)
                response = client.sendmail(self.config.from_address, [to_address], message.as_string())
        except ssl.SSLError as error:
            raise SmtpError(
                f"SMTP TLS failed for host {self.config.host}: {error}. "
                "If this is smtpmail.mmt.com, set SMTP_TLS_VERIFY=false (internal CA)."
            ) from error
        except smtplib.SMTPException as error:
            raise SmtpError(f"SMTP delivery failed for {to_address}: {error}") from error
        except OSError as error:
            raise SmtpError(f"SMTP connection failed for host {self.config.host}: {error}") from error

        message_id = str(message.get("Message-ID") or "").strip() or f"<{to_address}>"
        smtp_response = ""
        if response:
            smtp_response = "; ".join(f"{recipient}: {detail}" for recipient, detail in response.items())
        return SendResult(to=to_address, message_id=message_id, smtp_response=smtp_response)


class InMemoryMailTransport:
    """Test double that records outbound mail without network I/O."""

    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.sent: list[OutboundMail] = []
        self.fail_for = {normalize_email(item).casefold() for item in (fail_for or set()) if normalize_email(item)}

    def send(self, mail: OutboundMail) -> SendResult:
        to_address = validate_email(mail.to, field_name="to")
        if to_address.casefold() in self.fail_for:
            raise SmtpError(f"SMTP delivery failed for {to_address}")
        self.sent.append(mail)
        return SendResult(to=to_address, message_id=f"<memory-{len(self.sent)}@test.local>", smtp_response="ok")


def live_mail_transport_from_env() -> SmtpMailTransport:
    return SmtpMailTransport(smtp_config_from_env())


async def send_mail_async(transport: MailTransport, mail: OutboundMail) -> SendResult:
    return await asyncio.to_thread(transport.send, mail)


def smtp_config_public_dict(config: SmtpConfig) -> dict[str, Any]:
    """Safe config snapshot for diagnostics (never includes password)."""
    return {
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "from_address": config.from_address,
        "starttls": config.starttls,
        "tls_verify": config.tls_verify,
        "timeout_seconds": config.timeout_seconds,
    }
