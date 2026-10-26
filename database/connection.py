import mysql.connector
from mysql.connector import Error
import bcrypt
import logging
from datetime import datetime
from config import Config

logger = logging.getLogger(__name__)

def hash_password(plain):
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def check_password(plain, hashed):
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except:
        return plain == hashed

def get_db():
    """Create and return a MySQL database connection."""
    try:
        conn = mysql.connector.connect(
            host=Config.DB_HOST,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            autocommit=False
        )
        return conn
    except Error as error:
        logger.error("Database connection failed (%s)", type(error).__name__)
        return None

def query(sql, params=None, fetch=False, fetch_one=False):
    """
    Execute a SQL query.

    Args:
        sql: SQL query string
        params: Query parameters (tuple or list)
        fetch: If True, return all rows as list of dicts
        fetch_one: If True, return single row as dict

    Returns:
        - fetch=True: list of dicts (empty list on error)
        - fetch_one=True: single dict or None
        - default: lastrowid for INSERT/UPDATE
    """
    conn = get_db()
    if not conn:
        return [] if fetch else (None if fetch_one else 0)

    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute(sql, params or ())

        if fetch:
            result = cursor.fetchall()
            return result if result else []
        elif fetch_one:
            result = cursor.fetchone()
            return result if result else None
        else:
            conn.commit()
            return cursor.lastrowid

    except Error as error:
        logger.error("Database query failed (%s)", type(error).__name__)
        conn.rollback()
        return [] if fetch else (None if fetch_one else 0)
    finally:
        cursor.close()
        conn.close()

_raw_query = query

def transaction(queries, require_affected_rows=False):
    """
    Execute multiple queries in a single transaction.

    Args:
        queries: List of (sql, params) tuples

    Returns:
        True if successful, False otherwise
    """
    conn = get_db()
    if not conn:
        return False

    cursor = conn.cursor(dictionary=True)
    try:
        for sql, params in queries:
            cursor.execute(sql, params or ())
            if require_affected_rows and cursor.rowcount != 1:
                raise ValueError('A transaction statement did not affect exactly one row.')
        conn.commit()
        return True
    except (Error, ValueError) as error:
        logger.error("Database transaction failed (%s)", type(error).__name__)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def transaction_with_insert_id(queries, require_affected_rows=False):
    """Run dependent writes atomically and return the first insert's ID."""
    conn = get_db()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)
    inserted_id = None
    try:
        for sql, params in queries:
            if callable(params):
                params = params(inserted_id)
            cursor.execute(sql, params or ())
            if require_affected_rows and cursor.rowcount != 1:
                raise ValueError('A transaction statement did not affect exactly one row.')
            if inserted_id is None:
                inserted_id = cursor.lastrowid
        if not inserted_id:
            raise ValueError('The first transaction statement must insert a row.')
        conn.commit()
        return inserted_id
    except (Error, ValueError) as error:
        logger.error("Database transaction failed (%s)", type(error).__name__)
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def format_time(val):
    """Format a time value (timedelta, time, string, or None) to 'HH:MM' string."""
    if val is None or val == '':
        return ''
    if isinstance(val, str):
        return val[:5]
    if hasattr(val, 'strftime'):
        return val.strftime('%H:%M')
    if hasattr(val, 'total_seconds'):
        total_seconds = int(val.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    return str(val)[:5]

def normalize_month_key(val):
    """Convert month representations (e.g. 'Oct 2026', '2026-10') to 7-char 'YYYY-MM' key."""
    if not val:
        return datetime.now().strftime('%Y-%m')
    val_str = str(val).strip()
    if len(val_str) == 7 and val_str[:4].isdigit() and val_str[4] == '-' and val_str[5:7].isdigit():
        return val_str
    for fmt in ('%b %Y', '%B %Y', '%Y-%m', '%m/%Y', '%b %y', '%Y/%m'):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.strftime('%Y-%m')
        except ValueError:
            continue
    return val_str[:7]