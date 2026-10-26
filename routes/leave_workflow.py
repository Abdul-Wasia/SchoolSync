from datetime import date, datetime, timedelta

from database.connection import query


def approved_leave_attendance_queries(student_id, section_id, from_date, to_date):
    """Build attendance upserts for the subjects assigned to a student's section."""
    if not section_id:
        return []

    if isinstance(from_date, datetime):
        from_date = from_date.date()
    elif not isinstance(from_date, date):
        from_date = date.fromisoformat(str(from_date))

    if isinstance(to_date, datetime):
        to_date = to_date.date()
    elif not isinstance(to_date, date):
        to_date = date.fromisoformat(str(to_date))

    if to_date < from_date:
        raise ValueError('Leave end date precedes start date.')

    assigned_courses = query(
        """SELECT DISTINCT subject_id, teacher_id
           FROM subject_teachers
           WHERE section_id = %s""",
        (section_id,),
        fetch=True
    ) or []

    writes = []
    current_date = from_date
    while current_date <= to_date:
        for course in assigned_courses:
            writes.append((
                """INSERT INTO attendance
                   (student_id, section_id, subject_id, teacher_id, date, status)
                   VALUES (%s, %s, %s, %s, %s, 'Leave')
                   ON DUPLICATE KEY UPDATE status = 'Leave', marked_at = NOW()""",
                (
                    student_id,
                    section_id,
                    course['subject_id'],
                    course['teacher_id'],
                    current_date.isoformat()
                )
            ))
        current_date += timedelta(days=1)

    return writes
