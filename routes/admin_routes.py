from flask import Blueprint, make_response, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, date
from database.connection import query, transaction, transaction_with_insert_id, hash_password
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
    role_filter = request.args.get('role', '').strip()
    search_term = request.args.get('q', '').strip()
    subject_filter = request.args.get('subject', '').strip()
    section_filter = request.args.get('section_id', type=int)

    filters = []
    filter_params = []
    if role_filter in {'Teacher', 'Student'}:
        filters.append("u.user_type = %s")
        filter_params.append(role_filter)
    if search_term:
        search_pattern = f"%{search_term}%"
        filters.append(
            """(u.username LIKE %s OR u.email LIKE %s
               OR COALESCE(ia.name, gr.name, p.name, f.name, t.name, s.name) LIKE %s
               OR t.subject LIKE %s OR s.student_system_id LIKE %s
               OR s.roll_number LIKE %s OR g.name LIKE %s OR sec.name LIKE %s)"""
        )
        filter_params.extend([search_pattern] * 8)
    if subject_filter:
        filters.append("u.user_type = 'Teacher' AND t.subject = %s")
        filter_params.append(subject_filter)
    if section_filter:
        filters.append("u.user_type = 'Student' AND s.section_id = %s")
        filter_params.append(section_filter)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    all_users = query(
        """SELECT u.*,
              COALESCE(ia.name, gr.name, p.name, f.name, t.name, s.name) AS full_name,
              CASE
                  WHEN u.user_type = 'IT_Admin' THEN ia.role
                  WHEN u.user_type = 'Teacher' THEN t.subject
                  WHEN u.user_type = 'Student' THEN CONCAT(g.name, ' - ', sec.name)
                  ELSE NULL
              END AS role_info,
              s.status AS student_status, s.student_system_id, s.roll_number
           FROM users u
           LEFT JOIN it_admins ia ON u.id = ia.user_id
           LEFT JOIN gr_office gr ON u.id = gr.user_id
           LEFT JOIN principals p ON u.id = p.user_id
           LEFT JOIN fa f ON u.id = f.user_id
           LEFT JOIN teachers t ON u.id = t.user_id
           LEFT JOIN students s ON u.id = s.user_id
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           {where_clause}
           ORDER BY u.created_at DESC""".format(where_clause=where_clause),
        tuple(filter_params),
        fetch=True
    )
    teacher_subjects = query(
        """SELECT DISTINCT subject FROM teachers
           WHERE subject IS NOT NULL AND TRIM(subject) <> ''
           ORDER BY subject""",
        fetch=True
    )
    sections = query(
        """SELECT sec.id, sec.name, sec.grade_id, g.name AS grade_name
           FROM sections sec JOIN grades g ON sec.grade_id = g.id
           ORDER BY g.name, sec.name""",
        fetch=True
    )
    approved_admissions = query(
        """SELECT id, application_ref, applicant_name, contact_phone, email, applied_grade_id,
                  (SELECT g.name FROM grades g WHERE g.id = admission_applications.applied_grade_id) AS grade_name
           FROM admission_applications
           WHERE status = 'Approved' AND student_id IS NULL
           ORDER BY submitted_at""",
        fetch=True
    )
    return {
        'users': all_users or [],
        'sections': sections or [],
        'approved_admissions': approved_admissions or [],
        'teacher_subjects': teacher_subjects or [],
        'user_filters': {
            'role': role_filter,
            'q': search_term,
            'subject': subject_filter,
            'section_id': section_filter
        }
    }

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
    admission_application_id = request.form.get('admission_application_id', type=int)
    admission = None
    valid_roles = {'IT_Admin', 'GR_Office', 'Principal', 'FA', 'Teacher', 'Student'}

    if not all([username, password, user_type, name]) or user_type not in valid_roles:
        flash('All required fields must be filled.', 'danger')
        return redirect(url_for('admin.users'))

    if admission_application_id:
        if user_type != 'Student':
            flash('An approved admission can only be linked to a Student account.', 'danger')
            return redirect(url_for('admin.users'))
        admission = query(
            """SELECT * FROM admission_applications
               WHERE id = %s AND status = 'Approved' AND student_id IS NULL""",
            (admission_application_id,),
            fetch_one=True
        )
        if not admission:
            flash('This admission is no longer approved for enrollment.', 'danger')
            return redirect(url_for('admin.users'))

        section_id = request.form.get('section_id', type=int)
        roll_number = request.form.get('roll_number', '').strip()
        section = query(
            """SELECT sec.id, CONCAT(g.name, ' - ', sec.name) AS section_label
               FROM sections sec JOIN grades g ON g.id = sec.grade_id
               WHERE sec.id = %s AND sec.grade_id = %s""",
            (section_id, admission['applied_grade_id']),
            fetch_one=True
        )
        if not section or not roll_number:
            flash('Choose a section in the applicant’s requested grade and enter a roll number.', 'danger')
            return redirect(url_for('admin.users'))
        if query(
            "SELECT id FROM students WHERE section_id = %s AND roll_number = %s",
            (section_id, roll_number),
            fetch_one=True
        ):
            flash('Roll number already exists in this section.', 'danger')
            return redirect(url_for('admin.users'))

        name = admission['applicant_name']
        email = admission.get('email') or email
        phone = admission['contact_phone']

    # Check username exists
    if query("SELECT id FROM users WHERE username = %s", (username,), fetch_one=True):
        flash('Username already exists.', 'danger')
        return redirect(url_for('admin.users'))

    hashed = hash_password(password)
    role_queries = {
        'IT_Admin': ("INSERT INTO it_admins (user_id, name, phone, role) VALUES (%s, %s, %s, %s)",
                     lambda user_id: (user_id, name, phone, 'System Administrator')),
        'GR_Office': ("INSERT INTO gr_office (user_id, name, phone) VALUES (%s, %s, %s)",
                      lambda user_id: (user_id, name, phone)),
        'Principal': ("INSERT INTO principals (user_id, name, phone) VALUES (%s, %s, %s)",
                      lambda user_id: (user_id, name, phone)),
        'FA': ("INSERT INTO fa (user_id, name, phone) VALUES (%s, %s, %s)",
               lambda user_id: (user_id, name, phone)),
        'Teacher': ("INSERT INTO teachers (user_id, name, subject, qualification, phone, email, hire_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    lambda user_id: (user_id, name, request.form.get('subject', ''),
                                     request.form.get('qualification', ''), phone, email,
                                     request.form.get('hire_date', '') or None)),
        'Student': ("INSERT INTO students (user_id, student_system_id, name, father_name, section_id, roll_number, dob, gender, address, parent_contact, admission_date, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    lambda user_id: (
                        user_id, f"SS-{datetime.now().year}-{user_id:04d}", name,
                        admission['guardian_name'] if admission else request.form.get('father_name', ''),
                        request.form.get('section_id') or None,
                        request.form.get('roll_number', ''),
                        admission['dob'] if admission else request.form.get('dob') or None,
                        admission['gender'] if admission else request.form.get('gender'),
                        admission['address'] if admission else request.form.get('address', ''),
                        admission['guardian_phone'] if admission else request.form.get('parent_contact', ''),
                        datetime.now().date(), 'PendingLogin'
                    ))
    }

    role_sql, role_params = role_queries[user_type]
    account_writes = [
        (
            "INSERT INTO users (username, password, user_type, email, phone) VALUES (%s, %s, %s, %s, %s)",
            (username, hashed, user_type, email, phone)
        ),
        (role_sql, role_params),
    ]
    if admission:
        account_writes.append((
            """UPDATE admission_applications
               SET status = 'Enrolled', student_id = (
                       SELECT id FROM students WHERE user_id = %s
                   ), enrolled_by = %s, enrolled_at = NOW(), access_token_hash = NULL
               WHERE id = %s AND status = 'Approved' AND student_id IS NULL""",
            lambda user_id: (user_id, session['user_id'], admission_application_id)
        ))
    if admission:
        user_id = transaction_with_insert_id(account_writes, require_affected_rows=True)
    else:
        user_id = transaction_with_insert_id(account_writes)
    if not user_id:
        flash('Failed to create user. No account changes were saved.', 'danger')
        return redirect(url_for('admin.users'))

    if user_type == 'Teacher':
        for fa in query("SELECT user_id FROM fa", fetch=True) or []:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (fa['user_id'], f'New teacher {name} added. Please assign courses.', 'info', url_for('fa.assign_courses'))
            )
    elif user_type == 'Student':
        for user in query("SELECT user_id FROM users WHERE user_type IN ('IT_Admin', 'GR_Office')", fetch=True) or []:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (
                    user['user_id'],
                    f'New student {name} enrolled. Login pending.',
                    'info',
                    url_for('admission.gr_admissions') if admission else url_for('admin.users')
                )
            )

    log_activity(session['user_id'], 'CREATE_USER', f'Created {user_type}: {username}')
    if admission:
        log_activity(
            session['user_id'],
            'ADMISSION_ENROLLED',
            f'Enrolled approved admission application {admission_application_id}'
        )
    flash(f'{user_type} created successfully.', 'success')
    section_label = None
    if user_type == 'Student' and request.form.get('section_id'):
        if admission:
            section_label = section.get('section_label')
        else:
            section_result = query(
                """SELECT CONCAT(g.name, ' - ', sec.name) AS section_label
                   FROM sections sec JOIN grades g ON g.id = sec.grade_id
                   WHERE sec.id = %s""",
                (request.form.get('section_id', type=int),),
                fetch_one=True
            )
            section_label = section_result.get('section_label') if section_result else None
    response = make_response(render_template(
        'admin/account_created.html',
        account={
            'user_id': user_id,
            'name': name,
            'username': username,
            'password': password,
            'phone': phone,
            'user_type': user_type,
            'student_id': f"SS-{datetime.now().year}-{user_id:04d}" if user_type == 'Student' else None,
            'section': section_label,
            'roll_number': request.form.get('roll_number', '').strip() if user_type == 'Student' else None,
            'login_pending': user_type == 'Student',
        }
    ))
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

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
           ORDER BY g.id, s.subject_name""",
        fetch=True
    ) or []
    grades = query(
        """SELECT g.*,
                  (SELECT COUNT(*) FROM sections sec WHERE sec.grade_id = g.id) as section_count
           FROM grades g
           ORDER BY g.id""",
        fetch=True
    ) or []

    grade_groups = []
    group_map = {}
    for grade in grades:
        group = {
            'grade': grade,
            'subjects': [],
            'teacher_total': 0,
            'theory_count': 0,
            'practical_count': 0,
        }
        group_map[grade['id']] = group
        grade_groups.append(group)

    for subject in subjects_list:
        group = group_map.get(subject['grade_id'])
        if not group:
            continue
        group['subjects'].append(subject)
        group['teacher_total'] += int(subject.get('teacher_count') or 0)
        if subject.get('type') == 'Practical':
            group['practical_count'] += 1
        else:
            group['theory_count'] += 1

    for group in grade_groups:
        group['subject_count'] = len(group['subjects'])

    subject_totals = {
        'subjects': len(subjects_list),
        'classes': len(grade_groups),
        'theory': sum(group['theory_count'] for group in grade_groups),
        'practical': sum(group['practical_count'] for group in grade_groups),
    }

    return render_template(
        'admin/subjects.html',
        grade_groups=grade_groups,
        subject_totals=subject_totals,
        grades=grades
    )

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
    selected_date = request.form.get('date', request.args.get('date', date.today().isoformat()))
    section_id = request.form.get('section_id') or request.args.get('section_id')
    subject_id = request.form.get('subject_id') or request.args.get('subject_id')

    if request.method == 'POST':
        if 'save_override' in request.form:
            if not (section_id and selected_date and subject_id):
                flash('Section, date, and subject are required.', 'danger')
            else:
                existing_records = query(
                    """SELECT a.id, a.student_id, a.status
                       FROM attendance a
                       WHERE a.section_id = %s AND a.date = %s AND a.subject_id = %s""",
                    (section_id, selected_date, subject_id),
                    fetch=True
                )
                valid_statuses = {'Present', 'Absent', 'Late', 'Leave'}
                updates = []
                for rec in (existing_records or []):
                    new_status = request.form.get(f"status_{rec['id']}")
                    if new_status and new_status in valid_statuses and new_status != rec['status']:
                        updates.append((
                            "UPDATE attendance SET status = %s, marked_at = NOW() WHERE id = %s",
                            (new_status, rec['id'])
                        ))

                if updates:
                    success = transaction(updates)
                    if success:
                        log_activity(session['user_id'], 'OVERRIDE_ATTENDANCE',
                                     f'Overrode {len(updates)} record(s) for section {section_id}, subject {subject_id}, date {selected_date}')
                        flash(f'Attendance overrides saved successfully ({len(updates)} record(s) updated).', 'success')
                    else:
                        flash('Failed to save attendance overrides.', 'danger')
                else:
                    flash('No attendance status changes were detected to save.', 'info')

    if section_id and selected_date and subject_id:
        attendance_records = query(
            """SELECT a.*, st.name as student_name, st.roll_number, s.name as section_name, sub.subject_name, t.name as teacher_name
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
                         attendance_records=attendance_records, today=date.today().isoformat(),
                         selected_section=section_id, selected_subject=subject_id, selected_date=selected_date)

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