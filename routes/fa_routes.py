from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, date
from database.connection import query, transaction
from routes.auth_routes import login_required, log_activity


def get_fee_months():
    months = []
    for i in range(12):
        m = date.today().replace(day=1)
        months.append((m.month, m.year))
        m = m.replace(month=m.month + 1)
    return months

fa_bp = Blueprint('fa', __name__, url_prefix='/fa')

@fa_bp.route('/dashboard')
@login_required(['FA'])
def dashboard():
    fa_record = query("SELECT id FROM fa WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    fa_id = fa_record['id'] if fa_record else None
    
    stats = {
        'teachers': query("SELECT COUNT(*) as count FROM teachers", fetch_one=True)['count'],
        'students': query("SELECT COUNT(*) as count FROM students WHERE status = 'Active'", fetch_one=True)['count'],
        'sections': query("SELECT COUNT(*) as count FROM sections", fetch_one=True)['count'],
        'pending_requests': query("SELECT COUNT(*) as count FROM class_requests WHERE status = 'Pending'", fetch_one=True)['count']
    }
    
    today = date.today()
    teacher_attendance = query(
        """SELECT t.name, ta.status 
           FROM teacher_attendance ta
           JOIN teachers t ON ta.teacher_id = t.id
           WHERE ta.date = %s""",
        (today,),
        fetch=True
    )
    
    return render_template('fa/dashboard.html', stats=stats, teacher_attendance=teacher_attendance, today=today)

@fa_bp.route('/teacher-attendance', methods=['GET', 'POST'])
@login_required(['FA'])
def teacher_attendance():
    fa_record = query("SELECT id FROM fa WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    fa_id = fa_record['id'] if fa_record else None
    
    if request.method == 'POST':
        action = request.form.get('action')
        today = date.today()
        
        if action == 'save_attendance':
            teachers = query("SELECT id FROM teachers", fetch=True)
            for teacher in teachers:
                tid = teacher['id']
                status = request.form.get(f'status_{tid}')
                notes = request.form.get(f'notes_{tid}', '')
                if status:
                    query(
                        """INSERT INTO teacher_attendance (teacher_id, date, status, marked_by_fa_id, notes)
                           VALUES (%s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE status = %s, marked_by_fa_id = %s, notes = %s, marked_at = NOW()""",
                        (tid, today, status, fa_id, notes, status, fa_id, notes)
                    )
                    if status == 'Absent':
                        # Notify Principal
                        principal_users = query("SELECT user_id FROM principals", fetch=True)
                        for p in principal_users:
                            query(
                                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                                (p['user_id'], f'Teacher {tid} marked absent today.', 'warning', url_for('principal.dashboard'))
                            )
            flash('Teacher attendance saved.', 'success')
            log_activity(session['user_id'], 'TEACHER_ATTENDANCE', f'Saved attendance for {today}')
        return redirect(url_for('fa.teacher_attendance'))
    
    # GET: Load all teachers
    teachers = query(
        """SELECT t.*, u.username 
           FROM teachers t
           JOIN users u ON t.user_id = u.id
           WHERE u.is_active = 1
           ORDER BY t.name""",
        fetch=True
    )
    
    # Auto-sync: if teachers table empty, create from users
    if not teachers:
        users = query("SELECT id, username FROM users WHERE user_type = 'Teacher' AND is_active = 1", fetch=True)
        for u in users:
            query(
                "INSERT INTO teachers (user_id, name, subject, phone, email) VALUES (%s, %s, %s, %s, %s)",
                (u['id'], u['username'], '', u['username'], u['username'])
            )
        teachers = query(
            """SELECT t.*, u.username 
               FROM teachers t
               JOIN users u ON t.user_id = u.id
               WHERE u.is_active = 1
               ORDER BY t.name""",
            fetch=True
        )
    
    # Check today's attendance
    today = date.today()
    attendance_today = query(
        "SELECT teacher_id, status, notes FROM teacher_attendance WHERE date = %s",
        (today,),
        fetch=True
    )
    attendance_map = {a['teacher_id']: a for a in attendance_today}
    
    return render_template('fa/teacher_attendance.html', teachers=teachers, attendance_map=attendance_map, today=today)

@fa_bp.route('/assign-courses', methods=['GET', 'POST'])
@login_required(['FA'])
def assign_courses():
    fa_record = query("SELECT id FROM fa WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    fa_id = fa_record['id'] if fa_record else None
    
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        subject_id = request.form.get('subject_id')
        section_ids = request.form.getlist('section_ids')
        
        if teacher_id and subject_id and section_ids:
            for section_id in section_ids:
                query(
                    """INSERT INTO subject_teachers (teacher_id, subject_id, section_id, assigned_by)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE assigned_by = %s, assigned_at = NOW()""",
                    (teacher_id, subject_id, section_id, session['user_id'], session['user_id'])
                )
            
            # Notify teacher
            teacher = query("SELECT user_id FROM teachers WHERE id = %s", (teacher_id,), fetch_one=True)
            if teacher:
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (teacher['user_id'], 'Your course assignments have been updated.', 'info', url_for('teacher.dashboard'))
                )
            
            flash('Courses assigned successfully.', 'success')
            log_activity(session['user_id'], 'ASSIGN_COURSES', f'Assigned subject {subject_id} to teacher {teacher_id}')
        return redirect(url_for('fa.assign_courses'))
    
    # GET
    teachers = query(
        """SELECT t.*, u.username 
           FROM teachers t
           JOIN users u ON t.user_id = u.id
           WHERE u.is_active = 1
           ORDER BY t.name""",
        fetch=True
    )
    subjects = query("SELECT s.*, g.name as grade_name FROM subjects s JOIN grades g ON s.grade_id = g.id ORDER BY g.name, s.subject_name", fetch=True)
    sections = query(
        """SELECT s.*, g.name as grade_name 
           FROM sections s 
           JOIN grades g ON s.grade_id = g.id 
           ORDER BY g.name, s.name""",
        fetch=True
    )
    
    current_assignments = query(
        """SELECT st.*, t.name as teacher_name, s.subject_name, sec.name as section_name, g.name as grade_name
           FROM subject_teachers st
           JOIN teachers t ON st.teacher_id = t.id
           JOIN subjects s ON st.subject_id = s.id
           JOIN sections sec ON st.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           ORDER BY t.name, g.name, sec.name, s.subject_name""",
        fetch=True
    )
    
    return render_template('fa/assign_courses.html', teachers=teachers, subjects=subjects, sections=sections, current_assignments=current_assignments)

@fa_bp.route('/assign-courses/remove/<int:assignment_id>', methods=['POST'])
@login_required(['FA'])
def remove_assignment(assignment_id):
    query("DELETE FROM subject_teachers WHERE id = %s", (assignment_id,))
    flash('Assignment removed.', 'success')
    log_activity(session['user_id'], 'REMOVE_ASSIGNMENT', f'Removed assignment {assignment_id}')
    return redirect(url_for('fa.assign_courses'))

@fa_bp.route('/timetable', methods=['GET', 'POST'])
@login_required(['FA'])
def timetable():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            section_id = request.form.get('section_id')
            subject_id = request.form.get('subject_id')
            teacher_id = request.form.get('teacher_id')
            day = request.form.get('day')
            period = request.form.get('period')
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            room_type = request.form.get('room_type', 'Classroom')
            
            query(
                """INSERT INTO timetable (section_id, subject_id, teacher_id, day, period, start_time, end_time, room_type)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (section_id, subject_id, teacher_id, day, period, start_time, end_time, room_type)
            )
            flash('Timetable slot added.', 'success')
            log_activity(session['user_id'], 'TIMETABLE_ADD', f'Added timetable for section {section_id}')
            
        elif action == 'delete':
            slot_id = request.form.get('slot_id')
            query("DELETE FROM timetable WHERE id = %s", (slot_id,))
            flash('Timetable slot deleted.', 'success')
            log_activity(session['user_id'], 'TIMETABLE_DELETE', f'Deleted timetable slot {slot_id}')
        
        return redirect(url_for('fa.timetable'))
    
    # GET
    timetable_data = query(
        """SELECT tt.*, s.name as section_name, g.name as grade_name, sub.subject_name, t.name as teacher_name
           FROM timetable tt
           JOIN sections s ON tt.section_id = s.id
           JOIN grades g ON s.grade_id = g.id
           JOIN subjects sub ON tt.subject_id = sub.id
           JOIN teachers t ON tt.teacher_id = t.id
           ORDER BY g.name, s.name, 
           FIELD(tt.day, 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'),
           tt.period""",
        fetch=True
    )
    
    sections = query(
        """SELECT s.*, g.name as grade_name 
           FROM sections s 
           JOIN grades g ON s.grade_id = g.id 
           ORDER BY g.name, s.name""",
        fetch=True
    )
    subjects = query("SELECT s.*, g.name as grade_name FROM subjects s JOIN grades g ON s.grade_id = g.id ORDER BY g.name, s.subject_name", fetch=True)
    teachers = query("SELECT t.*, u.username FROM teachers t JOIN users u ON t.user_id = u.id WHERE u.is_active = 1 ORDER BY t.name", fetch=True)
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    
    return render_template('fa/timetable.html', timetable=timetable_data, sections=sections, subjects=subjects, teachers=teachers, days=days)

@fa_bp.route('/class-requests', methods=['GET', 'POST'])
@login_required(['FA'])
def class_requests():
    fa_record = query("SELECT id FROM fa WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    fa_id = fa_record['id'] if fa_record else None
    
    if request.method == 'POST':
        action = request.form.get('action')
        request_id = request.form.get('request_id')
        
        if action == 'approve':
            req = query("SELECT * FROM class_requests WHERE id = %s", (request_id,), fetch_one=True)
            if req:
                query(
                    "UPDATE class_requests SET status = 'Approved', reviewed_at = NOW(), reviewed_by_fa_id = %s WHERE id = %s",
                    (fa_id, request_id)
                )
                
                # Assign teacher to subject
                query(
                    """INSERT INTO subject_teachers (teacher_id, subject_id, section_id, assigned_by)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE assigned_by = %s, assigned_at = NOW()""",
                    (req['teacher_id'], req['subject_id'], req['section_id'], session['user_id'], session['user_id'])
                )
                
                # Notify teacher
                teacher = query("SELECT user_id FROM teachers WHERE id = %s", (req['teacher_id'],), fetch_one=True)
                if teacher:
                    query(
                        "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                        (teacher['user_id'], f'Your class request for {req["class_name"]} has been approved.', 'success', url_for('teacher.dashboard'))
                    )
                
                # Notify IT Admin
                admin_users = query("SELECT user_id FROM users WHERE user_type = 'IT_Admin'", fetch=True)
                for admin in admin_users:
                    query(
                        "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                        (admin['user_id'], f'Class request approved: {req["class_name"]} assigned.', 'info', url_for('admin.dashboard'))
                    )
                
                flash('Request approved and teacher assigned.', 'success')
                
        elif action == 'reject':
            reason = request.form.get('reason', '')
            query(
                "UPDATE class_requests SET status = 'Rejected', fa_response_note = %s, reviewed_at = NOW(), reviewed_by_fa_id = %s WHERE id = %s",
                (reason, fa_id, request_id)
            )
            
            req = query("SELECT * FROM class_requests WHERE id = %s", (request_id,), fetch_one=True)
            if req:
                teacher = query("SELECT user_id FROM teachers WHERE id = %s", (req['teacher_id'],), fetch_one=True)
                if teacher:
                    query(
                        "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                        (teacher['user_id'], f'Your class request for {req["class_name"]} was rejected. Reason: {reason}', 'danger', url_for('teacher.dashboard'))
                    )
            
            flash('Request rejected.', 'warning')
        
        log_activity(session['user_id'], f'CLASS_REQUEST_{action.upper()}', f'Request {request_id} {action}d')
        return redirect(url_for('fa.class_requests'))
    
    # GET
    requests = query(
        """SELECT cr.*, t.name as teacher_name, g.name as grade_name, sec.name as section_name, s.subject_name
           FROM class_requests cr
           JOIN teachers t ON cr.teacher_id = t.id
           JOIN grades g ON cr.grade_id = g.id
           JOIN sections sec ON cr.section_id = sec.id
           JOIN subjects s ON cr.subject_id = s.id
           ORDER BY cr.requested_at DESC""",
        fetch=True
    )
    
    return render_template('fa/class_requests.html', requests=requests)

@fa_bp.route('/students')
@login_required(['FA'])
def students():
    grade_id = request.args.get('grade_id', type=int)
    section_id = request.args.get('section_id', type=int)
    search = request.args.get('search', '').strip()
    
    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    
    sections = []
    if grade_id:
        sections = query("SELECT * FROM sections WHERE grade_id = %s ORDER BY name", (grade_id,), fetch=True)
    
    students_query = """
        SELECT s.*, sec.name as section_name, g.name as grade_name
        FROM students s
        LEFT JOIN sections sec ON s.section_id = sec.id
        LEFT JOIN grades g ON sec.grade_id = g.id
        WHERE s.status = 'Active'
    """
    params = []
    
    if grade_id:
        students_query += " AND g.id = %s"
        params.append(grade_id)
    if section_id:
        students_query += " AND s.section_id = %s"
        params.append(section_id)
    if search:
        students_query += " AND (s.name LIKE %s OR s.student_system_id LIKE %s OR s.roll_number LIKE %s)"
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    
    students_query += " ORDER BY g.name, sec.name, s.roll_number"
    
    students_list = query(students_query, tuple(params), fetch=True)
    
    return render_template('fa/students.html', students=students_list, grades=grades, sections=sections, 
                         selected_grade=grade_id, selected_section=section_id, search=search)

@fa_bp.route('/reports')
@login_required(['FA'])
def reports():
    # Section-wise summary
    report = query(
        """SELECT g.name as grade_name, sec.name as section_name, sec.capacity,
              COUNT(s.id) as student_count,
              COUNT(CASE WHEN s.status = 'Active' THEN 1 END) as active_count
           FROM sections sec
           JOIN grades g ON sec.grade_id = g.id
           LEFT JOIN students s ON sec.id = s.section_id
           GROUP BY sec.id
           ORDER BY g.name, sec.name""",
        fetch=True
    )

    return render_template('fa/reports.html', report=report)


@fa_bp.route('/fees', methods=['GET', 'POST'])
@login_required(['FA'])
def fees():
    selected_month = request.args.get('month') or date.today().strftime('%b %Y')
    grade_id = request.args.get('grade_id', type=int)
    section_id = request.args.get('section_id', type=int)

    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    sections = query("SELECT * FROM sections ORDER BY name", fetch=True)

    fee_structure = query(
        """SELECT fs.*, g.name as grade_name FROM fee_structure fs
           JOIN grades g ON fs.grade_id = g.id
           ORDER BY g.name, fs.month_year""",
        fetch=True
    )

    if request.method == 'POST' and request.form.get('action') == 'mark-paid':
        student_id = request.form.get('student_id', type=int)
        month_year = request.form.get('month_year')
        amount = request.form.get('amount', type=float) or 0
        if student_id and month_year:
            query(
                """INSERT INTO student_fees (student_id, month_year, amount, status, marked_at)
                   VALUES (%s, %s, %s, 'Paid', NOW())
                   ON DUPLICATE KEY UPDATE amount = VALUES(amount), status = 'Paid', marked_at = NOW()""",
                (student_id, month_year, amount)
            )
            student = query("SELECT name, user_id FROM students WHERE id = %s", (student_id,), fetch_one=True)
            if student:
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (student['user_id'], f'Your fee for {month_year} is marked as paid', 'success', url_for('student.fees'))
                )
            flash('Fee marked as paid.', 'success')
            return redirect(url_for('fa.fees', month=month_year, grade_id=grade_id, section_id=section_id))

    month_rows = query(
        """SELECT sf.*, s.name, s.roll_number, sec.name as section_name, g.name as grade_name
           FROM student_fees sf
           JOIN students s ON sf.student_id = s.id
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE sf.month_year = %s""",
        (selected_month,),
        fetch=True
    ) if selected_month else []

    students = query(
        """SELECT s.*, sec.name as section_name, g.name as grade_name,
              COALESCE(sf.amount, 0) as fee_amount,
              COALESCE(sf.status, 'Pending') as fee_status,
              sf.month_year
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           LEFT JOIN student_fees sf ON sf.student_id = s.id AND sf.month_year = %s
           WHERE s.status = 'Active'""",
        (selected_month,),
        fetch=True
    )

    if grade_id:
        grade_section_ids = [row['id'] for row in query("SELECT id FROM sections WHERE grade_id = %s", (grade_id,), fetch=True)]
        students = [stu for stu in students if stu.get('section_id') in grade_section_ids]
    if section_id:
        students = [stu for stu in students if stu.get('section_id') == section_id]

    total_collected = sum(float((stu.get('fee_amount') or 0)) for stu in students if (stu.get('fee_status') or '').lower() == 'paid')
    paid_count = sum(1 for stu in students if (stu.get('fee_status') or '').lower() == 'paid')
    pending_count = len(students) - paid_count

    return render_template('fa/fees.html', grades=grades, sections=sections, fee_structure=fee_structure,
                         students=students, selected_month=selected_month, grade_id=grade_id,
                         section_id=section_id, total_collected=total_collected,
                         paid_count=paid_count, pending_count=pending_count)


@fa_bp.route('/fees/mark-paid', methods=['POST'])
@login_required(['FA'])
def mark_fee_paid():
    student_id = request.form.get('student_id', type=int)
    month_year = request.form.get('month_year')
    amount = request.form.get('amount', type=float) or 0
    if not student_id or not month_year:
        flash('Student and month are required.', 'danger')
        return redirect(url_for('fa.fees'))
    query(
        """INSERT INTO student_fees (student_id, month_year, amount, status, marked_at)
           VALUES (%s, %s, %s, 'Paid', NOW())
           ON DUPLICATE KEY UPDATE amount = VALUES(amount), status = 'Paid', marked_at = NOW()""",
        (student_id, month_year, amount)
    )
    student = query("SELECT name, user_id FROM students WHERE id = %s", (student_id,), fetch_one=True)
    if student:
        query(
            "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
            (student['user_id'], f'Your fee for {month_year} is marked as paid', 'success', url_for('student.fees'))
        )
    flash('Fee status updated.', 'success')
    return redirect(url_for('fa.fees', month=month_year))


@fa_bp.route('/fees/set-structure', methods=['POST'])
@login_required(['FA'])
def set_fee_structure():
    grade_id = request.form.get('grade_id', type=int)
    month_year = request.form.get('month_year')
    amount = request.form.get('amount', type=float) or 0
    if not grade_id or not month_year:
        flash('Grade and month are required.', 'danger')
        return redirect(url_for('fa.fees'))
    query(
        """INSERT INTO fee_structure (grade_id, month_year, amount)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE amount = VALUES(amount)""",
        (grade_id, month_year, amount)
    )
    flash('Fee structure updated.', 'success')
    return redirect(url_for('fa.fees', month=month_year))


@fa_bp.route('/exam-schedule', methods=['GET', 'POST'])
@login_required(['FA'])
def exam_schedule():
    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        grade_id = request.form.get('grade_id', type=int)
        exam_type = request.form.get('exam_type')
        exam_date = request.form.get('exam_date')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        room = request.form.get('room', '').strip()
        if subject_id and grade_id and exam_type and exam_date:
            query(
                """INSERT INTO exam_schedule (subject_id, grade_id, exam_type, exam_date, start_time, end_time, room, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (subject_id, grade_id, exam_type, exam_date, start_time or None, end_time or None, room or None, session['user_id'])
            )
            students = query("SELECT user_id FROM students WHERE status = 'Active' AND section_id IN (SELECT id FROM sections WHERE grade_id = %s)", (grade_id,), fetch=True)
            teachers = query("SELECT user_id FROM teachers", fetch=True)
            for item in students + teachers:
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (item['user_id'], f'New {exam_type} scheduled for grade {grade_id}', 'info', url_for('student.dashboard'))
                )
            flash('Exam scheduled successfully.', 'success')
        else:
            flash('Please complete all required fields.', 'danger')
        return redirect(url_for('fa.exam_schedule'))

    exams = query(
        """SELECT es.*, s.subject_name, g.name as grade_name
           FROM exam_schedule es
           JOIN subjects s ON es.subject_id = s.id
           JOIN grades g ON es.grade_id = g.id
           ORDER BY es.exam_date ASC, es.start_time ASC""",
        fetch=True
    )
    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    subjects = query("SELECT * FROM subjects ORDER BY subject_name", fetch=True)
    return render_template('fa/exam_schedule.html', exams=exams, grades=grades, subjects=subjects)


@fa_bp.route('/leave-requests')
@login_required(['FA'])
def leave_requests():
    requests = query(
        """SELECT la.*, s.name as student_name, t.name as teacher_name, sec.name as section_name, g.name as grade_name
           FROM leave_applications la
           JOIN students s ON la.student_id = s.id
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           LEFT JOIN teachers t ON la.teacher_id = t.id
           ORDER BY la.created_at DESC""",
        fetch=True
    )
    return render_template('fa/leave_requests.html', requests=requests)


@fa_bp.route('/leave-requests/respond', methods=['POST'])
@login_required(['FA'])
def respond_leave_request():
    leave_id = request.form.get('leave_id', type=int)
    action = request.form.get('action')
    note = request.form.get('response_note', '')
    if not leave_id or not action:
        flash('Leave request missing.', 'danger')
        return redirect(url_for('fa.leave_requests'))
    status = 'Approved' if action == 'approve' else 'Rejected'
    query(
        "UPDATE leave_applications SET status = %s, reviewed_by = %s, reviewed_at = NOW(), response_note = %s WHERE id = %s",
        (status, session['user_id'], note, leave_id)
    )
    leave = query("SELECT * FROM leave_applications WHERE id = %s", (leave_id,), fetch_one=True)
    if leave:
        student = query("SELECT user_id, name FROM students WHERE id = %s", (leave['student_id'],), fetch_one=True)
        if student:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (student['user_id'], f'Your leave application has been {status.lower()}.', 'info', url_for('student.leave'))
            )
    flash('Leave request updated.', 'success')
    return redirect(url_for('fa.leave_requests'))