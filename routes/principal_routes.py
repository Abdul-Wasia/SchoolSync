from flask import Blueprint, render_template, request
from datetime import date, timedelta
from database.connection import query, format_time
from routes.auth_routes import login_required

principal_bp = Blueprint('principal', __name__, url_prefix='/principal')

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
PERIODS = list(range(1, 9))


def _int(value):
    return int(value) if value is not None else 0


def _pct(present, total):
    return round((present / total) * 100, 1) if total else 0


@principal_bp.route('/dashboard')
@login_required(['Principal'])
def dashboard():
    today = date.today()
    today_name = today.strftime('%A')
    selected_section_id = request.args.get('section_id', type=int)

    # ------------------------------------------------------------------
    # Headline statistics
    # ------------------------------------------------------------------
    stats = {
        'students': query(
            "SELECT COUNT(*) as count FROM students WHERE status = 'Active'",
            fetch_one=True
        )['count'],
        'teachers': query("SELECT COUNT(*) as count FROM teachers", fetch_one=True)['count'],
        'sections': query("SELECT COUNT(*) as count FROM sections", fetch_one=True)['count'],
        'subjects': query("SELECT COUNT(*) as count FROM subjects", fetch_one=True)['count'],
        'grades': query("SELECT COUNT(*) as count FROM grades", fetch_one=True)['count'],
    }

    today_attendance = query(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
                  SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
                  SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late,
                  SUM(CASE WHEN status = 'Leave' THEN 1 ELSE 0 END) as leave_count
           FROM attendance
           WHERE date = %s""",
        (today,),
        fetch_one=True
    ) or {}
    present_today = _int(today_attendance.get('present'))
    absent_today = _int(today_attendance.get('absent'))
    late_today = _int(today_attendance.get('late'))
    leave_today = _int(today_attendance.get('leave_count'))
    total_today = _int(today_attendance.get('total'))
    stats['present_today'] = present_today
    stats['absent_today'] = absent_today
    stats['late_today'] = late_today
    stats['leave_today'] = leave_today
    stats['records_today'] = total_today
    stats['attendance_pct'] = _pct(present_today, total_today)
    stats['today_classes'] = query(
        "SELECT COUNT(*) as count FROM timetable WHERE day = %s",
        (today_name,),
        fetch_one=True
    )['count']

    # ------------------------------------------------------------------
    # Sections with their subjects, assigned teachers and today's status
    # ------------------------------------------------------------------
    sections = query(
        """SELECT sec.id, sec.name as section_name, sec.capacity,
                  g.id as grade_id, g.name as grade_name,
                  (SELECT COUNT(*) FROM students stu
                   WHERE stu.section_id = sec.id AND stu.status = 'Active') as student_count
           FROM sections sec
           JOIN grades g ON sec.grade_id = g.id
           ORDER BY g.id, sec.name""",
        fetch=True
    ) or []

    subject_assignments = query(
        """SELECT st.section_id, sub.id as subject_id, sub.subject_name, sub.type,
                  t.id as teacher_id, t.name as teacher_name,
                  CONCAT(g.name, ' - ', sec.name) as section_label
           FROM subject_teachers st
           JOIN subjects sub ON st.subject_id = sub.id
           JOIN teachers t ON st.teacher_id = t.id
           JOIN sections sec ON st.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           ORDER BY st.section_id, sub.subject_name""",
        fetch=True
    ) or []
    subjects_by_section = {}
    for row in subject_assignments:
        subjects_by_section.setdefault(row['section_id'], []).append(row)

    today_by_section = query(
        """SELECT section_id, COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
                  SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent
           FROM attendance
           WHERE date = %s
           GROUP BY section_id""",
        (today,),
        fetch=True
    ) or []
    today_map = {row['section_id']: row for row in today_by_section}

    today_schedule = query(
        """SELECT tt.section_id, tt.period, tt.start_time, tt.end_time, tt.room_type,
                  sub.subject_name, t.name as teacher_name,
                  CONCAT(g.name, ' - ', sec.name) as section_label
           FROM timetable tt
           JOIN subjects sub ON tt.subject_id = sub.id
           JOIN teachers t ON tt.teacher_id = t.id
           JOIN sections sec ON tt.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE tt.day = %s
           ORDER BY tt.period, g.id, sec.name""",
        (today_name,),
        fetch=True
    ) or []
    schedule_by_section = {}
    for slot in today_schedule:
        slot['start_time'] = format_time(slot.get('start_time'))
        slot['end_time'] = format_time(slot.get('end_time'))
        schedule_by_section.setdefault(slot['section_id'], []).append(slot)

    section_cards = []
    for section in sections:
        attendance = today_map.get(section['id'], {})
        present = _int(attendance.get('present'))
        total = _int(attendance.get('total'))
        section_cards.append({
            **section,
            'subjects': subjects_by_section.get(section['id'], []),
            'subject_count': len(subjects_by_section.get(section['id'], [])),
            'today_present': present,
            'today_absent': _int(attendance.get('absent')),
            'today_total': total,
            'today_pct': _pct(present, total),
            'today_schedule': schedule_by_section.get(section['id'], []),
        })

    # ------------------------------------------------------------------
    # Weekly timetable for the selected section
    # ------------------------------------------------------------------
    timetable_sections = [
        {
            'id': section['id'],
            'label': f"{section['grade_name']} - {section['section_name']}",
        }
        for section in sections
    ]
    if not selected_section_id and timetable_sections:
        selected_section_id = timetable_sections[0]['id']

    selected_section = next(
        (card for card in section_cards if card['id'] == selected_section_id),
        None
    )
    weekly_rows = query(
        """SELECT tt.day, tt.period, tt.start_time, tt.end_time, tt.room_type,
                  sub.subject_name, t.name as teacher_name
           FROM timetable tt
           JOIN subjects sub ON tt.subject_id = sub.id
           JOIN teachers t ON tt.teacher_id = t.id
           WHERE tt.section_id = %s
           ORDER BY FIELD(tt.day, 'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'),
                    tt.period""",
        (selected_section_id,),
        fetch=True
    ) or []
    weekly = {day: {} for day in DAYS}
    for slot in weekly_rows:
        slot['start_time'] = format_time(slot.get('start_time'))
        slot['end_time'] = format_time(slot.get('end_time'))
        weekly.setdefault(slot['day'], {})[slot['period']] = slot

    # ------------------------------------------------------------------
    # Attendance analytics (last 30 days)
    # ------------------------------------------------------------------
    section_comparison = query(
        """SELECT sec.id, g.name as grade_name, sec.name as section_name,
                  COUNT(a.id) as total_records,
                  SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count,
                  SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) as absent_count,
                  ROUND(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) / COUNT(a.id) * 100, 1) as avg_percentage
           FROM attendance a
           JOIN sections sec ON a.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE a.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
           GROUP BY sec.id, g.id, g.name, sec.name
           ORDER BY g.id, sec.name""",
        fetch=True
    ) or []
    for row in section_comparison:
        row['total_records'] = _int(row['total_records'])
        row['present_count'] = _int(row['present_count'])
        row['absent_count'] = _int(row['absent_count'])

    subject_attendance = query(
        """SELECT g.name as grade_name, sec.name as section_name,
                  sub.subject_name, t.name as teacher_name,
                  COUNT(a.id) as total_records,
                  SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count,
                  SUM(CASE WHEN a.status = 'Absent' THEN 1 ELSE 0 END) as absent_count,
                  ROUND(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) / COUNT(a.id) * 100, 1) as percentage
           FROM attendance a
           JOIN sections sec ON a.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           JOIN subjects sub ON a.subject_id = sub.id
           JOIN teachers t ON a.teacher_id = t.id
           WHERE a.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
           GROUP BY sec.id, sub.id, g.id, g.name, sec.name, sub.subject_name, t.name
           ORDER BY g.id, sec.name, sub.subject_name""",
        fetch=True
    ) or []
    for row in subject_attendance:
        row['total_records'] = _int(row['total_records'])
        row['present_count'] = _int(row['present_count'])
        row['absent_count'] = _int(row['absent_count'])

    trend_lookup = {
        row['date']: row
        for row in (query(
            """SELECT date, COUNT(*) as total,
                      SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present
               FROM attendance
               WHERE date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
               GROUP BY date""",
            fetch=True
        ) or [])
    }
    trend_data = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        row = trend_lookup.get(day, {})
        total = _int(row.get('total'))
        present = _int(row.get('present'))
        # Sundays and holidays have no records; plotting them as 0% would make
        # the trend look like attendance collapsed every week.
        if not total:
            continue
        trend_data.append({
            'date': day.strftime('%b %d'),
            'total': total,
            'present': present,
            'pct': _pct(present, total),
        })

    # ------------------------------------------------------------------
    # Students, teachers and results
    # ------------------------------------------------------------------
    low_attendance = query(
        """SELECT s.name, s.student_system_id, s.roll_number,
                  sec.name as section_name, g.name as grade_name,
                  COUNT(a.id) as total_classes,
                  SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count,
                  ROUND(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) / COUNT(a.id) * 100, 1) as percentage
           FROM students s
           JOIN sections sec ON s.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           JOIN attendance a ON s.id = a.student_id
           WHERE s.status = 'Active'
           GROUP BY s.id, s.name, s.student_system_id, s.roll_number, g.id, g.name, sec.name
           HAVING percentage < 75
           ORDER BY percentage ASC, s.name
           LIMIT 30""",
        fetch=True
    ) or []

    subject_performance = query(
        """SELECT s.subject_name, g.name as grade_name,
                  COUNT(r.id) as exam_count,
                  ROUND(AVG(r.marks_obtained / r.total_marks * 100), 1) as avg_percentage
           FROM results r
           JOIN subjects s ON r.subject_id = s.id
           JOIN grades g ON s.grade_id = g.id
           GROUP BY s.id, s.subject_name, g.id, g.name
           ORDER BY avg_percentage DESC""",
        fetch=True
    ) or []

    teacher_attendance = {
        row['id']: row
        for row in (query(
            """SELECT t.id,
                      COUNT(ta.id) as days_recorded,
                      SUM(CASE WHEN ta.status = 'Present' THEN 1 ELSE 0 END) as present_days,
                      SUM(CASE WHEN ta.status = 'Absent' THEN 1 ELSE 0 END) as absent_days,
                      SUM(CASE WHEN ta.status = 'Late' THEN 1 ELSE 0 END) as late_days,
                      ROUND(SUM(CASE WHEN ta.status = 'Present' THEN 1 ELSE 0 END) / COUNT(ta.id) * 100, 1) as attendance_pct
               FROM teachers t
               LEFT JOIN teacher_attendance ta ON t.id = ta.teacher_id
                   AND ta.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
               GROUP BY t.id""",
            fetch=True
        ) or [])
    }

    teachers = query(
        """SELECT t.id, t.name, t.subject, t.phone, t.email, t.qualification
           FROM teachers t
           ORDER BY t.name""",
        fetch=True
    ) or []
    for teacher in teachers:
        summary = teacher_attendance.get(teacher['id'], {})
        teacher['days_recorded'] = _int(summary.get('days_recorded'))
        teacher['present_days'] = _int(summary.get('present_days'))
        teacher['absent_days'] = _int(summary.get('absent_days'))
        teacher['late_days'] = _int(summary.get('late_days'))
        teacher['attendance_pct'] = summary.get('attendance_pct')
        teacher['classes'] = [
            row for row in subject_assignments if row['teacher_id'] == teacher['id']
        ]
        teacher['class_count'] = len(teacher['classes'])

    all_students = query(
        """SELECT s.name, s.student_system_id, s.roll_number,
                  sec.name as section_name, g.name as grade_name,
                  COALESCE(stats.total_records, 0) as total_records,
                  COALESCE(stats.present_records, 0) as present_records,
                  stats.percentage
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           LEFT JOIN (
               SELECT student_id, COUNT(*) as total_records,
                      SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_records,
                      ROUND(SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as percentage
               FROM attendance
               GROUP BY student_id
           ) stats ON stats.student_id = s.id
           WHERE s.status = 'Active'
           ORDER BY g.id, sec.name, s.roll_number""",
        fetch=True
    ) or []
    for student in all_students:
        student['total_records'] = _int(student['total_records'])
        student['present_records'] = _int(student['present_records'])
        student['percentage'] = student['percentage'] or 0

    return render_template(
        'principal/dashboard.html',
        stats=stats,
        today=today,
        today_name=today_name,
        section_cards=section_cards,
        timetable_sections=timetable_sections,
        selected_section_id=selected_section_id,
        selected_section=selected_section,
        weekly=weekly,
        days=DAYS,
        periods=PERIODS,
        today_schedule=today_schedule,
        section_comparison=section_comparison,
        subject_attendance=subject_attendance,
        trend_data=trend_data,
        low_attendance=low_attendance,
        subject_performance=subject_performance,
        teachers=teachers,
        all_students=all_students,
        all_teachers=teachers,
    )
