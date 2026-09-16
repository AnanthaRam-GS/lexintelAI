"""Seed development users into the LegalAI PostgreSQL database.

Creates or updates default development users with roles and bcrypt-hashed passwords:
- lawyer@legalai.local (role: lawyer)
- admin@legalai.local (role: admin)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.security import hash_password
from backend.app.db.models import User
from backend.app.db.session import SessionLocal

SEED_USERS = [
    {
        "email": "lawyer@legalai.local",
        "password": "LawyerPassword123!",
        "role": "lawyer",
        "full_name": "LegalAI Development Lawyer",
    },
    {
        "email": "admin@legalai.local",
        "password": "AdminPassword123!",
        "role": "admin",
        "full_name": "LegalAI Development Admin",
    },
]


def seed_development_users() -> list[dict[str, str]]:
    """Idempotently seed or update development users in PostgreSQL."""
    db = SessionLocal()
    seeded = []
    try:
        for user_data in SEED_USERS:
            email = user_data["email"].strip().lower()
            role = user_data["role"]
            plain_pwd = user_data["password"]

            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    email=email,
                    full_name=user_data["full_name"],
                    hashed_password=hash_password(plain_pwd),
                    role=role,
                    email_verified=1,
                )
                db.add(user)
                action = "Created"
            else:
                user.hashed_password = hash_password(plain_pwd)
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


if __name__ == "__main__":
    print("Seeding LegalAI development users into PostgreSQL...")
    results = seed_development_users()
    print(f"\nSuccessfully seeded {len(results)} development user(s).")
