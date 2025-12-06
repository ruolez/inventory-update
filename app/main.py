"""
Inventory Update Application - Main Flask Application
"""
import os
import secrets
from functools import wraps
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv

from .database import PostgresManager, MSSQLManager

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

# Disable template caching for development - templates reload on every request
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Initialize database managers
pg_manager = PostgresManager()

# Initialize app settings table
pg_manager.init_settings_table()

# Central Time zone
CENTRAL_TZ = ZoneInfo("America/Chicago")


def get_current_time():
    """Get current time in Central timezone"""
    return datetime.now(CENTRAL_TZ)


def no_cache(response):
    """Add no-cache headers to response"""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def add_cors_headers(response):
    """Add CORS headers for LAN access"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response


@app.after_request
def after_request(response):
    """Apply no-cache and CORS headers to all responses"""
    response = no_cache(response)
    response = add_cors_headers(response)
    return response


def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.is_json:
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def get_admin_db():
    """Get Admin DB connection from config"""
    config = pg_manager.get_admin_db_config()
    if not config:
        return None
    return MSSQLManager(
        server=config['server'],
        database=config['database'],
        user=config['username'],
        password=config['password']
    )


def get_primary_store_db():
    """Get primary store DB connection"""
    store = pg_manager.get_primary_store()
    if not store:
        return None
    return MSSQLManager(
        server=store['server'],
        database=store['database'],
        user=store['username'],
        password=store['password']
    )


# ==================== PAGES ====================

@app.route('/')
def index():
    """Redirect to login or scan page"""
    if 'username' in session:
        return redirect(url_for('scan'))
    return redirect(url_for('login'))


@app.route('/login')
def login():
    """Login page"""
    if 'username' in session:
        return redirect(url_for('scan'))
    return render_template('login.html')


@app.route('/scan')
@login_required
def scan():
    """Main scanning page"""
    return render_template('scan.html', username=session.get('full_name', session.get('username')))


@app.route('/settings')
def settings():
    """Settings/configuration page - accessible without login for initial setup"""
    return render_template('settings.html', logged_in='username' in session)


@app.route('/history')
@login_required
def history():
    """Transaction history page"""
    return render_template('history.html')


# ==================== AUTH API ====================

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Authenticate user against AdminUserProject_admin"""
    data = request.get_json()
    username = data.get('username', '').strip()

    if not username:
        return jsonify({'error': 'Username is required'}), 400

    admin_db = get_admin_db()
    if not admin_db:
        return jsonify({'error': 'Admin database not configured. Please configure in settings.'}), 503

    try:
        user = admin_db.authenticate_user(username)
        if not user:
            return jsonify({'error': 'User not found'}), 401

        # Only reject if activated is explicitly False (None means active by default)
        if user.get('activated') is False:
            return jsonify({'error': 'User account is not activated'}), 401

        # Set session
        session['username'] = user['username']
        session['full_name'] = user.get('full_name', username)
        session['statususer'] = user.get('statususer', '')

        # Log session to PostgreSQL
        session_token = secrets.token_hex(32)
        pg_manager.create_session(
            session_token=session_token,
            username=user['username'],
            full_name=user.get('full_name', username)
        )

        return jsonify({
            'success': True,
            'username': user['username'],
            'full_name': user.get('full_name', username)
        })
    except Exception as e:
        return jsonify({'error': f'Authentication failed: {str(e)}'}), 500


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """End user session"""
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/me')
@login_required
def api_me():
    """Get current user info"""
    return jsonify({
        'username': session.get('username'),
        'full_name': session.get('full_name')
    })


# ==================== INVENTORY API ====================

