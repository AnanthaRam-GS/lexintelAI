# Security

This document records the step 13 hardening (SEC-001 to SEC-009, R04, R05, R35). It covers what is enforced, how
to set up development, the residual risks, and the dependency scan. API behaviour is in `docs/API_CONTRACTS.md`.

## Status

| Item | Finding | Status | Where |
|---|---|---|---|
| SEC-001 | No rate limiting; anonymous routes trigger paid LLM calls and PDF parsing | **Fixed**: per-IP limits on public query routes, per-user limits on professional routes, and a global cap on concurrent LLM generations | `core/rate_limit.py`, `api/query.py` |
| SEC-002 | `seed_users.py` hard-coded lawyer and admin passwords | **Fixed**: passwords come only from `SEED_LAWYER_PASSWORD` / `SEED_ADMIN_PASSWORD`; the script refuses production; startup refuses (outside development and test) if any user still has a historical seed password | `scripts/seed_users.py`, `core/startup_checks.py` |
| SEC-003 | No login throttling; registration 409 enumerated accounts | **Fixed**: per-account and per-IP failed-login lockout; register, resend and verify answer identically for existing and unknown emails | `api/auth.py` |
| SEC-004 | `is_active` never enforced | **Fixed**: checked at login and on every authenticated request, with the generic failure | `api/auth.py`, `core/dependencies.py` |
| SEC-005 | Public default JWT secret used if none was set outside production | **Fixed**: the default is removed; startup and token use refuse a missing, default or short (< 32 bytes) secret outside `APP_ENV=test` | `core/security.py`, `core/startup_checks.py` |
| SEC-006 | Cookie not `Secure` outside production; no CSRF defence beyond SameSite=Lax | **Fixed**: `HttpOnly`, explicit `SameSite`, `Secure` in production; Origin/Referer check on cookie-authenticated writes | `core/security.py`, `core/request_guards.py` |
| SEC-007 | Raw error text in ingestion job errors | Fixed earlier (`docs/INGESTION_RELIABILITY.md`, "Errors (SEC-007)") | — |
| SEC-008 | Admin upload read fully into memory before the size check | **Fixed**: streamed read with an early 413; oversize `Content-Length` rejected before the body is read | `api/ingest.py`, `core/request_guards.py` |
| SEC-009 | `/dev/component-preview` shipped in the app | **Fixed**: 404 in production builds | `frontend/app/dev/component-preview/` |
| SEC-010 | Logout does not revoke the JWT | **Accepted** by the plan (residual risk below) | — |
| Negative authorization | Never exercised at runtime | **Tested**: `test_security_hardening.NegativeAuthorizationTests` (DB suite) | `backend/scripts/tests/` |

## Development setup

The backend refuses to start without a proper JWT secret. Set one once in the repository `.env` (never commit it):

1. Generate a secret:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Put it in `.env` as `JWT_SECRET_KEY=<the value>`. It must be at least 32 bytes and must not be the old public default.
3. Changing the secret signs everyone out; log in again.

To (re)create the development lawyer and admin accounts:

1. Choose two passwords of at least 12 characters, for example with
   `python -c "import secrets; print(secrets.token_urlsafe(18))"`.
2. Either add them to `.env` as `SEED_LAWYER_PASSWORD=...` and `SEED_ADMIN_PASSWORD=...`, or pass them for one run:
   `SEED_LAWYER_PASSWORD='...' SEED_ADMIN_PASSWORD='...' .venv/bin/python backend/scripts/seed_users.py`
3. The script updates the existing `lawyer@legalai.local` and `admin@legalai.local` users in place (and creates them
   if missing). It prints only IDs, emails and roles, never a password.

The script refuses to run when a variable is missing, shorter than 12 characters or one of the historical seed
passwords, and always with `APP_ENV=production`. Re-seeding is also how you replace the old known passwords in an
existing dev database. Until then the dev accounts keep them, which is allowed in development only.

Tests need neither: the DB test bootstrap sets `APP_ENV=test` (a random per-process JWT secret) and seeds the accounts
with random per-process passwords.

## Startup checks (`core/startup_checks.py`)

These run in the application lifespan, before anything else. A failure raises `InsecureConfigurationError`, so
uvicorn does not start.

- **JWT secret:** outside `APP_ENV=test`, it must be set, at least 32 bytes, and not the old public default. The default
  is recognised by its SHA-256 digest, so the value is no longer in the code. Error messages never include the value.
- **Seed passwords:** outside development and test, every user's bcrypt hash is checked against the historical seed
  passwords. If any matches, startup is refused with the count and the user IDs, never the password or email.
  - Checking a salted bcrypt hash needs the candidate plaintext. So the old values, which are already public in git
    history, are kept base64-encoded in `core/known_credentials.py`, which keeps them out of logs, greps and secret
    scanners. They are decoded only inside the check and never printed.
  - The check costs one bcrypt verification per user per candidate (about 0.2 s each), so a very large user table
    slows startup. That is acceptable for this deployment size.

