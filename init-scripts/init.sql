-- Inventory Update Application - PostgreSQL Schema
-- Initialize database tables

-- Admin DB connection config
CREATE TABLE IF NOT EXISTS admin_db_config (
    id SERIAL PRIMARY KEY,
    server VARCHAR(255) NOT NULL,
    database VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Store connections (multiple stores with nicknames)
CREATE TABLE IF NOT EXISTS store_connections (
    id SERIAL PRIMARY KEY,
    nickname VARCHAR(100) UNIQUE NOT NULL,
    server VARCHAR(255) NOT NULL,
    database VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255),
    is_primary BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transaction history log (local backup)
CREATE TABLE IF NOT EXISTS transaction_log (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    store_nickname VARCHAR(100) NOT NULL,
    product_id INTEGER NOT NULL,
    product_upc VARCHAR(20),
    product_sku VARCHAR(20),
    product_description VARCHAR(50),
    old_quantity REAL,
    new_quantity REAL NOT NULL,
    difference REAL,
    user_entered_qty REAL,
    quotations_qty REAL DEFAULT 0,
    purchase_orders_qty REAL DEFAULT 0,
    top_bins_qty REAL DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migration: Add new columns to existing table (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'transaction_log' AND column_name = 'user_entered_qty') THEN
        ALTER TABLE transaction_log ADD COLUMN user_entered_qty REAL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'transaction_log' AND column_name = 'quotations_qty') THEN
        ALTER TABLE transaction_log ADD COLUMN quotations_qty REAL DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'transaction_log' AND column_name = 'purchase_orders_qty') THEN
        ALTER TABLE transaction_log ADD COLUMN purchase_orders_qty REAL DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'transaction_log' AND column_name = 'top_bins_qty') THEN
        ALTER TABLE transaction_log ADD COLUMN top_bins_qty REAL DEFAULT 0;
    END IF;
END $$;

-- Session tracking
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_token VARCHAR(255) UNIQUE,
    username VARCHAR(50),
    full_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_transaction_log_username ON transaction_log(username);
CREATE INDEX IF NOT EXISTS idx_transaction_log_created_at ON transaction_log(created_at);
CREATE INDEX IF NOT EXISTS idx_transaction_log_status ON transaction_log(status);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_store_connections_primary ON store_connections(is_primary);
