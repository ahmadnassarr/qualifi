"""Send emails through any SMTP account (free options: a Gmail app password, Brevo, Mailjet...).

Settings (environment or .env):
  QUALIFI_SMTP_HOST, QUALIFI_SMTP_PORT (587 = STARTTLS, 465 = SSL), QUALIFI_SMTP_USER,
  QUALIFI_SMTP_PASSWORD, QUALIFI_MAIL_FROM (e.g. "Qualifi <no-reply@yourdomain.com>")

Without QUALIFI_SMTP_HOST the email is printed to the console and the log instead,
so password reset still works while you run the site on your own computer.
"""
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app


def mail_configured():
    return bool(os.environ.get("QUALIFI_SMTP_HOST"))


def send_email(to, subject, body):
    """Send in the background so the page answers at once (and equally fast whether
    or not the address has an account)."""
    app = current_app._get_current_object()
    if app.config.get("TESTING"):
        app.config.setdefault("MAIL_OUTBOX", []).append({"to": to, "subject": subject, "body": body})
        return
    if not mail_configured():
        app.logger.warning("Email not sent (QUALIFI_SMTP_HOST is not set). To: %s | %s\n%s", to, subject, body)
        print(f"\n----- EMAIL (not sent: no SMTP settings) -----\nTo: {to}\nSubject: {subject}\n\n{body}\n"
              "----------------------------------------------\n", flush=True)
        return
    threading.Thread(target=_deliver, args=(app, to, subject, body), daemon=True).start()


def _deliver(app, to, subject, body):
    host = os.environ["QUALIFI_SMTP_HOST"]
    port = int(os.environ.get("QUALIFI_SMTP_PORT", 587))
    user = os.environ.get("QUALIFI_SMTP_USER", "")
    password = os.environ.get("QUALIFI_SMTP_PASSWORD", "")
    msg = EmailMessage()
    msg["From"] = os.environ.get("QUALIFI_MAIL_FROM") or user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as s:
                if user:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=context)
                if user:
                    s.login(user, password)
                s.send_message(msg)
    except Exception:
        app.logger.exception("Could not send email to %s", to)
