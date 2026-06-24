from __future__ import annotations

import hmac
import json
import os
import smtplib
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
RECIPIENT = "aifusionlabs@gmail.com"
SUBJECT = "[RadarWire] Vercel SMTP smoke test"
CONFIRM_VALUE = "send-one-email"
TOKEN_ENV = "RADAR_SMTP_SMOKE_TOKEN"


class handler(BaseHTTPRequestHandler):
    """Vercel-only SMTP smoke endpoint.

    GET is safe/read-only and returns configuration presence booleans.
    POST sends exactly one message for that request only, and only when
    ?confirm=send-one-email plus the RADAR_SMTP_SMOKE_TOKEN gate are supplied
    by the operator.
    """

    def _write_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _env_summary(self) -> dict:
        username = os.getenv("RADAR_SMTP_USERNAME")
        password = os.getenv("RADAR_SMTP_PASSWORD")
        smoke_token = os.getenv(TOKEN_ENV)
        return {
            "smtp_host": SMTP_HOST,
            "smtp_port": SMTP_PORT,
            "tls": True,
            "from_env": "RADAR_SMTP_USERNAME",
            "from_env_set": bool(username),
            "password_env": "RADAR_SMTP_PASSWORD",
            "password_env_set": bool(password),
            "smoke_token_env": TOKEN_ENV,
            "smoke_token_env_set": bool(smoke_token),
            "to": RECIPIENT,
            "subject": SUBJECT,
            "runs_crawler": False,
            "runs_hermes": False,
            "runs_scheduler": False,
            "runs_production_worker": False,
            "uses_sqlite_or_radar_data": False,
        }

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "mode": "read_only_preflight",
                "send_method": "POST",
                "send_requires_query": f"confirm={CONFIRM_VALUE}",
                "send_requires_token": "X-Radar-Smoke-Token header or token query param",
                **self._env_summary(),
            },
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if query.get("confirm", [None])[0] != CONFIRM_VALUE:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "refusing_to_send_without_explicit_confirm_query",
                    "required_query": f"confirm={CONFIRM_VALUE}",
                    **self._env_summary(),
                },
            )
            return

        expected_token = os.getenv(TOKEN_ENV)
        supplied_token = self.headers.get("X-Radar-Smoke-Token") or query.get("token", [""])[0]
        if not expected_token:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "missing_required_smoke_token_env",
                    **self._env_summary(),
                },
            )
            return
        if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
            self._write_json(
                HTTPStatus.FORBIDDEN,
                {
                    "ok": False,
                    "error": "invalid_or_missing_smoke_token",
                    **self._env_summary(),
                },
            )
            return

        username = os.getenv("RADAR_SMTP_USERNAME")
        password = os.getenv("RADAR_SMTP_PASSWORD")
        if not username or not password:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "missing_required_smtp_env",
                    **self._env_summary(),
                },
            )
            return

        msg = EmailMessage()
        msg["From"] = username
        msg["To"] = RECIPIENT
        msg["Reply-To"] = username
        msg["Subject"] = SUBJECT
        msg.set_content(
            "RadarWire Vercel SMTP smoke test.\n\n"
            "This endpoint sends one operator-approved test email only.\n"
            "It does not run RadarWire crawling, Hermes analysis, scheduler, "
            "production worker, SQLite, or .radar-data.\n"
        )

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(username, password)
                smtp.send_message(msg)
        except Exception as exc:  # Do not include credential values in response.
            self._write_json(
                HTTPStatus.BAD_GATEWAY,
                {
                    "ok": False,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                    **self._env_summary(),
                },
            )
            return

        self._write_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "status": "sent",
                "message_count": 1,
                **self._env_summary(),
            },
        )
