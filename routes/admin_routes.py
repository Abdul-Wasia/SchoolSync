from flask import Blueprint, make_response, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, date
from database.connection import query, transaction, hash_password
from routes.auth_routes import login_required, log_activity

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@login_required(['IT_Admin'])
def dashboard():
    stats = {
        'students': query("SELECT COUNT(*) as count FROM students WHERE status = 'Active'", fetch_one=True)['count'],
        'teachers': query("SELECT COUNT(*) as count FROM teachers", fetch_one=True)['count'],
        'sections': query("SELECT COUNT(*) as count FROM sections", fetch_one=True)['count'],
        'pending': query("SELECT COUNT(*) as count FROM students WHERE status = 'PendingLogin'", fetch_one=True)['count']
    }
    
    recent_activity = query(
        """SELECT al.*, u.username 
           FROM activity_log al 
           JOIN users u ON al.user_id = u.id 
           ORDER BY al.logged_at DESC LIMIT 10""",
        fetch=True
    )
    
    pending_students = query(
        """SELECT s.*, sec.name as section_name, g.name as grade_name
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE s.status = 'PendingLogin'
           ORDER BY s.admission_date DESC""",
        fetch=True
    )
    
    return render_template('admin/dashboard.html', stats=stats, recent_activity=recent_activity, pending_students=pending_students)

def get_user_management_context():
    all_users = query(
        """SELECT u.*, 
              COALESCE(ia.name, gr.name, p.name, f.name, t.name, s.name) AS full_name,
              CASE
                  WHEN u.user_type = 'IT_Admin' THEN ia.role
                  WHEN u.user_type = 'Teacher' THEN t.subject
                  WHEN u.user_type = 'Student' THEN CONCAT(g.name, ' - ', sec.name)
                  ELSE NULL
              END AS role_info,
              s.status AS student_status
           FROM users u
           LEFT JOIN it_admins ia ON u.id = ia.user_id
           LEFT JOIN gr_office gr ON u.id = gr.user_id
           LEFT JOIN principals p ON u.id = p.user_id
           LEFT JOIN fa f ON u.id = f.user_id
           LEFT JOIN teachers t ON u.id = t.user_id
           LEFT JOIN students s ON u.id = s.user_id
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           ORDER BY u.created_at DESC""",
        fetch=True
    )
    sections = query(
        """SELECT sec.id, sec.name, g.name AS grade_name
           FROM sections sec JOIN grades g ON sec.grade_id = g.id
           ORDER BY g.name, sec.name""",
        fetch=True
    )
    return {'users': all_users or [], 'sections': sections or []}

@admin_bp.route('/users')
@login_required(['IT_Admin'])
def users():
    return render_template('admin/users.html', **get_user_management_context())

@admin_bp.route('/create-user', methods=['POST'])
@login_required(['IT_Admin'])
def create_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    user_type = request.form.get('user_type')
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    name = request.form.get('name', '').strip()
    
    if not all([username, password, user_type, name]):
        flash('All required fields must be filled.', 'danger')
        return redirect(url_for('admin.users'))
    
    # Check username exists
    if query("SELECT id FROM users WHERE username = %s", (username,), fetch_one=True):
        flash('Username already exists.', 'danger')
        return redirect(url_for('admin.users'))
    
    hashed = hash_password(password)
    queries = [
        ("INSERT INTO users (username, password, user_type, email, phone) VALUES (%s, %s, %s, %s, %s)",
         (username, hashed, user_type, email, phone))
    ]
    
    user_id = query(queries[0][0], queries[0][1])
    
    if not user_id:
        flash('Failed to create user.', 'danger')
        return redirect(url_for('admin.users'))
    
    # Insert into role-specific table
    role_queries = {
        'IT_Admin': ("INSERT INTO it_admins (user_id, name, phone, role) VALUES (%s, %s, %s, %s)", 
                     (user_id, name, phone, 'System Administrator')),
        'GR_Office': ("INSERT INTO gr_office (user_id, name, phone) VALUES (%s, %s, %s)", 
                      (user_id, name, phone)),
        'Principal': ("INSERT INTO principals (user_id, name, phone) VALUES (%s, %s, %s)", 
                      (user_id, name, phone)),
        'FA': ("INSERT INTO fa (user_id, name, phone) VALUES (%s, %s, %s)", 
               (user_id, name, phone)),
        'Teacher': ("INSERT INTO teachers (user_id, name, subject, qualification, phone, email, hire_date) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                    (user_id, name, request.form.get('subject', ''), request.form.get('qualification', ''), phone, email, request.form.get('hire_date', '') or None)),
        'Student': ("INSERT INTO students (user_id, student_system_id, name, father_name, section_id, roll_number, dob, gender, address, parent_contact, admission_date, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                    (user_id, f"SS-{datetime.now().year}-{user_id:04d}", name, request.form.get('father_name', ''), 
                     request.form.get('section_id') or None, request.form.get('roll_number', ''), 
                     request.form.get('dob') or None, request.form.get('gender'), 
                     request.form.get('address', ''), request.form.get('parent_contact', ''), 
                     datetime.now().date(), 'PendingLogin'))
    }
    
    if user_type in role_queries:
        q, p = role_queries[user_type]
        query(q, p)
        
        if user_type == 'Teacher':
            # Notify FA
            fa_users = query("SELECT user_id FROM fa", fetch=True)
            for fa in fa_users:
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (fa['user_id'], f'New teacher {name} added. Please assign courses.', 'info', url_for('fa.assign_courses'))
                )
        elif user_type == 'Student':
            # Notify IT Admin and GR Office
            for u in query("SELECT user_id FROM users WHERE user_type IN ('IT_Admin', 'GR_Office')", fetch=True):
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (u['user_id'], f'New student {name} enrolled. Login pending.', 'info', url_for('admin.users'))
                )
    
    log_activity(session['user_id'], 'CREATE_USER', f'Created {user_type}: {username}')
    flash(f'{user_type} created successfully.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/activate-student/<int:student_id>', methods=['POST'])
