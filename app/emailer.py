import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _get_config():
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from_addr": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "agent@example.com",
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    }


def send_mail(to: str, subject: str, body: str, bcc: str = None) -> None:
    cfg = _get_config()

    if not cfg["host"] or not to:
        print(f"[MAIL SKIPPED - kein SMTP oder keine Empfängeradresse] to={to!r} subject={subject!r}")
        return

    msg = MIMEMultipart()
    msg["From"] = cfg["from_addr"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    recipients = [to]
    if bcc:
        recipients.append(bcc)

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["user"] and cfg["password"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from_addr"], recipients, msg.as_string())
        print(f"[MAIL GESENDET] to={to} bcc={bcc!r} subject={subject!r}")
    except Exception as exc:
        print(f"[MAIL FEHLER] to={to} subject={subject!r}: {exc}")
