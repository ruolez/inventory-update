#!/bin/bash
# Run Flask app locally (outside Docker) for network access to MSSQL
# PostgreSQL still runs in Docker

# Start PostgreSQL in Docker
docker-compose up -d db

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
sleep 5

# Set environment variables
export FLASK_APP=app.main:app
export FLASK_ENV=development
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/inventory
export TZ=America/Chicago

# Expose PostgreSQL port if not already
docker-compose exec -d db bash -c "echo 'Port already exposed'" 2>/dev/null

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Run Flask
echo "Starting Flask on http://localhost:5557"
python -m flask run --host=0.0.0.0 --port=5557
