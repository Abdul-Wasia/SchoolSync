from flask import Flask, render_template, session, request, jsonify, redirect, url_for, flash, Response, abort
import os
import datetime
import csv
import io
from pathlib import Path
from datetime import timedelta
from config import Config
from database.connection import query, format_time
from routes.auth_routes import login_required

# Import blueprints
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.fa_routes import fa_bp
from routes.teacher_routes import teacher_bp
from routes.student_routes import student_bp
from routes.principal_routes import principal_bp
from routes.gr_routes import gr_bp
from routes.admission_routes import admission_bp
from routes.ai_routes import ai_bp
from routes.document_routes import documents_bp, build_whatsapp_link
from routes.notice_routes import notice_bp
from routes.calendar_routes import calendar_bp
from security.csrf import get_csrf_token, protect_state_changing_request

app = Flask(__name__)
app.config.from_object(Config)

# Ensure new tables exist
def ensure_schema():
    required_sql = [
        """CREATE TABLE IF NOT EXISTS course_materials (
            id INT PRIMARY KEY AUTO_INCREMENT,
            teacher_id INT NOT NULL,
            subject_id INT NOT NULL,
            section_id INT NOT NULL,
            title VARCHAR(200) NOT NULL,
            description TEXT,
            material_type ENUM('PDF','Video','Link','Notes','Slides') DEFAULT 'PDF',
            file_path VARCHAR(255),
            external_url VARCHAR(500),
            ai_summary TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (section_id) REFERENCES sections(id)
        )""",
        """CREATE TABLE IF NOT EXISTS leave_applications (
            id INT PRIMARY KEY AUTO_INCREMENT,
            student_id INT NOT NULL,
            teacher_id INT,
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            reason TEXT NOT NULL,
            status ENUM('Pending','Approved','Rejected') DEFAULT 'Pending',
            reviewed_by INT,
            reviewed_at TIMESTAMP NULL,
            response_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (teacher_id) REFERENCES teachers(id)
        )""",
        """CREATE TABLE IF NOT EXISTS exam_schedule (
            id INT PRIMARY KEY AUTO_INCREMENT,
            subject_id INT NOT NULL,
            grade_id INT NOT NULL,
            exam_type ENUM('Quiz','Mid-Term','Final-Term','Assignment') DEFAULT 'Quiz',
            exam_date DATE NOT NULL,
            start_time TIME,
            end_time TIME,
            room VARCHAR(50),
            created_by INT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (grade_id) REFERENCES grades(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )""",
        """CREATE TABLE IF NOT EXISTS fee_structure (
            id INT PRIMARY KEY AUTO_INCREMENT,
            grade_id INT NOT NULL,
            month_year VARCHAR(20) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_fee_structure (grade_id, month_year),
            FOREIGN KEY (grade_id) REFERENCES grades(id)
        )""",
        """CREATE TABLE IF NOT EXISTS student_fees (
            id INT PRIMARY KEY AUTO_INCREMENT,
            student_id INT NOT NULL,
            month_year VARCHAR(20) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            status ENUM('Pending','Paid') DEFAULT 'Pending',
            marked_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_student_fee (student_id, month_year),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )"""
    ]
    for statement in required_sql:
        query(statement)

    if not query("SHOW COLUMNS FROM submissions LIKE 'feedback'", fetch_one=True):
        query("ALTER TABLE submissions ADD COLUMN feedback TEXT NULL AFTER marks_obtained")

    migration_path = Path(__file__).resolve().parent / 'database' / 'migrations' / '002_admission_portal.sql'
    migration_sql = migration_path.read_text(encoding='utf-8')
    migration_sql = '\n'.join(
        line for line in migration_sql.splitlines()
        if not line.lstrip().startswith('--')
    )
    migration_statements = [
        statement.strip()
        for statement in migration_sql.split(';')
        if statement.strip()
    ]
    for statement in migration_statements:
        query(statement)

    # Apply 003 real-world enhancements migration
    mig_003_path = Path(__file__).resolve().parent / 'database' / 'migrations' / '003_realworld_enhancements.sql'
    if mig_003_path.exists():
        mig_003_sql = mig_003_path.read_text(encoding='utf-8')
        mig_003_sql = '\n'.join(
            line for line in mig_003_sql.splitlines()
            if not line.lstrip().startswith('--')
        )
        for statement in mig_003_sql.split(';'):
            if statement.strip():
                query(statement.strip())

    # Add emergency and health columns to students if missing
    student_cols = [
        ('blood_group', 'VARCHAR(10) NULL AFTER gender'),
        ('emergency_contact_name', 'VARCHAR(100) NULL AFTER parent_contact'),
        ('emergency_contact_phone', 'VARCHAR(20) NULL AFTER emergency_contact_name'),
        ('emergency_relation', 'VARCHAR(50) NULL AFTER emergency_contact_phone'),
        ('medical_notes', 'TEXT NULL AFTER emergency_relation')
    ]
    for col_name, col_def in student_cols:
        if not query(f"SHOW COLUMNS FROM students LIKE '{col_name}'", fetch_one=True):
            query(f"ALTER TABLE students ADD COLUMN {col_name} {col_def}")

    # Add priority and category to announcements if missing
    ann_cols = [
        ('priority', "ENUM('Normal','High','Urgent') NOT NULL DEFAULT 'Normal' AFTER target_role"),
        ('category', "VARCHAR(50) NOT NULL DEFAULT 'General' AFTER priority")
    ]
    for col_name, col_def in ann_cols:
        if not query(f"SHOW COLUMNS FROM announcements LIKE '{col_name}'", fetch_one=True):
            query(f"ALTER TABLE announcements ADD COLUMN {col_name} {col_def}")

