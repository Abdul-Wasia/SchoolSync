"""Printable documents and quick-alert modules for SchoolSync.

This module is purely additive. It reuses the existing database tables,
session context and authentication helpers without touching existing routes.

Contents:
    * Printable monthly fee challan (browser print / save as PDF)
    * Printable student academic report card
    * Defaulters & fee summary report (Finance / Principal panel)
    * WhatsApp quick-alert link builder used by the templates
"""

import re
from calendar import monthrange
from datetime import date, datetime
from urllib.parse import quote

from flask import Blueprint, abort, render_template, request, session, flash, redirect, url_for

from database.connection import query, normalize_month_key
from routes.auth_routes import login_required


# ---------------------------------------------------------------------------
# Tunable policy values (used for the challan). These are display-only and do
# not require any database change.
# ---------------------------------------------------------------------------
FEE_DUE_DAY = 10            # Day of the month the fee is due
LATE_FEE_FLAT = 200.0       # Flat late-fee fine applied after the due date
PASS_MARK_PERCENTAGE = 40.0  # Minimum percentage to pass a subject / overall

STAFF_ROLES = {'IT_Admin', 'FA', 'Principal', 'GR_Office'}

documents_bp = Blueprint('documents', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_whatsapp_link(phone, message=''):
    """Return a wa.me click-to-chat URL for a parent contact number.

    Local Pakistani numbers such as ``03001234567`` are normalised to the
    international ``923001234567`` form expected by WhatsApp.
    """
    digits = re.sub(r'\D', '', phone or '')
    if not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0'):
        digits = '92' + digits[1:]
    elif not digits.startswith('92') and len(digits) <= 10:
        digits = '92' + digits
    link = 'https://wa.me/' + digits
    if message:
        link += '?text=' + quote(message)
    return link


def _grade_for(percentage):
    """Map a percentage to a letter grade."""
    if percentage is None:
        return '-'
    if percentage >= 90:
        return 'A+'
    if percentage >= 80:
        return 'A'
    if percentage >= 70:
        return 'B'
    if percentage >= 60:
        return 'C'
    if percentage >= 50:
        return 'D'
    return 'F'


def _safe_percentage(obtained, total):
    try:
        obtained = float(obtained or 0)
        total = float(total or 0)
    except (TypeError, ValueError):
        return 0.0
    if total <= 0:
        return 0.0
    return round(obtained / total * 100, 1)


def _load_student(student_id):
    return query(
        """SELECT s.*, sec.name AS section_name, sec.grade_id AS grade_id,
                  g.name AS grade_name
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE s.id = %s""",
        (student_id,),
        fetch_one=True
    )


def _can_view_student(student):
    user_type = session.get('user_type')
    if user_type in STAFF_ROLES or user_type == 'Teacher':
        return True
    if user_type == 'Student':
        own = query(
            "SELECT id FROM students WHERE user_id = %s",
            (session.get('user_id'),),
            fetch_one=True
        )
        return bool(own and own['id'] == student['id'])
    return False


def _resolve_month(raw_month):
    """Return (display_month, month_key, due_date) for a requested month."""
    raw_month = (raw_month or '').strip()
    if not raw_month:
        raw_month = date.today().strftime('%b %Y')
    month_key = normalize_month_key(raw_month)
    try:
        year = int(month_key[:4])
        month = int(month_key[5:7])
    except (ValueError, IndexError):
        today = date.today()
        year, month = today.year, today.month
        month_key = today.strftime('%Y-%m')
    last_day = monthrange(year, month)[1]
    due_day = min(FEE_DUE_DAY, last_day)
    due_date = date(year, month, due_day)
    return raw_month, month_key, due_date


def _lookup_fee_amount(grade_id, month_key):
    """Return the monthly fee amount for a grade, tolerating both schemas."""
    if not grade_id:
        return 0.0
    row = query(
        "SELECT amount FROM fee_structure WHERE grade_id = %s AND month_year = %s LIMIT 1",
        (grade_id, month_key),
        fetch_one=True
    )
    if not row:
        row = query(
            "SELECT amount FROM fee_structure WHERE grade_id = %s ORDER BY id DESC LIMIT 1",
            (grade_id,),
            fetch_one=True
        )
    try:
        return float(row['amount']) if row and row.get('amount') is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fee_status(student_id, month_key, raw_month):
    row = query(
        """SELECT status FROM student_fees
           WHERE student_id = %s AND month_year IN (%s, %s)
           ORDER BY id DESC LIMIT 1""",
        (student_id, month_key, raw_month),
        fetch_one=True
    )
    status = (row or {}).get('status') or 'Unpaid'
    return status


# ---------------------------------------------------------------------------
# 1. Printable Fee Challan
# ---------------------------------------------------------------------------
@documents_bp.route('/fee-challan/<int:student_id>')
@login_required(['IT_Admin', 'FA', 'Principal', 'Student'])
def fee_challan(student_id):
    student = _load_student(student_id)
    if not student:
        abort(404)
    if not _can_view_student(student):
        abort(403)

    raw_month = request.args.get('month', '')
    display_month, month_key, due_date = _resolve_month(raw_month)

    total_fee = _lookup_fee_amount(student.get('grade_id'), month_key)
    status = _fee_status(student_id, month_key, display_month)
    is_paid = status.lower() == 'paid'

    late_fee = 0.0
    if not is_paid and date.today() > due_date:
        late_fee = LATE_FEE_FLAT
    payable = total_fee + late_fee

    return render_template(
        'print/fee_challan.html',
        student=student,
        month=display_month,
        month_key=month_key,
        due_date=due_date,
        total_fee=total_fee,
        late_fee=late_fee,
        payable=payable,
        status='Paid' if is_paid else 'Unpaid',
        issued_on=date.today()
    )


# ---------------------------------------------------------------------------
# 2. Report Card / Result Generator
# ---------------------------------------------------------------------------
@documents_bp.route('/report-card/<int:student_id>')
@login_required(['IT_Admin', 'FA', 'Principal', 'Student'])
def report_card(student_id):
    student = _load_student(student_id)
    if not student:
        abort(404)
    if not _can_view_student(student):
        abort(403)

    exam_type = request.args.get('exam_type')
    params = [student_id]
    sql = """SELECT r.*, sub.subject_name
             FROM results r
             JOIN subjects sub ON r.subject_id = sub.id
             WHERE r.student_id = %s"""
    if exam_type:
        sql += " AND r.exam_type = %s"
        params.append(exam_type)
    sql += " ORDER BY sub.subject_name, r.exam_date"

    rows = query(sql, tuple(params), fetch=True) or []

    subjects = {}
    for row in rows:
        name = row['subject_name']
        entry = subjects.setdefault(name, {
            'subject_name': name,
            'obtained': 0.0,
            'total': 0.0,
            'exams': []
        })
        entry['obtained'] += float(row.get('marks_obtained') or 0)
        entry['total'] += float(row.get('total_marks') or 0)
        entry['exams'].append(row)

    total_obtained = 0.0
    total_max = 0.0
    subject_rows = []
    for name, entry in subjects.items():
        percentage = _safe_percentage(entry['obtained'], entry['total'])
        passed = percentage >= PASS_MARK_PERCENTAGE
        entry['percentage'] = percentage
        entry['grade'] = _grade_for(percentage)
        entry['passed'] = passed
        sub_entry = dict(entry)
        sub_entry.pop('exams', None)
        subject_rows.append(sub_entry)
        total_obtained += entry['obtained']
        total_max += entry['total']

    subject_rows.sort(key=lambda item: item['subject_name'])
    overall_percentage = _safe_percentage(total_obtained, total_max)
    overall_passed = bool(subject_rows) and all(item['passed'] for item in subject_rows)
    overall_grade = _grade_for(overall_percentage)

    return render_template(
        'print/report_card.html',
        student=student,
        subject_rows=subject_rows,
        total_obtained=round(total_obtained, 2),
        total_max=round(total_max, 2),
        overall_percentage=overall_percentage,
        overall_grade=overall_grade,
        overall_passed=overall_passed,
        exam_type=exam_type,
        issued_on=date.today()
    )


# ---------------------------------------------------------------------------
# 4. Defaulters & Fee Summary Report
# ---------------------------------------------------------------------------
@documents_bp.route('/defaulters')
@login_required(['IT_Admin', 'FA', 'Principal'])
def defaulters():
    raw_month = request.args.get('month', '')
    display_month, month_key, _ = _resolve_month(raw_month)
    grade_id = request.args.get('grade_id', type=int)
    section_id = request.args.get('section_id', type=int)

    sql = """SELECT s.id, s.name, s.student_system_id, s.roll_number,
                    s.parent_contact, s.father_name,
                    sec.name AS section_name, sec.grade_id AS grade_id,
                    g.name AS grade_name,
                    COALESCE(fs.amount, 0) AS fee_amount,
                    COALESCE(sf.status, 'Unpaid') AS fee_status
             FROM students s
             LEFT JOIN sections sec ON s.section_id = sec.id
             LEFT JOIN grades g ON sec.grade_id = g.id
             LEFT JOIN (
                 SELECT grade_id, MAX(amount) AS amount
                 FROM fee_structure GROUP BY grade_id
             ) fs ON fs.grade_id = g.id
             LEFT JOIN student_fees sf
                 ON sf.student_id = s.id AND sf.month_year IN (%s, %s)
             WHERE s.status = 'Active'"""
    params = [month_key, display_month]

    if grade_id:
        sql += " AND g.id = %s"
        params.append(grade_id)
    if section_id:
        sql += " AND s.section_id = %s"
        params.append(section_id)
    sql += " ORDER BY g.name, sec.name, s.roll_number"

    students = query(sql, tuple(params), fetch=True) or []

    defaulters = [s for s in students if (s.get('fee_status') or '').lower() != 'paid']
    total_outstanding = sum(float(s.get('fee_amount') or 0) for s in defaulters)
    total_expected = sum(float(s.get('fee_amount') or 0) for s in students)
    total_collected = total_expected - total_outstanding

    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    sections = query("SELECT * FROM sections ORDER BY name", fetch=True)

    return render_template(
        'fa/defaulters.html',
        defaulters=defaulters,
        students=students,
        total_outstanding=total_outstanding,
        total_collected=total_collected,
        total_expected=total_expected,
        selected_month=display_month,
        grade_id=grade_id,
        section_id=section_id,
        grades=grades,
        sections=sections
    )


# ---------------------------------------------------------------------------
# 5. Documents Center (staff picker for report cards / fee challans)
# ---------------------------------------------------------------------------
EXAM_TYPES = ['Quiz', 'Assignment', 'Mid-Term', 'Final-Term']


@documents_bp.route('/documents')
@login_required(['IT_Admin', 'FA', 'Principal'])
def index():
    """Staff-facing directory to quickly open documents for any student."""
    raw_month = request.args.get('month', '')
    display_month, month_key, _ = _resolve_month(raw_month)
    grade_id = request.args.get('grade_id', type=int)
    section_id = request.args.get('section_id', type=int)
    search = request.args.get('search', '').strip()
    exam_type = request.args.get('exam_type', '').strip()

    sql = """SELECT s.id, s.name, s.student_system_id, s.roll_number,
                    s.parent_contact, s.father_name,
                    sec.name AS section_name, g.name AS grade_name
             FROM students s
             LEFT JOIN sections sec ON s.section_id = sec.id
             LEFT JOIN grades g ON sec.grade_id = g.id
             WHERE s.status = 'Active'"""
    params = []

    if grade_id:
        sql += " AND g.id = %s"
        params.append(grade_id)
    if section_id:
        sql += " AND s.section_id = %s"
        params.append(section_id)
    if search:
        sql += " AND (s.name LIKE %s OR s.student_system_id LIKE %s OR s.roll_number LIKE %s)"
        params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
    sql += " ORDER BY g.name, sec.name, s.roll_number"

    students = query(sql, tuple(params), fetch=True) or []
    grades = query("SELECT * FROM grades ORDER BY name", fetch=True)
    sections = query("SELECT * FROM sections ORDER BY name", fetch=True)

    return render_template(
        'documents/index.html',
        students=students,
        grades=grades,
        sections=sections,
        selected_month=display_month,
        month_key=month_key,
        grade_id=grade_id,
        section_id=section_id,
        search=search,
        exam_type=exam_type,
        exam_types=EXAM_TYPES
    )


# ---------------------------------------------------------------------------
# 6. Official Student Certificate Generator (Bonafide, Character, Transfer)
# ---------------------------------------------------------------------------
CERTIFICATE_TYPES = ['Bonafide', 'Character', 'Transfer', 'Leaving']


@documents_bp.route('/certificate/<int:student_id>')
@login_required(['IT_Admin', 'GR_Office', 'FA', 'Principal', 'Student'])
def certificate(student_id):
    student = _load_student(student_id)
    if not student:
        abort(404)
    if not _can_view_student(student):
        abort(403)

    cert_type = request.args.get('type', 'Bonafide').strip().capitalize()
    if cert_type not in CERTIFICATE_TYPES:
        cert_type = 'Bonafide'
    reason = request.args.get('reason', 'Official Purposes and Records').strip()

    att_row = query(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present
           FROM attendance WHERE student_id = %s""",
        (student_id,),
        fetch_one=True
    ) or {}
    total_att = int(att_row.get('total') or 0)
    present_att = int(att_row.get('present') or 0)
    attendance_pct = _safe_percentage(present_att, total_att) if total_att > 0 else 100.0

    existing_cert = query(
        """SELECT * FROM student_certificates
           WHERE student_id = %s AND certificate_type = %s
           ORDER BY id DESC LIMIT 1""",
        (student_id, cert_type),
        fetch_one=True
    )
    if existing_cert:
        cert_number = existing_cert['certificate_number']
        issued_date = existing_cert['issued_date']
    else:
        year = date.today().year
        cert_number = f"SS-{year}-{cert_type[:3].upper()}-{student['id']:04d}"
        issued_date = date.today()
        if session.get('user_type') in {'IT_Admin', 'GR_Office', 'FA', 'Principal'}:
            query(
                """INSERT INTO student_certificates
                   (certificate_number, student_id, certificate_type, reason, issued_date, issued_by)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE reason = VALUES(reason)""",
                (cert_number, student_id, cert_type, reason, issued_date, session.get('user_id'))
            )

    return render_template(
        'print/certificate.html',
        student=student,
        cert_type=cert_type,
        cert_number=cert_number,
        issued_date=issued_date,
        reason=reason,
        attendance_pct=attendance_pct
    )


# ---------------------------------------------------------------------------
# 7. Class Monthly Attendance Register (Master Sheet 1-31 Matrix)
# ---------------------------------------------------------------------------
@documents_bp.route('/attendance-register')
@login_required(['IT_Admin', 'FA', 'Principal', 'Teacher'])
def attendance_register():
    raw_month = request.args.get('month', '')
    display_month, month_key, _ = _resolve_month(raw_month)
    section_id = request.args.get('section_id', type=int)

    sections = query(
        """SELECT sec.id, sec.name as section_name, g.id as grade_id, g.name as grade_name
           FROM sections sec
           JOIN grades g ON sec.grade_id = g.id
           ORDER BY g.id, sec.name""",
        fetch=True
    ) or []

    if not section_id and sections:
        section_id = sections[0]['id']

    selected_section = next((s for s in sections if s['id'] == section_id), None)

    try:
        year = int(month_key[:4])
        month = int(month_key[5:7])
    except (ValueError, IndexError):
        today = date.today()
        year, month = today.year, today.month
    num_days = monthrange(year, month)[1]
    days_range = list(range(1, num_days + 1))

    students = query(
        """SELECT id, name, roll_number, student_system_id
           FROM students
           WHERE section_id = %s AND status = 'Active'
           ORDER BY roll_number, name""",
        (section_id,),
        fetch=True
    ) or []

    start_date = f"{month_key}-01"
    end_date = f"{month_key}-{num_days:02d}"
    records = query(
        """SELECT student_id, DAY(date) as day_num, status
           FROM attendance
           WHERE section_id = %s AND date >= %s AND date <= %s""",
        (section_id, start_date, end_date),
        fetch=True
    ) or []

    att_map = {}
    for r in records:
        att_map.setdefault(r['student_id'], {})[r['day_num']] = r['status']

    matrix_rows = []
    total_p_all = 0
    total_marked_all = 0
    for stu in students:
        s_id = stu['id']
        daily = {}
        p_count = 0
        a_count = 0
        l_count = 0
        v_count = 0
        for day in days_range:
            st = att_map.get(s_id, {}).get(day)
            daily[day] = st
            if st == 'Present':
                p_count += 1
            elif st == 'Absent':
                a_count += 1
            elif st == 'Late':
                l_count += 1
            elif st == 'Leave':
                v_count += 1

        marked_total = p_count + a_count + l_count + v_count
        pct = round((p_count / marked_total * 100), 1) if marked_total > 0 else 0.0
        total_p_all += p_count
        total_marked_all += marked_total

        matrix_rows.append({
            'student': stu,
            'daily': daily,
            'present': p_count,
            'absent': a_count,
            'late': l_count,
            'leave': v_count,
            'total_marked': marked_total,
            'percentage': pct
        })

    overall_pct = round((total_p_all / total_marked_all * 100), 1) if total_marked_all > 0 else 0.0

    return render_template(
        'documents/attendance_register.html',
        sections=sections,
        section_id=section_id,
        selected_section=selected_section,
        selected_month=display_month,
        month_key=month_key,
        days_range=days_range,
        num_days=num_days,
        matrix_rows=matrix_rows,
        overall_pct=overall_pct
    )


# ---------------------------------------------------------------------------
# 8. Student Conduct & Commendation Logs
# ---------------------------------------------------------------------------
@documents_bp.route('/student/<int:student_id>/conduct')
@login_required()
def student_conduct(student_id):
    student = _load_student(student_id)
    if not student:
        abort(404)
    if not _can_view_student(student):
        abort(403)

    logs = query(
        """SELECT l.*, u.username as recorded_by_name, u.user_type as recorded_by_role
           FROM student_conduct_logs l
           JOIN users u ON l.recorded_by = u.id
           WHERE l.student_id = %s
           ORDER BY l.incident_date DESC, l.created_at DESC""",
        (student_id,),
        fetch=True
    ) or []

    is_staff = session.get('user_type') in {'IT_Admin', 'FA', 'Principal', 'Teacher'}

    return render_template(
        'documents/student_conduct.html',
        student=student,
        logs=logs,
        is_staff=is_staff
    )


@documents_bp.route('/student/<int:student_id>/conduct/add', methods=['POST'])
@login_required(['IT_Admin', 'FA', 'Principal', 'Teacher'])
def add_student_conduct(student_id):
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    log_type = request.form.get('log_type', 'Commendation').strip()
    incident_date = request.form.get('incident_date') or date.today().isoformat()

    if not title or not description:
        flash('Title and description are required.', 'danger')
        return redirect(url_for('documents.student_conduct', student_id=student_id))

    valid_types = {'Commendation', 'Achievement', 'Discipline_Warning', 'Attendance_Notice'}
    if log_type not in valid_types:
        log_type = 'Commendation'

    query(
        """INSERT INTO student_conduct_logs
           (student_id, recorded_by, log_type, title, description, incident_date)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (student_id, session['user_id'], log_type, title, description, incident_date)
    )

    flash('Student conduct record logged successfully.', 'success')
    return redirect(url_for('documents.student_conduct', student_id=student_id))

