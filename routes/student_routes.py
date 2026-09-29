from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, date
from database.connection import query
from routes.auth_routes import login_required, log_activity
import os
from werkzeug.utils import secure_filename
from config import Config


def month_list():
    months = []
    current = date.today().replace(day=1)
    for _ in range(12):
        months.append(current.strftime('%b %Y'))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months

student_bp = Blueprint('student', __name__, url_prefix='/student')

def get_student_record():
    """Get student record for current user."""
    return query(
        """SELECT s.*, sec.name as section_name, g.name as grade_name, g.id as grade_id
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE s.user_id = %s""",
        (session['user_id'],),
        fetch_one=True
    )

@student_bp.route('/dashboard')
@login_required(['Student'])
def dashboard():
    student = get_student_record()
    if not student:
        flash('Student profile not found.', 'danger')
        return redirect(url_for('auth.logout'))
    
    if student['status'] == 'PendingLogin':
        return render_template('student/pending.html', student=student)
    
    section_id = student['section_id']
    
    # Overall attendance stats
    attendance_stats = query(
        """SELECT 
              COUNT(*) as total,
              SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
              SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
              SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late,
              SUM(CASE WHEN status = 'Leave' THEN 1 ELSE 0 END) as leave
           FROM attendance
           WHERE student_id = %s""",
        (student['id'],),
        fetch_one=True
    )
    if not attendance_stats:
        attendance_stats = {'total': 0, 'present': 0, 'absent': 0, 'late': 0, 'leave': 0}
    
    # Pending assignments
    pending_assignments = 0
    if section_id:
        pending_result = query(
            """SELECT COUNT(*) as count
               FROM assignments a
               JOIN assignment_sections acs ON a.id = acs.assignment_id
               LEFT JOIN submissions sub ON sub.assignment_id = a.id AND sub.student_id = %s
               WHERE acs.section_id = %s AND a.due_date >= NOW() AND sub.id IS NULL""",
            (student['id'], section_id),
            fetch_one=True
        )
        pending_assignments = pending_result['count'] if pending_result else 0
    
    # Course list
    courses = []
    if section_id:
        courses = query(
            """SELECT st.*, s.subject_name, s.id as subject_id
               FROM subject_teachers st
               JOIN subjects s ON st.subject_id = s.id
               WHERE st.section_id = %s
               ORDER BY s.subject_name""",
            (section_id,),
            fetch=True
        )
    
    # Latest announcements
    announcements = query(
        """SELECT a.* FROM announcements a
           WHERE a.is_active = 1 
           AND (a.target_role = 'All' OR a.target_role = 'Student')
           AND (a.grade_id IS NULL OR a.grade_id = %s)
           AND (a.section_id IS NULL OR a.section_id = %s)
           ORDER BY a.created_at DESC LIMIT 5""",
        (student['grade_id'], section_id),
        fetch=True
    )
    
    return render_template('student/dashboard.html', student=student, attendance_stats=attendance_stats,
                         pending_assignments=pending_assignments, courses=courses, announcements=announcements)

@student_bp.route('/attendance')
@login_required(['Student'])
def attendance():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    
    section_id = student['section_id']
    subject_id = request.args.get('subject_id', type=int)
    
    # Get all subjects for this section
    subjects = query(
        """SELECT s.*, st.teacher_id, t.name as teacher_name
           FROM subjects s
           JOIN subject_teachers st ON s.id = st.subject_id AND st.section_id = %s
           JOIN teachers t ON st.teacher_id = t.id
           ORDER BY s.subject_name""",
        (section_id,),
        fetch=True
    ) if section_id else []
    
    # Calculate attendance for each subject
    for sub in subjects:
        stats = query(
            """SELECT 
                  COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
                  SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
                  SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late,
                  SUM(CASE WHEN status = 'Leave' THEN 1 ELSE 0 END) as leave
               FROM attendance
               WHERE student_id = %s AND subject_id = %s""",
            (student['id'], sub['id']),
            fetch_one=True
        )
        if not stats:
            stats = {'total': 0, 'present': 0, 'absent': 0, 'late': 0, 'leave': 0}
        sub['stats'] = stats
        total = stats.get('total') or 0
        present = stats.get('present') or 0
        if total > 0:
            sub['percentage'] = round((present / total) * 100, 1)
        else:
            sub['percentage'] = 0
    
    # Detailed view for selected subject
    detailed_records = []
    if subject_id:
        detailed_records = query(
            """SELECT a.*, s.subject_name
               FROM attendance a
               JOIN subjects s ON a.subject_id = s.id
               WHERE a.student_id = %s AND a.subject_id = %s
               ORDER BY a.date DESC""",
            (student['id'], subject_id),
            fetch=True
        )
    
    return render_template('student/attendance.html', student=student, subjects=subjects,
                         detailed_records=detailed_records, selected_subject=subject_id)

