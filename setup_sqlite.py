# LEGACY (step 20): an early SQLite prototype kept for the record. Do not use it: the app needs PostgreSQL with the
# Alembic migrations (create_all skips them), and it seeds accounts with a fixed, publicly known password.
# Follow README.md, "Quick start", and backend/scripts/seed_users.py instead.
import sys
import os

# Ensure backend package can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from backend.app.db.session import engine, SessionLocal
from backend.app.db.base import Base
# Import models to ensure they are registered with Base
from backend.app.db import models
from backend.app.core.security import hash_password
from backend.app.db.models import User

print("Creating SQLite database tables...")
Base.metadata.create_all(bind=engine)

print("Seeding test users...")
db = SessionLocal()

lawyer_email = "counsel.verma@highcourt.nic.in"
admin_email = "admin.sharma@legalai.gov.in"

if not db.query(User).filter(User.email == lawyer_email).first():
    db.add(User(
        email=lawyer_email,
        hashed_password=hash_password("password123"),
        role="lawyer"
    ))
    print(f"Created user {lawyer_email} with password 'password123'")

if not db.query(User).filter(User.email == admin_email).first():
    db.add(User(
        email=admin_email,
        hashed_password=hash_password("password123"),
        role="admin"
    ))
    print(f"Created user {admin_email} with password 'password123'")

db.commit()
db.close()
print("Database setup complete! You can now start the backend.")
