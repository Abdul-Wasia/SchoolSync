from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import hashlib
import secrets
import threading
import time
from collections import deque
from database.connection import query, hash_password, check_password

auth_bp = Blueprint('auth', __name__)


OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 30
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_login_failures = {}
_login_failures_lock = threading.Lock()


def login_is_throttled(ip_address, now=None):
    now = time.monotonic() if now is None else now
    cutoff = now - LOGIN_FAILURE_WINDOW_SECONDS
    with _login_failures_lock:
        failures = _login_failures.get(ip_address)
        if not failures:
            return False
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            _login_failures.pop(ip_address, None)
            return False
        return len(failures) >= LOGIN_FAILURE_LIMIT


def record_login_failure(ip_address, now=None):
    now = time.monotonic() if now is None else now
    cutoff = now - LOGIN_FAILURE_WINDOW_SECONDS
    with _login_failures_lock:
        if len(_login_failures) > 10000 and ip_address not in _login_failures:
            for address, failures in list(_login_failures.items()):
                while failures and failures[0] <= cutoff:
                    failures.popleft()
                if not failures:
                    _login_failures.pop(address, None)
        failures = _login_failures.setdefault(ip_address, deque())
        while failures and failures[0] <= cutoff:
            failures.popleft()
        failures.append(now)


def clear_login_failures(ip_address):
    with _login_failures_lock:
        _login_failures.pop(ip_address, None)


def generate_otp(length=6):
    return ''.join(secrets.choice('0123456789') for _ in range(length))


def hash_otp_code(code):
    return hashlib.sha256(str(code).strip().encode('utf-8')).hexdigest()


def can_resend_otp():
    last_sent = session.get('otp_last_sent_at')
    if not last_sent:
        return True
    return (datetime.now() - datetime.fromisoformat(last_sent)).total_seconds() >= OTP_RESEND_COOLDOWN_SECONDS


def get_otp_attempts():
    return int(session.get('otp_attempts', 0))


def increment_otp_attempts():
    session['otp_attempts'] = get_otp_attempts() + 1
    return session['otp_attempts']


def reset_otp_session_state():
    for key in ('otp_verified', 'otp_attempts', 'otp_last_sent_at'):
        session.pop(key, None)

def login_required(allowed_roles=None):
    """Decorator to require login and optionally check role."""
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            if allowed_roles and session.get('user_type') not in allowed_roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_activity(user_id, action, details=None):
    """Log user activity."""
    ip = request.remote_addr if request else 'unknown'
    query(
        "INSERT INTO activity_log (user_id, action, details, ip_address) VALUES (%s, %s, %s, %s)",
        (user_id, action, details, ip)
    )

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ip = request.remote_addr
        if login_is_throttled(ip):
            flash('Too many failed attempts. Try again in 15 minutes.', 'danger')
            return render_template('auth/login.html')

        user = query(
            "SELECT * FROM users WHERE username = %s AND is_active = 1",
            (username,),
            fetch_one=True
        )

        valid = bool(user and check_password(password, user['password']))
        if valid:
            clear_login_failures(ip)
            if user['password'] and not user['password'].startswith('$2b$'):
                new_hash = hash_password(password)
                query("UPDATE users SET password = %s WHERE id = %s", (new_hash, user['id']))

            prev_login = query(
                "SELECT last_login FROM users WHERE id = %s",
                (user['id'],),
                fetch_one=True
            )
            last_login_val = prev_login['last_login'] if prev_login and prev_login.get('last_login') else None

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_type'] = user['user_type']
            session['email'] = user.get('email', '')
            session['last_login'] = last_login_val
            session['last_active'] = datetime.now().isoformat()

            query(
                "UPDATE users SET last_login = NOW() WHERE id = %s",
                (user['id'],)
            )
            log_activity(user['id'], 'LOGIN', f'User {username} logged in')

            redirects = {
                'IT_Admin': 'admin.dashboard',
                'GR_Office': 'gr.dashboard',
                'Principal': 'principal.dashboard',
                'FA': 'fa.dashboard',
                'Teacher': 'teacher.dashboard',
                'Student': 'student.dashboard'
            }
            return redirect(url_for(redirects.get(user['user_type'], 'auth.login')))
        else:
            record_login_failure(ip)
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'GET':
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return render_template('auth/logout.html')

    user_id = session.get('user_id')
    username = session.get('username')
    if user_id:
        log_activity(user_id, 'LOGOUT', f'User {username} logged out')
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        user = query(
            "SELECT id, username FROM users WHERE email = %s AND is_active = 1",
            (email,),
            fetch_one=True
        )

        if user:
            if not can_resend_otp():
                flash('Please wait a moment before requesting another OTP.', 'warning')
                return render_template('auth/forgot_password.html')

            otp = generate_otp()
            expires_at = datetime.now() + timedelta(minutes=10)
            otp_hash = hash_otp_code(otp)

            query(
                "UPDATE otp_codes SET is_used = 1 WHERE email = %s AND is_used = 0",
                (email,)
            )

            query(
                "INSERT INTO otp_codes (email, code, expires_at) VALUES (%s, %s, %s)",
                (email, otp_hash, expires_at)
            )

            session['reset_email'] = email
            session['otp_attempts'] = 0
            session['otp_last_sent_at'] = datetime.now().isoformat()
            flash('OTP sent to your email address. Please check your inbox.', 'info')
            return redirect(url_for('auth.verify_otp'))
        else:
            flash('No active account found with this email.', 'danger')
    
    return render_template('auth/forgot_password.html')

