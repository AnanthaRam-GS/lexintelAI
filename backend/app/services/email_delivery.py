"""Email delivery abstraction for account verification messages."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import logging
import smtplib

from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when a verification email cannot be safely delivered."""


@dataclass(frozen=True)
class EmailDeliveryService:
    settings: Settings

    def send_email_verification_otp(self, email: str, otp: str, expiry_minutes: int) -> None:
        mode = self.settings.email_delivery_mode.strip().lower()
        if mode == "console":
            self._send_console(email=email, otp=otp, expiry_minutes=expiry_minutes)
            return
        if mode == "smtp":
            self._send_smtp(email=email, otp=otp, expiry_minutes=expiry_minutes)
            return
        raise EmailDeliveryError("Email delivery is not configured.")

    def _send_console(self, *, email: str, otp: str, expiry_minutes: int) -> None:
        if self.settings.app_env == "production":
            raise EmailDeliveryError("Console email delivery is disabled in production.")
        logger.info(
            "Development email verification OTP for %s: %s (expires in %s minutes)",
            email,
            otp,
            expiry_minutes,
        )

    def _send_smtp(self, *, email: str, otp: str, expiry_minutes: int) -> None:
        if not self.settings.smtp_host or not self.settings.smtp_from_email:
            raise EmailDeliveryError("SMTP host/from address is not configured.")
        message = EmailMessage()
        message["Subject"] = "Your LegalAI verification code"
        message["From"] = self.settings.smtp_from_email
        message["To"] = email
        message.set_content(
            "\n".join(
                [
                    "Your LegalAI email verification code is:",
                    "",
                    otp,
                    "",
                    f"This code expires in {expiry_minutes} minutes.",
                    "If you did not request this code, you can ignore this email.",
                ]
            )
        )
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - exact SMTP exceptions vary by server
            raise EmailDeliveryError("Verification email could not be sent.") from exc


def get_email_delivery_service(settings: Settings | None = None) -> EmailDeliveryService:
    return EmailDeliveryService(settings or Settings())
