"""Notice Board and Circulars Management for SchoolSync.

Allows Administrators, Principals, and FA Staff to broadcast official
announcements, circulars, urgent alerts, and academic notices, and allows
all roles (Students, Teachers, Staff) to view and filter them.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
from database.connection import query
from routes.auth_routes import login_required

notice_bp = Blueprint('notices', __name__, url_prefix='/notices')

STAFF_ROLES = {'IT_Admin', 'Principal', 'FA'}
CATEGORIES = ['General', 'Academic', 'Holiday', 'Event', 'Exam', 'Urgent']
PRIORITIES = ['Normal', 'High', 'Urgent']
TARGET_ROLES = ['All', 'Student', 'Teacher', 'FA', 'Principal', 'GR_Office', 'IT_Admin']


@notice_bp.route('/')
@login_required()
def index():
    user_type = session.get('user_type')
    is_staff = user_type in STAFF_ROLES

    category = request.args.get('category', '').strip()
    priority = request.args.get('priority', '').strip()
    search = request.args.get('search', '').strip()

    sql = """
        SELECT a.*, u.username as posted_by_name, u.user_type as posted_by_role,
               g.name as grade_name, s.name as section_name
        FROM announcements a
        LEFT JOIN users u ON a.posted_by = u.id
        LEFT JOIN grades g ON a.grade_id = g.id
        LEFT JOIN sections s ON a.section_id = s.id
        WHERE 1=1
    """
    params = []

    # Non-staff users only see active notices targeted to their role or 'All'
    if not is_staff:
        sql += " AND a.is_active = 1 AND a.target_role IN ('All', %s)"
        params.append(user_type)

    if category and category != 'All':
        sql += " AND a.category = %s"
        params.append(category)

    if priority and priority != 'All':
        sql += " AND a.priority = %s"
        params.append(priority)

    if search:
        sql += " AND (a.title LIKE %s OR a.content LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    sql += " ORDER BY FIELD(a.priority, 'Urgent', 'High', 'Normal'), a.created_at DESC"

    notices = query(sql, tuple(params), fetch=True) or []
    grades = query("SELECT id, name FROM grades ORDER BY name", fetch=True) or []
    sections = query("SELECT id, name, grade_id FROM sections ORDER BY name", fetch=True) or []

    urgent_count = sum(1 for n in notices if n.get('priority') == 'Urgent' and n.get('is_active'))

    return render_template(
        'notices/index.html',
        notices=notices,
        categories=CATEGORIES,
        priorities=PRIORITIES,
        target_roles=TARGET_ROLES,
        selected_category=category,
        selected_priority=priority,
        search=search,
        is_staff=is_staff,
        grades=grades,
        sections=sections,
        urgent_count=urgent_count
    )


@notice_bp.route('/create', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA'])
def create():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', 'General').strip()
    priority = request.form.get('priority', 'Normal').strip()
    target_role = request.form.get('target_role', 'All').strip()
    grade_id = request.form.get('grade_id') or None
    section_id = request.form.get('section_id') or None

    if not title or not content:
        flash('Title and content are required.', 'danger')
        return redirect(url_for('notices.index'))

    if category not in CATEGORIES:
        category = 'General'
    if priority not in PRIORITIES:
        priority = 'Normal'
    if target_role not in TARGET_ROLES:
        target_role = 'All'

    query(
        """INSERT INTO announcements
           (title, content, posted_by, target_role, grade_id, section_id, is_active, priority, category)
           VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)""",
        (title, content, session['user_id'], target_role, grade_id, section_id, priority, category)
    )

    flash('Announcement published to the Notice Board successfully.', 'success')
    return redirect(url_for('notices.index'))


@notice_bp.route('/toggle/<int:notice_id>', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA'])
def toggle(notice_id):
    notice = query("SELECT id, is_active FROM announcements WHERE id = %s", (notice_id,), fetch_one=True)
    if not notice:
        abort(404)

    new_status = 0 if notice['is_active'] else 1
    query("UPDATE announcements SET is_active = %s WHERE id = %s", (new_status, notice_id))
    flash('Notice status updated.', 'info')
    return redirect(url_for('notices.index'))


@notice_bp.route('/delete/<int:notice_id>', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA'])
def delete(notice_id):
    query("DELETE FROM announcements WHERE id = %s", (notice_id,))
    flash('Notice deleted successfully.', 'success')
    return redirect(url_for('notices.index'))


@notice_bp.route('/api/latest')
@login_required()
def api_latest():
    user_type = session.get('user_type')
    notices = query(
        """SELECT id, title, priority, category, created_at
           FROM announcements
           WHERE is_active = 1 AND target_role IN ('All', %s)
           ORDER BY FIELD(priority, 'Urgent', 'High', 'Normal'), created_at DESC
           LIMIT 5""",
        (user_type,),
        fetch=True
    ) or []
    return jsonify(notices)
