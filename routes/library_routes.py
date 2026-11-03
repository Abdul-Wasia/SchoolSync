"""School Library Management System for SchoolSync.

Supports:
- Book catalog searching and filtering
- Adding & managing book inventory
- Book issuing to students and teachers
- Book return processing with overdue fine calculation
- Student personal borrowing history and catalog browsing
"""

from datetime import date, datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort, jsonify
from database.connection import query
from routes.auth_routes import login_required

library_bp = Blueprint('library', __name__, url_prefix='/library')

STAFF_ROLES = {'IT_Admin', 'Principal', 'FA', 'Teacher'}
DAILY_OVERDUE_FINE = 10.0  # PKR 10 per day overdue


def _is_staff():
    return session.get('user_type') in STAFF_ROLES


@library_bp.route('/')
@login_required()
def catalog():
    """Browse and search book catalog."""
    search_q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    sql = """
        SELECT b.*,
               (b.total_copies - b.available_copies) as issued_count
        FROM library_books b
        WHERE 1=1
    """
    params = []

    if search_q:
        sql += " AND (b.title LIKE %s OR b.author LIKE %s OR b.isbn LIKE %s)"
        pattern = f"%{search_q}%"
        params.extend([pattern, pattern, pattern])

    if category:
        sql += " AND b.category = %s"
        params.append(category)

    sql += " ORDER BY b.title ASC"

    books = query(sql, tuple(params) if params else None, fetch=True) or []
    categories = query(
        "SELECT DISTINCT category FROM library_books WHERE category IS NOT NULL AND category != '' ORDER BY category",
        fetch=True
    ) or []

    # If student, load their active loans count
    my_active_loans = 0
    if session.get('user_type') == 'Student':
        student = query("SELECT id FROM students WHERE user_id = %s", (session['user_id'],), fetch_one=True)
        if student:
            loans_count = query(
                "SELECT COUNT(*) as cnt FROM library_issues WHERE student_id = %s AND status = 'Issued'",
                (student['id'],),
                fetch_one=True
            )
            if loans_count:
                my_active_loans = loans_count.get('cnt', 0)

    # If staff, load active students and teachers for the quick issue modal
    students_list = []
    teachers_list = []
    if _is_staff():
        students_list = query(
            """SELECT s.id, s.name, s.roll_number, s.student_system_id, g.name as grade_name, sec.name as section_name
               FROM students s
               LEFT JOIN sections sec ON s.section_id = sec.id
               LEFT JOIN grades g ON sec.grade_id = g.id
               WHERE s.status = 'Active'
               ORDER BY g.name, sec.name, s.roll_number""",
            fetch=True
        ) or []
        teachers_list = query(
            "SELECT id, name, subject FROM teachers ORDER BY name",
            fetch=True
        ) or []

    return render_template(
        'library/index.html',
        books=books,
        categories=categories,
        search_q=search_q,
        selected_category=category,
        is_staff=_is_staff(),
        my_active_loans=my_active_loans,
        students=students_list,
        teachers=teachers_list,
        today=date.today()
    )


