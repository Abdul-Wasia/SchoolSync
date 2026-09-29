from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
import random
from database.connection import query, hash_password, check_password

auth_bp = Blueprint('auth', __name__)

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
        from app import login_attempts

        if login_attempts.get(ip, 0) >= 5:
            flash('Too many failed attempts. Try again in 15 minutes.', 'danger')
            return render_template('auth/login.html')

        user = query(
            "SELECT * FROM users WHERE username = %s AND is_active = 1",
            (username,),
            fetch_one=True
        )

        valid = bool(user and check_password(password, user['password']))
        if valid:
            login_attempts.pop(ip, None)
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
            login_attempts[ip] = login_attempts.get(ip, 0) + 1
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
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
            # Generate 6-digit OTP
            otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            expires_at = datetime.now() + timedelta(minutes=10)
            
            # Invalidate old OTPs for this email
            query(
                "UPDATE otp_codes SET is_used = 1 WHERE email = %s AND is_used = 0",
                (email,)
            )
            
            # Insert new OTP
            query(
                "INSERT INTO otp_codes (email, code, expires_at) VALUES (%s, %s, %s)",
                (email, otp, expires_at)
            )
            
            session['reset_email'] = email
            flash(f'OTP sent to {email}. For development: Your OTP is {otp}', 'info')
            return redirect(url_for('auth.verify_otp'))
        else:
            flash('No active account found with this email.', 'danger')
    
    return render_template('auth/forgot_password.html')

@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        flash('Please request a password reset first.', 'warning')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        code = request.form.get('otp', '').strip()
        
        otp_record = query(
            """SELECT * FROM otp_codes 
               WHERE email = %s AND code = %s AND is_used = 0 AND expires_at > NOW()
               ORDER BY created_at DESC LIMIT 1""",
            (session['reset_email'], code),
            fetch_one=True
        )
        
        if otp_record:
            query(
                "UPDATE otp_codes SET is_used = 1 WHERE id = %s",
                (otp_record['id'],)
            )
            session['otp_verified'] = True
            flash('OTP verified successfully.', 'success')
            return redirect(url_for('auth.reset_password'))
        else:
            flash('Invalid or expired OTP.', 'danger')
    
    return render_template('auth/verify_otp.html')

@auth_bp.route('/resend-otp')
def resend_otp():
    if 'reset_email' not in session:
        return redirect(url_for('auth.forgot_password'))
    
    email = session['reset_email']
    otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    expires_at = datetime.now() + timedelta(minutes=10)
    
    query(
        "UPDATE otp_codes SET is_used = 1 WHERE email = %s AND is_used = 0",
        (email,)
    )
    query(
        "INSERT INTO otp_codes (email, code, expires_at) VALUES (%s, %s, %s)",
        (email, otp, expires_at)
    )
    
    flash(f'New OTP sent. For development: Your OTP is {otp}', 'info')
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
        "SELECT id, username, user_type, email, created_at, last_login FROM users WHERE id = %s",
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