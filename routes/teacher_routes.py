from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, jsonify, abort, send_file
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from database.connection import query, transaction, format_time
from routes.auth_routes import login_required, log_activity
from routes.ai_helper import call_ai, extract_material_text
from routes.leave_workflow import approved_leave_attendance_queries
import os
from pathlib import Path
from config import Config
from security.file_uploads import UploadValidationError, save_validated_upload

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')

def get_teacher_id():
    """Get teacher record ID for current user."""
    return query("SELECT id, name FROM teachers WHERE user_id = %s", (session['user_id'],), fetch_one=True)

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
        """SELECT st.*, s.subject_name, s.type, sec.name as section_name, g.name as grade_name,
              (SELECT COUNT(*)
               FROM students stu
               WHERE stu.section_id = sec.id AND stu.status = 'Active') as student_count,
              (SELECT COUNT(DISTINCT a.id)
               FROM assignments a
               JOIN assignment_sections acs ON acs.assignment_id = a.id
               WHERE a.teacher_id = st.teacher_id AND a.subject_id = st.subject_id
                 AND acs.section_id = st.section_id) as total_assignments,
              (SELECT COUNT(*)
               FROM assignments a
               JOIN assignment_sections acs ON acs.assignment_id = a.id
               JOIN students stu ON stu.section_id = acs.section_id AND stu.status = 'Active'
               WHERE a.teacher_id = st.teacher_id AND a.subject_id = st.subject_id
                 AND acs.section_id = st.section_id AND a.due_date >= NOW()
                 AND NOT EXISTS (
                     SELECT 1 FROM submissions sub
                     WHERE sub.assignment_id = a.id AND sub.student_id = stu.id
                 )) as pending_assignments
           FROM subject_teachers st
           JOIN subjects s ON st.subject_id = s.id
           JOIN sections sec ON st.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE st.teacher_id = %s
           ORDER BY g.name, sec.name, s.subject_name""",
        (teacher_id,),
        fetch=True
    )
    
    # Get latest assignment ID per course for "view submissions" link
    for course in courses:
        latest = query(
            """SELECT a.id FROM assignments a
                    JOIN assignment_sections acs ON acs.assignment_id = a.id
                    WHERE a.teacher_id = %s AND a.subject_id = %s AND acs.section_id = %s
               ORDER BY a.created_at DESC LIMIT 1""",
                (teacher_id, course['subject_id'], course['section_id']),
            fetch_one=True
        )
        course['next_assignment_id'] = latest['id'] if latest else 0
    
    # Today's schedule
    today = date.today()
    day_name = today.strftime('%A')
    schedule = query(
        """SELECT tt.*, s.subject_name, sec.name as section_name,
                  g.name as grade_name,
                  CONCAT(g.name, ' - ', sec.name) as section_label
           FROM timetable tt
           JOIN subjects s ON tt.subject_id = s.id
           JOIN sections sec ON tt.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE tt.teacher_id = %s AND tt.day = %s
           ORDER BY tt.period""",
        (teacher_id, day_name),
        fetch=True
    )
    for slot in (schedule or []):
        slot['start_time'] = format_time(slot.get('start_time'))
        slot['end_time'] = format_time(slot.get('end_time'))
    
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

    # Attendance totals across every class this teacher handles
    attendance_totals = query(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
                  SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
                  SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late,
                  SUM(CASE WHEN status = 'Leave' THEN 1 ELSE 0 END) as leave_count
           FROM attendance
           WHERE teacher_id = %s""",
        (teacher_id,),
        fetch_one=True
    ) or {}
    attendance_totals = {key: int(value or 0) for key, value in attendance_totals.items()}
    attendance_totals['percentage'] = (
        round(attendance_totals['present'] / attendance_totals['total'] * 100, 1)
        if attendance_totals['total'] else 0
    )

    # Per-course attendance totals
    course_attendance = query(
        """SELECT section_id, subject_id, COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present
           FROM attendance
           WHERE teacher_id = %s
           GROUP BY section_id, subject_id""",
        (teacher_id,),
        fetch=True
    ) or []
    course_attendance_map = {
        (row['section_id'], row['subject_id']): row for row in course_attendance
    }
    for course in courses:
        summary = course_attendance_map.get(
            (course['section_id'], course['subject_id']), {}
        )
        course['attendance_total'] = int(summary.get('total') or 0)
        course['attendance_present'] = int(summary.get('present') or 0)
        course['attendance_pct'] = (
            round(course['attendance_present'] / course['attendance_total'] * 100, 1)
            if course['attendance_total'] else 0
        )
    
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
                         teacher_id=teacher_id, teacher_name=teacher_record['name'],
                         courses=courses, schedule=schedule,
                         pending_grading=pending_grading, my_requests=my_requests,
                         attendance_totals=attendance_totals,
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
        """SELECT s.subject_name, s.type, sec.name as section_name, g.name as grade_name, sec.id as section_id, g.id as grade_id
           FROM subjects s
           JOIN sections sec ON %s = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE s.id = %s""",
        (section_id, subject_id),
        fetch_one=True
    )
    
    today = date.today()

    # Get students
    students = query(
        """SELECT stu.*,
                  COALESCE(att.present_total, 0) as present_total,
                  COALESCE(att.absent_total, 0) as absent_total,
                  att.today_status
           FROM students stu
           LEFT JOIN (
               SELECT student_id,
                      SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_total,
                      SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_total,
                      MAX(CASE WHEN date = %s THEN status END) as today_status
               FROM attendance
               WHERE section_id = %s AND subject_id = %s
               GROUP BY student_id
           ) att ON att.student_id = stu.id
           WHERE stu.section_id = %s AND stu.status = 'Active'
           ORDER BY stu.roll_number""",
        (today, section_id, subject_id, section_id),
        fetch=True
    )
    
    # Get assignments for this teacher+section
    assignments = query(
        """SELECT a.* FROM assignments a
           JOIN assignment_sections acs ON a.id = acs.assignment_id
              WHERE a.teacher_id = %s AND acs.section_id = %s AND a.subject_id = %s
           ORDER BY a.due_date DESC""",
          (teacher_id, section_id, subject_id),
        fetch=True
    )

    materials = query(
        """SELECT * FROM course_materials
           WHERE teacher_id = %s AND subject_id = %s AND section_id = %s
           ORDER BY uploaded_at DESC""",
        (teacher_id, subject_id, section_id),
        fetch=True
    ) or []
    for material in materials:
        material['file_available'] = bool(_material_upload_path(material.get('file_path')))

    course_results = query(
        """SELECT r.id, r.exam_type, r.marks_obtained, r.total_marks, r.grade, r.exam_date,
                  stu.name as student_name, stu.roll_number
           FROM results r
           JOIN students stu ON stu.id = r.student_id
           WHERE r.subject_id = %s AND stu.section_id = %s
           ORDER BY r.exam_date DESC, stu.roll_number, stu.name
           LIMIT 100""",
        (subject_id, section_id),
        fetch=True
    ) or []
    
    # Check if attendance already marked today
    attendance_marked = query(
        "SELECT COUNT(*) as count FROM attendance WHERE teacher_id = %s AND section_id = %s AND subject_id = %s AND date = %s",
        (teacher_id, section_id, subject_id, today),
        fetch_one=True
    )['count'] > 0
    
    return render_template('teacher/course.html',
                         course_info=course_info, students=students, assignments=assignments, materials=materials,
                         course_results=course_results,
                         attendance_marked=attendance_marked, teacher_id=teacher_id,
                         subject_id=subject_id, section_id=section_id, now=datetime.now())

@teacher_bp.route('/course/<int:subject_id>/<int:section_id>/save-results', methods=['POST'])
@login_required(['Teacher'])
def save_results(subject_id, section_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        abort(403)

    teacher_id = teacher_record['id']
    assigned_course = query(
        """SELECT id FROM subject_teachers
           WHERE teacher_id = %s AND subject_id = %s AND section_id = %s""",
        (teacher_id, subject_id, section_id),
        fetch_one=True
    )
    if not assigned_course:
        abort(403)

    exam_type = request.form.get('exam_type')
    exam_date_value = request.form.get('exam_date', '')
    if exam_type not in {'Quiz', 'Assignment', 'Mid-Term', 'Final-Term'}:
        flash('Choose a valid exam type.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    try:
        exam_date = date.fromisoformat(exam_date_value)
        total_marks = Decimal(request.form.get('total_marks', '').strip())
    except (TypeError, ValueError, InvalidOperation):
        flash('Enter a valid exam date and total marks.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    if (not total_marks.is_finite() or total_marks <= 0 or total_marks > Decimal('999.99')
            or total_marks.as_tuple().exponent < -2):
        flash('Total marks must be between 0.01 and 999.99, with at most two decimal places.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    try:
        student_ids = {int(value) for value in request.form.getlist('student_ids')}
    except ValueError:
        flash('The student list is invalid.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))
    if not student_ids:
        flash('No students were selected.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    authorized_students = query(
        """SELECT id FROM students
           WHERE section_id = %s AND status = 'Active'""",
        (section_id,),
        fetch=True
    ) or []
    authorized_ids = {student['id'] for student in authorized_students}
    if not student_ids.issubset(authorized_ids):
        abort(403)

    submitted_marks = {}
    for student_id in student_ids:
        raw_mark = request.form.get(f'marks_{student_id}', '').strip()
        if not raw_mark:
            continue
        try:
            mark = Decimal(raw_mark)
        except InvalidOperation:
            flash('Marks must be valid numbers.', 'danger')
            return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))
        if (not mark.is_finite() or mark < 0 or mark > total_marks
                or mark.as_tuple().exponent < -2):
            flash('Each mark must be between zero and the total marks, with at most two decimal places.', 'danger')
            return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))
        submitted_marks[student_id] = mark

    if not submitted_marks:
        flash('Enter marks for at least one student.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    placeholders = ', '.join(['%s'] * len(submitted_marks))
    existing_results = query(
        f"""SELECT id, student_id FROM results
            WHERE subject_id = %s AND exam_type = %s AND exam_date = %s
              AND student_id IN ({placeholders})
            ORDER BY id DESC""",
        (subject_id, exam_type, exam_date, *submitted_marks.keys()),
        fetch=True
    ) or []
    result_ids = {}
    for result in existing_results:
        result_ids.setdefault(result['student_id'], result['id'])

    writes = []
    for student_id, mark in submitted_marks.items():
        existing_id = result_ids.get(student_id)
        if existing_id:
            writes.append((
                """UPDATE results SET marks_obtained = %s, total_marks = %s
                   WHERE id = %s AND student_id = %s AND subject_id = %s""",
                (mark, total_marks, existing_id, student_id, subject_id)
            ))
        else:
            writes.append((
                """INSERT INTO results
                   (student_id, subject_id, exam_type, marks_obtained, total_marks, exam_date)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (student_id, subject_id, exam_type, mark, total_marks, exam_date)
            ))

    if not transaction(writes):
        flash('Results could not be saved. No marks were changed.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    flash(f'Results saved for {len(submitted_marks)} student(s).', 'success')
    log_activity(
        session['user_id'],
        'SAVE_RESULTS',
        f'Saved {exam_type} results for subject {subject_id}, section {section_id}'
    )
    return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

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
    
    submitted_ids = request.form.getlist('student_ids')
    try:
        student_ids = {int(student_id) for student_id in submitted_ids}
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid student selection'}), 400

    authorized_students = query(
        "SELECT id FROM students WHERE section_id = %s AND status = 'Active'",
        (section_id,),
        fetch=True
    ) or []
    authorized_ids = {student['id'] for student in authorized_students}
    if not student_ids.issubset(authorized_ids):
        return jsonify({'success': False, 'message': 'A selected student is outside this course'}), 403

    valid_statuses = {'Present', 'Absent', 'Late', 'Leave'}
    for student_id in student_ids:
        status = request.form.get(f'status_{student_id}')
        if status and status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Invalid attendance status'}), 400
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

    course_assignment = query(
        "SELECT id FROM subject_teachers WHERE teacher_id = %s AND subject_id = %s AND section_id = %s",
        (teacher_id, subject_id, section_id),
        fetch_one=True
    )
    if not course_assignment:
        abort(403)

    title = request.form.get('title', '').strip()
    instructions = request.form.get('instructions', '')
    due_date = request.form.get('due_date')
    total_marks = request.form.get('total_marks', 100)
    requested_section_ids = request.form.getlist('section_ids')
    try:
        section_ids = {int(value) for value in requested_section_ids}
    except ValueError:
        flash('Choose valid course sections.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))

    authorized_sections = query(
        "SELECT section_id FROM subject_teachers WHERE teacher_id = %s AND subject_id = %s",
        (teacher_id, subject_id),
        fetch=True
    ) or []
    authorized_section_ids = {row['section_id'] for row in authorized_sections}
    if not section_ids or section_id not in section_ids or not section_ids.issubset(authorized_section_ids):
        flash('Assignments can only be shared with sections assigned to you for this subject.', 'danger')
        return redirect(url_for('teacher.course', subject_id=subject_id, section_id=section_id))
    
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

    if not title:
        return jsonify({'success': False, 'message': 'A title is required'}), 400
    if not (file and file.filename) and not external_url:
        return jsonify({'success': False, 'message': 'Choose a file or enter an external URL'}), 400
    if external_url and not (file and file.filename) and not external_url.startswith(('http://', 'https://')):
        return jsonify({'success': False, 'message': 'External URLs must start with http:// or https://'}), 400
    
    file_path = None
    if file and file.filename:
        try:
            filename = save_validated_upload(
                file,
                current_app.config.get(
                    'PRIVATE_MATERIALS_FOLDER',
                    os.path.join(current_app.instance_path, 'course_materials')
                ),
                {'pdf', 'docx', 'png', 'jpg', 'jpeg'},
                Config.MAX_CONTENT_LENGTH
            )
        except UploadValidationError as error:
            return jsonify({'success': False, 'message': str(error)}), 400
        except OSError:
            current_app.logger.exception('Unable to store course material for teacher %s', teacher_id)
            return jsonify({'success': False, 'message': 'Unable to store the uploaded file'}), 500
        file_path = f'private/course_materials/{filename}'
        external_url = ''
    
    # Use URL if no file uploaded
    if not file_path and external_url:
        file_path = external_url
    
    # Insert into course_materials
    material_id = query(
        """INSERT INTO course_materials (teacher_id, subject_id, section_id, title, description, material_type, file_path, external_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (teacher_id, subject_id, section_id, title, description, material_type, file_path, external_url or None)
    )
    
    if not material_id:
        return jsonify({'success': False, 'message': 'Failed to save material'}), 500
    
    summary = ''
    material_text = extract_material_text(file_path)
    if material_text:
        summary_result = call_ai(
            f"""Summarize this teacher-uploaded course material for students.
Give a simple explanation, key points, and one practice question.
Use only the source text below and do not invent facts.

Title: {title}
Subject: {subject_id}
Source text:
{material_text}""",
            max_tokens=900
        )
        if summary_result['success']:
            summary = summary_result['text']
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
            (student['user_id'], f'New material uploaded: {title}', 'info', url_for('teacher.course', subject_id=subject_id, section_id=section_id))
        )
    
    material_url = external_url or url_for('teacher.material_file', material_id=material_id)
    return jsonify({
        'success': True,
        'message': 'Material uploaded successfully',
        'material': {
            'id': material_id,
            'title': title,
            'description': description,
            'material_type': material_type,
            'url': material_url
        }
    })


def _material_upload_path(file_path):
    if not file_path:
        return None

    if file_path.startswith('private/course_materials/'):
        filename = file_path.removeprefix('private/course_materials/')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return None
        upload_root = Path(current_app.config.get(
            'PRIVATE_MATERIALS_FOLDER',
            os.path.join(current_app.instance_path, 'course_materials')
        )).resolve()
    elif file_path.startswith('uploads/materials/'):
        filename = file_path.removeprefix('uploads/materials/')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return None
        upload_root = (Path(current_app.static_folder) / 'uploads' / 'materials').resolve()
    else:
        return None

    candidate = (upload_root / filename).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@teacher_bp.route('/material-file/<int:material_id>')
@login_required()
def material_file(material_id):
    material = query(
        """SELECT id, teacher_id, subject_id, section_id, file_path
           FROM course_materials WHERE id = %s""",
        (material_id,),
        fetch_one=True
    )
    if not material:
        abort(404, description='This course material is no longer available. Ask your teacher to upload it again.')

    user_type = session.get('user_type')
    if user_type == 'Teacher':
        teacher_record = get_teacher_id()
        if not teacher_record or teacher_record['id'] != material['teacher_id']:
            abort(404)
        assigned_course = query(
            """SELECT id FROM subject_teachers
               WHERE teacher_id = %s AND subject_id = %s AND section_id = %s""",
            (teacher_record['id'], material['subject_id'], material['section_id']),
            fetch_one=True
        )
        if not assigned_course:
            abort(404)
    elif user_type == 'Student':
        student = query(
            """SELECT id FROM students
               WHERE user_id = %s AND section_id = %s AND status = 'Active'""",
            (session['user_id'], material['section_id']),
            fetch_one=True
        )
        if not student:
            abort(404)
    else:
        abort(404)

    file_path = _material_upload_path(material['file_path'])
    if not file_path:
        abort(404, description='This course material is no longer available. Ask your teacher to upload it again.')

    return send_file(
        file_path,
        as_attachment=request.args.get('download') == '1',
        download_name=file_path.name
    )

@teacher_bp.route('/request-class', methods=['POST'])
@login_required(['Teacher'])
def request_class():
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))
    
    teacher_id = teacher_record['id']
    
    class_name = request.form.get('class_name', '').strip()
    grade_id = request.form.get('grade_id', type=int)
    section_id = request.form.get('section_id', type=int)
    subject_id = request.form.get('subject_id', type=int)
    reason = request.form.get('reason', '')
    
    if not all([class_name, grade_id, section_id, subject_id]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('teacher.dashboard'))

    matching_course = query(
        """SELECT sec.id FROM sections sec
           JOIN subjects sub ON sub.grade_id = sec.grade_id
           WHERE sec.id = %s AND sec.grade_id = %s AND sub.id = %s""",
        (section_id, grade_id, subject_id),
        fetch_one=True
    )
    if not matching_course:
        flash('Choose a subject and section from the selected grade.', 'danger')
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
    today = date.today()

    # Only the classes, sections and courses assigned to this teacher are exposed.
    assigned_courses = query(
        """SELECT DISTINCT st.subject_id, st.section_id, sec.grade_id,
                  sec.name AS section_name, g.name AS grade_name,
                  sub.subject_name
           FROM subject_teachers st
           JOIN sections sec ON sec.id = st.section_id
           JOIN grades g ON g.id = sec.grade_id
           JOIN subjects sub ON sub.id = st.subject_id
           WHERE st.teacher_id = %s
           ORDER BY sec.grade_id, sec.name, sub.subject_name""",
        (teacher_id,),
        fetch=True
    ) or []
    course_lookup = {
        (course['subject_id'], course['section_id']): course
        for course in assigned_courses
    }
    course_groups = []
    for course in assigned_courses:
        if (not course_groups
                or course_groups[-1]['grade_name'] != course['grade_name']
                or course_groups[-1]['section_name'] != course['section_name']):
            course_groups.append({
                'grade_name': course['grade_name'],
                'section_name': course['section_name'],
                'courses': []
            })
        course_groups[-1]['courses'].append(course)

    # The course picker submits a single "subject_id:section_id" value.
    selected_course = (
        request.args.get('course') or request.form.get('course') or ''
    ).strip()
    selected_grade = request.args.get('grade_id', type=int) or request.form.get('grade_id', type=int)
    selected_section = request.args.get('section_id', type=int) or request.form.get('section_id', type=int)
    selected_subject = request.args.get('subject_id', type=int) or request.form.get('subject_id', type=int)
    selected_course_info = None

    if selected_course:
        try:
            course_subject_id, course_section_id = (
                int(part) for part in selected_course.split(':', 1)
            )
        except (TypeError, ValueError):
            abort(400)
        selected_course_info = course_lookup.get((course_subject_id, course_section_id))
        if not selected_course_info:
            abort(403)
    elif selected_subject or selected_section or selected_grade:
        # Backwards-compatible links (e.g. from a course page) still must match
        # a course that is actually assigned to this teacher.
        if not (selected_subject and selected_section):
            abort(403)
        selected_course_info = course_lookup.get((selected_subject, selected_section))
        if not selected_course_info:
            abort(403)

    if selected_course_info:
        selected_grade = selected_course_info['grade_id']
        selected_section = selected_course_info['section_id']
        selected_subject = selected_course_info['subject_id']

    selected_date = request.args.get('date') or request.form.get('date') or today.isoformat()
    try:
        selected_date_value = date.fromisoformat(selected_date)
    except (TypeError, ValueError):
        abort(400)
    selected_date = selected_date_value.isoformat()
    if selected_date_value > today:
        flash('Attendance cannot be viewed or marked for a future date.', 'warning')
        return redirect(url_for('teacher.attendance'))

    students = []
    attendance_by_student = {}
    attendance_marked = False

    if selected_course_info:
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
            if selected_date != today.isoformat():
                flash('Cannot mark attendance for past dates.', 'danger')
            else:
                valid_statuses = {'Present', 'Absent', 'Late', 'Leave'}
                submitted_statuses = [
                    request.form.get(f'status_{student["id"]}')
                    for student in students
                ]
                if any(status and status not in valid_statuses for status in submitted_statuses):
                    abort(400)
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
                return redirect(url_for(
                    'teacher.attendance',
                    course=f'{selected_subject}:{selected_section}',
                    date=selected_date
                ))
    elif request.method == 'POST' and 'save_attendance' in request.form:
        abort(403)

    return render_template('teacher/attendance.html',
                         assigned_courses=assigned_courses,
                         course_groups=course_groups,
                         selected_course_info=selected_course_info,
                         students=students,
                         selected_grade=selected_grade, selected_section=selected_section,
                         selected_subject=selected_subject, selected_date=selected_date,
                         attendance_marked=attendance_marked,
                         attendance_by_student=attendance_by_student,
                         today=today.isoformat())

@teacher_bp.route('/submissions/<int:assignment_id>')
@login_required(['Teacher'])
def submissions(assignment_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        return redirect(url_for('auth.logout'))

    teacher_id = teacher_record['id']

    requested_section_id = request.args.get('section_id', type=int)
    assignment = query(
        """SELECT a.*, s.subject_name, sec.name as section_name, g.name as grade_name,
                  sec.id as section_id
           FROM assignments a
           JOIN subjects s ON a.subject_id = s.id
           JOIN assignment_sections acs ON a.id = acs.assignment_id
           JOIN sections sec ON acs.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           JOIN subject_teachers st ON st.subject_id = a.subject_id
               AND st.section_id = sec.id AND st.teacher_id = a.teacher_id
           WHERE a.id = %s AND a.teacher_id = %s
             AND (%s IS NULL OR sec.id = %s)
           ORDER BY sec.id
           LIMIT 1""",
        (assignment_id, teacher_id, requested_section_id, requested_section_id),
        fetch_one=True
    )

    if not assignment:
        flash('Assignment not found.', 'danger')
        return redirect(url_for('teacher.dashboard'))

    students_list = query(
        """SELECT stu.id as student_id, stu.name as student_name, stu.roll_number,
                  stu.student_system_id, sub.id as submission_id, sub.file_path,
                  sub.text_response, sub.submitted_at, sub.marks_obtained, sub.feedback
           FROM students stu
           LEFT JOIN submissions sub ON sub.id = (
               SELECT sub2.id FROM submissions sub2
               WHERE sub2.assignment_id = %s AND sub2.student_id = stu.id
               ORDER BY sub2.submitted_at DESC, sub2.id DESC
               LIMIT 1
           )
           WHERE stu.section_id = %s AND stu.status = 'Active'
           ORDER BY stu.roll_number, stu.name""",
        (assignment_id, assignment['section_id']),
        fetch=True
    )

    submitted_count = 0
    late_count = 0
    for student in students_list:
        submission = student['submission_id'] is not None
        student['status'] = 'Not Submitted'
        student['file_available'] = False
        if submission:
            submitted_count += 1
            is_late = student['submitted_at'] is not None and student['submitted_at'] > assignment['due_date']
            student['status'] = 'Late' if is_late else 'Submitted'
            late_count += int(is_late)
            student['file_available'] = bool(_submission_upload_path(student['file_path']))

    return render_template(
        'teacher/submissions.html',
        assignment=assignment,
        submissions=students_list,
        total_students=len(students_list),
        submitted_count=submitted_count,
        pending_count=len(students_list) - submitted_count,
        late_count=late_count
    )


def _submission_upload_path(file_path):
    if not file_path:
        return None

    if file_path.startswith('private/submissions/'):
        filename = file_path.removeprefix('private/submissions/')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return None
        upload_root = Path(current_app.config.get(
            'PRIVATE_SUBMISSIONS_FOLDER',
            os.path.join(current_app.instance_path, 'submissions')
        )).resolve()
        candidate = (upload_root / filename).resolve()
    elif file_path.startswith('uploads/submissions/'):
        filename = file_path.removeprefix('uploads/submissions/')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return None
        upload_root = (Path(current_app.static_folder) / 'uploads' / 'submissions').resolve()
        candidate = (upload_root / filename).resolve()
    else:
        return None

    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@teacher_bp.route('/submission-file/<int:submission_id>')
@login_required(['Teacher'])
def submission_file(submission_id):
    teacher_record = get_teacher_id()
    if not teacher_record:
        abort(404)

    submission = query(
        """SELECT sub.file_path
           FROM submissions sub
           JOIN assignments a ON a.id = sub.assignment_id
           JOIN students stu ON stu.id = sub.student_id
           JOIN assignment_sections acs ON acs.assignment_id = a.id
               AND acs.section_id = stu.section_id
           JOIN subject_teachers st ON st.subject_id = a.subject_id
               AND st.section_id = stu.section_id AND st.teacher_id = a.teacher_id
           WHERE sub.id = %s AND a.teacher_id = %s AND st.teacher_id = %s
           LIMIT 1""",
        (submission_id, teacher_record['id'], teacher_record['id']),
        fetch_one=True
    )
    file_path = _submission_upload_path(submission['file_path']) if submission else None
    if not file_path:
        abort(404, description='This submission file is no longer available. Ask the student to submit it again.')

    return send_file(
        file_path,
        as_attachment=request.args.get('download') == '1',
        download_name=file_path.name
    )


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
           WHERE (la.teacher_id = %s OR la.teacher_id IS NULL)
             AND EXISTS (
                 SELECT 1 FROM subject_teachers st
                 WHERE st.teacher_id = %s AND st.section_id = s.section_id
             )
           ORDER BY la.created_at DESC""",
        (teacher_id, teacher_id),
        fetch=True
    )
    return render_template('teacher/leave_requests.html', applications=applications)


@teacher_bp.route('/leave-requests/respond', methods=['POST'])
@login_required(['Teacher'])
def respond_leave_request():
    leave_id = request.form.get('leave_id', type=int)
    action = request.form.get('action')
    note = request.form.get('response_note', '')
    if not leave_id or action not in {'approve', 'reject'}:
        flash('Leave request missing.', 'danger')
        return redirect(url_for('teacher.leave_requests'))

    teacher_record = get_teacher_id()
    if not teacher_record:
        abort(403)
    teacher_id = teacher_record['id']
    leave = query(
        """SELECT la.* FROM leave_applications la
           JOIN students stu ON stu.id = la.student_id
           WHERE la.id = %s AND la.status = 'Pending'
             AND (la.teacher_id = %s OR la.teacher_id IS NULL)
             AND EXISTS (
                 SELECT 1 FROM subject_teachers st
                 WHERE st.teacher_id = %s AND st.section_id = stu.section_id
             )""",
        (leave_id, teacher_id, teacher_id),
        fetch_one=True
    )
    if not leave:
        flash('This leave request is no longer pending or assigned to you.', 'warning')
        return redirect(url_for('teacher.leave_requests'))

    status = 'Approved' if action == 'approve' else 'Rejected'
    student = query(
        "SELECT id, user_id, section_id FROM students WHERE id = %s",
        (leave['student_id'],),
        fetch_one=True
    )
    if not student:
        flash('The student record for this leave request is unavailable.', 'danger')
        return redirect(url_for('teacher.leave_requests'))

    writes = [(
        """UPDATE leave_applications
           SET status = %s, reviewed_by = %s, reviewed_at = NOW(), response_note = %s
           WHERE id = %s AND status = 'Pending'
             AND (teacher_id = %s OR teacher_id IS NULL)""",
        (status, session['user_id'], note, leave_id, teacher_id)
    )]
    attendance_writes = []
    if status == 'Approved':
        attendance_writes = approved_leave_attendance_queries(
            student['id'], student['section_id'], leave['from_date'], leave['to_date']
        )
        writes.extend(attendance_writes)

    if not transaction(writes):
        flash('Leave request could not be updated. No attendance changes were saved.', 'danger')
        return redirect(url_for('teacher.leave_requests'))

    query(
        "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
        (
            student['user_id'],
            f'Your leave application has been {status.lower()}.',
            'success' if status == 'Approved' else 'warning',
            url_for('student.leave')
        )
    )
    if status == 'Approved' and not attendance_writes:
        flash('Leave approved, but no subject assignments were found to update attendance.', 'warning')
    else:
        flash('Leave request status updated.', 'success')
    return redirect(url_for('teacher.leave_requests'))


@teacher_bp.route('/grade-submission', methods=['POST'])
@login_required(['Teacher'])
def grade_submission():
    submission_id = request.form.get('submission_id', type=int)
    marks = request.form.get('marks', type=float)
    feedback = request.form.get('feedback', '').strip()
    teacher_record = get_teacher_id()
    if not teacher_record or submission_id is None or marks is None:
        flash('A valid mark is required.', 'danger')
        return redirect(request.referrer or url_for('teacher.dashboard'))

    submission = query(
        """SELECT a.id as assignment_id, a.total_marks, stu.section_id
           FROM submissions sub
           JOIN assignments a ON a.id = sub.assignment_id
           JOIN students stu ON stu.id = sub.student_id
           JOIN assignment_sections acs ON acs.assignment_id = a.id
               AND acs.section_id = stu.section_id
           JOIN subject_teachers st ON st.subject_id = a.subject_id
               AND st.section_id = stu.section_id AND st.teacher_id = a.teacher_id
           WHERE sub.id = %s AND a.teacher_id = %s AND st.teacher_id = %s
           LIMIT 1""",
        (submission_id, teacher_record['id'], teacher_record['id']),
        fetch_one=True
    )
    if not submission:
        abort(404)
    if marks < 0 or marks > submission['total_marks']:
        flash(f'Marks must be between 0 and {submission["total_marks"]}.', 'danger')
    else:
        query(
            """UPDATE submissions
               SET marks_obtained = %s, feedback = %s, graded_by = %s, graded_at = NOW()
               WHERE id = %s""",
            (marks, feedback or None, session['user_id'], submission_id)
        )
        flash('Marks and feedback saved.', 'success')
        log_activity(session['user_id'], 'GRADE_SUBMISSION', f'Graded submission {submission_id} with {marks} marks')

    return redirect(url_for(
        'teacher.submissions',
        assignment_id=submission['assignment_id'],
        section_id=submission['section_id']
    ))