@student_bp.route('/assignments')
@login_required(['Student'])
def assignments():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    
    section_id = student['section_id']
    if not section_id:
        return render_template('student/assignments.html', student=student, assignments=[])
    
    assignments_list = query(
        """SELECT a.*, s.subject_name,
              CASE 
                  WHEN sub.id IS NOT NULL THEN 'Submitted'
                  WHEN a.due_date < NOW() THEN 'Overdue'
                  ELSE 'Pending'
              END as status,
              sub.marks_obtained, sub.submitted_at
           FROM assignments a
           JOIN subjects s ON a.subject_id = s.id
           JOIN assignment_sections acs ON a.id = acs.assignment_id
           LEFT JOIN submissions sub ON sub.assignment_id = a.id AND sub.student_id = %s
           WHERE acs.section_id = %s
           ORDER BY a.due_date""",
        (student['id'], section_id),
        fetch=True
    )
    
    return render_template('student/assignments.html', student=student, assignments=assignments_list)

@student_bp.route('/submit/<int:assignment_id>', methods=['POST'])
@login_required(['Student'])
def submit_assignment(assignment_id):
    student = get_student_record()
    if not student:
        return redirect(url_for('auth.logout'))
    
    text_response = request.form.get('text_response', '')
    file = request.files.get('file')
    file_path = None
    
    if file and file.filename:
        filename = secure_filename(f"{student['id']}_{assignment_id}_{file.filename}")
        upload_path = os.path.join(Config.UPLOAD_FOLDER, 'submissions', filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        file.save(upload_path)
        file_path = f'uploads/submissions/{filename}'
    
    query(
        """INSERT INTO submissions (assignment_id, student_id, file_path, text_response, submitted_at)
           VALUES (%s, %s, %s, %s, NOW())
           ON DUPLICATE KEY UPDATE file_path = %s, text_response = %s, submitted_at = NOW()""",
        (assignment_id, student['id'], file_path, text_response, file_path, text_response)
    )
    
    flash('Assignment submitted successfully.', 'success')
    log_activity(session['user_id'], 'SUBMIT_ASSIGNMENT', f'Submitted assignment {assignment_id}')
    return redirect(url_for('student.assignments'))

@student_bp.route('/courses')
@login_required(['Student'])
def courses():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    
    section_id = student['section_id']
    if not section_id:
        return render_template('student/courses.html', student=student, courses=[])
    
    courses_list = query(
        """SELECT st.*, s.subject_name, s.id as subject_id, s.type as subject_type,
                  t.name as teacher_name
           FROM subject_teachers st
           JOIN subjects s ON st.subject_id = s.id
           JOIN teachers t ON st.teacher_id = t.id
           WHERE st.section_id = %s
           ORDER BY s.subject_name""",
        (section_id,),
        fetch=True
    )
    
    # Get latest announcements
    announcements = query(
        """SELECT a.* FROM announcements a
           WHERE a.is_active = 1 
           AND (a.target_role = 'All' OR a.target_role = 'Student')
           AND (a.grade_id IS NULL OR a.grade_id = %s)
           AND (a.section_id IS NULL OR a.section_id = %s)
           ORDER BY a.created_at DESC LIMIT 3""",
        (student['grade_id'], section_id),
        fetch=True
    )
    
    return render_template('student/courses.html', student=student, courses=courses_list, announcements=announcements)

@student_bp.route('/results')
@login_required(['Student'])
def results():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))

    results = query(
        """SELECT r.*, s.subject_name, s.type as subject_type
           FROM results r
           JOIN subjects s ON r.subject_id = s.id
           WHERE r.student_id = %s
           ORDER BY r.exam_date DESC, s.subject_name""",
        (student['id'],),
        fetch=True
    )

    grouped = {}
    for r in results:
        if r['subject_name'] not in grouped:
            grouped[r['subject_name']] = []
        grouped[r['subject_name']].append(r)

    return render_template('student/results.html', student=student, grouped_results=grouped)


@student_bp.route('/fees')
@login_required(['Student'])
def fees():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))

    months = month_list()
    records = query(
        """SELECT * FROM student_fees WHERE student_id = %s ORDER BY STR_TO_DATE(CONCAT('01 ', month_year), '%d %b %Y') DESC""",
        (student['id'],),
        fetch=True
    )
    fee_map = {row['month_year']: row for row in records}

    return render_template('student/fees.html', student=student, months=months, fee_map=fee_map)


