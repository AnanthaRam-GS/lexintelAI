"""Seed development users into the LegalAI PostgreSQL database.

Creates or updates the development users with roles and bcrypt-hashed passwords:
- lawyer@legalai.local (role: lawyer), password from SEED_LAWYER_PASSWORD
- admin@legalai.local (role: admin), password from SEED_ADMIN_PASSWORD

SEC-002: there are no built-in passwords. The script refuses to run when either
variable is missing, too short or a known historical seed password, and always
refuses when APP_ENV=production. Passwords are never printed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MIN_SEED_PASSWORD_LENGTH = 12

SEED_USERS = [
    {
        "email": "lawyer@legalai.local",
        "password_env": "SEED_LAWYER_PASSWORD",
        "role": "lawyer",
        "full_name": "LegalAI Development Lawyer",
    },
    {
        "email": "admin@legalai.local",
        "password_env": "SEED_ADMIN_PASSWORD",
        "role": "admin",
        "full_name": "LegalAI Development Admin",
    },
]


class SeedRefused(RuntimeError):
    """The seed script must not run with this environment."""


def seed_passwords(environ: dict[str, str] | None = None, app_env: str | None = None) -> dict[str, str]:
    """The seed password per email from the environment; raises SeedRefused (without the values) otherwise."""
    from backend.app.core.known_credentials import historical_seed_passwords

    environ = dict(os.environ) if environ is None else environ
    if (app_env or "").strip().casefold() == "production":
        raise SeedRefused("Refusing to seed development users with APP_ENV=production.")
    known = set(historical_seed_passwords())
    passwords, problems = {}, []
    for user in SEED_USERS:
        name = user["password_env"]
        value = environ.get(name, "")
        if not value.strip():
            problems.append(f"{name} is not set")
        elif len(value) < MIN_SEED_PASSWORD_LENGTH:
            problems.append(f"{name} is shorter than {MIN_SEED_PASSWORD_LENGTH} characters")
        elif value in known:
            problems.append(f"{name} is a known historical seed password")
        else:
            passwords[user["email"]] = value
    if problems:
        raise SeedRefused("Refusing to seed: " + "; ".join(problems) + ". See docs/SECURITY.md.")
    return passwords


def seed_development_users(passwords: dict[str, str]) -> list[dict[str, str]]:
    """Idempotently seed or update development users in PostgreSQL."""
    from backend.app.core.security import hash_password
    from backend.app.db.models import User
    from backend.app.db.session import SessionLocal

    db = SessionLocal()
    seeded = []
    try:
        for user_data in SEED_USERS:
            email = user_data["email"].strip().lower()
            role = user_data["role"]
            hashed = hash_password(passwords[user_data["email"]])

            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    email=email,
                    full_name=user_data["full_name"],
                    hashed_password=hashed,
                    role=role,
                    email_verified=1,
                )
                db.add(user)
                action = "Created"
            else:
                user.hashed_password = hashed
                user.full_name = user_data["full_name"]
                user.role = role
                user.email_verified = 1
                action = "Updated"

            db.commit()
            db.refresh(user)
            seeded.append({
                "id": str(user.id),
                "email": user.email,
                "role": user.role,
                "action": action,
            })
            print(f"[{action}] User id={user.id}, email='{user.email}', role='{user.role}'")

    finally:
        db.close()

    return seeded


def main() -> int:
    from backend.app.core.config import Settings

    settings = Settings()
    # Values from .env, overridden by the process environment.
    environ = {"SEED_LAWYER_PASSWORD": settings.seed_lawyer_password, "SEED_ADMIN_PASSWORD": settings.seed_admin_password}
    environ.update({key: value for key, value in os.environ.items() if key in environ})
    try:
        passwords = seed_passwords(environ, app_env=settings.app_env)
    except SeedRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Seeding LegalAI development users into PostgreSQL...")
    results = seed_development_users(passwords)
    print(f"\nSuccessfully seeded {len(results)} development user(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