@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        flash('Please request a password reset first.', 'warning')
        return redirect(url_for('auth.forgot_password'))

    if get_otp_attempts() >= OTP_MAX_ATTEMPTS:
        session['otp_verified'] = False
        flash('Too many invalid OTP attempts. Please request a new code.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        code = request.form.get('otp', '').strip()

        otp_record = query(
            """SELECT * FROM otp_codes
               WHERE email = %s AND is_used = 0 AND expires_at > NOW()
               ORDER BY created_at DESC LIMIT 1""",
            (session['reset_email'],),
            fetch_one=True
        )

        if not otp_record:
            flash('Invalid or expired OTP.', 'danger')
            return render_template('auth/verify_otp.html')

        stored_code = otp_record.get('code')
        matches = stored_code == hash_otp_code(code) or stored_code == code

        if matches:
            query(
                "UPDATE otp_codes SET is_used = 1 WHERE id = %s",
                (otp_record['id'],)
            )
            session['otp_verified'] = True
            session['otp_attempts'] = 0
            flash('OTP verified successfully.', 'success')
            return redirect(url_for('auth.reset_password'))

        attempts = increment_otp_attempts()
        if attempts >= OTP_MAX_ATTEMPTS:
            session['otp_verified'] = False
            flash('Too many invalid OTP attempts. Please request a new code.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        flash('Invalid or expired OTP.', 'danger')

    return render_template('auth/verify_otp.html')

@auth_bp.route('/resend-otp', methods=['POST'])
def resend_otp():
    if 'reset_email' not in session:
        return redirect(url_for('auth.forgot_password'))

    if not can_resend_otp():
        flash('Please wait a moment before requesting another OTP.', 'warning')
        return redirect(url_for('auth.verify_otp'))

    email = session['reset_email']
    otp = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=10)
    otp_hash = hash_otp_code(otp)

    query(
        "UPDATE otp_codes SET is_used = 1 WHERE email = %s AND is_used = 0",
        (email,)
    )
    query(
        "INSERT INTO otp_codes (email, code, expires_at) VALUES (%s, %s, %s)",
        (email, otp_hash, expires_at)
    )

    session['otp_attempts'] = 0
    session['otp_last_sent_at'] = datetime.now().isoformat()
    flash('A new OTP has been sent to your email address.', 'info')
    return redirect(url_for('auth.verify_otp'))

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or 'reset_email' not in session:
        flash('Please verify OTP first.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        else:
            query(
                "UPDATE users SET password = %s WHERE email = %s",
                (hash_password(password), session['reset_email'])
            )
            session.pop('otp_verified', None)
            session.pop('reset_email', None)
            flash('Password reset successful. Please log in.', 'success')
            return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html')

@auth_bp.route('/profile')
@login_required()
def profile():
    user = query(
        "SELECT id, username, user_type, email, is_active, created_at, last_login FROM users WHERE id = %s",
        (session['user_id'],),
        fetch_one=True
    )
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.login'))
    
    # Get role-specific info
    role_info = None
    if user['user_type'] == 'Student':
        role_info = query("SELECT * FROM students WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    elif user['user_type'] == 'Teacher':
        role_info = query("SELECT * FROM teachers WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    elif user['user_type'] == 'FA':
        role_info = query("SELECT * FROM fa WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    
    return render_template('profile.html', user=user, role_info=role_info)

@auth_bp.route('/change-password', methods=['POST'])
@login_required()
def change_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    user = query("SELECT password FROM users WHERE id = %s", (session['user_id'],), fetch_one=True)

    if not user or not check_password(current_password, user['password']):
        flash('Current password is incorrect.', 'danger')
    elif len(new_password) < 6:
        flash('New password must be at least 6 characters.', 'danger')
    elif new_password != confirm_password:
        flash('New passwords do not match.', 'danger')
    else:
        query(
            "UPDATE users SET password = %s WHERE id = %s",
            (hash_password(new_password), session['user_id'])
        )
        log_activity(session['user_id'], 'CHANGE_PASSWORD', 'User changed their password')
        flash('Password changed successfully.', 'success')

    return redirect(url_for('auth.profile'))