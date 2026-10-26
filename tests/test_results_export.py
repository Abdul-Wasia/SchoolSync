import os
import unittest
from unittest.mock import patch


with patch.dict(os.environ, {'DEBUG': 'true', 'SECRET_KEY': 'test-secret-key-for-results-export'}):
    with patch('database.connection.query'):
        import app as schoolsync_app


class ResultsExportTests(unittest.TestCase):
    def setUp(self):
        self.client = schoolsync_app.app.test_client()
        schoolsync_app.app.config['TESTING'] = True

    def test_student_can_export_own_results(self):
        results = [{
            'subject_name': 'Mathematics',
            'exam_type': 'Final-Term',
            'marks_obtained': 90,
            'total_marks': 100,
            'grade': 'A',
            'exam_date': '2026-10-01',
        }]
        with self.client.session_transaction() as session:
            session['user_id'] = 42
            session['user_type'] = 'Student'

        with patch.object(schoolsync_app, 'query', side_effect=[
            {'id': 7, 'status': 'Active'},
            results,
        ]) as query_mock:
            response = self.client.get('/export/results/7')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Mathematics', response.data)
        self.assertEqual(query_mock.call_count, 2)
        self.assertEqual(query_mock.call_args_list[0].args[1], (42,))
        self.assertEqual(query_mock.call_args_list[1].args[1], (7,))

    def test_student_cannot_export_another_students_results(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 42
            session['user_type'] = 'Student'

        with patch.object(schoolsync_app, 'query', return_value={'id': 7, 'status': 'Active'}) as query_mock:
            response = self.client.get('/export/results/8')

        self.assertEqual(response.status_code, 403)
        query_mock.assert_called_once()

    def test_non_student_role_cannot_export_results(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 42
            session['user_type'] = 'Teacher'

        with patch.object(schoolsync_app, 'query') as query_mock:
            response = self.client.get('/export/results/7')

        self.assertEqual(response.status_code, 302)
        query_mock.assert_not_called()

    def test_student_without_active_results_access_is_denied(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 42
            session['user_type'] = 'Student'

        with patch.object(schoolsync_app, 'query', return_value={'id': 7, 'status': 'PendingLogin'}) as query_mock:
            response = self.client.get('/export/results/7')

        self.assertEqual(response.status_code, 403)
        query_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
