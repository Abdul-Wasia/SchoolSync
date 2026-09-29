from flask import Flask, render_template, session, request, jsonify, redirect, url_for, flash, Response
import os
import datetime
import csv
import io
from datetime import timedelta
from config import Config
from database.connection import query
from routes.auth_routes import login_required

login_attempts = {}

# Import blueprints
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.fa_routes import fa_bp
from routes.teacher_routes import teacher_bp
from routes.student_routes import student_bp
from routes.principal_routes import principal_bp
from routes.gr_routes import gr_bp
from routes.ai_routes import ai_bp

app = Flask(__name__)
app.config.from_object(Config)

# Create upload folders
for folder in ['documents', 'assignments', 'materials', 'submissions']:
    path = os.path.join(Config.UPLOAD_FOLDER, folder)
    os.makedirs(path, exist_ok=True)

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

ensure_schema()

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(fa_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(student_bp)
app.register_blueprint(principal_bp)
app.register_blueprint(gr_bp)
app.register_blueprint(ai_bp)

@app.before_request
def check_session_timeout():
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
        unread_count = query(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = 0",
            (session['user_id'],),
            fetch_one=True
        )['count'] if query("SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = 0", (session['user_id'],), fetch_one=True) else 0

    return {
        'unread_count': unread_count,
        'now': datetime.datetime.now(),
        'session': session,
        'subjectColor': subject_color
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
def mark_notification_read(notif_id):
    if 'user_id' not in session:
        return jsonify({'success': False})

    query(
        "UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s",
        (notif_id, session['user_id'])
    )
    return jsonify({'success': True})

@app.route('/notifications/read-all', methods=['POST'])
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
@login_required()
def export_results_csv(student_id):
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
    app.run(debug=True, host='0.0.0.0', port=5000)