"""Automated tests for newly implemented real-world school management modules:
1. School Library Management & Book Circulation Desk
2. Tamper-Proof Official Certificate Public Verification with QR link
3. Subject Performance Analytics & Gradebook Insights
4. Centralized Parent/Guardian Quick Communication Hub
"""

import unittest
from datetime import date, timedelta
from app import app
from database.connection import query


class RealWorldNewModulesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        import database.connection as db_conn
        if hasattr(db_conn, '_raw_query'):
            db_conn.query = db_conn._raw_query
            import routes.library_routes as lr
            import routes.document_routes as dr
            lr.query = db_conn._raw_query
            dr.query = db_conn._raw_query

    def _login_as(self, username, user_type):
        import database.connection as db_conn
        q_func = getattr(db_conn, '_raw_query', query)
        user = q_func("SELECT id, username FROM users WHERE username = %s", (username,), fetch_one=True)
        self.assertIsNotNone(user, f"User {username} should exist in database")
        with self.client.session_transaction() as sess:
            sess['user_id'] = user['id']
            sess['username'] = user['username']
            sess['user_type'] = user_type
            sess['_csrf_token'] = 'test-realworld-csrf-token'

    def post_with_csrf(self, endpoint, data=None, follow_redirects=False):
        payload = dict(data or {})
        payload['csrf_token'] = 'test-realworld-csrf-token'
        return self.client.post(endpoint, data=payload, follow_redirects=follow_redirects)

    # -----------------------------------------------------------------------
    # 1. School Library Module Tests
    # -----------------------------------------------------------------------
    def test_library_catalog_access_for_all_roles(self):
        for username, role in [('student1', 'Student'), ('teacher1', 'Teacher'), ('admin', 'IT_Admin')]:
            self._login_as(username, role)
            response = self.client.get('/library/')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'School Library', response.data)

    def test_student_restricted_from_staff_circulation_desk(self):
        self._login_as('student1', 'Student')
        response = self.client.get('/library/circulation')
        # login_required redirects unauthorized roles to login with a flash
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_library_book_add_issue_and_return_lifecycle(self):
        # 1. Add book as IT_Admin
        self._login_as('admin', 'IT_Admin')
        test_title = f"Test Algorithm Volume {date.today().isoformat()}"
        res = self.post_with_csrf('/library/add', {
            'title': test_title,
            'author': 'Donald Knuth',
            'category': 'Computer Science',
            'isbn': '978-0201896831',
            'rack_location': 'Rack CS-01',
            'total_copies': 1,
            'published_year': 2020
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Check DB
        book = query("SELECT * FROM library_books WHERE title = %s", (test_title,), fetch_one=True)
        self.assertIsNotNone(book)
        self.assertEqual(book['available_copies'], 1)
        book_id = book['id']

        # 2. Issue book to student1
        student = query("SELECT id FROM students WHERE user_id = (SELECT id FROM users WHERE username='student1')", fetch_one=True)
        self.assertIsNotNone(student)

        due_date = (date.today() + timedelta(days=14)).isoformat()
        res_issue = self.post_with_csrf('/library/issue', {
            'book_id': book_id,
            'recipient_type': 'Student',
            'student_id': student['id'],
            'due_date': due_date,
            'notes': 'Issued for mid-term project research'
        }, follow_redirects=True)
        self.assertEqual(res_issue.status_code, 200)

        # Verify available copies decremented
        book_after_issue = query("SELECT available_copies FROM library_books WHERE id = %s", (book_id,), fetch_one=True)
        self.assertEqual(book_after_issue['available_copies'], 0)

        # 3. Student views their borrowed book
        self._login_as('student1', 'Student')
        res_student_books = self.client.get('/library/my-books')
        self.assertEqual(res_student_books.status_code, 200)
        self.assertIn(test_title.encode(), res_student_books.data)

        # 4. Return book as Teacher
        self._login_as('teacher1', 'Teacher')
        issue_record = query("SELECT id FROM library_issues WHERE book_id = %s AND status = 'Issued'", (book_id,), fetch_one=True)
        self.assertIsNotNone(issue_record)

        res_return = self.post_with_csrf(f"/library/return/{issue_record['id']}", {
            'fine_amount': '0.00'
        }, follow_redirects=True)
        self.assertEqual(res_return.status_code, 200)

        # Verify copies incremented back to 1
        book_after_return = query("SELECT available_copies FROM library_books WHERE id = %s", (book_id,), fetch_one=True)
        self.assertEqual(book_after_return['available_copies'], 1)

    # -----------------------------------------------------------------------
    # 2. Tamper-Proof Official Certificate Public Verification Tests
    # -----------------------------------------------------------------------
    def test_public_certificate_verification_valid_and_invalid(self):
        # Clean unauthenticated client
        unauth_client = self.app.test_client()

        # Check existing certificate or create one for test
        cert = query("SELECT certificate_number FROM student_certificates LIMIT 1", fetch_one=True)
        if cert:
            valid_code = cert['certificate_number']
            res_valid = unauth_client.get(f"/verify/certificate/{valid_code}")
            self.assertEqual(res_valid.status_code, 200)
            self.assertIn(b'OFFICIAL RECORD VERIFIED', res_valid.data)
            self.assertIn(valid_code.encode(), res_valid.data)

        # Test invalid non-existent certificate
        fake_code = "SS-9999-FAKE-0000"
        res_fake = unauth_client.get(f"/verify/certificate/{fake_code}")
        self.assertEqual(res_fake.status_code, 200)
        self.assertIn(b'VERIFICATION FAILED', res_fake.data)
        self.assertIn(b'Certificate Not Found', res_fake.data)

    # -----------------------------------------------------------------------
    # 3. Academic Analytics Tests
    # -----------------------------------------------------------------------
    def test_academic_analytics_access(self):
        # Staff can access
        for username, role in [('teacher1', 'Teacher'), ('principal', 'Principal'), ('admin', 'IT_Admin')]:
            self._login_as(username, role)
            res = self.client.get('/academic-analytics')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Subject Performance Analytics', res.data)

        # Student cannot access (redirected with 302 to login)
        self._login_as('student1', 'Student')
        res_student = self.client.get('/academic-analytics')
        self.assertEqual(res_student.status_code, 302)
        self.assertIn('/login', res_student.headers.get('Location', ''))

    # -----------------------------------------------------------------------
    # 4. Parent Communication Hub Tests
    # -----------------------------------------------------------------------
    def test_parent_communication_hub_access(self):
        # Staff can access
        for username, role in [('teacher1', 'Teacher'), ('fa_user', 'FA'), ('principal', 'Principal')]:
            self._login_as(username, role)
            res = self.client.get('/parent-communication')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Parent &amp; Guardian Communication Hub', res.data)

        # Student cannot access (redirected with 302 to login)
        self._login_as('student1', 'Student')
        res_student = self.client.get('/parent-communication')
        self.assertEqual(res_student.status_code, 302)
        self.assertIn('/login', res_student.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