@app.route('/api/product/lookup')
@login_required
def api_product_lookup():
    """Lookup product by barcode in primary store"""
    barcode = request.args.get('barcode', '').strip()

    if not barcode:
        return jsonify({'error': 'Barcode is required'}), 400

    store_db = get_primary_store_db()
    if not store_db:
        return jsonify({'error': 'Primary store not configured. Please configure in settings.'}), 503

    try:
        product = store_db.lookup_product_by_upc(barcode)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        return jsonify({
            'product_id': product['ProductID'],
            'product_upc': product['ProductUPC'],
            'product_sku': product['ProductSKU'],
            'product_description': product['ProductDescription'],
            'quantity_on_hand': product['QuantOnHand'],
            'last_count_date': product['LastCountDate'].isoformat() if product['LastCountDate'] else None
        })
    except Exception as e:
        return jsonify({'error': f'Lookup failed: {str(e)}'}), 500


@app.route('/api/product/update-quantity', methods=['POST'])
@login_required
def api_update_quantity():
    """Update product quantity (user entered + quotations qty + top bins qty)"""
    data = request.get_json()
    product_id = data.get('product_id')
    user_entered_qty = data.get('new_quantity')
    quotations_qty = data.get('quotations_qty', 0) or 0
    purchase_orders_qty = data.get('purchase_orders_qty', 0) or 0
    top_bins_qty = data.get('top_bins_qty', 0) or 0

    if product_id is None:
        return jsonify({'error': 'Product ID is required'}), 400
    if user_entered_qty is None:
        return jsonify({'error': 'New quantity is required'}), 400

    try:
        user_entered_qty = float(user_entered_qty)
        quotations_qty = float(quotations_qty)
        purchase_orders_qty = float(purchase_orders_qty)
        top_bins_qty = float(top_bins_qty)
    except ValueError:
        return jsonify({'error': 'Invalid quantity value'}), 400

    # Calculate final quantity: user entered + quotations + top bins (NOT purchase orders)
    final_qty = user_entered_qty + quotations_qty + top_bins_qty

    store_db = get_primary_store_db()
    admin_db = get_admin_db()
    primary_store = pg_manager.get_primary_store()

    if not store_db:
        return jsonify({'error': 'Primary store not configured'}), 503
    if not admin_db:
        return jsonify({'error': 'Admin database not configured'}), 503

    try:
        # Get current product info
        product = store_db.get_product_by_id(product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        old_quantity = product['QuantOnHand'] or 0
        difference = final_qty - old_quantity
        current_time = get_current_time()

        # Update Items_tbl in store DB with final quantity
        store_db.update_product_quantity(
            product_id=product_id,
            new_quantity=final_qty,
            last_count_date=current_time
        )

        # Record in ManualInventoryUpdate (Admin DB) - uses final qty
        admin_db.record_inventory_update(
            username=session.get('username'),
            product_description=product['ProductDescription'],
            product_sku=product['ProductSKU'],
            product_upc=product['ProductUPC'],
            old_qty=old_quantity,
            new_qty=final_qty,
            diff_qty=difference,
            update_type='Inventory',
            date_created=current_time
        )

        # Log to PostgreSQL with detailed breakdown
        pg_manager.log_transaction(
            username=session.get('username'),
            store_nickname=primary_store['nickname'] if primary_store else 'unknown',
            product_id=product_id,
            product_upc=product['ProductUPC'],
            product_sku=product['ProductSKU'],
            product_description=product['ProductDescription'],
            old_quantity=old_quantity,
            new_quantity=final_qty,
            difference=difference,
            status='success',
            user_entered_qty=user_entered_qty,
            quotations_qty=quotations_qty,
            purchase_orders_qty=purchase_orders_qty,
            top_bins_qty=top_bins_qty
        )

        return jsonify({
            'success': True,
            'product_id': product_id,
            'old_quantity': old_quantity,
            'new_quantity': final_qty,
            'user_entered_qty': user_entered_qty,
            'quotations_qty': quotations_qty,
            'purchase_orders_qty': purchase_orders_qty,
            'top_bins_qty': top_bins_qty,
            'difference': difference
        })
    except Exception as e:
        # Log failed transaction
        try:
            pg_manager.log_transaction(
                username=session.get('username'),
                store_nickname=primary_store['nickname'] if primary_store else 'unknown',
                product_id=product_id,
                product_upc=data.get('product_upc', ''),
                product_sku=data.get('product_sku', ''),
                product_description=data.get('product_description', ''),
                old_quantity=None,
                new_quantity=final_qty,
                difference=None,
                status='failed',
                error_message=str(e),
                user_entered_qty=user_entered_qty,
                quotations_qty=quotations_qty,
                purchase_orders_qty=purchase_orders_qty,
                top_bins_qty=top_bins_qty
            )
        except:
            pass
        return jsonify({'error': f'Update failed: {str(e)}'}), 500


@app.route('/api/transactions')
@login_required
def api_transactions():
    """Get transaction history"""
    try:
        transactions = pg_manager.get_transactions(
            limit=request.args.get('limit', 100, type=int),
            offset=request.args.get('offset', 0, type=int),
            status=request.args.get('status'),
            username=request.args.get('username')
        )
        return jsonify({'transactions': transactions})
    except Exception as e:
        return jsonify({'error': f'Failed to get transactions: {str(e)}'}), 500


@app.route('/api/product/quotations')
@login_required
def api_product_quotations():
    """Get pending quotations containing this product"""
    upc = request.args.get('upc', '').strip()

    if not upc:
        return jsonify({'error': 'UPC is required'}), 400

    admin_db = get_admin_db()
    if not admin_db:
        return jsonify({'error': 'Admin database not configured'}), 503

    try:
        pending_quotations = admin_db.get_pending_quotations()
        results = []
        total_qty = 0

        for quotation in pending_quotations:
            source_db = quotation.get('SourceDB')
            quotation_number = quotation.get('QuotationNumber')
            dop1 = quotation.get('Dop1')

            if not source_db or not dop1:
                continue

            try:
                quotation_id = int(dop1)
            except (ValueError, TypeError):
                continue

            store = pg_manager.get_store_by_nickname(source_db)
            if not store:
                results.append({
                    'source_db': source_db,
                    'quotation_number': quotation_number,
                    'qty_ordered': None,
                    'store_configured': False,
                    'error': 'Store not configured'
                })
                continue

            try:
                store_db = MSSQLManager(
                    server=store['server'],
                    database=store['database'],
                    user=store['username'],
                    password=store['password']
                )
                product = store_db.get_product_in_quotation(quotation_id, upc)
                if product and product.get('Qty'):
                    qty = float(product['Qty'])
                    results.append({
                        'source_db': source_db,
                        'quotation_number': quotation_number,
                        'qty_ordered': qty,
                        'store_configured': True
                    })
                    total_qty += qty
            except Exception as e:
                results.append({
                    'source_db': source_db,
                    'quotation_number': quotation_number,
                    'qty_ordered': None,
                    'store_configured': True,
                    'error': str(e)
                })

        return jsonify({
            'quotations': results,
            'total_qty': total_qty
        })
    except Exception as e:
        return jsonify({'error': f'Failed to get quotations: {str(e)}'}), 500


@app.route('/api/product/purchase-orders')
@login_required
def api_product_purchase_orders():
    """Get pending purchase orders containing this product"""
    upc = request.args.get('upc', '').strip()

    if not upc:
        return jsonify({'error': 'UPC is required'}), 400

    store_db = get_primary_store_db()
    if not store_db:
        return jsonify({'error': 'Primary store not configured'}), 503

    try:
        pending_pos = store_db.get_pending_purchase_orders()
        results = []
        total_qty = 0

        for po in pending_pos:
            po_id = po.get('PoID')
            po_number = po.get('PoNumber')

            if not po_id:
                continue

            try:
                product = store_db.get_product_in_purchase_order(po_id, upc)
                if product and product.get('QtyOrdered'):
                    qty = float(product['QtyOrdered'])
                    results.append({
                        'po_number': po_number,
                        'qty_ordered': qty
                    })
                    total_qty += qty
            except Exception as e:
                results.append({
                    'po_number': po_number,
                    'qty_ordered': None,
                    'error': str(e)
                })

        return jsonify({
            'purchase_orders': results,
            'total_qty': total_qty
        })
    except Exception as e:
        return jsonify({'error': f'Failed to get purchase orders: {str(e)}'}), 500


@app.route('/api/product/bin-locations')
@login_required
def api_product_bin_locations():
    """Get total quantity in bin locations for this product"""
    upc = request.args.get('upc', '').strip()

    if not upc:
        return jsonify({'error': 'UPC is required'}), 400

    store_db = get_primary_store_db()
    if not store_db:
        return jsonify({'error': 'Primary store not configured'}), 503

    try:
        result = store_db.get_bin_locations_total(upc)
        total_qty = float(result.get('total_qty') or 0) if result else 0

        return jsonify({
            'total_qty': total_qty
        })
    except Exception as e:
        return jsonify({'error': f'Failed to get bin locations: {str(e)}'}), 500


# ==================== CONFIG API ====================

@app.route('/api/config/status')
def api_config_status():
    """Check if Admin DB and primary store are configured"""
    admin_config = pg_manager.get_admin_db_config()
    primary_store = pg_manager.get_primary_store()
    return jsonify({
        'admin_db_configured': admin_config is not None and bool(admin_config.get('server')),
        'primary_store_configured': primary_store is not None
    })


@app.route('/api/config/admin-db', methods=['GET'])
def api_get_admin_db_config():
    """Get Admin DB config (without password)"""
    config = pg_manager.get_admin_db_config()
    if config:
        config.pop('password', None)
    return jsonify({'config': config})


@app.route('/api/config/admin-db', methods=['POST'])
def api_save_admin_db_config():
    """Save Admin DB config"""
    data = request.get_json()
    try:
        pg_manager.save_admin_db_config(
            server=data.get('server'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Failed to save config: {str(e)}'}), 500


@app.route('/api/config/test-admin-db', methods=['POST'])
def api_test_admin_db():
    """Test Admin DB connection"""
    data = request.get_json()
    server = data.get('server', '').strip()
    database = data.get('database', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    print(f"DEBUG - Received server: '{server}'")
    print(f"DEBUG - Server repr: {repr(server)}")

    if not all([server, database, username]):
        return jsonify({'success': False, 'error': 'Server, database, and username are required'}), 400

    try:
        manager = MSSQLManager(
            server=server,
            database=database,
            user=username,
            password=password
        )
        manager.test_connection()
        return jsonify({'success': True, 'message': 'Connection successful'})
    except Exception as e:
        import traceback
        print(f"MSSQL Connection Error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/config/stores', methods=['GET'])
def api_get_stores():
    """Get all store connections"""
    stores = pg_manager.get_all_stores()
    # Remove passwords from response
    for store in stores:
        store.pop('password', None)
    return jsonify({'stores': stores})


@app.route('/api/config/stores', methods=['POST'])
def api_add_store():
    """Add new store connection"""
    data = request.get_json()
    try:
        store_id = pg_manager.add_store(
            nickname=data.get('nickname'),
            server=data.get('server'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password'),
            is_primary=data.get('is_primary', False)
        )
        return jsonify({'success': True, 'id': store_id})
    except Exception as e:
        return jsonify({'error': f'Failed to add store: {str(e)}'}), 500


@app.route('/api/config/stores/<int:store_id>', methods=['PUT'])
def api_update_store(store_id):
    """Update store connection"""
    data = request.get_json()
    try:
        pg_manager.update_store(
            store_id=store_id,
            nickname=data.get('nickname'),
            server=data.get('server'),
            database=data.get('database'),
            username=data.get('username'),
            password=data.get('password'),
            is_primary=data.get('is_primary'),
            is_active=data.get('is_active')
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Failed to update store: {str(e)}'}), 500


@app.route('/api/config/stores/<int:store_id>', methods=['DELETE'])
def api_delete_store(store_id):
    """Delete store connection"""
    try:
        pg_manager.delete_store(store_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Failed to delete store: {str(e)}'}), 500


@app.route('/api/config/stores/<int:store_id>/test', methods=['POST'])
def api_test_store(store_id):
    """Test specific store connection"""
    store = pg_manager.get_store_by_id(store_id)
    if not store:
        return jsonify({'error': 'Store not found'}), 404

    try:
        manager = MSSQLManager(
            server=store['server'],
            database=store['database'],
            user=store['username'],
            password=store['password']
        )
        manager.test_connection()
        return jsonify({'success': True, 'message': 'Connection successful'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/config/stores/<int:store_id>/set-primary', methods=['POST'])
def api_set_primary_store(store_id):
    """Set a store as primary"""
    try:
        pg_manager.set_primary_store(store_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Failed to set primary store: {str(e)}'}), 500


# ==================== SETTINGS API ====================

@app.route('/api/config/settings/quantity-threshold', methods=['GET'])
def api_get_quantity_threshold():
    """Get quantity threshold setting"""
    setting = pg_manager.get_setting('quantity_threshold')
    threshold = float(setting['value']) if setting else 10
    return jsonify({'threshold': threshold})


@app.route('/api/config/settings/quantity-threshold', methods=['POST'])
def api_save_quantity_threshold():
    """Save quantity threshold setting"""
    data = request.get_json()
    threshold = data.get('threshold')

    if threshold is None:
        return jsonify({'error': 'Threshold value is required'}), 400

    try:
        threshold = float(threshold)
        if threshold < 0:
            return jsonify({'error': 'Threshold must be a non-negative number'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid threshold value'}), 400

    try:
        pg_manager.save_setting('quantity_threshold', threshold)
        return jsonify({'success': True, 'threshold': threshold})
    except Exception as e:
        return jsonify({'error': f'Failed to save threshold: {str(e)}'}), 500


@app.route('/api/product/check-difference', methods=['POST'])
@login_required
def api_check_difference():
    """Check if quantity difference exceeds threshold (before updating)"""
    data = request.get_json()
    product_id = data.get('product_id')
    user_entered_qty = data.get('new_quantity')
    quotations_qty = data.get('quotations_qty', 0) or 0
    top_bins_qty = data.get('top_bins_qty', 0) or 0

    if product_id is None:
        return jsonify({'error': 'Product ID is required'}), 400
    if user_entered_qty is None:
        return jsonify({'error': 'New quantity is required'}), 400

    try:
        user_entered_qty = float(user_entered_qty)
        quotations_qty = float(quotations_qty)
        top_bins_qty = float(top_bins_qty)
    except ValueError:
        return jsonify({'error': 'Invalid quantity value'}), 400

    # Calculate final quantity: user entered + quotations + top bins
    final_qty = user_entered_qty + quotations_qty + top_bins_qty

    store_db = get_primary_store_db()
    if not store_db:
        return jsonify({'error': 'Primary store not configured'}), 503

    try:
        # Get current product info
        product = store_db.get_product_by_id(product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        old_quantity = product['QuantOnHand'] or 0
        difference = final_qty - old_quantity

        # Get threshold setting
        setting = pg_manager.get_setting('quantity_threshold')
        threshold = float(setting['value']) if setting else 10

        # Check if difference exceeds threshold (absolute value)
        exceeds_threshold = abs(difference) > threshold

        return jsonify({
            'old_quantity': old_quantity,
            'final_qty': final_qty,
            'difference': difference,
            'threshold': threshold,
            'exceeds_threshold': exceeds_threshold
        })
    except Exception as e:
        return jsonify({'error': f'Check failed: {str(e)}'}), 500


# ==================== HEALTH CHECK ====================

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': get_current_time().isoformat()
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5557, debug=True)
