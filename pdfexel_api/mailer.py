from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from pdfexel_api import settings

log = logging.getLogger("pdfexel_api.mailer")


class MailerConfigError(Exception):
    detail = "SMTP is not configured"


class MailerSmtpError(Exception):
    def __init__(self, detail: str = "Failed to send email"):
        self.detail = detail
        super().__init__(detail)


def send_otp(email: str, code: str) -> None:
    if not settings.SMTP_PASSWORD:
        raise MailerConfigError()

    msg = EmailMessage()
    msg["Subject"] = f"Код входа pdfexel: {code}"
    msg["From"] = formataddr(("pdfexel", settings.SMTP_FROM))
    msg["To"] = email
    msg.set_content(
        "\n".join(
            [
                "Здравствуйте!",
                "",
                f"Ваш код для входа на pdfexel: {code}",
                "Код действует 10 минут.",
                "",
                "Если вы не запрашивали код — просто удалите письмо.",
                "",
                "— pdfexel",
                "https://pdfexel.ru",
            ]
        )
    )

    try:
        if settings.SMTP_USE_TLS:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
    except MailerConfigError:
        raise
    except Exception as exc:
        log.exception("smtp.send_failed to=%s", email)
        raise MailerSmtpError() from exc