ensure_schema()

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(fa_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(student_bp)
app.register_blueprint(principal_bp)
app.register_blueprint(gr_bp)
app.register_blueprint(admission_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(documents_bp)
app.register_blueprint(notice_bp)
app.register_blueprint(calendar_bp)

@app.template_filter('format_time')
def template_format_time(val):
    return format_time(val)

@app.template_filter('wa_link')
def template_whatsapp_link(phone, message=''):
    return build_whatsapp_link(phone, message)

# Also expose as a callable global so templates may use wa_link(phone, message)
app.jinja_env.globals['wa_link'] = build_whatsapp_link

@app.before_request
def enforce_csrf_protection():
    return protect_state_changing_request()

@app.context_processor
def inject_csrf_token():
    return {'csrf_token': get_csrf_token}

@app.before_request
def check_session_timeout():
    static_file_path = None
    if request.endpoint == 'static' and request.view_args:
        static_filename = request.view_args.get('filename', '')
        static_file_path = os.path.realpath(os.path.join(app.static_folder, static_filename))
        for protected_folder in ('assignments', 'documents', 'materials'):
            protected_root = os.path.realpath(os.path.join(app.static_folder, 'uploads', protected_folder))
            try:
                within_protected_root = (
                    os.path.commonpath([
                        os.path.normcase(protected_root),
                        os.path.normcase(static_file_path),
                    ]) == os.path.normcase(protected_root)
                )
            except ValueError:
                within_protected_root = False
            if within_protected_root:
                abort(404)

        submissions_root = os.path.realpath(os.path.join(app.static_folder, 'uploads', 'submissions'))
        try:
            within_submissions_root = (
                os.path.commonpath([
                    os.path.normcase(submissions_root),
                    os.path.normcase(static_file_path),
                ]) == os.path.normcase(submissions_root)
            )
        except ValueError:
            within_submissions_root = False
    else:
        within_submissions_root = False

    if within_submissions_root:
        if 'user_id' not in session:
            abort(403)

        filename = os.path.relpath(static_file_path, submissions_root)
        if filename == os.pardir or filename.startswith(os.pardir + os.sep) or os.path.isabs(filename):
            abort(404)
        relative_path = 'uploads/submissions/' + filename.replace(os.sep, '/')

        user_type = session.get('user_type')
        if user_type == 'Teacher':
            teacher = query(
                "SELECT id FROM teachers WHERE user_id = %s",
                (session.get('user_id'),),
                fetch_one=True
            )
            if not teacher:
                abort(403)
            authorized_file = query(
                """SELECT sub.id
                   FROM submissions sub
                   JOIN assignments a ON a.id = sub.assignment_id
                   JOIN students stu ON stu.id = sub.student_id
                   JOIN assignment_sections acs ON acs.assignment_id = a.id
                       AND acs.section_id = stu.section_id
                   JOIN subject_teachers st ON st.subject_id = a.subject_id
                       AND st.section_id = stu.section_id AND st.teacher_id = a.teacher_id
                   WHERE sub.file_path = %s AND a.teacher_id = %s AND st.teacher_id = %s
                   LIMIT 1""",
                (relative_path, teacher['id'], teacher['id']),
                fetch_one=True
            )
            if not authorized_file:
                abort(403)
        elif user_type == 'Student':
            student = query(
                "SELECT id FROM students WHERE user_id = %s",
                (session.get('user_id'),),
                fetch_one=True
            )
            if not student:
                abort(403)
            authorized_file = query(
                """SELECT id FROM submissions
                   WHERE file_path = %s AND student_id = %s
                   LIMIT 1""",
                (relative_path, student['id']),
                fetch_one=True
            )
            if not authorized_file:
                abort(403)
        else:
            abort(403)

    if 'user_id' in session:
        last_active = session.get('last_active')
        if last_active:
            diff = datetime.datetime.now() - datetime.datetime.fromisoformat(last_active)
            if diff > timedelta(minutes=30):
                session.clear()
                flash('Session expired due to inactivity. Please login again.', 'warning')
                return redirect(url_for('auth.login'))
        session['last_active'] = datetime.datetime.now().isoformat()

# Context processor
@app.context_processor
def inject_globals():
    def subject_color(name):
        name = name.lower() if name else ''
        if 'math' in name:
            return 'linear-gradient(135deg, #3b82f6, #1d4ed8)'
        elif 'computer' in name or 'cs' in name or 'programming' in name:
            return 'linear-gradient(135deg, #22c55e, #16a34a)'
        elif 'english' in name:
            return 'linear-gradient(135deg, #a855f7, #9333ea)'
        elif 'physics' in name:
            return 'linear-gradient(135deg, #f97316, #ea580c)'
        elif 'urdu' in name:
            return 'linear-gradient(135deg, #ec4899, #db2777)'
        elif 'chemistry' in name:
            return 'linear-gradient(135deg, #06b6d4, #0891b2)'
        elif 'biology' in name:
            return 'linear-gradient(135deg, #84cc16, #65a30d)'
        elif 'science' in name:
            return 'linear-gradient(135deg, #14b8a6, #0d9488)'
        else:
            return 'linear-gradient(135deg, #64748b, #475569)'

    unread_count = 0
    if 'user_id' in session:
        try:
            notif_res = query(
                "SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = 0",
                (session['user_id'],),
                fetch_one=True
            )
            if isinstance(notif_res, dict) and notif_res.get('count') is not None:
                unread_count = int(notif_res['count'])
            else:
                unread_count = 0
        except (TypeError, ValueError, AttributeError, Exception):
            unread_count = 0

    return {
        'unread_count': unread_count,
        'now': datetime.datetime.now(),
        'session': session,
        'subjectColor': subject_color,
        'format_time': format_time
    }

# Notification API routes
@app.route('/notifications')
def get_notifications():
    if 'user_id' not in session:
        return jsonify([])

    notifications = query(
        "SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
        (session['user_id'],),
        fetch=True
    )
    return jsonify(notifications)

@app.route('/notifications/read/<int:notif_id>', methods=['POST'])
@login_required()
def mark_notification_read(notif_id):
    if 'user_id' not in session:
        return jsonify({'success': False})

    query(
        "UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s",
        (notif_id, session['user_id'])
    )
    return jsonify({'success': True})

@app.route('/notifications/read-all', methods=['POST'])
@login_required()
def mark_all_read():
    if 'user_id' not in session:
        return jsonify({'success': False})

    query(
        "UPDATE notifications SET is_read = 1 WHERE user_id = %s",
        (session['user_id'],)
    )
    return jsonify({'success': True})

# ===== CASCADING DROPDOWN API =====
@app.route('/api/grades')
def api_grades():
    grades = query("SELECT id, name FROM grades ORDER BY name", fetch=True)
    return jsonify(grades)

@app.route('/api/sections/<int:grade_id>')
def api_sections_by_grade(grade_id):
    sections = query(
        "SELECT id, name FROM sections WHERE grade_id = %s ORDER BY name",
        (grade_id,),
        fetch=True
    )
    return jsonify(sections)

@app.route('/api/subjects/<int:grade_id>')
def api_subjects_by_grade(grade_id):
    subjects = query(
        "SELECT id, subject_name FROM subjects WHERE grade_id = %s ORDER BY subject_name",
        (grade_id,),
        fetch=True
    )
    return jsonify(subjects)

@app.route('/export/attendance/<int:section_id>/<date>')
@login_required(['IT_Admin','FA','Principal'])
def export_attendance_csv(section_id, date):
    records = query("""
        SELECT s.roll_number, s.name, a.status, a.marked_at
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        WHERE a.section_id=%s AND a.date=%s
        ORDER BY s.roll_number
    """, (section_id, date), fetch=True)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll No','Student Name','Status','Marked At'])
    for r in (records or []):
        writer.writerow([r['roll_number'], r['name'], r['status'], r['marked_at']])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=attendance_{date}.csv'}
    )

@app.route('/export/results/<int:student_id>')
@login_required(['Student'])
def export_results_csv(student_id):
    student = query(
        "SELECT id, status FROM students WHERE user_id = %s",
        (session['user_id'],),
        fetch_one=True
    )
    if not student or student['id'] != student_id or student['status'] == 'PendingLogin':
        abort(403)

    results = query("""
        SELECT sub.subject_name, r.exam_type, r.marks_obtained,
               r.total_marks, r.grade, r.exam_date
        FROM results r JOIN subjects sub ON r.subject_id=sub.id
        WHERE r.student_id=%s ORDER BY sub.subject_name
    """, (student_id,), fetch=True)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Subject','Exam Type','Marks','Total','Grade','Date'])
    for r in (results or []):
        writer.writerow([r['subject_name'], r['exam_type'], r['marks_obtained'], r['total_marks'], r['grade'], r['exam_date']])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=results.csv'})

# Root redirect
@app.route('/')
def index():
    if 'user_id' in session:
        redirects = {
            'IT_Admin': 'admin.dashboard',
            'GR_Office': 'gr.dashboard',
            'Principal': 'principal.dashboard',
            'FA': 'fa.dashboard',
            'Teacher': 'teacher.dashboard',
            'Student': 'student.dashboard'
        }
        return redirect(url_for(redirects.get(session['user_type'], 'auth.login')))
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    app.run(debug=app.config.get('DEBUG', False), host='127.0.0.1', port=5000)