@login_required(['IT_Admin'])
def activate_student(student_id):
    student = query("SELECT * FROM students WHERE id = %s", (student_id,), fetch_one=True)
    if student:
        query("UPDATE students SET status = 'Active' WHERE id = %s", (student_id,))
        query("UPDATE users SET is_active = 1 WHERE id = %s", (student['user_id'],))
        
        # Notify GR Office
        gr_users = query("SELECT user_id FROM gr_office", fetch=True)
        for gr in gr_users:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (gr['user_id'], f'Login activated for student {student["name"]}', 'success', url_for('gr.dashboard'))
            )
        
        log_activity(session['user_id'], 'ACTIVATE_STUDENT', f'Activated student {student["name"]}')
        flash('Student activated successfully.', 'success')
    else:
        flash('Student not found.', 'danger')
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/toggle-user/<int:user_id>', methods=['POST'])
@login_required(['IT_Admin'])
def toggle_user(user_id):
    user = query("SELECT is_active FROM users WHERE id = %s", (user_id,), fetch_one=True)
    if user:
        new_status = 0 if user['is_active'] else 1
        query("UPDATE users SET is_active = %s WHERE id = %s", (new_status, user_id))
        log_activity(session['user_id'], 'TOGGLE_USER', f'User {user_id} set to {"active" if new_status else "inactive"}')
        flash('User status updated.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/reset-password/<int:user_id>', methods=['POST'])
@login_required(['IT_Admin'])
def reset_password(user_id):
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    user = query("SELECT id, username FROM users WHERE id = %s", (user_id,), fetch_one=True)

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users'))

    if len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.users'))
    if new_password != confirm_password:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('admin.users'))

    query("UPDATE users SET password = %s WHERE id = %s", (hash_password(new_password), user_id))
    log_activity(session['user_id'], 'RESET_PASSWORD', f'Reset password for user {user_id}')
    flash('Password reset. Share the temporary password with the user and ask them to change it after signing in.', 'success')
    response = make_response(render_template(
        'admin/users.html',
        **get_user_management_context(),
        temporary_password=new_password,
        temporary_password_username=user['username']
    ))
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@admin_bp.route('/grades-sections')
@login_required(['IT_Admin'])
def grades_sections():
    grades = query(
        """SELECT g.*, COUNT(s.id) as section_count,
              (SELECT COUNT(*) FROM students st JOIN sections se ON st.section_id = se.id WHERE se.grade_id = g.id) as student_count
           FROM grades g
           LEFT JOIN sections s ON g.id = s.grade_id
           GROUP BY g.id
           ORDER BY g.name""",
        fetch=True
    )
    
    sections = query(
        """SELECT s.*, g.name as grade_name,
              (SELECT COUNT(*) FROM students st WHERE st.section_id = s.id) as student_count
           FROM sections s
           JOIN grades g ON s.grade_id = g.id
           ORDER BY g.name, s.name""",
        fetch=True
    )
    
    return render_template('admin/grades_sections.html', grades=grades, sections=sections)

@admin_bp.route('/create-grade', methods=['POST'])
@login_required(['IT_Admin'])
def create_grade():
    name = request.form.get('name', '').strip()
    if name:
        query("INSERT INTO grades (name, created_by) VALUES (%s, %s)", (name, session['user_id']))
        log_activity(session['user_id'], 'CREATE_GRADE', f'Created grade: {name}')
        flash('Grade created successfully.', 'success')
    return redirect(url_for('admin.grades_sections'))

