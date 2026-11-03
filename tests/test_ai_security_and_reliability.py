"""Automated tests for SchoolSync AI Assistant Security and Reliability:
1. Authentication & Role-based Access Control
2. Protected AI Status Endpoint & Information Disclosure Prevention
3. Quiz Input Validation (Missing, Non-numeric, Clamped question counts)
4. Provider Fallback & Error Handling
5. JSON Parsing Robustness
6. Safe Material Extraction & Path Traversal Prevention
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from app import app
from routes.ai_helper import call_ai, call_ai_json, extract_material_text


class AiAssistantSecurityAndReliabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def _login_as(self, user_id=1, username='admin', user_type='IT_Admin'):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username
            sess['user_type'] = user_type
            sess['_csrf_token'] = 'test-ai-csrf-token'

    def _set_csrf_only(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess['_csrf_token'] = 'test-ai-csrf-token'

    def post_json(self, endpoint, data=None):
        headers = {
            'X-CSRFToken': 'test-ai-csrf-token',
            'Content-Type': 'application/json'
        }
        return self.client.post(endpoint, data=json.dumps(data or {}), headers=headers)

    # -----------------------------------------------------------------------
    # 1. Authentication & Role Enforcement Tests
    # -----------------------------------------------------------------------
    def test_unauthenticated_requests_are_rejected(self):
        # AI Status requires authentication (GET request)
        fresh_client = self.app.test_client()
        res_status = fresh_client.get('/ai/status')
        self.assertEqual(res_status.status_code, 401)
        self.assertFalse(res_status.json['success'])

        # Endpoints with CSRF token but no user session return 401
        self._set_csrf_only()
        for endpoint, payload in [
            ('/ai/summarize', {'topic': 'Photosynthesis'}),
            ('/ai/generate-quiz', {'topic': 'Algebra'}),
            ('/ai/generate-plan', {'exam_date': '2026-12-01', 'subjects': ['Math']}),
            ('/ai/generate-report', {'report_data': {}}),
            ('/ai/write-announcement', {'topic': 'Sports Day'}),
            ('/ai/chat/send', {'message': 'Hello'}),
        ]:
            res = self.post_json(endpoint, payload)
            self.assertEqual(res.status_code, 401, f"Endpoint {endpoint} should return 401 for unauthenticated user")
            self.assertFalse(res.json['success'])

    def test_role_authorization_on_sensitive_ai_routes(self):
        # Student attempting to generate formal school administration report
        self._login_as(user_id=7, username='student1', user_type='Student')
        res_report = self.post_json('/ai/generate-report', {'report_data': {}})
        self.assertEqual(res_report.status_code, 403)
        self.assertFalse(res_report.json['success'])

        # Principal can access report generation
        self._login_as(user_id=3, username='principal', user_type='Principal')
        with patch('routes.ai_routes.call_ai', return_value={'success': True, 'text': 'Executive Summary: Good progress.'}):
            res_principal = self.post_json('/ai/generate-report', {'report_data': {}})
            self.assertEqual(res_principal.status_code, 200)
            self.assertTrue(res_principal.json['success'])

    # -----------------------------------------------------------------------
    # 2. Protected AI Status Endpoint Tests
    # -----------------------------------------------------------------------
    def test_ai_status_endpoint_does_not_leak_keys_or_make_external_calls(self):
        self._login_as(user_id=1, username='admin', user_type='IT_Admin')
        
        with patch('requests.post') as mock_post:
            res = self.client.get('/ai/status')
            self.assertEqual(res.status_code, 200)
            data = res.json
            self.assertTrue(data['success'])
            self.assertIn('providers', data)

            # Confirm no external HTTP network requests were triggered
            mock_post.assert_not_called()

            # Confirm credentials are NOT leaked in response
            response_text = json.dumps(data)
            self.assertNotIn('api_key', response_text.lower())
            self.assertNotIn('bearer', response_text.lower())
            self.assertNotIn('?key=', response_text.lower())

    # -----------------------------------------------------------------------
    # 3. Quiz Input Validation Tests
    # -----------------------------------------------------------------------
    def test_quiz_input_validation(self):
        self._login_as(user_id=7, username='student1', user_type='Student')

        # Missing topic
        res_missing = self.post_json('/ai/generate-quiz', {'topic': '', 'num_questions': 5})
        self.assertEqual(res_missing.status_code, 400)
        self.assertIn('error', res_missing.json)

        # Non-numeric question count (e.g. 'five' or None) -> gracefully defaulted, no 500 error
        with patch('routes.ai_routes.call_ai_json') as mock_ai_json:
            mock_ai_json.return_value = {
                'questions': [{'question': 'Sample?', 'options': ['A', 'B', 'C', 'D'], 'correct': 'A'}]
            }

            for invalid_val in ['five', 'invalid', None, [], {}]:
                res = self.post_json('/ai/generate-quiz', {'topic': 'Science', 'num_questions': invalid_val})
                self.assertEqual(res.status_code, 200)
                self.assertTrue(res.json['success'])

            # Negative and zero question counts are clamped to minimum 1
            res_zero = self.post_json('/ai/generate-quiz', {'topic': 'Math', 'num_questions': -10})
            self.assertEqual(res_zero.status_code, 200)

            # Excessive question counts are clamped to maximum 20
            res_huge = self.post_json('/ai/generate-quiz', {'topic': 'Math', 'num_questions': 99999})
            self.assertEqual(res_huge.status_code, 200)

    # -----------------------------------------------------------------------
    # 4. Provider Fallback & Error Handling Tests
    # -----------------------------------------------------------------------
    def test_provider_fallback_chain(self):
        # Test Groq failing with 500, Gemini succeeds
        with patch('config.Config.GROQ_API_KEY', 'synthetic-groq-key'), \
             patch('config.Config.GEMINI_API_KEY', 'synthetic-gemini-key'), \
             patch('requests.post') as mock_post:

            groq_fail = MagicMock()
            groq_fail.status_code = 500

            gemini_success = MagicMock()
            gemini_success.status_code = 200
            gemini_success.json.return_value = {
                'candidates': [{'content': {'parts': [{'text': 'Gemini answer'}]}}]
            }

            mock_post.side_effect = [groq_fail, gemini_success]

            result = call_ai("Test question")
            self.assertTrue(result['success'])
            self.assertEqual(result['text'], 'Gemini answer')
            self.assertEqual(result['provider'], 'Gemini')

    def test_all_providers_failing_returns_graceful_message(self):
        with patch('config.Config.GROQ_API_KEY', 'synthetic-groq-key'), \
             patch('config.Config.GEMINI_API_KEY', 'synthetic-gemini-key'), \
             patch('config.Config.OPENROUTER_API_KEY', ''), \
             patch('config.Config.CLAUDE_API_KEY', ''), \
             patch('requests.post') as mock_post:

            mock_post.side_effect = Exception("Connection Timeout")

            result = call_ai("Test question")
            self.assertFalse(result['success'])
            self.assertIn('temporarily unavailable', result['text'])

    # -----------------------------------------------------------------------
    # 5. JSON Parsing Robustness
    # -----------------------------------------------------------------------
    def test_call_ai_json_parsing(self):
        # Case 1: Markdown code block wrapped JSON
        with patch('routes.ai_helper.call_ai') as mock_call:
            mock_call.return_value = {
                'success': True,
                'text': '```json\n{"questions": [{"question": "Q1"}]}\n```'
            }
            parsed = call_ai_json("Generate quiz")
            self.assertIsNotNone(parsed)
            self.assertIn('questions', parsed)

        # Case 2: Raw clean JSON
        with patch('routes.ai_helper.call_ai') as mock_call:
            mock_call.return_value = {
                'success': True,
                'text': '{"questions": [{"question": "Q2"}]}'
            }
            parsed = call_ai_json("Generate quiz")
            self.assertIsNotNone(parsed)

        # Case 3: Malformed text returns None without crashing
        with patch('routes.ai_helper.call_ai') as mock_call:
            mock_call.return_value = {
                'success': True,
                'text': 'Not a valid json string at all'
            }
            parsed = call_ai_json("Generate quiz")
            self.assertIsNone(parsed)

    # -----------------------------------------------------------------------
    # 6. Safe Material Extraction Tests
    # -----------------------------------------------------------------------
    def test_extract_material_text_blocks_path_traversal(self):
        traversal_attempts = [
            '../../etc/passwd',
            '..\\..\\windows\\system32\\cmd.exe',
            '/etc/shadow',
            'C:\\Windows\\System32\\cmd.exe',
            'uploads/materials/../../../secret.txt'
        ]
        for path in traversal_attempts:
            result = extract_material_text(path)
            self.assertEqual(result, '', f"Path traversal attempt '{path}' must return empty string")


if __name__ == '__main__':
    unittest.main()