## Sign-in protection

- **Generic failures:** unknown email, wrong password and a deactivated account all return the same 401. For unknown
  emails the password is checked against a dummy hash, so timing matches.
- **Throttling:** failures are counted per email and per client IP within `LOGIN_FAILURE_WINDOW_SECONDS` (900).
  - At `LOGIN_MAX_FAILURES_PER_ACCOUNT` (5) or `LOGIN_MAX_FAILURES_PER_IP` (20), login returns 429 `LOGIN_THROTTLED`
    with `Retry-After` for `LOGIN_LOCKOUT_SECONDS` (900).
  - Unknown emails are counted the same way, so lockout reveals nothing.
  - A successful login clears that email's count.
- **Registration, resend, verify:** responses are identical for existing and unknown emails. An existing account's
  owner gets an "account already exists" email instead of a code. See `docs/API_CONTRACTS.md` for the exact shapes.
- **Sessions:** every request reloads the user. A deactivated user, or a user who no longer exists, gets 401. The role
  always comes from the database, never from the token.

## Rate limits and LLM capacity (`core/rate_limit.py`)

- **Public query routes** (`/query/public`, `/query/public/pdf`): one shared budget per client IP, 5 per minute and
  100 per day by default.
- **Professional query routes:** per user, 10 per minute and 300 per day.
- **Over a limit:** 429 `RATE_LIMITED` with `Retry-After` and a plain-language message, before retrieval or any
  provider call.
- **Concurrent generations:** a semaphore allows at most `LLM_MAX_CONCURRENT_GENERATIONS` (4) LLM generations at once.
  A request waits up to `LLM_GENERATION_WAIT_SECONDS` (10) for a slot, then gets 503 `MODEL_BUSY` with
  `Retry-After: 15`.
- **Client IP:** the TCP peer. `X-Forwarded-For` is trusted only when the peer is in `TRUSTED_PROXIES`; then the
  right-most address that is not a trusted proxy is used, so a client-supplied left-most entry cannot spoof it.
  Behind a reverse proxy, set `TRUSTED_PROXIES` to the proxy's address, or every client shares the proxy's budget.
- **Single process only:** all counters and the semaphore live in process memory. With several uvicorn workers or
  hosts, each keeps its own counters, so effective limits multiply by the process count, and counters reset on
  restart. Scaling out needs a shared store (for example Redis) for the limiter, login throttle and generation cap.

The frontend shows the backend's plain-language message for `RATE_LIMITED`, `LOGIN_THROTTLED` and `MODEL_BUSY`.

## CSRF approach

The JWT is in an `HttpOnly` cookie, so CSRF is the relevant browser risk. There are two layers:

1. **SameSite cookie.** `AUTH_COOKIE_SAMESITE` defaults to `lax`, so browsers do not send the cookie on cross-site
   `POST`s, iframes or subresource requests. `none` forces `Secure`.
2. **Origin check** (`OriginCheckMiddleware`). A `POST`, `PUT`, `PATCH` or `DELETE` that carries the auth cookie must
   come from an allowed origin, the same list CORS uses (`FRONTEND_ORIGIN` plus the local dev origins).
   - The `Origin` header is checked, or the origin of `Referer` when `Origin` is absent. `Origin: null` is rejected.
     Failures get 403 `CSRF_ORIGIN_REJECTED`.
   - A request with neither header passes. Browsers always send `Origin` on cross-origin writes, so such a request
     comes from a non-browser client, which cannot ride a victim's cookies.
   - Requests without the auth cookie are not checked: anonymous calls and `Authorization: Bearer` clients have no
     ambient credential to forge.

`GET` routes do not change state, so they are not checked.

## Upload size (SEC-008)

- `BodySizeLimitMiddleware` answers 413 `REQUEST_TOO_LARGE` to any request whose `Content-Length` exceeds
  `MAX_UPLOAD_SIZE_MB` plus 1 MB of multipart overhead, without reading the body.
- The admin ingest route reads the file in 1 MB chunks and stops with 413 as soon as the limit is passed. At most the
  limit plus one chunk is read.
- The query PDF routes and the lawyer proof upload already streamed with a limit.

Starlette still receives a request body that lacks a `Content-Length` header (chunked encoding) into its spooled
temporary file before the route runs. The route-level limit then bounds what is read into memory.

## Residual risks

- **SEC-010, no token revocation (accepted).** Logout clears the cookie, but a copied JWT stays valid until it
  expires (`JWT_EXPIRY_MINUTES`, 60). Deactivating a user still blocks them at once, because every request checks
  `is_active`.