@admin_bp.route('/create-section', methods=['POST'])
@login_required(['IT_Admin'])
def create_section():
    grade_id = request.form.get('grade_id')
    name = request.form.get('name', '').strip()
    capacity = request.form.get('capacity', 40)
    if grade_id and name:
        query("INSERT INTO sections (grade_id, name, capacity) VALUES (%s, %s, %s)", (grade_id, name, capacity))
        log_activity(session['user_id'], 'CREATE_SECTION', f'Created section: {name} for grade {grade_id}')
        flash('Section created successfully.', 'success')
    return redirect(url_for('admin.grades_sections'))

@admin_bp.route('/subjects')
@login_required(['IT_Admin'])
def subjects():
    subjects_list = query(
        """SELECT s.*, g.name as grade_name,
              (SELECT COUNT(*) FROM subject_teachers st WHERE st.subject_id = s.id) as teacher_count
           FROM subjects s
           JOIN grades g ON s.grade_id = g.id
           ORDER BY g.name, s.subject_name""",
        fetch=True
    )
    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    return render_template('admin/subjects.html', subjects=subjects_list, grades=grades)

@admin_bp.route('/create-subject', methods=['POST'])
@login_required(['IT_Admin'])
def create_subject():
    subject_name = request.form.get('subject_name', '').strip()
    grade_id = request.form.get('grade_id')
    subject_type = request.form.get('type', 'Theory')
    description = request.form.get('description', '')
    if subject_name and grade_id:
        query("INSERT INTO subjects (subject_name, grade_id, type, description) VALUES (%s, %s, %s, %s)", 
              (subject_name, grade_id, subject_type, description))
        log_activity(session['user_id'], 'CREATE_SUBJECT', f'Created subject: {subject_name}')
        flash('Subject created successfully.', 'success')
    return redirect(url_for('admin.subjects'))

@admin_bp.route('/audit-log')
@login_required(['IT_Admin'])
def audit_log():
    logs = query(
        """SELECT al.*, u.username 
           FROM activity_log al 
           JOIN users u ON al.user_id = u.id 
           ORDER BY al.logged_at DESC""",
        fetch=True
    )
    return render_template('admin/audit_log.html', logs=logs)

@admin_bp.route('/override-attendance', methods=['GET', 'POST'])
@login_required(['IT_Admin'])
def override_attendance():
    sections = query(
        """SELECT s.*, g.name as grade_name 
           FROM sections s 
           JOIN grades g ON s.grade_id = g.id 
           ORDER BY g.name, s.name""",
        fetch=True
    )
    
    attendance_records = []
    selected_date = date.today().isoformat()
    if request.method == 'POST':
        section_id = request.form.get('section_id')
        selected_date = request.form.get('date', date.today().isoformat())
        subject_id = request.form.get('subject_id')
        
        if section_id and selected_date and subject_id:
            attendance_records = query(
                """SELECT a.*, st.name as student_name, s.name as section_name, sub.subject_name, t.name as teacher_name
                   FROM attendance a
                   JOIN students st ON a.student_id = st.id
                   JOIN sections s ON a.section_id = s.id
                   JOIN subjects sub ON a.subject_id = sub.id
                   JOIN teachers t ON a.teacher_id = t.id
                   WHERE a.section_id = %s AND a.date = %s AND a.subject_id = %s
                   ORDER BY st.roll_number""",
                (section_id, selected_date, subject_id),
                fetch=True
            )
    
    subjects = query("SELECT * FROM subjects ORDER BY subject_name", fetch=True)
    return render_template('admin/override_attendance.html', sections=sections, subjects=subjects, 
                         attendance_records=attendance_records, today=date.today().isoformat())

@admin_bp.route('/api/students-by-section/<int:section_id>')
@login_required(['IT_Admin'])
def api_students_by_section(section_id):
    students = query(
        """SELECT id, name, roll_number 
           FROM students 
           WHERE section_id = %s AND status = 'Active' 
           ORDER BY roll_number""",
        (section_id,),
        fetch=True
    )
    return jsonify(students)

@admin_bp.route('/api/subjects-by-section/<int:section_id>')
@login_required(['IT_Admin'])
def api_subjects_by_section(section_id):
    subjects_list = query(
        """SELECT DISTINCT sub.id, sub.subject_name
           FROM subjects sub
           JOIN subject_teachers st ON sub.id = st.subject_id
           WHERE st.section_id = %s
           ORDER BY sub.subject_name""",
        (section_id,),
        fetch=True
    )
    return jsonify(subjects_list)