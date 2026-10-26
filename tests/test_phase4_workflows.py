import os
import unittest
from datetime import date
from unittest.mock import patch

with patch.dict(os.environ, {'DEBUG': 'true', 'SECRET_KEY': 'test-secret-key-for-phase-four'}):
    with patch('database.connection.query'):
        import app as schoolsync_app

import routes.fa_routes as fa_routes
import routes.leave_workflow as leave_workflow
import routes.student_routes as student_routes
import routes.teacher_routes as teacher_routes


class Phase4WorkflowTests(unittest.TestCase):
    def setUp(self):
        schoolsync_app.app.config['TESTING'] = True
        self.client = schoolsync_app.app.test_client()

    def set_identity(self, user_id, role):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['user_type'] = role
            session['_csrf_token'] = 'phase-four-test-token'

    def post_with_csrf(self, endpoint, data):
        return self.client.post(endpoint, data={**data, 'csrf_token': 'phase-four-test-token'})

    def test_teacher_records_results_and_updates_existing_exam_rows(self):
        self.set_identity(80, 'Teacher')
        writes = []

        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 12}), patch.object(
            teacher_routes, 'query', side_effect=[
                {'id': 5},
                [{'id': 21}, {'id': 22}],
                [{'id': 90, 'student_id': 21}],
            ]
        ), patch.object(teacher_routes, 'transaction', side_effect=lambda statements: writes.extend(statements) or True), patch.object(
            teacher_routes, 'log_activity'
        ):
            response = self.post_with_csrf(
                '/teacher/course/3/4/save-results',
                {
                    'exam_type': 'Mid-Term',
                    'exam_date': '2026-10-15',
                    'total_marks': '50',
                    'student_ids': ['21', '22'],
                    'marks_21': '45.50',
                    'marks_22': '0',
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0][0].startswith('UPDATE results'))
        self.assertEqual(writes[0][1], (45.50, 50, 90, 21, 3))
        self.assertTrue(writes[1][0].startswith('INSERT INTO results'))
        self.assertEqual(writes[1][1], (22, 3, 'Mid-Term', 0, 50, date(2026, 10, 15)))

    def test_teacher_cannot_enter_results_for_unassigned_or_forged_students(self):
        self.set_identity(80, 'Teacher')
        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 12}), patch.object(
            teacher_routes, 'query', side_effect=[{'id': 5}, [{'id': 21}]]
        ), patch.object(teacher_routes, 'transaction') as transaction_mock:
            response = self.post_with_csrf(
                '/teacher/course/3/4/save-results',
                {
                    'exam_type': 'Quiz',
                    'exam_date': '2026-10-15',
                    'total_marks': '10',
                    'student_ids': ['21', '999'],
                    'marks_21': '8',
                    'marks_999': '7',
                }
            )

        self.assertEqual(response.status_code, 403)
        transaction_mock.assert_not_called()

        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 12}), patch.object(
            teacher_routes, 'query', return_value=None
        ), patch.object(teacher_routes, 'transaction') as transaction_mock:
            unauthorized_course = self.post_with_csrf(
                '/teacher/course/3/4/save-results',
                {
                    'exam_type': 'Quiz',
                    'exam_date': '2026-10-15',
                    'total_marks': '10',
                    'student_ids': ['21'],
                    'marks_21': '8',
                }
            )
        self.assertEqual(unauthorized_course.status_code, 403)
        transaction_mock.assert_not_called()

    def test_teacher_rejects_marks_above_total_and_reports_failed_save(self):
        self.set_identity(80, 'Teacher')
        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 12}), patch.object(
            teacher_routes, 'query', side_effect=[{'id': 5}, [{'id': 21}]]
        ), patch.object(teacher_routes, 'transaction') as transaction_mock:
            invalid_marks = self.post_with_csrf(
                '/teacher/course/3/4/save-results',
                {
                    'exam_type': 'Quiz',
                    'exam_date': '2026-10-15',
                    'total_marks': '10',
                    'student_ids': ['21'],
                    'marks_21': '11',
                }
            )
        self.assertEqual(invalid_marks.status_code, 302)
        transaction_mock.assert_not_called()

        with self.client.session_transaction() as session:
            session['_csrf_token'] = 'phase-four-test-token'
        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 12}), patch.object(
            teacher_routes, 'query', side_effect=[
                {'id': 5},
                [{'id': 21}],
                [],
            ]
        ), patch.object(teacher_routes, 'transaction', return_value=False):
            failed_save = self.post_with_csrf(
                '/teacher/course/3/4/save-results',
                {
                    'exam_type': 'Quiz',
                    'exam_date': '2026-10-15',
                    'total_marks': '10',
                    'student_ids': ['21'],
                    'marks_21': '8',
                }
            )
        self.assertEqual(failed_save.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertIn('Results could not be saved', str(session.get('_flashes')))

    def test_approved_leave_uses_all_assigned_subjects_and_dates(self):
        with patch.object(leave_workflow, 'query', return_value=[
            {'subject_id': 7, 'teacher_id': 18},
            {'subject_id': 9, 'teacher_id': 24},
        ]) as query_mock:
            writes = leave_workflow.approved_leave_attendance_queries(
                30, 5, date(2026, 10, 15), date(2026, 10, 16)
            )

        query_mock.assert_called_once()
        self.assertEqual(len(writes), 4)
        self.assertEqual(
            {statement[1][2] for statement in writes},
            {7, 9}
        )
        self.assertEqual(
            {statement[1][3] for statement in writes},
            {18, 24}
        )
        self.assertEqual(
            {statement[1][4] for statement in writes},
            {'2026-10-15', '2026-10-16'}
        )
        self.assertNotIn(1, {statement[1][2] for statement in writes})

    def test_fa_leave_approval_updates_status_and_attendance_atomically(self):
        self.set_identity(50, 'FA')
        leave = {
            'id': 90,
            'student_id': 30,
            'user_id': 31,
            'section_id': 5,
            'from_date': date(2026, 10, 15),
            'to_date': date(2026, 10, 15),
        }
        attendance_write = (
            'INSERT INTO attendance ...',
            (30, 5, 7, 18, '2026-10-15')
        )
        statements = []
        with patch.object(fa_routes, 'query', side_effect=[leave, 1]) as query_mock, patch.object(
            fa_routes, 'approved_leave_attendance_queries', return_value=[attendance_write]
        ), patch.object(fa_routes, 'transaction', side_effect=lambda writes: statements.extend(writes) or True):
            response = self.post_with_csrf(
                '/fa/leave-requests/respond',
                {'leave_id': '90', 'action': 'approve'}
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(statements), 2)
        self.assertIn("status = 'Pending'", statements[0][0])
        self.assertEqual(statements[1], attendance_write)
        self.assertEqual(query_mock.call_count, 2)

    def test_teacher_leave_approval_uses_the_shared_attendance_transaction(self):
        self.set_identity(80, 'Teacher')
        leave = {
            'id': 90,
            'student_id': 30,
            'from_date': date(2026, 10, 15),
            'to_date': date(2026, 10, 15),
        }
        student = {'id': 30, 'user_id': 31, 'section_id': 5}
        attendance_write = ('INSERT INTO attendance ...', (30, 5, 7, 18, '2026-10-15'))
        statements = []

        with patch.object(teacher_routes, 'get_teacher_id', return_value={'id': 18}), patch.object(
            teacher_routes, 'query', side_effect=[leave, student, 1]
        ) as query_mock, patch.object(
            teacher_routes, 'approved_leave_attendance_queries', return_value=[attendance_write]
        ), patch.object(
            teacher_routes, 'transaction', side_effect=lambda writes: statements.extend(writes) or True
        ):
            response = self.post_with_csrf(
                '/teacher/leave-requests/respond',
                {'leave_id': '90', 'action': 'approve'}
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(statements), 2)
        self.assertIn("status = 'Pending'", statements[0][0])
        self.assertEqual(statements[1], attendance_write)
        self.assertEqual(query_mock.call_count, 3)

    def test_fa_rejects_unknown_leave_action_without_changing_records(self):
        self.set_identity(50, 'FA')
        with patch.object(fa_routes, 'query') as query_mock, patch.object(
            fa_routes, 'transaction'
        ) as transaction_mock:
            response = self.post_with_csrf(
                '/fa/leave-requests/respond',
                {'leave_id': '90', 'action': 'anything'}
            )

        self.assertEqual(response.status_code, 302)
        query_mock.assert_not_called()
        transaction_mock.assert_not_called()

    def test_leave_approval_warns_when_section_has_no_attendance_assignments(self):
        self.set_identity(50, 'FA')
        leave = {
            'id': 90,
            'student_id': 30,
            'user_id': 31,
            'section_id': None,
            'from_date': date(2026, 10, 15),
            'to_date': date(2026, 10, 15),
        }
        with patch.object(fa_routes, 'query', side_effect=[leave, 1]), patch.object(
            fa_routes, 'approved_leave_attendance_queries', return_value=[]
        ), patch.object(fa_routes, 'transaction', return_value=True):
            response = self.post_with_csrf(
                '/fa/leave-requests/respond',
                {'leave_id': '90', 'action': 'approve'}
            )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertIn('no subject assignments were found', str(session.get('_flashes')))

    def test_student_rejects_reversed_or_invalid_leave_dates(self):
        self.set_identity(70, 'Student')
        with patch.object(student_routes, 'get_student_record', return_value={
            'id': 30, 'status': 'Active', 'section_id': 5, 'name': 'Synthetic Student'
        }), patch.object(student_routes, 'query') as query_mock:
            reversed_dates = self.post_with_csrf(
                '/student/leave',
                {'from_date': '2026-10-16', 'to_date': '2026-10-15', 'reason': 'Synthetic reason'}
            )
            invalid_date = self.post_with_csrf(
                '/student/leave',
                {'from_date': 'not-a-date', 'to_date': '2026-10-16', 'reason': 'Synthetic reason'}
            )

        self.assertEqual(reversed_dates.status_code, 302)
        self.assertEqual(invalid_date.status_code, 302)
        query_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
