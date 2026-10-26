"""Academic Calendar and School Events & Holidays Management for SchoolSync.

Allows Administrators, Principals, and FA Staff to schedule and publish
holidays, exam dates, parent-teacher meetings, sports events, and celebrations,
and allows all roles (Students, Teachers, Staff) to view the school calendar.
"""

from calendar import monthrange, month_name
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
from database.connection import query
from routes.auth_routes import login_required

calendar_bp = Blueprint('calendar', __name__, url_prefix='/calendar')

STAFF_ROLES = {'IT_Admin', 'Principal', 'FA'}
EVENT_TYPES = ['Holiday', 'Exam', 'Sports', 'Meeting', 'Academic', 'Celebration']
TARGET_AUDIENCES = ['All', 'Student', 'Teacher', 'Staff']


@calendar_bp.route('/')
@login_required()
def index():
    user_type = session.get('user_type')
    is_staff = user_type in STAFF_ROLES

    today = date.today()
    try:
        req_year = int(request.args.get('year', today.year))
        req_month = int(request.args.get('month', today.month))
        if req_month < 1 or req_month > 12:
            req_month = today.month
    except (ValueError, TypeError):
        req_year, req_month = today.year, today.month

    event_type_filter = request.args.get('type', '').strip()

    # Calculate month grid (Monday=0 ... Sunday=6)
    first_weekday, num_days = monthrange(req_year, req_month)
    month_start = date(req_year, req_month, 1)
    month_end = date(req_year, req_month, num_days)

    # Prev / Next month navigation
    if req_month == 1:
        prev_month, prev_year = 12, req_year - 1
    else:
        prev_month, prev_year = req_month - 1, req_year

    if req_month == 12:
        next_month, next_year = 1, req_year + 1
    else:
        next_month, next_year = req_month + 1, req_year

    # Query events overlapping this month
    sql = """
        SELECT e.*, u.username as creator_name
        FROM school_events e
        LEFT JOIN users u ON e.created_by = u.id
        WHERE e.start_date <= %s AND e.end_date >= %s
    """
    params = [month_end, month_start]

    if not is_staff:
        # Filter for role
        role_filter = 'Student' if user_type == 'Student' else ('Teacher' if user_type == 'Teacher' else 'Staff')
        sql += " AND e.target_audience IN ('All', %s)"
        params.append(role_filter)

    if event_type_filter and event_type_filter != 'All':
        sql += " AND e.event_type = %s"
        params.append(event_type_filter)

    sql += " ORDER BY e.start_date, e.title"
    events = query(sql, tuple(params), fetch=True) or []

    # Map events to days of the month
    events_by_day = {}
    for day_num in range(1, num_days + 1):
        cur_d = date(req_year, req_month, day_num)
        day_events = [
            e for e in events
            if e['start_date'] <= cur_d <= e['end_date']
        ]
        events_by_day[day_num] = day_events

    # Calendar matrix (weeks of 7 days)
    calendar_weeks = []
    current_week = []
    # Fill padding before 1st of month
    for _ in range(first_weekday):
        current_week.append(None)

    for day_num in range(1, num_days + 1):
        current_week.append({
            'day': day_num,
            'date': date(req_year, req_month, day_num),
            'is_today': (req_year == today.year and req_month == today.month and day_num == today.day),
            'events': events_by_day[day_num]
        })
        if len(current_week) == 7:
            calendar_weeks.append(current_week)
            current_week = []

    # Fill padding after last day
    if current_week:
        while len(current_week) < 7:
            current_week.append(None)
        calendar_weeks.append(current_week)

    # Upcoming events in next 60 days
    upcoming_sql = """
        SELECT e.*, u.username as creator_name
        FROM school_events e
        LEFT JOIN users u ON e.created_by = u.id
        WHERE e.end_date >= %s AND e.start_date <= %s
    """
    upcoming_params = [today, today + timedelta(days=60)]
    if not is_staff:
        role_filter = 'Student' if user_type == 'Student' else ('Teacher' if user_type == 'Teacher' else 'Staff')
        upcoming_sql += " AND e.target_audience IN ('All', %s)"
        upcoming_params.append(role_filter)
    upcoming_sql += " ORDER BY e.start_date ASC LIMIT 10"

    upcoming_events = query(upcoming_sql, tuple(upcoming_params), fetch=True) or []

    return render_template(
        'calendar/index.html',
        calendar_weeks=calendar_weeks,
        current_year=req_year,
        current_month=req_month,
        current_month_name=month_name[req_month],
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        events=events,
        upcoming_events=upcoming_events,
        event_types=EVENT_TYPES,
        target_audiences=TARGET_AUDIENCES,
        selected_type=event_type_filter,
        is_staff=is_staff,
        today=today
    )


@calendar_bp.route('/create', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA'])
def create():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    event_type = request.form.get('event_type', 'Academic').strip()
    start_date_str = request.form.get('start_date', '').strip()
    end_date_str = request.form.get('end_date', '').strip() or start_date_str
    target_audience = request.form.get('target_audience', 'All').strip()

    if not title or not start_date_str:
        flash('Event title and start date are required.', 'danger')
        return redirect(url_for('calendar.index'))

    try:
        start_d = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_d = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('calendar.index'))

    if start_d > end_d:
        flash('Start date cannot be after end date.', 'danger')
        return redirect(url_for('calendar.index'))

    if event_type not in EVENT_TYPES:
        event_type = 'Academic'
    if target_audience not in TARGET_AUDIENCES:
        target_audience = 'All'

    query(
        """INSERT INTO school_events
           (title, description, event_type, start_date, end_date, target_audience, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (title, description, event_type, start_d, end_d, target_audience, session['user_id'])
    )

    flash('Event added to the Academic Calendar successfully.', 'success')
    return redirect(url_for('calendar.index', year=start_d.year, month=start_d.month))


@calendar_bp.route('/delete/<int:event_id>', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA'])
def delete(event_id):
    query("DELETE FROM school_events WHERE id = %s", (event_id,))
    flash('Event removed from Academic Calendar.', 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/api/events')
@login_required()
def api_events():
    user_type = session.get('user_type')
    is_staff = user_type in STAFF_ROLES

    year = request.args.get('year', type=int) or date.today().year
    month = request.args.get('month', type=int) or date.today().month
    _, num_days = monthrange(year, month)

    sql = """
        SELECT id, title, description, event_type, start_date, end_date, target_audience
        FROM school_events
        WHERE start_date <= %s AND end_date >= %s
    """
    params = [date(year, month, num_days), date(year, month, 1)]
    if not is_staff:
        role_filter = 'Student' if user_type == 'Student' else ('Teacher' if user_type == 'Teacher' else 'Staff')
        sql += " AND target_audience IN ('All', %s)"
        params.append(role_filter)

    events = query(sql, tuple(params), fetch=True) or []
    # format dates
    for e in events:
        if isinstance(e.get('start_date'), (date, datetime)):
            e['start_date'] = e['start_date'].strftime('%Y-%m-%d')
        if isinstance(e.get('end_date'), (date, datetime)):
            e['end_date'] = e['end_date'].strftime('%Y-%m-%d')

    return jsonify(events)
