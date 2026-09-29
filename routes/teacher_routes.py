from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, date, timedelta
from database.connection import query, transaction
from routes.auth_routes import login_required, log_activity
import os
from werkzeug.utils import secure_filename
from config import Config
import requests

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')

def get_teacher_id():
    """Get teacher record ID for current user."""
    return query("SELECT id FROM teachers WHERE user_id = %s", (session['user_id'],), fetch_one=True)

@teacher_bp.route('/dashboard')
@login_required(['Teacher'])
def dashboard():
    teacher_record = get_teacher_id()
    if not teacher_record:
        flash('Teacher profile not found. Contact administrator.', 'danger')
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    # Get assigned courses with pending assignment counts
    courses = query(
        """SELECT st.*, s.subject_name, sec.name as section_name, g.name as grade_name,
              COUNT(DISTINCT stu.id) as student_count,
              COUNT(DISTINCT a.id) as total_assignments,
              COUNT(DISTINCT CASE WHEN sub.id IS NULL AND a.due_date >= NOW() THEN sub2.id END) as pending_assignments
           FROM subject_teachers st
           JOIN subjects s ON st.subject_id = s.id
           JOIN sections sec ON st.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           LEFT JOIN students stu ON stu.section_id = sec.id AND stu.status = 'Active'
           LEFT JOIN assignments a ON a.teacher_id = st.teacher_id AND a.subject_id = st.subject_id
           LEFT JOIN assignment_sections acs ON acs.assignment_id = a.id AND acs.section_id = sec.id
           LEFT JOIN submissions sub2 ON sub2.assignment_id = a.id AND sub2.student_id IN (SELECT id FROM students WHERE section_id = sec.id AND status = 'Active')
           LEFT JOIN submissions sub ON sub.assignment_id = a.id
           WHERE st.teacher_id = %s
           GROUP BY st.id
           ORDER BY g.name, sec.name, s.subject_name""",
        (teacher_id,),
        fetch=True
    )
    
    # Get latest assignment ID per course for "view submissions" link
    for course in courses:
        latest = query(
            """SELECT a.id FROM assignments a
               WHERE a.teacher_id = %s AND a.subject_id = %s
               ORDER BY a.created_at DESC LIMIT 1""",
            (teacher_id, course['subject_id']),
            fetch_one=True
        )
        course['next_assignment_id'] = latest['id'] if latest else 0
    
    # Today's schedule
    today = date.today()
    day_name = today.strftime('%A')
    schedule = query(
        """SELECT tt.*, s.subject_name, sec.name as section_name
           FROM timetable tt
           JOIN subjects s ON tt.subject_id = s.id
           JOIN sections sec ON tt.section_id = sec.id
           WHERE tt.teacher_id = %s AND tt.day = %s
           ORDER BY tt.period""",
        (teacher_id, day_name),
        fetch=True
    )
    
    # Pending grading
    pending_result = query(
        """SELECT COUNT(*) as count
           FROM submissions sub
           JOIN assignments a ON sub.assignment_id = a.id
           WHERE a.teacher_id = %s AND sub.marks_obtained IS NULL""",
        (teacher_id,),
        fetch_one=True
    )
    pending_grading = pending_result['count'] if pending_result else 0
    
    # My class requests
    my_requests = query(
        """SELECT cr.*, g.name as grade_name, sec.name as section_name, s.subject_name
           FROM class_requests cr
           JOIN grades g ON cr.grade_id = g.id
           JOIN sections sec ON cr.section_id = sec.id
           JOIN subjects s ON cr.subject_id = s.id
           WHERE cr.teacher_id = %s
           ORDER BY cr.requested_at DESC""",
        (teacher_id,),
        fetch=True
    )
    
    # For request modal
    all_grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    all_sections = query(
        """SELECT s.*, g.name as grade_name 
           FROM sections s 
           JOIN grades g ON s.grade_id = g.id 
           ORDER BY g.name, s.name""",
        fetch=True
    )
    all_subjects = query("SELECT s.*, g.name as grade_name FROM subjects s JOIN grades g ON s.grade_id = g.id ORDER BY g.name, s.subject_name", fetch=True)
    
    return render_template('teacher/dashboard.html', 
                         teacher_id=teacher_id, courses=courses, schedule=schedule,
                         pending_grading=pending_grading, my_requests=my_requests,
                         all_grades=all_grades, all_sections=all_sections, all_subjects=all_subjects,
                         now=datetime.now())

