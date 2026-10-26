#!/bin/bash
# LEGACY (step 20): an early Ubuntu-only setup kept for the record. Do not use it: it drops the "legalai" database
# and creates a PostgreSQL user with a fixed, publicly known password. Follow README.md, "Quick start", instead.
set -e

echo "1. Installing PostgreSQL..."
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib

echo "2. Setting up PostgreSQL user and database..."
sudo -u postgres psql -c "DROP DATABASE IF EXISTS legalai;"
sudo -u postgres psql -c "DROP USER IF EXISTS \"user\";"
sudo -u postgres psql -c "CREATE USER \"user\" WITH ENCRYPTED PASSWORD 'password';"
sudo -u postgres psql -c "CREATE DATABASE legalai;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE legalai TO \"user\";"
sudo -u postgres psql -c "ALTER DATABASE legalai OWNER TO \"user\";"
sudo -u postgres psql -c "GRANT ALL ON SCHEMA public TO \"user\";" legalai

echo "3. Creating .env file if it doesn't exist..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Copied .env.example to .env."
else
    echo ".env file already exists."
fi

echo "4. Running Alembic database migrations..."
if [[ "$VIRTUAL_ENV" != "" ]]; then
    python3 -m alembic upgrade head
else
    ./backend/.venv/bin/python -m alembic upgrade head
fi

echo "✅ Setup complete! You can now run your backend server:"
echo "python3 -m uvicorn backend.main:app --reload --port 8000"
