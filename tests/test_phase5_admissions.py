import os
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import patch

with patch.dict(os.environ, {'DEBUG': 'true', 'SECRET_KEY': 'test-secret-key-for-phase-five'}):
    with patch('database.connection.query'):
        import app as schoolsync_app

import routes.admission_routes as admission_routes
import routes.admin_routes as admin_routes


class Phase5AdmissionsTests(unittest.TestCase):
    def setUp(self):
        schoolsync_app.app.config['TESTING'] = True
        self.client = schoolsync_app.app.test_client()
        with self.client.session_transaction() as session:
            session['_csrf_token'] = 'phase-five-test-token'

    def set_identity(self, user_id, role, application_ref=None):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['user_type'] = role
            session['_csrf_token'] = 'phase-five-test-token'
            if application_ref:
                session['admission_application_ref'] = application_ref

    def test_startup_ensures_admission_tables_and_preserves_existing_intake_state(self):
        statements = []

        def record_query(sql, params=None, fetch=False, fetch_one=False):
            statements.append(sql)
            return None

        with patch.object(schoolsync_app, 'query', side_effect=record_query):
            schoolsync_app.ensure_schema()

        self.assertTrue(any(
            'CREATE TABLE IF NOT EXISTS admission_intake' in sql
            for sql in statements
        ))
        self.assertTrue(any(
            'INSERT IGNORE INTO admission_intake' in sql
            and 'VALUES (1, 0)' in sql
            for sql in statements
        ))
        intake_table = next(
            sql for sql in statements
            if 'CREATE TABLE IF NOT EXISTS admission_intake' in sql
        )
        self.assertIn('updated_by INT NULL', intake_table)
        self.assertIn('FOREIGN KEY (updated_by)', intake_table)
        for table in (
            'admission_applications',
            'admission_documents',
            'admission_audit_log',
        ):
            self.assertTrue(any(
                'CREATE TABLE IF NOT EXISTS ' + table in sql
                for sql in statements
            ))

    def test_gr_can_open_admissions_intake_after_successful_update(self):
        self.set_identity(9, 'GR_Office')

        with patch.object(
            admission_routes,
            'query',
            return_value={'id': 7},
        ), patch.object(admission_routes, 'transaction', return_value=True) as transaction_mock, patch.object(
            admission_routes, 'log_activity'
        ):
            response = self.client.post(
                '/gr/admissions/intake',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'action': 'open',
                },
            )

        self.assertEqual(response.status_code, 302)
        transaction_mock.assert_called_once()
        with self.client.session_transaction() as session:
            self.assertIn('Admission intake opened.', str(session.get('_flashes')))

    def test_gr_can_send_approved_application_to_active_it_admins(self):
        self.set_identity(9, 'GR_Office')
        required_documents = [
            {'category': category, 'status': 'Approved'}
            for category in admission_routes.REQUIRED_DOCUMENTS
        ]
        writes = []

        def fake_query(sql, params=None, fetch=False, fetch_one=False):
            if 'SELECT id FROM gr_office' in sql:
                return {'id': 7}
            if 'SELECT id, status FROM admission_applications' in sql:
                return {'id': 23, 'status': 'Pending Review'}
            if 'SELECT d.* FROM admission_documents' in sql:
                return required_documents
            if 'SELECT id FROM admission_audit_log' in sql:
                return None
            if "SELECT id FROM users WHERE user_type = 'IT_Admin'" in sql:
                return [{'id': 3}, {'id': 4}]
            if 'SELECT application_ref FROM admission_applications' in sql:
                return {'application_ref': 'synthetic-ref'}
            self.fail(f'Unexpected query: {sql}')

        def capture_transaction(statements, require_affected_rows=False):
            self.assertTrue(require_affected_rows)
            writes.extend(statements)
            return True

        with patch.object(admission_routes, 'query', side_effect=fake_query), patch.object(
            admission_routes, 'transaction', side_effect=capture_transaction
        ) as transaction_mock, patch.object(admission_routes, 'log_activity'):
            response = self.client.post(
                '/gr/admissions/23/review',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'action': 'send_to_admin',
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(writes), 4)
        self.assertIn("SET status = %s", writes[0][0])
        self.assertIn('APPLICATION_SENT_TO_ADMIN', writes[0][0])
        self.assertIn('INSERT INTO admission_audit_log', writes[1][0])
        self.assertIn('INSERT INTO notifications', writes[2][0])
        self.assertIn('INSERT INTO notifications', writes[3][0])
        self.assertEqual(writes[2][1][0], 3)
        self.assertEqual(writes[3][1][0], 4)
        self.assertEqual(writes[2][1][3], '/admin/users')
        transaction_mock.assert_called_once()
        with self.client.session_transaction() as session:
            self.assertIn(
                'Application approved and sent to IT Admin for Student account creation.',
                str(session.get('_flashes')),
            )

    def test_public_application_form_is_standalone_and_does_not_render_staff_navigation(self):
        self.set_identity(9, 'GR_Office')
        with patch.object(
            admission_routes,
            'query',
            side_effect=[
                {'id': 1, 'is_open': 1},
                [{'id': 4, 'name': 'Grade 4'}],
            ],
        ):
            response = self.client.get('/admission')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Secure public application form', response.data)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertNotIn(b'class="sidebar"', response.data)
        self.assertNotIn(b'Logout', response.data)

    def test_public_submission_is_available_and_persists_private_document_paths(self):
        writes = []

        def fake_query(sql, params=None, fetch=False, fetch_one=False):
            if 'SELECT id, is_open FROM admission_intake' in sql:
                return {'id': 1, 'is_open': 1}
            if 'SELECT id FROM grades' in sql:
                return {'id': 4}
            if 'SELECT id FROM admission_applications' in sql:
                return None
            if 'SELECT user_id FROM gr_office' in sql:
                return []
            return None

        def capture_transaction(statements, require_affected_rows=False):
            writes.extend(statements)
            self.assertTrue(require_affected_rows)
            self.assertEqual(statements[0][1][1].__len__(), 64)
            return 81

        with patch.object(admission_routes, 'query', side_effect=fake_query), patch.object(
            admission_routes, 'transaction_with_insert_id', side_effect=capture_transaction
        ):
            response = self.client.post(
                '/admission',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'applicant_name': 'Synthetic Applicant',
                    'guardian_name': 'Synthetic Guardian',
                    'guardian_phone': '555-0100',
                    'contact_phone': '555-0101',
                    'email': 'applicant@example.test',
                    'address': 'Synthetic address',
                    'previous_school': 'Synthetic School',
                    'previous_grade': 'Grade 4',
                    'applied_grade_id': '4',
                    'dob': '2015-02-03',
                    'gender': 'Other',
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Application submitted', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(len(writes), 2)
        self.assertIn('INSERT INTO admission_applications', writes[0][0])
        self.assertIn('INSERT INTO admission_audit_log', writes[1][0])
        self.assertNotIn(writes[0][1][1].encode(), response.data)

    def test_public_intake_closed_does_not_start_a_submission_transaction(self):
        with patch.object(
            admission_routes,
            'query',
            side_effect=[
                {'id': 1, 'is_open': 0},
                [],
            ],
        ), patch.object(admission_routes, 'transaction_with_insert_id') as transaction_mock:
            response = self.client.post(
                '/admission',
                data={'csrf_token': 'phase-five-test-token'}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admissions are currently closed', response.data)
        transaction_mock.assert_not_called()

    def test_applicant_cannot_upload_corrections_without_private_application_session(self):
        with patch.object(admission_routes, 'query') as query_mock:
            response = self.client.post(
                '/admission/corrections',
                data={'csrf_token': 'phase-five-test-token'}
            )

        self.assertEqual(response.status_code, 403)
        query_mock.assert_not_called()

    def test_non_gr_role_cannot_open_admission_dashboard(self):
        self.set_identity(20, 'Teacher')
        with patch.object(admission_routes, 'query') as query_mock:
            response = self.client.get('/gr/admissions')

        self.assertEqual(response.status_code, 302)
        query_mock.assert_not_called()

    def test_applicant_token_is_verified_before_status_session_is_granted(self):
        access_code = 'synthetic-private-access-code'
        application = {
            'id': 2,
            'application_ref': 'synthetic-reference',
            'access_token_hash': admission_routes.hashlib.sha256(access_code.encode()).hexdigest(),
            'token_expires_at': datetime.now() + timedelta(minutes=10),
            'status': 'Incomplete',
        }
        with patch.object(admission_routes, 'query', return_value=application):
            response = self.client.post(
                '/admission/status',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'application_ref': 'synthetic-reference',
                    'access_token': access_code,
                }
            )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['admission_application_ref'], 'synthetic-reference')

    def test_applicant_cannot_use_expired_or_incorrect_status_token(self):
        with self.client.session_transaction() as session:
            session['admission_application_ref'] = 'previously-authorized-reference'
        application = {
            'id': 2,
            'application_ref': 'synthetic-reference',
            'access_token_hash': admission_routes.hashlib.sha256(b'correct-code').hexdigest(),
            'token_expires_at': datetime.now() - timedelta(minutes=1),
            'status': 'Incomplete',
        }
        with patch.object(admission_routes, 'query', return_value=application):
            response = self.client.post(
                '/admission/status',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'application_ref': 'synthetic-reference',
                    'access_token': 'wrong-code',
                }
            )

        self.assertEqual(response.status_code, 400)
        with self.client.session_transaction() as session:
            self.assertNotIn('admission_application_ref', session)

    def test_gr_document_download_is_private_and_requires_gr_role(self):
        with tempfile.TemporaryDirectory() as folder:
            root = os.path.join(folder, 'admissions')
            os.mkdir(root)
            with open(os.path.join(root, 'synthetic.pdf'), 'wb') as uploaded:
                uploaded.write(b'%PDF-synthetic')
            schoolsync_app.app.config['PRIVATE_ADMISSIONS_FOLDER'] = root
            self.set_identity(9, 'GR_Office')

            with patch.object(
                admission_routes,
                'query',
                side_effect=[
                    {'id': 7},
                    {'file_path': 'private/admissions/synthetic.pdf', 'application_id': 2},
                ],
            ):
                response = self.client.get('/gr/admissions/document/4?download=1')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'%PDF-synthetic')
            self.assertIn('attachment', response.headers['Content-Disposition'])
            response.close()

    def test_gr_can_render_application_review_detail(self):
        self.set_identity(9, 'GR_Office')
        application = {
            'id': 2,
            'application_ref': 'synthetic-reference',
            'applicant_name': 'Synthetic Applicant',
            'status': 'Pending Review',
            'dob': datetime(2015, 2, 3).date(),
            'gender': 'Other',
            'contact_phone': '555-0101',
            'email': None,
            'guardian_name': 'Synthetic Guardian',
            'guardian_phone': '555-0100',
            'applied_grade': 'Grade 4',
            'previous_school': 'Synthetic School',
            'previous_grade': 'Grade 3',
            'address': 'Synthetic address',
            'internal_note': None,
        }
        approved_documents = [
            {'category': category, 'status': 'Approved'}
            for category in admission_routes.REQUIRED_DOCUMENTS
        ]
        with patch.object(
            admission_routes,
            'query',
            side_effect=[{'id': 7}, application, [], approved_documents, None],
        ), patch.object(schoolsync_app, 'query', return_value={'count': 0}):
            response = self.client.get('/gr/admissions/2')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Synthetic Applicant', response.data)
        self.assertIn(b'Document versions', response.data)
        self.assertIn(b'Send to Admin', response.data)

    def test_gr_cannot_send_application_to_admin_without_approved_required_documents(self):
        self.set_identity(9, 'GR_Office')
        with patch.object(
            admission_routes,
            'query',
            side_effect=[
                {'id': 7},
                {'id': 2, 'status': 'Pending Review'},
                [],
            ],
        ), patch.object(admission_routes, 'transaction') as transaction_mock:
            response = self.client.post(
                '/gr/admissions/2/review',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'action': 'send_to_admin',
                }
            )

        self.assertEqual(response.status_code, 302)
        transaction_mock.assert_not_called()

    def test_admission_document_path_rejects_traversal_and_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = os.path.join(folder, 'admissions')
            os.mkdir(root)
            outside = os.path.join(folder, 'outside.pdf')
            with open(outside, 'wb') as document:
                document.write(b'synthetic')

            with schoolsync_app.app.test_request_context('/'):
                schoolsync_app.app.config['PRIVATE_ADMISSIONS_FOLDER'] = root
                self.assertIsNone(admission_routes._admission_document_path('private/admissions/../outside.pdf'))
                self.assertIsNone(admission_routes._admission_document_path('private/admissions/missing.pdf'))

    def test_corrections_replace_only_requested_file_and_store_it_privately(self):
        with tempfile.TemporaryDirectory() as folder:
            schoolsync_app.app.config['PRIVATE_ADMISSIONS_FOLDER'] = folder
            self.set_identity(0, 'Applicant', 'synthetic-reference')
            statements = []

            def capture_transaction(writes):
                statements.extend(writes)
                return True

            with patch.object(
                admission_routes,
                'query',
                side_effect=[
                    {
                        'id': 2,
                        'application_ref': 'synthetic-reference',
                        'status': 'Corrections Requested',
                        'token_expires_at': datetime.now() + timedelta(days=1),
                    },
                    [{
                        'category': 'Birth Certificate',
                        'status': 'Replacement Requested',
                    }, {
                        'category': 'Report Card',
                        'status': 'Approved',
                    }],
                ],
            ), patch.object(admission_routes, 'transaction', side_effect=capture_transaction):
                response = self.client.post(
                    '/admission/corrections',
                    data={
                        'csrf_token': 'phase-five-test-token',
                        'document_birth_certificate': (BytesIO(b'%PDF-synthetic'), 'birth.pdf'),
                    },
                    content_type='multipart/form-data',
                )

            self.assertEqual(response.status_code, 302)
            self.assertEqual(len(statements), 3)
            self.assertIn('private/admissions/', statements[0][1][2])
            self.assertEqual(os.listdir(folder), [statements[0][1][2].split('/')[-1]])

    def test_applicant_cannot_replace_a_document_not_requested_by_gr(self):
        self.set_identity(0, 'Applicant', 'synthetic-reference')
        with patch.object(
            admission_routes,
            'query',
            side_effect=[
                {
                    'id': 2,
                    'application_ref': 'synthetic-reference',
                    'status': 'Corrections Requested',
                    'token_expires_at': datetime.now() + timedelta(days=1),
                },
                [{
                    'category': 'Birth Certificate',
                    'status': 'Replacement Requested',
                }, {
                    'category': 'Report Card',
                    'status': 'Approved',
                }],
            ],
        ), patch.object(admission_routes, 'save_validated_upload') as save_mock, patch.object(
            admission_routes, 'transaction'
        ) as transaction_mock:
            response = self.client.post(
                '/admission/corrections',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'document_report_card': (BytesIO(b'%PDF-synthetic'), 'report.pdf'),
                },
                content_type='multipart/form-data',
            )

        self.assertEqual(response.status_code, 302)
        save_mock.assert_not_called()
        transaction_mock.assert_not_called()

    def test_approved_application_enrollment_is_atomic_and_scoped(self):
        self.set_identity(3, 'IT_Admin')
        approved_application = {
            'id': 23,
            'application_ref': 'synthetic-ref',
            'applicant_name': 'Synthetic Applicant',
            'guardian_name': 'Synthetic Guardian',
            'guardian_phone': '555-0100',
            'contact_phone': '555-0101',
            'email': 'applicant@example.test',
            'applied_grade_id': 4,
            'dob': datetime(2015, 2, 3).date(),
            'gender': 'Other',
            'address': 'Synthetic address',
        }
        writes = []

        def capture_transaction(statements, require_affected_rows=False):
            writes.extend(statements)
            self.assertTrue(require_affected_rows)
            linked_user_id = 51
            self.assertEqual(statements[2][1](linked_user_id), (linked_user_id, 3, 23))
            return 51

        with patch.object(
            admin_routes,
            'query',
            side_effect=[
                approved_application,
                {'id': 7, 'section_label': 'Grade 4 - A'},
                None,
                None,
                [],
            ],
        ), patch.object(admin_routes, 'hash_password', return_value='synthetic-hash'), patch.object(
            admin_routes, 'transaction_with_insert_id', side_effect=capture_transaction
        ), patch.object(admin_routes, 'log_activity'), patch.object(
            schoolsync_app, 'query', return_value={'count': 0}
        ):
            response = self.client.post(
                '/admin/create-user',
                data={
                    'csrf_token': 'phase-five-test-token',
                    'username': 'synthetic-student',
                    'password': 'synthetic-password',
                    'user_type': 'Student',
                    'name': 'Synthetic Applicant',
                    'admission_application_id': '23',
                    'section_id': '7',
                    'roll_number': 'SYN-01',
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(writes), 3)
        self.assertIn('INSERT INTO users', writes[0][0])
        self.assertIn('INSERT INTO students', writes[1][0])
        self.assertIn("SET status = 'Enrolled'", writes[2][0])
        self.assertIn(b'Synthetic Applicant', response.data)
        self.assertIn(b'synthetic-student', response.data)
        self.assertIn(b'synthetic-password', response.data)
        self.assertIn(b'SS-', response.data)
        self.assertIn(b'Grade 4 - A', response.data)
        self.assertIn(b'SYN-01', response.data)
        self.assertNotIn(b'Date of Birth', response.data)
        self.assertNotIn(b'Father', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])


if __name__ == '__main__':
    unittest.main()
