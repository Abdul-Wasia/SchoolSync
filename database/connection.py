import mysql.connector
from mysql.connector import Error
import bcrypt
from config import Config

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
    except Error as e:
        print(f"Database connection error: {e}")
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
    
    cursor = conn.cursor(dictionary=True)
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
            
    except Error as e:
        print(f"SQL Error: {e}")
        print(f"Query: {sql}")
        print(f"Params: {params}")
        conn.rollback()
        return [] if fetch else (None if fetch_one else 0)
    finally:
        cursor.close()
        conn.close()

def transaction(queries):
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
        conn.commit()
        return True
    except Error as e:
        print(f"Transaction Error: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS