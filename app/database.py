"""
Database connection managers for PostgreSQL and MSSQL
"""
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
import pyodbc


class PostgresManager:
    """Manages PostgreSQL database connections and operations"""

    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@db:5432/inventory')

    @contextmanager
    def get_connection(self):
        """Get a database connection"""
        conn = psycopg2.connect(self.database_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== Admin DB Config ====================

    def get_admin_db_config(self):
        """Get Admin DB configuration"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM admin_db_config ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                return dict(row) if row else None

    def save_admin_db_config(self, server, database, username, password):
        """Save Admin DB configuration"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Delete existing config
                cur.execute("DELETE FROM admin_db_config")
                # Insert new config
                cur.execute("""
                    INSERT INTO admin_db_config (server, database, username, password, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (server, database, username, password))

    # ==================== Store Connections ====================

    def get_all_stores(self):
        """Get all store connections"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM store_connections
                    ORDER BY is_primary DESC, nickname ASC
                """)
                return [dict(row) for row in cur.fetchall()]

    def get_store_by_id(self, store_id):
        """Get store by ID"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM store_connections WHERE id = %s", (store_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_primary_store(self):
        """Get primary store connection"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM store_connections
                    WHERE is_primary = TRUE AND is_active = TRUE
                    LIMIT 1
                """)
                row = cur.fetchone()
                return dict(row) if row else None

    def add_store(self, nickname, server, database, username, password, is_primary=False):
        """Add new store connection"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # If setting as primary, unset other primaries
                if is_primary:
                    cur.execute("UPDATE store_connections SET is_primary = FALSE")

                cur.execute("""
                    INSERT INTO store_connections
                    (nickname, server, database, username, password, is_primary)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (nickname, server, database, username, password, is_primary))
                return cur.fetchone()[0]

    def update_store(self, store_id, nickname=None, server=None, database=None,
                     username=None, password=None, is_primary=None, is_active=None):
        """Update store connection"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Build dynamic update query
                updates = []
                params = []

                if nickname is not None:
                    updates.append("nickname = %s")
                    params.append(nickname)
                if server is not None:
                    updates.append("server = %s")
                    params.append(server)
                if database is not None:
                    updates.append("database = %s")
                    params.append(database)
                if username is not None:
                    updates.append("username = %s")
                    params.append(username)
                if password is not None:
                    updates.append("password = %s")
                    params.append(password)
                if is_primary is not None:
                    # If setting as primary, unset other primaries first
                    if is_primary:
                        cur.execute("UPDATE store_connections SET is_primary = FALSE")
                    updates.append("is_primary = %s")
                    params.append(is_primary)
                if is_active is not None:
                    updates.append("is_active = %s")
                    params.append(is_active)

                if updates:
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(store_id)
                    query = f"UPDATE store_connections SET {', '.join(updates)} WHERE id = %s"
                    cur.execute(query, params)

    def delete_store(self, store_id):
        """Delete store connection"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM store_connections WHERE id = %s", (store_id,))

    def set_primary_store(self, store_id):
        """Set a store as primary (unsets others)"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Unset all primaries
                cur.execute("UPDATE store_connections SET is_primary = FALSE")
                # Set new primary
                cur.execute("""
                    UPDATE store_connections
                    SET is_primary = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (store_id,))

    def get_store_by_nickname(self, nickname):
        """Get store connection by nickname"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM store_connections
                    WHERE nickname = %s AND is_active = TRUE
                """, (nickname,))
                row = cur.fetchone()
                return dict(row) if row else None

    # ==================== Transaction Log ====================

    def log_transaction(self, username, store_nickname, product_id, product_upc,
                        product_sku, product_description, old_quantity, new_quantity,
                        difference, status, error_message=None,
                        user_entered_qty=None, quotations_qty=0, purchase_orders_qty=0,
                        top_bins_qty=0):
        """Log a transaction with detailed breakdown"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO transaction_log
                    (username, store_nickname, product_id, product_upc, product_sku,
                     product_description, old_quantity, new_quantity, difference,
                     user_entered_qty, quotations_qty, purchase_orders_qty, top_bins_qty,
                     status, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (username, store_nickname, product_id, product_upc, product_sku,
                      product_description, old_quantity, new_quantity, difference,
                      user_entered_qty, quotations_qty, purchase_orders_qty, top_bins_qty,
                      status, error_message))

    def get_transactions(self, limit=100, offset=0, status=None, username=None):
        """Get transaction history"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = "SELECT * FROM transaction_log WHERE 1=1"
                params = []

                if status:
                    query += " AND status = %s"
                    params.append(status)
                if username:
                    query += " AND username = %s"
                    params.append(username)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                rows = cur.fetchall()
                # Convert datetime to ISO format
                result = []
                for row in rows:
                    row_dict = dict(row)
                    if row_dict.get('created_at'):
                        row_dict['created_at'] = row_dict['created_at'].isoformat()
                    result.append(row_dict)
                return result

    # ==================== Sessions ====================

    def create_session(self, session_token, username, full_name):
        """Create a new session"""
        expires_at = datetime.now() + timedelta(hours=24)
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sessions (session_token, username, full_name, expires_at)
                    VALUES (%s, %s, %s, %s)
                """, (session_token, username, full_name, expires_at))

    def get_session(self, session_token):
        """Get session by token"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM sessions
                    WHERE session_token = %s AND expires_at > CURRENT_TIMESTAMP
                """, (session_token,))
                row = cur.fetchone()
                return dict(row) if row else None

    def delete_expired_sessions(self):
        """Clean up expired sessions"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP")

    # ==================== App Settings ====================

    def init_settings_table(self):
        """Create app_settings table if it doesn't exist"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key VARCHAR(100) PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Insert default threshold if not exists
                cur.execute("""
                    INSERT INTO app_settings (key, value)
                    VALUES ('quantity_threshold', '10')
                    ON CONFLICT (key) DO NOTHING
                """)

    def get_setting(self, key):
        """Get a setting value by key"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT key, value FROM app_settings WHERE key = %s", (key,))
                row = cur.fetchone()
                return dict(row) if row else None

    def save_setting(self, key, value):
        """Save/update a setting value"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = CURRENT_TIMESTAMP
                """, (key, str(value)))


