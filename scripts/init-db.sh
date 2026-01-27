#!/bin/bash

# Script to initialize database

set -e

echo "🔧 Initializing database..."

cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
export JWT_SECRET_KEY="dev-secret-key-change-in-production"
export ENCRYPTION_KEY="dev-encryption-key-32-bytes-long!!"

# Run migrations
echo "Running migrations..."
alembic upgrade head

echo "✅ Database initialized successfully"

