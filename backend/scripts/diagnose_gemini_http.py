"""Diagnose Gemini provider health with a minimal harmless request."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import AnswerMode, GeminiAnswerAdapter, ModelProviderError, ModelUnavailableError


DIAGNOSTIC_PATH = REPO_ROOT / "data/structured/manifests/legal_answer_gemini_http_diagnostic.json"


class GeminiHealthCheckOutput(BaseModel):
    ok: str


def main() -> int:
    settings = Settings()
    before = settings.gemini_model or None
    payload = {
        "schema_version": "legalai_gemini_http_diagnostic_v1",
        "configured_model_before": before,
        "configured_model_after": before,
        "endpoint_version": "v1beta",
        "diagnostic_http_status": None,
        "provider_error_code": None,
        "provider_error_message_sanitized": None,
        "root_cause": None,
        "fix_applied": "SANITIZE_PYDANTIC_JSON_SCHEMA_FOR_GEMINI",
        "health_check_status": "NOT_RUN",
        "actual_model": None,
    }
    if not settings.gemini_api_key or not settings.gemini_model:
        payload["root_cause"] = "AUTHENTICATION_CONFIGURATION"
        payload["health_check_status"] = "SKIPPED_CREDENTIALS_OR_MODEL_UNAVAILABLE"
        write_json(payload)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    try:
        response = GeminiAnswerAdapter(settings).generate_structured_answer(
            'Return JSON exactly as {"ok":"OK"}.',
            schema=GeminiHealthCheckOutput,
            mode=AnswerMode.PUBLIC,
        )
    except ModelUnavailableError as exc:
        payload["root_cause"] = "AUTHENTICATION_CONFIGURATION"
        payload["health_check_status"] = "MODEL_UNAVAILABLE"
        payload["provider_error_message_sanitized"] = str(exc)
    except ModelProviderError as exc:
        payload["diagnostic_http_status"] = exc.http_status
        payload["provider_error_code"] = exc.provider_code
        payload["provider_error_message_sanitized"] = exc.provider_message or str(exc)
        payload["root_cause"] = classify_root_cause(exc)
        payload["health_check_status"] = "FAILED"
    else:
        payload["diagnostic_http_status"] = 200
        payload["health_check_status"] = "SUCCESS"
        payload["actual_model"] = response.model_metadata.actual_model_id
        payload["root_cause"] = "NONE"
    write_json(payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def classify_root_cause(exc: ModelProviderError) -> str:
    code = exc.code
    message = (exc.provider_message or "").lower()
    if code == "GEMINI_AUTH_ERROR":
        return "AUTHENTICATION_CONFIGURATION"
    if code == "GEMINI_RATE_LIMIT":
        return "QUOTA_OR_RATE_LIMIT"
    if code == "GEMINI_TIMEOUT":
        return "NETWORK_OR_TLS"
    if exc.http_status == 404 or "not found" in message or "not available" in message:
        return "MODEL_UNAVAILABLE_OR_RETIRED"
    if exc.http_status == 400:
        return "REQUEST_SCHEMA_INVALID"
    if exc.http_status and 500 <= exc.http_status <= 599:
        return "UNKNOWN_PROVIDER_FAILURE"
    return "UNKNOWN_PROVIDER_FAILURE"


def write_json(payload: dict) -> None:
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