- **In-memory limits**, per process, reset on restart; see above.
- **Development-only enumeration:** with `APP_ENV` development/test and `EXPOSE_DEV_VERIFICATION_TOKENS=true`,
  registration returns `dev_verification_otp` only for new accounts. That flag must stay off anywhere reachable.
- **OTP attempt limit:** `verify-email` returns 429 after 5 wrong codes, which only an address with a pending code can
  reach. That reveals only that someone registered the address and has not yet verified it.
- **Existing dev accounts** keep the historical seed passwords until you re-seed (development is exempt from the
  startup check).
- **Dependency findings not fixed:** listed below.

## Dependency scan (step 13)

Commands:
- `npm audit` (frontend);
- `pip-audit -r <pip freeze of .venv> --no-deps --vulnerability-service osv`, with severities from the GitHub
  advisory database.

### Fixed (critical and high, minimal non-breaking bumps; all suites pass)

| Package | From → to | Severity | Advisories |
|---|---|---|---|
| next (+ eslint-config-next) | 16.3.4 → 16.3.8 (patch) | critical | GHSA-vcvr-r3jv-pc5j (RCE in `next/og` ImageResponse), GHSA-3w37-wq28-93x7 |
| sharp | 0.35.4 → 0.35.5 | high | GHSA-wq5f-xc86-pv6w |
| source-map-js | 1.2.1 → 1.2.2 | high | GHSA-68fv-2mgg-jv7q |
| brace-expansion | 1.1.18 → 1.1.21 | high | GHSA-q2hr-2g5m-vwhr |
| vite (dev, via vitest) | 8.2.2 → 8.3.5 | high | GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw |
| certifi | 2026.7.22 → 2026.10.19 | critical | GHSA-6q48-6c7w-9gw2 (compromised emSign intermediates) |
| aiohttp | 3.14.3 → 3.14.4 (patch) | high (+ medium/low) | GHSA-9xw5-w5jj-pvcg, GHSA-5wr8-gcqf-gqf3, GHSA-2g87-pp6c-29x5 |
| urllib3 | 2.7.0 → 2.8.0 | high (+ medium) | GHSA-vxq7-64xx-v4gw, GHSA-8988-9cw3-xx77 |

Notes on these fixes:
- The Python packages are transitive. `requirements.txt` now carries floors for them.
- `frontend/package-lock.json` had an invalid root entry, a merge leftover that duplicated `recharts`. It was
  repaired, so `npm audit` and `npm ci` can read it, and `recharts` is now locked at the 3.10.1 that `package.json`
  and `node_modules` already used.

### Not fixed (recorded)

| Package | Severity | Advisory | Why not fixed / exposure |
|---|---|---|---|
| eslint-config-next 16.3.8 → @next/eslint-plugin-next → fast-glob → micromatch → braces | high (5) | GHSA-vfj7-8cjw-p6xm (braces stack exhaustion) | The only fix npm offers is a major downgrade to 14.x. Dev-only lint tooling, never shipped or given untrusted input. |
| chromadb 1.5.9 | critical (2), high (2) | GHSA-f4j7-r4q5-qw2c, GHSA-36p7-vc44-83pf, GHSA-2wm9-hf6c-p5cr, GHSA-xph7-9rjv-w5fr | No fixed release. All four are in the Chroma HTTP server and its auth/RBAC; LegalAI uses the embedded `PersistentClient` and runs no Chroma server. Chroma was out of scope for this step. |
| starlette 0.46.2 | high (3), medium (3), low (1) | GHSA-7f5h-v6xp-fcq8, GHSA-wqp7-x3pw-xc5r, GHSA-82w8-qh3p-5jfq, and others | The fixes need starlette ≥ 0.49.1 or 1.x, and FastAPI 0.115 (pinned `<0.116`) requires `starlette<0.47`, so this needs a FastAPI upgrade (a separate, tested change). Exposure: no `FileResponse` or `StaticFiles` is used (7f5h and wqp7 are unreachable; wqp7 is also Windows-only). The urlencoded form DoS (82w8) is bounded by the 11 MB request body limit. |
| pyjwt 2.14.0 | medium (2) | GHSA-x33g-cr3x-6449, GHSA-42vr-xj54-vc7v | Only critical and high are fixed in this step. Neither path is used: LegalAI signs HS256 with a shared secret and never uses JWKs, `PyJWKClient` or `verify_signature=False`. Upgrade to 2.15.0 with the FastAPI upgrade. |
| accelerate 1.14.0, mako 1.4.1, multidict 6.7.1, oauthlib 3.3.1 | medium | GHSA-4j2p-28q2-5m79, GHSA-5639-2j2p-m4mx, GHSA-54p9-h82j-f925, GHSA-hj66-6f7g-4r5v, GHSA-xpv3-w29h-x7cv | Medium only, so not in scope. None is on a request path: model loading of trusted local checkpoints, Alembic templates, transitive multidict, and an unused OAuth stack. |