@library_bp.route('/add', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA', 'Teacher'])
def add_book():
    """Add a new book to the library catalog."""
    title = request.form.get('title', '').strip()
    author = request.form.get('author', '').strip()
    isbn = request.form.get('isbn', '').strip() or None
    category = request.form.get('category', 'General').strip() or 'General'
    rack_location = request.form.get('rack_location', '').strip() or None
    publisher = request.form.get('publisher', '').strip() or None

    try:
        total_copies = int(request.form.get('total_copies', 1))
        if total_copies < 1:
            total_copies = 1
    except ValueError:
        total_copies = 1

    try:
        pub_year = int(request.form.get('published_year', '')) if request.form.get('published_year') else None
    except ValueError:
        pub_year = None

    if not title or not author:
        flash('Book title and author are required.', 'danger')
        return redirect(url_for('library.catalog'))

    query(
        """INSERT INTO library_books
           (isbn, title, author, category, rack_location, total_copies, available_copies, publisher, published_year)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (isbn, title, author, category, rack_location, total_copies, total_copies, publisher, pub_year)
    )

    flash(f"Book '{title}' successfully added to the catalog.", 'success')
    return redirect(url_for('library.catalog'))


@library_bp.route('/issue', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA', 'Teacher'])
def issue_book():
    """Issue a book copy to a student or teacher."""
    book_id = request.form.get('book_id', type=int)
    recipient_type = request.form.get('recipient_type', 'Student')
    student_id = request.form.get('student_id', type=int) if recipient_type == 'Student' else None
    teacher_id = request.form.get('teacher_id', type=int) if recipient_type == 'Teacher' else None
    due_date_str = request.form.get('due_date')
    notes = request.form.get('notes', '').strip() or None

    if not book_id:
        flash('Please select a book to issue.', 'danger')
        return redirect(url_for('library.catalog'))

    if recipient_type == 'Student' and not student_id:
        flash('Please select a student borrower.', 'danger')
        return redirect(url_for('library.catalog'))

    if recipient_type == 'Teacher' and not teacher_id:
        flash('Please select a teacher borrower.', 'danger')
        return redirect(url_for('library.catalog'))

    # Verify book availability
    book = query("SELECT id, title, available_copies FROM library_books WHERE id = %s", (book_id,), fetch_one=True)
    if not book:
        flash('Selected book does not exist.', 'danger')
        return redirect(url_for('library.catalog'))

    if book['available_copies'] < 1:
        flash(f"Sorry, no available copies left for '{book['title']}'. All copies are currently issued.", 'warning')
        return redirect(url_for('library.catalog'))

    # Default due date to 14 days from today if not provided
    today = date.today()
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            due_date = today.replace(day=min(today.day + 14, 28))
    else:
        # 14 days loan
        from datetime import timedelta
        due_date = today + timedelta(days=14)

    # Insert issue and decrement available copies
    query(
        """INSERT INTO library_issues
           (book_id, student_id, teacher_id, issue_date, due_date, status, notes, issued_by)
           VALUES (%s, %s, %s, %s, %s, 'Issued', %s, %s)""",
        (book_id, student_id, teacher_id, today, due_date, notes, session.get('user_id'))
    )

    query(
        "UPDATE library_books SET available_copies = available_copies - 1 WHERE id = %s AND available_copies > 0",
        (book_id,)
    )

    flash(f"Book '{book['title']}' issued successfully. Due date: {due_date.strftime('%b %d, %Y')}.", 'success')
    return redirect(url_for('library.circulation'))


@library_bp.route('/circulation')
@login_required(['IT_Admin', 'Principal', 'FA', 'Teacher'])
def circulation():
    """View active book loans, overdue items, and circulation history."""
    filter_status = request.args.get('status', 'Issued').strip()

    sql = """
        SELECT i.*,
               b.title as book_title, b.author as book_author, b.isbn, b.rack_location,
               s.name as student_name, s.roll_number, s.student_system_id,
               g.name as grade_name, sec.name as section_name,
               t.name as teacher_name,
               u.username as issued_by_user
        FROM library_issues i
        JOIN library_books b ON i.book_id = b.id
        LEFT JOIN students s ON i.student_id = s.id
        LEFT JOIN sections sec ON s.section_id = sec.id
        LEFT JOIN grades g ON sec.grade_id = g.id
        LEFT JOIN teachers t ON i.teacher_id = t.id
        LEFT JOIN users u ON i.issued_by = u.id
        WHERE 1=1
    """
    params = []

    if filter_status in {'Issued', 'Returned', 'Lost'}:
        sql += " AND i.status = %s"
        params.append(filter_status)

    sql += " ORDER BY i.due_date ASC, i.issue_date DESC"

    issues = query(sql, tuple(params) if params else None, fetch=True) or []
    today = date.today()

    # Calculate dynamic overdue days and potential fines for active issues
    for item in issues:
        item['is_overdue'] = False
        item['days_overdue'] = 0
        item['calculated_fine'] = float(item.get('fine_amount') or 0.0)

        if item['status'] == 'Issued' and item['due_date']:
            due = item['due_date']
            if isinstance(due, datetime):
                due = due.date()
            if today > due:
                item['is_overdue'] = True
                days = (today - due).days
                item['days_overdue'] = days
                item['calculated_fine'] = float(days * DAILY_OVERDUE_FINE)

    return render_template(
        'library/circulation.html',
        issues=issues,
        filter_status=filter_status,
        today=today,
        daily_fine=DAILY_OVERDUE_FINE
    )


@library_bp.route('/return/<int:issue_id>', methods=['POST'])
@login_required(['IT_Admin', 'Principal', 'FA', 'Teacher'])
def return_book(issue_id):
    """Mark a book as returned, compute final fine, and increment inventory copies."""
    issue = query(
        """SELECT i.*, b.id as book_id, b.title as book_title
           FROM library_issues i
           JOIN library_books b ON i.book_id = b.id
           WHERE i.id = %s""",
        (issue_id,),
        fetch_one=True
    )
    if not issue:
        flash('Issue record not found.', 'danger')
        return redirect(url_for('library.circulation'))

    if issue['status'] == 'Returned':
        flash('This book has already been returned.', 'info')
        return redirect(url_for('library.circulation'))

    today = date.today()
    due = issue['due_date']
    if isinstance(due, datetime):
        due = due.date()

    fine = 0.0
    if today > due:
        days = (today - due).days
        fine = float(days * DAILY_OVERDUE_FINE)

    # Optional manual fine override from form
    fine_override = request.form.get('fine_amount')
    if fine_override is not None and fine_override.strip() != '':
        try:
            fine = max(0.0, float(fine_override))
        except ValueError:
            pass

    query(
        """UPDATE library_issues
           SET status = 'Returned',
               return_date = %s,
               fine_amount = %s
           WHERE id = %s""",
        (today, fine, issue_id)
    )

    query(
        "UPDATE library_books SET available_copies = LEAST(total_copies, available_copies + 1) WHERE id = %s",
        (issue['book_id'],)
    )

    flash(f"Book '{issue['book_title']}' successfully marked as returned. (Fine applied: PKR {fine:.2f})", 'success')
    return redirect(url_for('library.circulation'))


@library_bp.route('/my-books')
@login_required(['Student'])
def my_books():
    """Student view of their personal borrowed books and borrowing history."""
    student = query("SELECT id, name FROM students WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not student:
        abort(403)

    records = query(
        """SELECT i.*,
                  b.title as book_title, b.author as book_author, b.isbn, b.rack_location, b.category
           FROM library_issues i
           JOIN library_books b ON i.book_id = b.id
           WHERE i.student_id = %s
           ORDER BY i.status ASC, i.due_date ASC""",
        (student['id'],),
        fetch=True
    ) or []

    today = date.today()
    for item in records:
        item['is_overdue'] = False
        item['days_overdue'] = 0
        if item['status'] == 'Issued' and item['due_date']:
            due = item['due_date']
            if isinstance(due, datetime):
                due = due.date()
            if today > due:
                item['is_overdue'] = True
                days = (today - due).days
                item['days_overdue'] = days
                item['fine_amount'] = float(days * DAILY_OVERDUE_FINE)

    return render_template(
        'library/my_books.html',
        records=records,
        student=student,
        today=today,
        daily_fine=DAILY_OVERDUE_FINE
    )

