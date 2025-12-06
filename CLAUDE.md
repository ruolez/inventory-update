# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Inventory Update is a mobile-first web application for barcode scanning and inventory recounting. Users scan barcodes to look up items and enter new quantities, with changes tracked across multiple databases.

## Technology Stack

- **Backend:** Python 3.11 + Flask
- **Frontend:** HTML5, CSS3, Vanilla JavaScript (no frameworks)
- **Databases:**
  - PostgreSQL (Docker): Local settings, store connections, transaction history, sessions
  - MSSQL (External): Admin DB for authentication (`AdminUserProject_admin`) and audit log (`ManualInventoryUpdate`)
  - MSSQL (External): Store DBs with `Items_tbl` for product data
- **Port:** 5557
- **Timezone:** America/Chicago (Central Time)

## Development Commands

### Running Locally (Required for MSSQL Access)

Docker for Mac cannot reach local network MSSQL servers. Run Flask locally with PostgreSQL in Docker:

```bash
# Start PostgreSQL container
docker-compose up -d db

# Create and activate Python 3.11 virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run Flask locally
export FLASK_APP=app.main:app
export FLASK_ENV=development
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/inventory
export TZ=America/Chicago
python -m flask run --host=0.0.0.0 --port=5557
```

### Docker Only (When MSSQL Not Needed)

```bash
docker-compose up -d --build
```

### Restarting Flask After Code Changes

```bash
pkill -f "flask run"; sleep 1; source venv/bin/activate && \
  export FLASK_APP=app.main:app && \
  export FLASK_ENV=development && \
  export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/inventory && \
  export TZ=America/Chicago && \
  python -m flask run --host=0.0.0.0 --port=5557
```

## Architecture

### Database Connections

- **PostgresManager** (`app/database.py`): Manages local PostgreSQL for config, sessions, and transaction logs
- **MSSQLManager** (`app/database.py`): Connects to external SQL Server using pymssql with FreeTDS driver (TDS version 7.0)

### External MSSQL Tables

- `AdminUserProject_admin`: User authentication (username lookup only, no password)
- `ManualInventoryUpdate`: Audit log for inventory changes
- `Items_tbl`: Product lookup by `ProductUPC`, update `QuantOnHand` and `LastCountDate`

### Key Implementation Details

- MSSQL connections use `tds_version='7.0'` for compatibility
- Named SQL Server instances (e.g., `server\INSTANCE`) running on port 1433 can be accessed with just the IP address
- User authentication treats `activated=None` as active (only `activated=False` is rejected)
- All responses have no-cache headers applied via `@app.after_request`

## API Endpoints

### Authentication
- `POST /api/auth/login` - Username-only login against Admin DB
- `POST /api/auth/logout` - End session
- `GET /api/auth/me` - Current user info

### Inventory
- `GET /api/product/lookup?barcode={upc}` - Lookup product in primary store
- `POST /api/product/update-quantity` - Update quantity (writes to store DB, Admin DB, and local log)
- `GET /api/transactions` - Transaction history

### Configuration
- `GET/POST /api/config/admin-db` - Admin DB connection settings
- `POST /api/config/test-admin-db` - Test Admin DB connection
- `GET/POST /api/config/stores` - Store connection CRUD
- `POST /api/config/stores/{id}/test` - Test store connection