@student_bp.route('/leave', methods=['GET', 'POST'])
@login_required(['Student'])
def leave():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))

    if request.method == 'POST':
        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')
        reason = request.form.get('reason', '').strip()
        if not from_date or not to_date or not reason:
            flash('Please fill all leave fields.', 'danger')
            return redirect(url_for('student.leave'))
        teacher = query("SELECT teacher_id FROM subject_teachers WHERE section_id = %s LIMIT 1", (student['section_id'],), fetch_one=True)
        leave_id = query(
            "INSERT INTO leave_applications (student_id, teacher_id, from_date, to_date, reason) VALUES (%s, %s, %s, %s, %s)",
            (student['id'], teacher['teacher_id'] if teacher else None, from_date, to_date, reason)
        )
        teacher_user = query("SELECT user_id FROM teachers WHERE id = %s", (teacher['teacher_id'] if teacher else None,), fetch_one=True)
        if teacher_user:
            query(
                "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                (teacher_user['user_id'], f'Student {student["name"]} applied for leave {from_date} to {to_date}', 'info', url_for('teacher.leave_requests'))
            )
        flash('Leave application submitted.', 'success')
        return redirect(url_for('student.leave'))

    applications = query(
        "SELECT * FROM leave_applications WHERE student_id = %s ORDER BY created_at DESC",
        (student['id'],),
        fetch=True
    )
    return render_template('student/leave.html', student=student, applications=applications)


@student_bp.route('/id-card')
@login_required(['Student'])
def id_card():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    return render_template('student/id_card.html', student=student)


@student_bp.route('/exam-schedule')
@login_required(['Student'])
def exam_schedule():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))

    exams = query(
        """SELECT es.*, s.subject_name
           FROM exam_schedule es
           JOIN subjects s ON es.subject_id = s.id
           WHERE es.grade_id = %s
           ORDER BY es.exam_date ASC""",
        (student['grade_id'],),
        fetch=True
    )
    return render_template('student/exam_schedule.html', student=student, exams=exams)

@student_bp.route('/timetable')
@login_required(['Student'])
def timetable():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    
    section_id = student['section_id']
    if not section_id:
        return render_template('student/timetable.html', student=student, timetable={})
    
    timetable_data = query(
        """SELECT tt.*, s.subject_name, t.name as teacher_name, tt.start_time, tt.end_time
           FROM timetable tt
           JOIN subjects s ON tt.subject_id = s.id
           JOIN teachers t ON tt.teacher_id = t.id
           WHERE tt.section_id = %s
           ORDER BY FIELD(tt.day, 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'), tt.period""",
        (section_id,),
        fetch=True
    )
    
    # Organize by day
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    organized = {day: [] for day in days}
    for slot in timetable_data:
        organized[slot['day']].append(slot)
    
    return render_template('student/timetable.html', student=student, timetable=organized, days=days)

@student_bp.route('/homework')
@login_required(['Student'])
def homework():
    student = get_student_record()
    if not student or student['status'] == 'PendingLogin':
        return redirect(url_for('student.dashboard'))
    
    section_id = student['section_id']
    if not section_id:
        return render_template('student/homework.html', student=student, homework_list=[])
    
    homework_list = query(
        """SELECT h.*, s.subject_name,
              CASE 
                  WHEN hs.id IS NOT NULL THEN 'Submitted'
                  WHEN h.due_date < NOW() THEN 'Overdue'
                  ELSE 'Pending'
              END as status,
              hs.marks_obtained, hs.submitted_at
           FROM homework h
           JOIN subjects s ON h.subject_id = s.id
           LEFT JOIN homework_submissions hs ON hs.homework_id = h.id AND hs.student_id = %s
           WHERE h.section_id = %s
           ORDER BY h.due_date""",
        (student['id'], section_id),
        fetch=True
    )
    
    return render_template('student/homework.html', student=student, homework_list=homework_list)

@student_bp.route('/submit-homework/<int:homework_id>', methods=['POST'])
@login_required(['Student'])
def submit_homework(homework_id):
    student = get_student_record()
    if not student:
        return redirect(url_for('auth.logout'))
    
    text_response = request.form.get('text_response', '')
    file = request.files.get('file')
    file_path = None
    
    if file and file.filename:
        filename = secure_filename(f"{student['id']}_{homework_id}_{file.filename}")
        upload_path = os.path.join(Config.UPLOAD_FOLDER, 'submissions', filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        file.save(upload_path)
        file_path = f'uploads/submissions/{filename}'
    
    query(
        """INSERT INTO homework_submissions (homework_id, student_id, file_path, text_response, submitted_at)
           VALUES (%s, %s, %s, %s, NOW())
           ON DUPLICATE KEY UPDATE file_path = %s, text_response = %s, submitted_at = NOW()""",
        (homework_id, student['id'], file_path, text_response, file_path, text_response)
    )
    
    flash('Homework submitted successfully.', 'success')
    log_activity(session['user_id'], 'SUBMIT_HOMEWORK', f'Submitted homework {homework_id}')
    return redirect(url_for('student.homework'))