@teacher_bp.route('/course/<int:subject_id>/<int:section_id>')
@login_required(['Teacher'])
def course(subject_id, section_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    # Verify assignment
    assignment = query(
        "SELECT * FROM subject_teachers WHERE teacher_id = %s AND subject_id = %s AND section_id = %s",
        (teacher_id, subject_id, section_id),
        fetch_one=True
    )
    
    if not assignment:
        flash('You are not assigned to this course.', 'danger')
        return redirect(url_for('teacher.dashboard'))
    
    # Get subject, section, grade info
    course_info = query(
        """SELECT s.subject_name, sec.name as section_name, g.name as grade_name, sec.id as section_id, g.id as grade_id
           FROM subjects s
           JOIN sections sec ON %s = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE s.id = %s""",
        (section_id, subject_id),
        fetch_one=True
    )
    
    # Get students
    students = query(
        """SELECT * FROM students 
           WHERE section_id = %s AND status = 'Active'
           ORDER BY roll_number""",
        (section_id,),
        fetch=True
    )
    
    # Get assignments for this teacher+section
    assignments = query(
        """SELECT a.* FROM assignments a
           JOIN assignment_sections acs ON a.id = acs.assignment_id
           WHERE a.teacher_id = %s AND acs.section_id = %s
           ORDER BY a.due_date DESC""",
        (teacher_id, section_id),
        fetch=True
    )
    
    # Check if attendance already marked today
    today = date.today()
    attendance_marked = query(
        "SELECT COUNT(*) as count FROM attendance WHERE teacher_id = %s AND section_id = %s AND subject_id = %s AND date = %s",
        (teacher_id, section_id, subject_id, today),
        fetch_one=True
    )['count'] > 0
    
    return render_template('teacher/course.html',
                         course_info=course_info, students=students, assignments=assignments,
                         attendance_marked=attendance_marked, teacher_id=teacher_id,
                         subject_id=subject_id, section_id=section_id, now=datetime.now())

@teacher_bp.route('/course/<int:subject_id>/<int:section_id>/save-attendance', methods=['POST'])
@login_required(['Teacher'])
def save_attendance(subject_id, section_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return jsonify({'success': False, 'message': 'Not authorized'}), 403
    
    teacher_id = teacher_record['id']
    today = date.today()
    
    # Verify assignment
    assignment = query(
        "SELECT * FROM subject_teachers WHERE teacher_id = %s AND subject_id = %s AND section_id = %s",
        (teacher_id, subject_id, section_id),
        fetch_one=True
    )
    
    if not assignment:
        return jsonify({'success': False, 'message': 'Not assigned to this course'}), 403
    
    # Check if past date (locked)
    attendance_date = request.form.get('date', today.isoformat())
    if attendance_date != today.isoformat():
        return jsonify({'success': False, 'message': 'Cannot mark attendance for past dates'}), 400
    
    # Save attendance for each student
    student_ids = request.form.getlist('student_ids')
    for student_id in student_ids:
        status = request.form.get(f'status_{student_id}')
        if status:
            query(
                """INSERT INTO attendance (student_id, section_id, subject_id, teacher_id, date, status)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE status = %s, marked_at = NOW()""",
                (student_id, section_id, subject_id, teacher_id, attendance_date, status, status)
            )
    
    flash('Attendance saved successfully.', 'success')
    log_activity(session['user_id'], 'SAVE_ATTENDANCE', f'Saved attendance for subject {subject_id}, section {section_id}')
    return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

@teacher_bp.route('/course/<int:subject_id>/<int:section_id>/create-assignment', methods=['POST'])
@login_required(['Teacher'])
def create_assignment(subject_id, section_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    title = request.form.get('title', '').strip()
    instructions = request.form.get('instructions', '')
    due_date = request.form.get('due_date')
    total_marks = request.form.get('total_marks', 100)
    section_ids = request.form.getlist('section_ids')
    
    if not title or not due_date:
        flash('Title and due date are required.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))
    
    assignment_id = query(
        """INSERT INTO assignments (title, instructions, subject_id, teacher_id, due_date, total_marks)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (title, instructions, subject_id, teacher_id, due_date, total_marks)
    )
    
    if assignment_id:
        for sec_id in section_ids:
            query(
                "INSERT IGNORE INTO assignment_sections (assignment_id, section_id) VALUES (%s, %s)",
                (assignment_id, sec_id)
            )
        
        # Notify students
        students = query(
            "SELECT user_id FROM students WHERE section_id IN (%s) AND status = 'Active'" % ','.join(['%s']*len(section_ids)),
            tuple(section_ids),
            fetch=True
        )
        for student in students:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (student['user_id'], f'New assignment: {title} for {subject_id}', 'info', url_for('student.assignments'))
            )
        
        flash('Assignment created successfully.', 'success'),
        log_activity(session['user_id'], 'CREATE_ASSIGNMENT', f'Created assignment: {title}'),
    else:
        flash('Failed to create assignment.', 'danger')

    return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

@teacher_bp.route('/course/<int:subject_id>/<int:section_id>/upload-material', methods=['POST'])
@login_required(['Teacher'])
def upload_material(subject_id, section_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return jsonify({'success': False, 'message': 'Not authorized'}), 403
    
    teacher_id = teacher_record['id']
    
    # Check assignment exists
    assignment = query(
        "SELECT * FROM subject_teachers WHERE teacher_id = %s AND subject_id = %s AND section_id = %s",
        (teacher_id, subject_id, section_id),
        fetch_one=True
    )
    if not assignment:
        return jsonify({'success': False, 'message': 'Not assigned to this course'}), 403
    
    # Handle file upload
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    material_type = request.form.get('material_type', 'PDF')
    external_url = request.form.get('external_url', '').strip()
    file = request.files.get('file')
    
    file_path = None
    if file and file.filename:
        filename = secure_filename(f"{teacher_id}_{subject_id}_{section_id}_{file.filename}")
        upload_path = os.path.join(Config.UPLOAD_FOLDER, 'materials', filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        file.save(upload_path)
        file_path = f'uploads/materials/{filename}'
    
    # Use URL if no file uploaded
    if not file_path and external_url:
        file_path = external_url
    
    if not title or not file_path:
        return jsonify({'success': False, 'message': 'Title and file/URL are required'}), 400
    
    # Insert into course_materials
    material_id = query(
        """INSERT INTO course_materials (teacher_id, subject_id, section_id, title, description, material_type, file_path, external_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (teacher_id, subject_id, section_id, title, description, material_type, file_path)
    )
    
    if not material_id:
        return jsonify({'success': False, 'message': 'Failed to save material'}), 500
    
    # Generate AI summary using Claude
    summary = ''
    try:
        prompt = (
            f"You are a helpful school teacher. Summarize the material '{title}' "
            f"for students. Give: 1) Simple 3-line summary 2) 5 key points 3) One real-world example. "
            "Keep language simple and clear. Format with proper headings using markdown."
        )
        
        # Call Claude API
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': Config.CLAUDE_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': Config.CLAUDE_MODEL,
                'max_tokens': 1024,
                'messages': [{'role': 'user', 'content': prompt}]
            },
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and 'content' in data and data['content']:
                summary = data['content'][0].get('text', '')
    except Exception:
        summary = ''
        # Continue even if AI summary fails
    
    # Update the material with AI summary
    query(
        "UPDATE course_materials SET ai_summary = %s WHERE id = %s",
        (summary, material_id)
    )
    
    # Notify all students in section about new material
    students = query(
        "SELECT user_id FROM students WHERE section_id = %s AND status = 'Active'",
        (section_id,),
        fetch=True
    )
    for student in students:
        query(
            "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
            (student['user_id'], 'New material uploaded in subject_name_name}: {title}', 'info', url_for('teacher.course', subject_id=subject_id, section_id=section_id))
        )
    
    return jsonify({'success': True, 'message': 'Material uploaded and summary generated', 'summary': summary})

@teacher_bp.route('/request-class', methods=['POST'])
@login_required(['Teacher'])
def request_class():
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    class_name = request.form.get('class_name', '').strip()
    grade_id = request.form.get('grade_id')
    section_id = request.form.get('section_id')
    subject_id = request.form.get('subject_id')
    reason = request.form.get('reason', '')
    
    if not all([class_name, grade_id, section_id, subject_id]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('teacher.dashboard'))
    
    query(
        """INSERT INTO class_requests (teacher_id, class_name, grade_id, section_id, subject_id, reason)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (teacher_id, class_name, grade_id, section_id, subject_id, reason)
    )
    
    # Notify FA
    fa_users = query("SELECT user_id FROM fa", fetch=True)
    for fa in fa_users:
        query(
            "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
            (fa['user_id'], f'New class request from teacher {teacher_id}: {class_name}', 'info', url_for('fa.class_requests'))
        )
    
    flash('Class request submitted.', 'success')
    log_activity(session['user_id'], 'REQUEST_CLASS', f'Requested class: {class_name}')
    return redirect(url_for('teacher.dashboard'))

@teacher_bp.route('/attendance', methods=['GET', 'POST'])
@login_required(['Teacher'])
def attendance():
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    # Get grades this teacher teaches
    grades = query(
        """SELECT DISTINCT g.* FROM grades g
           JOIN sections s ON g.id = s.grade_id
           JOIN subject_teachers st ON s.id = st.section_id
           WHERE st.teacher_id = %s
           ORDER BY g.name""",
        (teacher_id,),
        fetch=True
    )
    
    selected_grade = request.args.get('grade_id', type=int) or (request.form.get('grade_id', type=int))
    selected_section = request.args.get('section_id', type=int) or (request.form.get('section_id', type=int))
    selected_subject = request.args.get('subject_id', type=int) or (request.form.get('subject_id', type=int))
    selected_date = request.args.get('date') or request.form.get('date') or date.today().isoformat()
    
    sections = []
    subjects = []
    students = []
    attendance_by_student = {}
    attendance_marked = False
    
    if selected_grade:
        sections = query(
            """SELECT s.* FROM sections s
               JOIN subject_teachers st ON s.id = st.section_id
               WHERE st.teacher_id = %s AND s.grade_id = %s
               ORDER BY s.name""",
            (teacher_id, selected_grade),
            fetch=True
        )
    
    if selected_section:
        subjects = query(
            """SELECT s.* FROM subjects s
               JOIN subject_teachers st ON s.id = st.subject_id
               WHERE st.teacher_id = %s AND st.section_id = %s
               ORDER BY s.subject_name""",
            (teacher_id, selected_section),
            fetch=True
        )
    
    if selected_subject and selected_section:
        students = query(
            """SELECT stu.* FROM students stu
               WHERE stu.section_id = %s AND stu.status = 'Active'
               ORDER BY stu.roll_number""",
            (selected_section,),
            fetch=True
        )
        
        attendance_records = query(
            "SELECT student_id, status FROM attendance WHERE teacher_id = %s AND section_id = %s AND subject_id = %s AND date = %s",
            (teacher_id, selected_section, selected_subject, selected_date),
            fetch=True
        )
        attendance_by_student = {
            record['student_id']: record['status']
            for record in attendance_records or []
        }
        attendance_marked = bool(attendance_by_student)
        
        if request.method == 'POST' and 'save_attendance' in request.form:
            if selected_date != date.today().isoformat():
                flash('Cannot mark attendance for past dates.', 'danger')
            else:
                for student in students:
                    status = request.form.get(f'status_{student["id"]}')
                    if status:
                        query(
                            """INSERT INTO attendance (student_id, section_id, subject_id, teacher_id, date, status)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON DUPLICATE KEY UPDATE status = %s, marked_at = NOW()""",
                            (student['id'], selected_section, selected_subject, teacher_id, selected_date, status, status)
                        )
                flash('Attendance saved successfully.', 'success')
                log_activity(session['user_id'], 'SAVE_ATTENDANCE_FULL', f'Saved attendance for subject {selected_subject}, section {selected_section}')
                return redirect(url_for('teacher.attendance', grade_id=selected_grade, section_id=selected_section, subject_id=selected_subject, date=selected_date))
    
    return render_template('teacher/attendance.html',
                         grades=grades, sections=sections, subjects=subjects, students=students,
                         selected_grade=selected_grade, selected_section=selected_section,
                         selected_subject=selected_subject, selected_date=selected_date,
                         attendance_marked=attendance_marked,
                         attendance_by_student=attendance_by_student,
                         today=date.today().isoformat())

@teacher_bp.route('/submissions/<int:assignment_id>')
@login_required(['Teacher'])
def submissions(assignment_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))

    teacher_id = teacher_record['id']

    assignment = query(
        """SELECT a.*, s.subject_name, sec.name as section_name, g.name as grade_name
           FROM assignments a
           JOIN subjects s ON a.subject_id = s.id
           JOIN assignment_sections acs ON a.id = acs.assignment_id
           JOIN sections sec ON acs.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE a.id = %s AND a.teacher_id = %s""",
        (assignment_id, teacher_id),
        fetch_one=True
    )

    if not assignment:
        flash('Assignment not found.', 'danger')
        return redirect(url_for('teacher.dashboard'))

    students_list = query(
        """SELECT st.student_id, sub.*, stu.name as student_name, stu.roll_number,
                  stu.student_system_id
           FROM assignment_sections acs
           JOIN students stu ON stu.section_id = acs.section_id AND stu.status = 'Active'
           LEFT JOIN submissions sub ON sub.assignment_id = acs.assignment_id AND sub.student_id = stu.id
           WHERE acs.assignment_id = %s
           ORDER BY stu.roll_number""",
        (assignment_id,),
        fetch=True
    )

    return render_template('teacher/submissions.html', assignment=assignment, submissions=students_list)


@teacher_bp.route('/leave-requests')
@login_required(['Teacher'])
def leave_requests():
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))

    teacher_id = teacher_record['id']
    applications = query(
        """SELECT la.*, s.name as student_name, sec.name as section_name,
           g.name as grade_name
           FROM leave_applications la
           JOIN students s ON la.student_id = s.id
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE la.teacher_id = %s OR la.teacher_id IS NULL
           ORDER BY la.created_at DESC""",
        (teacher_id,),
        fetch=True
    )
    return render_template('teacher/leave_requests.html', applications=applications)


@teacher_bp.route('/leave-requests/respond', methods=['POST'])
@login_required(['Teacher'])
def respond_leave_request():
    leave_id = request.form.get('leave_id', type=int)
    action = request.form.get('action')
    note = request.form.get('response_note', '')
    if not leave_id or not action:
        flash('Leave request missing.', 'danger')
        return redirect(url_for('teacher.leave_requests'))

    status = 'Approved' if action == 'approve' else 'Rejected'
    query(
        "UPDATE leave_applications SET status = %s, reviewed_by = %s, reviewed_at = NOW(), response_note = %s WHERE id = %s",
        (status, session['user_id'], note, leave_id)
    )

    leave = query("SELECT * FROM leave_applications WHERE id = %s", (leave_id,), fetch_one=True)
    if leave and status == 'Approved':
        student = query("SELECT * FROM students WHERE id = %s", (leave['student_id'],), fetch_one=True)
        if student:
            start_date = date.fromisoformat(leave['from_date'])
            end_date = date.fromisoformat(leave['to_date'])
            current_date = start_date
            while current_date <= end_date:
                query(
                    "INSERT INTO attendance (student_id, section_id, subject_id, teacher_id, date, status) VALUES (%s, %s, %s, %s, %s, 'Leave') ON DUPLICATE KEY UPDATE status = 'Leave'",
                    (student['id'], student['section_id'], 1, leave['teacher_id'] or 1, current_date.isoformat())
                )
                current_date += timedelta(days=1)
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (student['user_id'], f'Your leave request from {leave["from_date"]} to {leave["to_date"]} was approved.', 'success', url_for('student.leave'))
            )
    elif leave:
        student = query("SELECT * FROM students WHERE id = %s", (leave['student_id'],), fetch_one=True)
        if student:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (student['user_id'], f'Your leave request from {leave["from_date"]} to {leave["to_date"]} was rejected. {note}', 'warning', url_for('student.leave'))
            )

    flash('Leave request status updated.', 'success')
    return redirect(url_for('teacher.leave_requests'))


@teacher_bp.route('/grade-submission', methods=['POST'])
@login_required(['Teacher'])
def grade_submission():
    submission_id = request.form.get('submission_id', type=int)
    marks = request.form.get('marks_obtained', type=float)
    
    if submission_id is not None and marks is not None:
        query(
            "UPDATE submissions SET marks_obtained = %s, graded_by = %s, graded_at = NOW() WHERE id = %s",
            (marks, session['user_id'], submission_id)
        )
        flash('Submission graded.', 'success')
        log_activity(session['user_id'], 'GRADE_SUBMISSION', f'Graded submission {submission_id} with {marks} marks')
    
    return redirect(request.referrer or url_for('teacher.dashboard'))