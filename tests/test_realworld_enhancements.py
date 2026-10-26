"""Tests for real-world school management enhancements.

Validates Notice Board, Academic Calendar, Student Certificate Generation,
Class Monthly Attendance Register, and Student Conduct Logs.
"""

import unittest
from datetime import date, timedelta
from app import app
from database.connection import query


class RealWorldEnhancementsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        import database.connection as db_conn
        if hasattr(db_conn, '_raw_query'):
            db_conn.query = db_conn._raw_query
            import routes.notice_routes as nr
            import routes.calendar_routes as cr
            import routes.document_routes as dr
            nr.query = db_conn._raw_query
            cr.query = db_conn._raw_query
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
            sess['_csrf_token'] = 'enhancement-test-token'

    def post_with_csrf(self, endpoint, data=None, follow_redirects=False):
        payload = dict(data or {})
        payload['csrf_token'] = 'enhancement-test-token'
        return self.client.post(endpoint, data=payload, follow_redirects=follow_redirects)

    # -----------------------------------------------------------------------
    # Notice Board & Circulars Tests
    # -----------------------------------------------------------------------
    def test_notice_board_access_for_all_roles(self):
        for username, role in [('student1', 'Student'), ('teacher1', 'Teacher'), ('admin', 'IT_Admin')]:
            self._login_as(username, role)
            response = self.client.get('/notices/')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Notice Board', response.data)

    def test_post_notice_as_admin(self):
        self._login_as('admin', 'IT_Admin')
        title = "Test Urgent System Maintenance Notice"
        response = self.post_with_csrf('/notices/create', data={
            'title': title,
            'content': 'School servers will be upgraded this weekend.',
            'category': 'General',
            'priority': 'Urgent',
            'target_role': 'All'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(title.encode(), response.data)

        # Verify in DB
        created = query("SELECT id FROM announcements WHERE title = %s", (title,), fetch_one=True)
        self.assertIsNotNone(created)

        # Cleanup
        query("DELETE FROM announcements WHERE id = %s", (created['id'],))

    def test_student_cannot_post_notice(self):
        self._login_as('student1', 'Student')
        response = self.post_with_csrf('/notices/create', data={
            'title': 'Hacked Notice',
            'content': 'Testing unauthorized post',
            'category': 'General',
            'priority': 'Urgent',
            'target_role': 'All'
        })
        self.assertEqual(response.status_code, 302)

    # -----------------------------------------------------------------------
    # Academic Calendar Tests
    # -----------------------------------------------------------------------
    def test_academic_calendar_view(self):
        self._login_as('teacher1', 'Teacher')
        response = self.client.get('/calendar/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Academic Calendar', response.data)

    def test_create_and_delete_calendar_event(self):
        self._login_as('principal', 'Principal')
        title = "Test Annual Founder Day"
        today = date.today()
        response = self.post_with_csrf('/calendar/create', data={
            'title': title,
            'description': 'Commemoration ceremony in central auditorium.',
            'event_type': 'Celebration',
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=1)).isoformat(),
            'target_audience': 'All'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(title.encode(), response.data)

        event = query("SELECT id FROM school_events WHERE title = %s", (title,), fetch_one=True)
        self.assertIsNotNone(event)

        # Delete
        del_resp = self.post_with_csrf(f'/calendar/delete/{event["id"]}', follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(query("SELECT id FROM school_events WHERE id = %s", (event['id'],), fetch_one=True))

    # -----------------------------------------------------------------------
    # Student Official Certificate Generator Tests
    # -----------------------------------------------------------------------
    def test_student_bonafide_certificate_generation(self):
        student = query("SELECT id, name FROM students WHERE status = 'Active' LIMIT 1", fetch_one=True)
        self.assertIsNotNone(student)

        self._login_as('admin', 'IT_Admin')
        response = self.client.get(f'/certificate/{student["id"]}?type=Bonafide')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Bonafide Enrollment Certificate', response.data)
        self.assertIn(student['name'].encode(), response.data)

    def test_student_character_and_transfer_certificates(self):
        student = query("SELECT id FROM students WHERE status = 'Active' LIMIT 1", fetch_one=True)
        self._login_as('principal', 'Principal')

        # Character certificate
        resp_char = self.client.get(f'/certificate/{student["id"]}?type=Character')
        self.assertEqual(resp_char.status_code, 200)
        self.assertIn(b'Character &amp; Conduct Certificate', resp_char.data)

        # Transfer certificate
        resp_tc = self.client.get(f'/certificate/{student["id"]}?type=Transfer')
        self.assertEqual(resp_tc.status_code, 200)
        self.assertIn(b'School Leaving &amp; Transfer Certificate', resp_tc.data)

    # -----------------------------------------------------------------------
    # Monthly Class Attendance Register Tests
    # -----------------------------------------------------------------------
    def test_monthly_attendance_register_access(self):
        self._login_as('teacher1', 'Teacher')
        response = self.client.get('/attendance-register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Class Attendance Register', response.data)

    # -----------------------------------------------------------------------
    # Student Conduct & Commendation Logs Tests
    # -----------------------------------------------------------------------
    def test_student_conduct_log_creation_and_view(self):
        student = query("SELECT id, name FROM students WHERE status = 'Active' LIMIT 1", fetch_one=True)
        self._login_as('teacher1', 'Teacher')

        title = "Mathematics Olympiad Gold Medal"
        response = self.post_with_csrf(f'/student/{student["id"]}/conduct/add', data={
            'title': title,
            'description': 'Secured 1st rank in inter-school math competition.',
            'log_type': 'Achievement',
            'incident_date': date.today().isoformat()
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(title.encode(), response.data)

        # Verify database
        log_entry = query("SELECT id FROM student_conduct_logs WHERE student_id = %s AND title = %s",
                          (student['id'], title), fetch_one=True)
        self.assertIsNotNone(log_entry)
        query("DELETE FROM student_conduct_logs WHERE id = %s", (log_entry['id'],))


if __name__ == '__main__':
    unittest.main()
