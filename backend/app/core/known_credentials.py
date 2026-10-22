"""Known-compromised credentials, kept only so startup can refuse them (SEC-002, SEC-005).

- ``PUBLIC_JWT_SECRET_SHA256``: SHA-256 of the JWT secret that was once the public code default.
  A configured secret is compared by digest; the value itself is no longer in the code.
- ``_HISTORICAL_SEED_PASSWORDS_B64``: the development seed passwords that were hard-coded in
  ``seed_users.py`` (and remain in git history, so they are public). Checking a bcrypt hash needs
  the candidate plaintext, so they are kept base64-encoded (to stay out of logs, greps and secret
  scanners, not as protection). They are decoded only inside ``historical_seed_passwords()`` and
  must never be printed or logged.
"""

from __future__ import annotations

import base64

PUBLIC_JWT_SECRET_SHA256 = "080b180b428d4998d948072f6356bf3cdde157e6fe14abaa44c3aefd552607bf"

_HISTORICAL_SEED_PASSWORDS_B64 = (
    "TGF3eWVyUGFzc3dvcmQxMjMh",
    "QWRtaW5QYXNzd29yZDEyMyE=",
)


def historical_seed_passwords() -> tuple[str, ...]:
    return tuple(base64.b64decode(value).decode("utf-8") for value in _HISTORICAL_SEED_PASSWORDS_B64)
