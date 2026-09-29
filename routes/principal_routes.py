from flask import Blueprint, render_template
from datetime import date, timedelta
from database.connection import query
from routes.auth_routes import login_required

principal_bp = Blueprint('principal', __name__, url_prefix='/principal')

@principal_bp.route('/dashboard')
@login_required(['Principal'])
def dashboard():
    # Basic stats
    stats = {
        'students': query("SELECT COUNT(*) as count FROM students WHERE status = 'Active'", fetch_one=True)['count'],
        'teachers': query("SELECT COUNT(*) as count FROM teachers", fetch_one=True)['count'],
        'sections': query("SELECT COUNT(*) as count FROM sections", fetch_one=True)['count'],
    }
    
    # Today's attendance percentage
    today = date.today()
    today_attendance = query(
        """SELECT 
              COUNT(*) as total,
              SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present
           FROM attendance
           WHERE date = %s""",
        (today,),
        fetch_one=True
    )
    stats['attendance_pct'] = round((today_attendance['present'] / today_attendance['total'] * 100) if today_attendance['total'] > 0 else 0, 1)
    
    # Low attendance students (< 75%)
    low_attendance = query(
        """SELECT s.name, s.student_system_id, sec.name as section_name, g.name as grade_name,
              COUNT(a.id) as total_classes,
              SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count,
              ROUND(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) / COUNT(a.id) * 100, 1) as percentage
           FROM students s
           JOIN sections sec ON s.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           JOIN attendance a ON s.id = a.student_id
           WHERE s.status = 'Active'
           GROUP BY s.id
           HAVING percentage < 75
           ORDER BY percentage ASC
           LIMIT 20""",
        fetch=True
    )
    
    # Attendance trend last 30 days
    trend_data = []
    for i in range(29, -1, -1):
        d = date.today() - timedelta(days=i)
        day_data = query(
            """SELECT 
                  COUNT(*) as total,
                  SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present
               FROM attendance
               WHERE date = %s""",
            (d,),
            fetch_one=True
        )
        trend_data.append({
            'date': d.strftime('%b %d'),
            'total': day_data['total'] or 0,
            'present': day_data['present'] or 0,
            'pct': round((day_data['present'] / day_data['total'] * 100) if day_data['total'] > 0 else 0, 1)
        })
    
    # Section comparison
    section_comparison = query(
        """SELECT g.name as grade_name, sec.name as section_name,
              COUNT(DISTINCT a.student_id) as students_tracked,
              COUNT(a.id) as total_records,
              SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) as present_count,
              ROUND(SUM(CASE WHEN a.status = 'Present' THEN 1 ELSE 0 END) / COUNT(a.id) * 100, 1) as avg_percentage
           FROM attendance a
           JOIN students s ON a.student_id = s.id
           JOIN sections sec ON a.section_id = sec.id
           JOIN grades g ON sec.grade_id = g.id
           WHERE a.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
           GROUP BY sec.id
           ORDER BY avg_percentage DESC""",
        fetch=True
    )
    
    # Subject performance (average marks)
    subject_performance = query(
        """SELECT s.subject_name, g.name as grade_name,
              COUNT(r.id) as exam_count,
              ROUND(AVG(r.marks_obtained / r.total_marks * 100), 1) as avg_percentage
           FROM results r
           JOIN subjects s ON r.subject_id = s.id
           JOIN grades g ON s.grade_id = g.id
           GROUP BY s.id
           ORDER BY avg_percentage DESC""",
        fetch=True
    )
    
    # All teachers with attendance summary
    teachers = query(
        """SELECT t.name, t.subject,
              COUNT(ta.id) as days_recorded,
              SUM(CASE WHEN ta.status = 'Present' THEN 1 ELSE 0 END) as present_days,
              SUM(CASE WHEN ta.status = 'Absent' THEN 1 ELSE 0 END) as absent_days,
              ROUND(SUM(CASE WHEN ta.status = 'Present' THEN 1 ELSE 0 END) / COUNT(ta.id) * 100, 1) as attendance_pct
           FROM teachers t
           LEFT JOIN teacher_attendance ta ON t.id = ta.teacher_id AND ta.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
           GROUP BY t.id
           ORDER BY t.name""",
        fetch=True
    )
    
    return render_template('principal/dashboard.html', stats=stats, low_attendance=low_attendance,
                         trend_data=trend_data, section_comparison=section_comparison,
                         subject_performance=subject_performance, teachers=teachers,
                         all_students=query(
                             """SELECT s.name, s.student_system_id, s.roll_number, sec.name as section_name, g.name as grade_name
                                FROM students s
                                LEFT JOIN sections sec ON s.section_id = sec.id
                                LEFT JOIN grades g ON sec.grade_id = g.id
                                WHERE s.status = 'Active'
                                ORDER BY g.name, sec.name, s.roll_number LIMIT 50""",
                             fetch=True
                         ),
                         all_teachers=query(
                             """SELECT t.name, t.subject, t.phone, t.email
                                FROM teachers t
                                ORDER BY t.name""",
                             fetch=True
                         ))