def get_mssql_connection_string(server, port, database, user, password, tds_version="7.4", timeout=30):
    """
    Generate MSSQL connection string using FreeTDS driver.

    TDS Version Guide:
    - 7.0: SQL Server 7.0
    - 7.1: SQL Server 2000
    - 7.2: SQL Server 2005
    - 7.3: SQL Server 2008
    - 7.4: SQL Server 2012/2014/2016/2017/2019/2022 (default)
    """
    connection_string = (
        f"DRIVER={{FreeTDS}};"
        f"SERVER={server};"
        f"PORT={port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"TDS_Version={tds_version};"
        f"CHARSET=UTF8;"
        f"TIMEOUT={timeout};"
    )
    return connection_string


class MSSQLManager:
    """Manages MSSQL database connections and operations using pyodbc"""

    def __init__(self, server, database, user, password):
        self.config = {
            'server': server,
            'database': database,
            'user': user,
            'password': password
        }

    def _get_connection_string(self, tds_version="7.4", timeout=10):
        """Get ODBC connection string"""
        server = self.config['server']
        port = 1433

        return get_mssql_connection_string(
            server=server,
            port=port,
            database=self.config['database'],
            user=self.config['user'],
            password=self.config['password'],
            tds_version=tds_version,
            timeout=timeout
        )

    @contextmanager
    def get_connection(self):
        """Get a database connection using FreeTDS ODBC driver"""
        conn_string = self._get_connection_string()
        conn = pyodbc.connect(conn_string, timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row_to_dict(self, cursor, row):
        """Convert a row to a dictionary using cursor description"""
        if row is None:
            return None
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, row))

    def test_connection(self):
        """Test database connection"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 AS test")
            result = cursor.fetchone()
            cursor.close()
            return result is not None

    # ==================== Authentication (Admin DB) ====================

    def authenticate_user(self, username):
        """Authenticate user against AdminUserProject_admin"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, full_name, statususer, activated
                FROM AdminUserProject_admin
                WHERE username = ?
            """, (username,))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result

    # ==================== Inventory Updates (Admin DB) ====================

    def record_inventory_update(self, username, product_description, product_sku,
                                 product_upc, old_qty, new_qty, diff_qty,
                                 update_type, date_created):
        """Record inventory update in ManualInventoryUpdate"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ManualInventoryUpdate
                (DateCreated, Username, UpdateType, ProductDescription,
                 ProductSKU, ProductUPC, OldQty, NewQty, DiffQty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date_created, username, update_type, product_description,
                  product_sku, product_upc, old_qty, new_qty, diff_qty))
            cursor.close()

    # ==================== Product Operations (Store DB) ====================

    def lookup_product_by_upc(self, upc):
        """Look up product by UPC in Items_tbl"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ProductID, ProductUPC, ProductSKU, ProductDescription,
                       QuantOnHand, LastCountDate, ISNULL(UnitQty2, 0) AS UnitQty2
                FROM Items_tbl
                WHERE ProductUPC = ?
            """, (upc,))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result

    def get_product_by_id(self, product_id):
        """Get product by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ProductID, ProductUPC, ProductSKU, ProductDescription,
                       QuantOnHand, LastCountDate
                FROM Items_tbl
                WHERE ProductID = ?
            """, (product_id,))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result

    def update_product_quantity(self, product_id, new_quantity, last_count_date):
        """Update product quantity and last count date"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE Items_tbl
                SET QuantOnHand = ?, LastCountDate = ?
                WHERE ProductID = ?
            """, (new_quantity, last_count_date, product_id))
            cursor.close()

    # ==================== Quotations (Admin DB) ====================

    def get_pending_quotations(self):
        """Get pending quotations from last 60 days with Dop2 and Dop3 populated"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT QuotationNumber, SourceDB, Dop1
                FROM QuotationsStatus
                WHERE DateCreate >= DATEADD(day, -60, GETDATE())
                  AND (Status IS NULL OR Status NOT IN ('CONVERTED', 'DELETED'))
                  AND Dop2 IS NOT NULL AND Dop2 != ''
                  AND Dop3 IS NOT NULL AND Dop3 != ''
            """)
            rows = cursor.fetchall()
            result = [self._row_to_dict(cursor, row) for row in rows]
            cursor.close()
            return result

    # ==================== Quotation Details (Store DB) ====================

    def get_product_in_quotation(self, quotation_id, product_upc):
        """Get total product quantity from QuotationsDetails_tbl (sum of all lines)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(Qty) AS Qty
                FROM QuotationsDetails_tbl
                WHERE QuotationID = ? AND ProductUPC = ?
            """, (quotation_id, product_upc))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result

    # ==================== Purchase Orders (Store DB) ====================

    def get_pending_purchase_orders(self):
        """Get pending POs from last 90 days with Status = 0 (not received)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT PoID, PoNumber
                FROM PurchaseOrders_tbl
                WHERE PoDate >= DATEADD(day, -90, GETDATE())
                  AND Status = 0
            """)
            rows = cursor.fetchall()
            result = [self._row_to_dict(cursor, row) for row in rows]
            cursor.close()
            return result

    def get_product_in_purchase_order(self, po_id, product_upc):
        """Get total product quantity from PurchaseOrdersDetails_tbl (sum of all lines)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(QtyOrdered) AS QtyOrdered
                FROM PurchaseOrdersDetails_tbl
                WHERE PoID = ? AND ProductUPC = ?
            """, (po_id, product_upc))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result

    # ==================== Bin Locations (Store DB) ====================

    def get_bin_locations_total(self, product_upc):
        """Get total quantity in bin locations for a product (cases × units per case)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(ISNULL(bl.Qty_Cases, 0) * ISNULL(i.UnitQty2, 0)) AS total_qty
                FROM Items_BinLocations bl
                LEFT JOIN Items_tbl i ON bl.ProductUPC = i.ProductUPC
                WHERE bl.ProductUPC = ?
            """, (product_upc,))
            row = cursor.fetchone()
            result = self._row_to_dict(cursor, row)
            cursor.close()
            return result
