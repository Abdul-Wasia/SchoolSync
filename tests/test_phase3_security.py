import os
import unittest
from unittest.mock import Mock, patch

import mysql.connector

with patch.dict(os.environ, {'DEBUG': 'true', 'SECRET_KEY': 'test-secret-key-for-phase-three'}):
    with patch('database.connection.query'):
        import app as schoolsync_app

import routes.admin_routes as admin_routes
import routes.auth_routes as auth_routes
from database import connection


class CsrfProtectionTests(unittest.TestCase):
    def setUp(self):
        schoolsync_app.app.config['TESTING'] = True
        self.client = schoolsync_app.app.test_client()

    def test_login_form_contains_csrf_token(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf_token"', response.data)

        with self.client.session_transaction() as session:
            token = session['_csrf_token']
        self.assertIn(token.encode(), response.data)

    def test_missing_or_invalid_csrf_token_rejects_form_before_database_access(self):
        for token in (None, 'invalid'):
            with self.subTest(token=token), patch.object(auth_routes, 'query') as query_mock:
                response = self.client.post(
                    '/login',
                    data={'username': 'synthetic', 'password': 'incorrect', **(
                        {'csrf_token': token} if token else {}
                    )}
                )
                self.assertEqual(response.status_code, 400)
                query_mock.assert_not_called()

    def test_valid_csrf_token_allows_login_workflow(self):
        page = self.client.get('/login')
        with self.client.session_transaction() as session:
            token = session['_csrf_token']

        with patch.object(auth_routes, 'query', return_value=None) as query_mock:
            response = self.client.post(
                '/login',
                data={'username': 'synthetic', 'password': 'incorrect', 'csrf_token': token}
            )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(response.status_code, 200)
        query_mock.assert_called_once()

    def test_json_mutation_requires_csrf_header(self):
        response = self.client.post('/ai/summarize', json={'topic': 'synthetic'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json['success'])

    def test_otp_forms_include_csrf_tokens(self):
        with self.client.session_transaction() as session:
            session['reset_email'] = 'synthetic@example.invalid'
        response = self.client.get('/verify-otp')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data.count(b'name="csrf_token"'), 2)

    def test_otp_limit_blocks_further_verification_attempts(self):
        with self.client.session_transaction() as session:
            session['reset_email'] = 'synthetic@example.invalid'
            session['otp_attempts'] = auth_routes.OTP_MAX_ATTEMPTS
            session['_csrf_token'] = 'otp-limit-token'

        with patch.object(auth_routes, 'query') as query_mock:
            response = self.client.post(
                '/verify-otp',
                data={'csrf_token': 'otp-limit-token', 'otp': '123456'}
            )

        self.assertEqual(response.status_code, 302)
        query_mock.assert_not_called()

    def test_logout_requires_post_and_csrf(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 17
            session['username'] = 'synthetic'
            session['_csrf_token'] = 'logout-csrf-token'

        with patch.object(schoolsync_app, 'query', return_value={'count': 0}):
            confirmation = self.client.get('/logout')
        with self.client.session_transaction() as session:
            self.assertEqual(session.get('user_id'), 17)

        with patch.object(auth_routes, 'log_activity'):
            response = self.client.post(
                '/logout',
                data={'csrf_token': 'logout-csrf-token'}
            )

        self.assertEqual(confirmation.status_code, 200)
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)


class LoginThrottleTests(unittest.TestCase):
    def setUp(self):
        auth_routes.clear_login_failures('192.0.2.10')

    def tearDown(self):
        auth_routes.clear_login_failures('192.0.2.10')

    def test_ip_throttle_expires_and_does_not_lock_account_identity(self):
        for attempt in range(auth_routes.LOGIN_FAILURE_LIMIT):
            auth_routes.record_login_failure('192.0.2.10', now=100 + attempt)
        self.assertTrue(auth_routes.login_is_throttled('192.0.2.10', now=200))
        self.assertFalse(auth_routes.login_is_throttled(
            '192.0.2.10',
            now=100 + auth_routes.LOGIN_FAILURE_WINDOW_SECONDS + 5
        ))

        auth_routes.record_login_failure('192.0.2.10', now=500)
        self.assertFalse(auth_routes.login_is_throttled('192.0.2.11', now=501))

    def test_login_route_throttles_before_database_lookup(self):
        address = '198.51.100.20'
        auth_routes.clear_login_failures(address)
        for _ in range(auth_routes.LOGIN_FAILURE_LIMIT):
            auth_routes.record_login_failure(address)
        client = schoolsync_app.app.test_client()
        login_page = client.get('/login')
        with client.session_transaction() as session:
            token = session['_csrf_token']

        try:
            with patch.object(auth_routes, 'query') as query_mock:
                response = client.post(
                    '/login',
                    data={'username': 'synthetic', 'password': 'incorrect', 'csrf_token': token},
                    environ_base={'REMOTE_ADDR': address}
                )
            self.assertEqual(login_page.status_code, 200)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Too many failed attempts', response.data)
            query_mock.assert_not_called()
        finally:
            auth_routes.clear_login_failures(address)


class DatabaseReliabilityTests(unittest.TestCase):
    def setUp(self):
        schoolsync_app.app.config['TESTING'] = True
        self.client = schoolsync_app.app.test_client()

    def test_role_account_writes_share_one_transaction(self):
        connection_mock = Mock()
        cursor = connection_mock.cursor.return_value
        cursor.lastrowid = 42

        with patch.object(connection, 'get_db', return_value=connection_mock):
            user_id = connection.transaction_with_insert_id([
                ('INSERT INTO users (username) VALUES (%s)', ('teacher',)),
                (
                    'INSERT INTO teachers (user_id, name) VALUES (%s, %s)',
                    lambda inserted_id: (inserted_id, 'Synthetic Teacher')
                ),
            ])

        self.assertEqual(user_id, 42)
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (42, 'Synthetic Teacher'))
        connection_mock.commit.assert_called_once()
        connection_mock.rollback.assert_not_called()

    def test_role_insert_failure_rolls_back_without_logging_sql_or_parameters(self):
        connection_mock = Mock()
        cursor = connection_mock.cursor.return_value
        cursor.lastrowid = 42
        cursor.execute.side_effect = [None, mysql.connector.Error('sensitive synthetic detail')]

        with patch.object(connection, 'get_db', return_value=connection_mock):
            with self.assertLogs(connection.logger, level='ERROR') as captured:
                result = connection.transaction_with_insert_id([
                    ('INSERT INTO users VALUES (%s)', ('synthetic-secret',)),
                    ('INSERT INTO teachers VALUES (%s)', (42,)),
                ])

        self.assertIsNone(result)
        connection_mock.rollback.assert_called_once()
        connection_mock.commit.assert_not_called()
        self.assertNotIn('synthetic-secret', '\n'.join(captured.output))
        self.assertNotIn('sensitive synthetic detail', '\n'.join(captured.output))

    def test_query_failure_log_omits_sql_and_parameters(self):
        connection_mock = Mock()
        connection_mock.cursor.return_value.execute.side_effect = mysql.connector.Error(
            'sensitive synthetic detail'
        )
        sql = 'UPDATE users SET password = %s WHERE username = %s'
        params = ('synthetic-hash', 'synthetic-user')

        with patch.object(connection, 'get_db', return_value=connection_mock):
            with self.assertLogs(connection.logger, level='ERROR') as captured:
                result = connection.query(sql, params)

        self.assertEqual(result, 0)
        output = '\n'.join(captured.output)
        self.assertNotIn(sql, output)
        self.assertNotIn('synthetic-hash', output)
        self.assertNotIn('synthetic-user', output)
        self.assertNotIn('sensitive synthetic detail', output)

    def test_admin_rejects_role_outside_six_defined_roles(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['user_type'] = 'IT_Admin'
            session['_csrf_token'] = 'phase-three-admin-token'

        with patch.object(admin_routes, 'query') as query_mock, patch.object(
            admin_routes, 'transaction_with_insert_id'
        ) as transaction_mock:
            response = self.client.post(
                '/admin/create-user',
                data={
                    'csrf_token': 'phase-three-admin-token',
                    'username': 'synthetic',
                    'password': 'synthetic-password',
                    'user_type': 'Unknown',
                    'name': 'Synthetic User',
                }
            )

        self.assertEqual(response.status_code, 302)
        query_mock.assert_not_called()
        transaction_mock.assert_not_called()

    def test_admin_creates_user_and_role_profile_in_same_transaction(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['user_type'] = 'IT_Admin'
            session['_csrf_token'] = 'phase-three-admin-token'

        transaction_queries = []

        def capture_transaction(queries):
            transaction_queries.extend(queries)
            self.assertEqual(len(queries), 2)
            self.assertIn('INSERT INTO users', queries[0][0])
            self.assertIn('INSERT INTO teachers', queries[1][0])
            self.assertEqual(queries[1][1](42)[0], 42)
            return 42

        with patch.object(admin_routes, 'query', side_effect=[None, []]) as query_mock, patch.object(
            admin_routes, 'hash_password', return_value='synthetic-hash'
        ), patch.object(admin_routes, 'transaction_with_insert_id', side_effect=capture_transaction) as transaction_mock, patch.object(
            admin_routes, 'log_activity'
        ), patch.object(schoolsync_app, 'query', return_value={'count': 0}):
            response = self.client.post(
                '/admin/create-user',
                data={
                    'csrf_token': 'phase-three-admin-token',
                    'username': 'synthetic-teacher',
                    'password': 'synthetic-password',
                    'user_type': 'Teacher',
                    'name': 'Synthetic Teacher',
                    'subject': 'Mathematics',
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'synthetic-teacher', response.data)
        self.assertIn(b'synthetic-password', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])
        transaction_mock.assert_called_once()
        self.assertEqual(len(transaction_queries), 2)
        self.assertEqual(query_mock.call_count, 2)


if __name__ == '__main__':
    unittest.main()
