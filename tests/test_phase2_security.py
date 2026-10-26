import os
import tempfile
import unittest
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

with patch.dict(os.environ, {'DEBUG': 'true', 'SECRET_KEY': 'test-secret-key-for-phase-two'}):
    with patch('database.connection.query'):
        import app as schoolsync_app

import routes.gr_routes as gr_routes
import routes.student_routes as student_routes
import routes.teacher_routes as teacher_routes
from routes.ai_helper import extract_material_text
from security.file_uploads import UploadValidationError, save_validated_upload


class UploadValidationTests(unittest.TestCase):
    def test_valid_pdf_uploads_get_unique_names(self):
        with tempfile.TemporaryDirectory() as directory:
            first = save_validated_upload(
                FileStorage(BytesIO(b'%PDF-1.7 synthetic'), filename='record.pdf'),
                directory,
                {'pdf'},
                1024
            )
            second = save_validated_upload(
                FileStorage(BytesIO(b'%PDF-1.7 synthetic'), filename='record.pdf'),
                directory,
                {'pdf'},
                1024
            )

            self.assertNotEqual(first, second)
            self.assertTrue(os.path.isfile(os.path.join(directory, first)))
            self.assertTrue(os.path.isfile(os.path.join(directory, second)))

    def test_rejects_traversal_unsupported_type_mismatched_content_and_oversize(self):
        cases = [
            (FileStorage(BytesIO(b'%PDF-1.7'), filename='../record.pdf'), {'pdf'}, 1024),
            (FileStorage(BytesIO(b'%PDF-1.7'), filename='record.exe'), {'pdf'}, 1024),
            (FileStorage(BytesIO(b'not a pdf'), filename='record.pdf'), {'pdf'}, 1024),
            (FileStorage(BytesIO(b'%PDF-1.7'), filename='record.pdf'), {'pdf'}, 4),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for upload, extensions, max_bytes in cases:
                with self.subTest(filename=upload.filename):
                    with self.assertRaises(UploadValidationError):
                        save_validated_upload(upload, directory, extensions, max_bytes)
            self.assertEqual(os.listdir(directory), [])


class Phase2RouteTests(unittest.TestCase):
    def setUp(self):
        schoolsync_app.app.config['TESTING'] = True
        self.client = schoolsync_app.app.test_client()

    def set_identity(self, user_id, user_type):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id
            session['user_type'] = user_type
            session['_csrf_token'] = 'phase-three-test-token'

    def post_with_csrf(self, *args, **kwargs):
        with self.client.session_transaction() as session:
            token = session.get('_csrf_token')
        if token:
            data = kwargs.setdefault('data', {})
            if isinstance(data, dict):
                data.setdefault('csrf_token', token)
            else:
                kwargs.setdefault('headers', {})['X-CSRFToken'] = token
        return self.client.post(*args, **kwargs)

    def test_gr_upload_stores_private_document_and_rejects_invalid_content(self):
        self.set_identity(12, 'GR_Office')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_DOCUMENTS_FOLDER'] = private_dir
            with patch.object(gr_routes, 'query', side_effect=[
                {'id': 4},
                {'id': 30, 'student_system_id': 'SS-2026-0030'},
                77,
            ]) as query_mock:
                response = self.post_with_csrf(
                    '/gr/verify/30',
                    data={
                        'action': 'upload_doc',
                        'document_type': 'Birth Certificate',
                        'document': (BytesIO(b'%PDF-1.7 synthetic'), 'birth.pdf'),
                    },
                    content_type='multipart/form-data'
                )

            self.assertEqual(response.status_code, 302)
            insert_params = query_mock.call_args_list[-1].args[1]
            self.assertTrue(insert_params[2].startswith('private/student_documents/'))
            self.assertTrue(os.path.isfile(os.path.join(private_dir, insert_params[2].rsplit('/', 1)[1])))

            with patch.object(gr_routes, 'query', side_effect=[
                {'id': 4},
                {'id': 30, 'student_system_id': 'SS-2026-0030'},
            ]) as invalid_query:
                invalid_response = self.post_with_csrf(
                    '/gr/verify/30',
                    data={
                        'action': 'upload_doc',
                        'document_type': 'Birth Certificate',
                        'document': (BytesIO(b'not a PDF'), 'birth.pdf'),
                    },
                    content_type='multipart/form-data'
                )

            self.assertEqual(invalid_response.status_code, 302)
            self.assertEqual(invalid_query.call_count, 2)

    def test_gr_document_download_requires_gr_role_and_document_record(self):
        self.set_identity(12, 'GR_Office')
        with tempfile.TemporaryDirectory() as directory:
            file_path = os.path.join(directory, 'doc.pdf')
            with open(file_path, 'wb') as document_file:
                document_file.write(b'%PDF-1.7 synthetic')

            with patch.object(gr_routes, 'query', side_effect=[
                {'id': 4},
                {'document_path': 'private/student_documents/doc.pdf',
                 'document_type': 'ID Proof', 'student_id': 30},
            ]), patch.object(gr_routes, '_document_upload_path', return_value=Path(file_path)):
                response = self.client.get('/gr/document/19')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'%PDF-1.7', response.data)
            response.close()

            self.set_identity(50, 'Student')
            with patch.object(gr_routes, 'query') as unauthorized_query:
                denied = self.client.get('/gr/document/19')
            self.assertEqual(denied.status_code, 302)
            unauthorized_query.assert_not_called()

    def test_missing_gr_document_has_safe_replacement_message(self):
        self.set_identity(12, 'GR_Office')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_DOCUMENTS_FOLDER'] = private_dir
            with patch.object(gr_routes, 'query', side_effect=[
                {'id': 4},
                {
                    'document_path': 'private/student_documents/missing.pdf',
                    'document_type': 'ID Proof',
                    'student_id': 30,
                },
            ]):
                response = self.client.get('/gr/document/19')

        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Upload a replacement document', response.data)
        self.assertNotIn(private_dir.encode(), response.data)

    def test_legacy_document_static_url_is_not_public(self):
        self.assert_protected_upload_not_public('documents')

    def test_assignment_static_url_is_not_public(self):
        self.assert_protected_upload_not_public('assignments')

    def assert_protected_upload_not_public(self, upload_type):
        original_static_folder = schoolsync_app.app.static_folder
        with tempfile.TemporaryDirectory() as static_folder:
            protected_directory = os.path.join(static_folder, 'uploads', upload_type)
            os.makedirs(protected_directory)
            with open(os.path.join(protected_directory, 'legacy.pdf'), 'wb') as protected_file:
                protected_file.write(b'%PDF-1.7 synthetic')

            schoolsync_app.app.static_folder = static_folder
            try:
                response = self.client.get(f'/static/uploads/{upload_type}/legacy.pdf')
                self.assertEqual(response.status_code, 404)
            finally:
                schoolsync_app.app.static_folder = original_static_folder

    def test_gr_document_verification_is_scoped_to_route_student(self):
        self.set_identity(12, 'GR_Office')
        with patch.object(gr_routes, 'query', side_effect=[
            {'id': 4},
            {'id': 30},
            0,
        ]) as query_mock:
            response = self.post_with_csrf(
                '/gr/verify/30',
                data={'action': 'verify_doc', 'doc_id': '81'}
            )

        self.assertEqual(response.status_code, 302)
        update_sql, update_params = query_mock.call_args_list[2].args
        self.assertIn('AND student_id = %s', update_sql)
        self.assertEqual(update_params, (4, 81, 30))

    def test_teacher_attendance_rejects_forged_student_ids(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            {'id': 15},
            [{'id': 40}],
        ]) as query_mock:
            response = self.post_with_csrf(
                '/teacher/course/9/3/save-attendance',
                data={
                    'date': date.today().isoformat(),
                    'student_ids': ['40', '999'],
                    'status_40': 'Present',
                    'status_999': 'Absent',
                }
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(query_mock.call_count, 3)

    def test_teacher_can_mark_attendance_for_assigned_students(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            {'id': 15},
            [{'id': 40}],
            0,
        ]) as query_mock, patch.object(teacher_routes, 'log_activity'):
            response = self.post_with_csrf(
                '/teacher/course/9/3/save-attendance',
                data={
                    'date': date.today().isoformat(),
                    'student_ids': ['40'],
                    'status_40': 'Present',
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_mock.call_count, 4)
        self.assertEqual(query_mock.call_args_list[3].args[1][0:4], (40, 3, 9, 6))

    def test_teacher_cannot_create_assignment_for_unassigned_section(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            {'id': 15},
            [{'section_id': 3}],
        ]) as query_mock:
            response = self.post_with_csrf(
                '/teacher/course/9/3/create-assignment',
                data={
                    'title': 'Synthetic assignment',
                    'due_date': '2026-10-30',
                    'section_ids': ['3', '99'],
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_mock.call_count, 3)

    def test_teacher_can_create_assignment_for_assigned_section(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            {'id': 15},
            [{'section_id': 3}],
            101,
            1,
            [],
        ]) as query_mock, patch.object(teacher_routes, 'log_activity'):
            response = self.post_with_csrf(
                '/teacher/course/9/3/create-assignment',
                data={
                    'title': 'Synthetic assignment',
                    'due_date': '2026-10-30',
                    'section_ids': ['3'],
                }
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_mock.call_args_list[3].args[1][2:4], (9, 6))
        self.assertEqual(query_mock.call_args_list[4].args[1], (101, 3))

    def test_teacher_material_upload_uses_validation_and_private_route_url(self):
        self.set_identity(22, 'Teacher')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_MATERIALS_FOLDER'] = private_dir
            with patch.object(teacher_routes, 'query', side_effect=[
                {'id': 6},
                {'id': 15},
                55,
                [],
            ]) as query_mock, patch.object(
                teacher_routes, 'save_validated_upload', return_value='safe-id.pdf'
            ) as save_mock, patch.object(teacher_routes, 'extract_material_text', return_value=''):
                response = self.post_with_csrf(
                    '/teacher/course/9/3/upload-material',
                    data={
                        'title': 'Synthetic material',
                        'material_type': 'PDF',
                        'file': (BytesIO(b'%PDF-1.7 synthetic'), 'lesson.pdf'),
                    },
                    content_type='multipart/form-data'
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['material']['url'], '/teacher/material-file/55')
        self.assertEqual(query_mock.call_count, 4)
        save_mock.assert_called_once()
        self.assertEqual(
            query_mock.call_args_list[2].args[1][6],
            'private/course_materials/safe-id.pdf'
        )

    def test_teacher_material_upload_rejects_bad_file_content(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            {'id': 15},
        ]):
            response = self.post_with_csrf(
                '/teacher/course/9/3/upload-material',
                data={
                    'title': 'Synthetic material',
                    'material_type': 'PDF',
                    'file': (BytesIO(b'not a PDF'), 'lesson.pdf'),
                },
                content_type='multipart/form-data'
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json['success'])

    def test_teacher_material_download_checks_course_ownership(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 8, 'teacher_id': 6, 'subject_id': 9, 'section_id': 3, 'file_path': 'uploads/materials/a.pdf'},
            {'id': 8},
        ]) as query_mock, patch.object(teacher_routes, '_material_upload_path', return_value='unused'):
            response = self.client.get('/teacher/material-file/14')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(query_mock.call_count, 2)

    def test_missing_material_has_safe_reupload_message(self):
        self.set_identity(50, 'Student')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_MATERIALS_FOLDER'] = private_dir
            with patch.object(teacher_routes, 'query', side_effect=[
                {
                    'id': 8,
                    'teacher_id': 6,
                    'subject_id': 9,
                    'section_id': 3,
                    'file_path': 'private/course_materials/missing.pdf',
                },
                {'id': 30},
            ]):
                response = self.client.get('/teacher/material-file/8')

        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Ask your teacher to upload it again', response.data)
        self.assertNotIn(private_dir.encode(), response.data)

    def test_student_course_marks_missing_material_and_submission_unavailable(self):
        self.set_identity(50, 'Student')
        material = {
            'id': 8,
            'file_path': 'private/course_materials/missing.pdf',
            'title': 'Synthetic lesson',
        }
        assignment = {
            'id': 9,
            'submission_id': 10,
            'submission_file': 'private/submissions/missing.pdf',
        }
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_MATERIALS_FOLDER'] = private_dir
            schoolsync_app.app.config['PRIVATE_SUBMISSIONS_FOLDER'] = private_dir
            with patch.object(student_routes, 'query', side_effect=[
                {'id': 30, 'status': 'Active', 'section_id': 3, 'grade_name': 'Grade 1'},
                [{
                    'subject_id': 9,
                    'subject_name': 'Mathematics',
                    'subject_type': 'Core',
                    'section_name': 'A',
                    'teacher_name': 'Teacher',
                }],
                [material],
                [assignment],
            ]), patch.object(student_routes, 'render_template', return_value='rendered') as render_mock:
                response = self.client.get('/student/course/9')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(render_mock.call_args.kwargs['materials'][0]['file_available'])
        self.assertFalse(render_mock.call_args.kwargs['assignments'][0]['submission_file_available'])

    def test_assigned_teacher_can_download_course_material(self):
        self.set_identity(22, 'Teacher')
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / 'course.pdf'
            file_path.write_bytes(b'%PDF-1.7 synthetic')
            with patch.object(teacher_routes, 'query', side_effect=[
                {'id': 8, 'teacher_id': 6, 'subject_id': 9, 'section_id': 3, 'file_path': 'uploads/materials/a.pdf'},
                {'id': 6},
                {'id': 7},
            ]), patch.object(teacher_routes, '_material_upload_path', return_value=file_path):
                response = self.client.get('/teacher/material-file/14')

                self.assertEqual(response.status_code, 200)
                self.assertIn(b'%PDF-1.7', response.data)
                response.close()

    def test_student_cannot_download_material_for_another_section(self):
        self.set_identity(50, 'Student')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 8, 'teacher_id': 6, 'subject_id': 9, 'section_id': 3, 'file_path': 'uploads/materials/a.pdf'},
            None,
        ]) as query_mock, patch.object(teacher_routes, '_material_upload_path', return_value='unused'):
            response = self.client.get('/teacher/material-file/14')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(query_mock.call_count, 2)

    def test_teacher_submission_download_requires_assignment_ownership(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            None,
        ]) as query_mock:
            denied = self.client.get('/teacher/submission-file/70')

        self.assertEqual(denied.status_code, 404)
        self.assertEqual(query_mock.call_count, 2)

        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / 'submission.pdf'
            file_path.write_bytes(b'%PDF-1.7 synthetic')
            with patch.object(teacher_routes, 'query', side_effect=[
                {'id': 6},
                {'file_path': 'uploads/submissions/submission.pdf'},
            ]), patch.object(teacher_routes, '_submission_upload_path', return_value=file_path):
                allowed = self.client.get('/teacher/submission-file/70')

            self.assertEqual(allowed.status_code, 200)
            self.assertIn(b'%PDF-1.7', allowed.data)
            allowed.close()

    def test_student_cannot_submit_homework_for_another_section(self):
        self.set_identity(50, 'Student')
        with patch.object(student_routes, 'query', side_effect=[
            {'id': 30, 'status': 'Active', 'section_id': 3},
            None,
        ]) as query_mock:
            response = self.post_with_csrf('/student/submit-homework/900', data={'text_response': 'forged'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_mock.call_count, 2)

    def test_student_assignment_upload_is_stored_outside_static(self):
        self.set_identity(50, 'Student')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_SUBMISSIONS_FOLDER'] = private_dir
            with patch.object(student_routes, 'query', side_effect=[
                {'id': 30, 'status': 'Active', 'section_id': 3},
                {'id': 700, 'subject_id': 9},
                1,
            ]) as query_mock, patch.object(student_routes, 'log_activity'):
                response = self.post_with_csrf(
                    '/student/submit/700',
                    data={
                        'text_response': 'synthetic response',
                        'file': (BytesIO(b'%PDF-1.7 synthetic'), 'answer.pdf'),
                    },
                    content_type='multipart/form-data'
                )

            self.assertEqual(response.status_code, 302)
            file_path = query_mock.call_args_list[2].args[1][2]
            self.assertTrue(file_path.startswith('private/submissions/'))
            self.assertTrue(os.path.isfile(os.path.join(private_dir, file_path.rsplit('/', 1)[1])))

    def test_student_replacement_upload_updates_submission_path_to_private_file(self):
        self.set_identity(50, 'Student')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_SUBMISSIONS_FOLDER'] = private_dir
            with patch.object(student_routes, 'query', side_effect=[
                {'id': 30, 'status': 'Active', 'section_id': 3},
                {'id': 700, 'subject_id': 9},
                1,
            ]) as query_mock, patch.object(student_routes, 'log_activity'):
                response = self.post_with_csrf(
                    '/student/submit/700',
                    data={
                        'text_response': 'replacement response',
                        'file': (BytesIO(b'%PDF-1.7 replacement'), 'replacement.pdf'),
                    },
                    content_type='multipart/form-data'
                )

            self.assertEqual(response.status_code, 302)
            insert_sql, params = query_mock.call_args_list[2].args
            self.assertIn('ON DUPLICATE KEY UPDATE file_path = %s', insert_sql)
            self.assertEqual(params[2], params[4])
            self.assertTrue(params[2].startswith('private/submissions/'))
            self.assertTrue(os.path.isfile(os.path.join(private_dir, params[2].rsplit('/', 1)[1])))

    def test_ai_material_extraction_handles_missing_legacy_file(self):
        with tempfile.TemporaryDirectory() as static_folder:
            original_static_folder = schoolsync_app.app.static_folder
            schoolsync_app.app.static_folder = static_folder
            try:
                with schoolsync_app.app.app_context():
                    extracted = extract_material_text('uploads/materials/missing.pdf')
            finally:
                schoolsync_app.app.static_folder = original_static_folder

        self.assertEqual(extracted, '')

    def test_student_submission_download_is_owner_only(self):
        self.set_identity(50, 'Student')
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / 'answer.pdf'
            file_path.write_bytes(b'%PDF-1.7 synthetic')
            schoolsync_app.app.config['PRIVATE_SUBMISSIONS_FOLDER'] = directory

            with patch.object(student_routes, 'query', side_effect=[
                {'id': 30},
                {'file_path': 'private/submissions/answer.pdf'},
            ]):
                allowed = self.client.get('/student/submission-file/20')
            self.assertEqual(allowed.status_code, 200)
            self.assertIn(b'%PDF-1.7', allowed.data)
            allowed.close()

            with patch.object(student_routes, 'query', side_effect=[
                {'id': 31},
                None,
            ]) as query_mock:
                denied = self.client.get('/student/submission-file/20')
            self.assertEqual(denied.status_code, 404)
            self.assertEqual(query_mock.call_count, 2)

    def test_missing_student_submission_has_safe_replacement_message(self):
        self.set_identity(50, 'Student')
        with tempfile.TemporaryDirectory() as private_dir:
            schoolsync_app.app.config['PRIVATE_SUBMISSIONS_FOLDER'] = private_dir
            with patch.object(student_routes, 'query', side_effect=[
                {'id': 30},
                {'file_path': 'private/submissions/missing.pdf'},
            ]):
                response = self.client.get('/student/submission-file/20')

        self.assertEqual(response.status_code, 404)
        self.assertIn(b'Upload a replacement file', response.data)
        self.assertNotIn(private_dir.encode(), response.data)

    def test_student_can_still_read_legacy_submission_without_moving_it(self):
        self.set_identity(50, 'Student')
        original_static_folder = schoolsync_app.app.static_folder
        with tempfile.TemporaryDirectory() as static_folder:
            legacy_directory = os.path.join(static_folder, 'uploads', 'submissions')
            os.makedirs(legacy_directory)
            with open(os.path.join(legacy_directory, 'legacy.pdf'), 'wb') as legacy_file:
                legacy_file.write(b'%PDF-1.7 legacy')

            schoolsync_app.app.static_folder = static_folder
            try:
                with patch.object(student_routes, 'query', side_effect=[
                    {'id': 30},
                    {'file_path': 'uploads/submissions/legacy.pdf'},
                ]):
                    response = self.client.get('/student/submission-file/20')
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'%PDF-1.7 legacy', response.data)
                response.close()
            finally:
                schoolsync_app.app.static_folder = original_static_folder

    def test_student_cannot_directly_fetch_another_students_submission(self):
        self.set_identity(50, 'Student')
        with patch.object(schoolsync_app, 'query', side_effect=[
            {'id': 30},
            None,
        ]) as query_mock:
            response = self.client.get('/static/uploads/submissions/other-student.pdf')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(query_mock.call_count, 2)

    def test_case_variant_submission_static_url_still_requires_ownership(self):
        self.set_identity(50, 'Student')
        original_static_folder = schoolsync_app.app.static_folder
        with tempfile.TemporaryDirectory() as static_folder:
            submission_folder = os.path.join(static_folder, 'uploads', 'submissions')
            os.makedirs(submission_folder)
            with open(os.path.join(submission_folder, 'other-student.pdf'), 'wb') as uploaded_file:
                uploaded_file.write(b'%PDF-1.7 synthetic')

            schoolsync_app.app.static_folder = static_folder
            try:
                with patch.object(schoolsync_app, 'query', side_effect=[
                    {'id': 30},
                    None,
                ]) as query_mock:
                    response = self.client.get('/static/UPLOADS/SUBMISSIONS/other-student.pdf')

                self.assertEqual(response.status_code, 403)
                self.assertEqual(query_mock.call_count, 2)
            finally:
                schoolsync_app.app.static_folder = original_static_folder

    def test_teacher_cannot_grade_another_teachers_submission(self):
        self.set_identity(22, 'Teacher')
        with patch.object(teacher_routes, 'query', side_effect=[
            {'id': 6},
            None,
        ]) as query_mock:
            response = self.post_with_csrf(
                '/teacher/grade-submission',
                data={'submission_id': '901', 'marks': '80'}
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(query_mock.call_count, 2)

    def test_direct_material_static_url_is_not_public(self):
        self.assert_protected_upload_not_public('materials')


if __name__ == '__main__':
    unittest.main()
