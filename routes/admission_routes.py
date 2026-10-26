import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from database.connection import query, transaction, transaction_with_insert_id
from routes.auth_routes import login_required, log_activity
from security.file_uploads import UploadValidationError, save_validated_upload


admission_bp = Blueprint('admission', __name__)

DOCUMENT_CATEGORIES = (
    'Birth Certificate',
    'Previous School Record',
    'ID Proof',
    'Address Proof',
    'Transfer Certificate',
    'Report Card',
    'Picture / Photo',
    'Parent/Guardian CNIC',
    'Other',
)
REQUIRED_DOCUMENTS = {
    'Birth Certificate',
    'Report Card',
    'Parent/Guardian CNIC',
}
UPLOAD_FIELDS = {
    'Birth Certificate': 'document_birth_certificate',
    'Previous School Record': 'document_previous_school_record',
    'ID Proof': 'document_id_proof',
    'Address Proof': 'document_address_proof',
    'Transfer Certificate': 'document_transfer_certificate',
    'Report Card': 'document_report_card',
    'Picture / Photo': 'document_photo',
    'Parent/Guardian CNIC': 'document_parent_cnic',
    'Other': 'document_other',
}
TOKEN_LIFETIME = timedelta(days=30)
STATUS_LOOKUP_LIMIT = 10
STATUS_LOOKUP_WINDOW_SECONDS = 15 * 60
_lookup_failures = {}
_lookup_failures_lock = threading.Lock()
_DUMMY_TOKEN_HASH = hashlib.sha256(b'invalid admission access token').hexdigest()


def _record_lookup_failure(address, now=None):
    now = time.monotonic() if now is None else now
    cutoff = now - STATUS_LOOKUP_WINDOW_SECONDS
    with _lookup_failures_lock:
        attempts = _lookup_failures.setdefault(address, deque())
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        attempts.append(now)


def _lookup_is_limited(address, now=None):
    now = time.monotonic() if now is None else now
    cutoff = now - STATUS_LOOKUP_WINDOW_SECONDS
    with _lookup_failures_lock:
        attempts = _lookup_failures.get(address)
        if not attempts:
            return False
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            _lookup_failures.pop(address, None)
            return False
        return len(attempts) >= STATUS_LOOKUP_LIMIT


def _intake():
    return query(
        "SELECT id, is_open FROM admission_intake WHERE id = 1",
        fetch_one=True
    )


def _current_application():
    application_ref = session.get('admission_application_ref')
    if not application_ref:
        return None
    application = query(
        """SELECT id, application_ref, status, token_expires_at
           FROM admission_applications
           WHERE application_ref = %s AND access_token_hash IS NOT NULL""",
        (application_ref,),
        fetch_one=True
    )
    if not application or application['token_expires_at'] <= datetime.now():
        session.pop('admission_application_ref', None)
        return None
    return application


def _latest_documents(application_id):
    rows = query(
        """SELECT d.* FROM admission_documents d
           JOIN (
               SELECT category, MAX(id) AS latest_id
               FROM admission_documents
               WHERE application_id = %s
               GROUP BY category
           ) latest ON latest.latest_id = d.id
           WHERE d.application_id = %s
           ORDER BY d.category""",
        (application_id, application_id),
        fetch=True
    ) or []
    return {row['category']: row for row in rows}


def _application_status_for_documents(latest_documents):
    if any(
        document.get('status') in {'Rejected', 'Replacement Requested'}
        for document in latest_documents.values()
    ):
        return 'Corrections Requested'
    if not REQUIRED_DOCUMENTS.issubset(latest_documents):
        return 'Incomplete'
    return 'Pending Review'


def _admission_document_path(file_path):
    prefix = 'private/admissions/'
    if not file_path or not file_path.startswith(prefix):
        return None
    filename = file_path.removeprefix(prefix)
    if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
        return None
    root = Path(current_app.config.get(
        'PRIVATE_ADMISSIONS_FOLDER',
        os.path.join(current_app.instance_path, 'admissions')
    )).resolve()
    candidate = (root / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _audit_write(application_id, actor_user_id, event_type, event_detail=None):
    return (
        """INSERT INTO admission_audit_log
           (application_id, actor_user_id, event_type, event_detail)
           VALUES (%s, %s, %s, %s)""",
        (application_id, actor_user_id, event_type, event_detail)
    )


@admission_bp.route('/admission', methods=['GET', 'POST'])
def public_form():
    intake = _intake()
    if not intake:
        abort(503, description='Admission intake is temporarily unavailable.')

    if request.method == 'POST':
        if not intake['is_open']:
            flash('Admissions are currently closed. Your application was not submitted.', 'warning')
        else:
            return _submit_application()

    grades = query("SELECT id, name FROM grades ORDER BY name", fetch=True) or []
    return render_template(
        'admission/form.html',
        grades=grades,
        admissions_open=bool(intake['is_open']),
        categories=DOCUMENT_CATEGORIES,
        upload_fields=UPLOAD_FIELDS,
        required_documents=REQUIRED_DOCUMENTS,
        form_data=request.form if request.method == 'POST' else {}
    )


def _submit_application():
    data = {
        'applicant_name': request.form.get('applicant_name', '').strip(),
        'guardian_name': request.form.get('guardian_name', '').strip(),
        'guardian_phone': request.form.get('guardian_phone', '').strip(),
        'contact_phone': request.form.get('contact_phone', '').strip(),
        'email': request.form.get('email', '').strip() or None,
        'address': request.form.get('address', '').strip(),
        'previous_school': request.form.get('previous_school', '').strip(),
        'previous_grade': request.form.get('previous_grade', '').strip(),
        'applied_grade_id': request.form.get('applied_grade_id', type=int),
        'dob': request.form.get('dob', ''),
        'gender': request.form.get('gender', ''),
    }
    required_fields = (
        'applicant_name', 'guardian_name', 'guardian_phone', 'contact_phone',
        'address', 'previous_school', 'previous_grade', 'applied_grade_id', 'dob', 'gender'
    )
    if any(not data[field] for field in required_fields):
        flash('Complete all required applicant and guardian fields.', 'danger')
        return redirect(url_for('admission.public_form'))
    if (
        len(data['applicant_name']) > 100
        or len(data['guardian_name']) > 100
        or len(data['guardian_phone']) > 20
        or len(data['contact_phone']) > 20
        or len(data['previous_school']) > 150
        or len(data['previous_grade']) > 50
        or len(data['address']) > 5000
        or (data['email'] is not None and len(data['email']) > 100)
        or data['gender'] not in {'Male', 'Female', 'Other'}
    ):
        flash('Some submitted values are invalid or too long.', 'danger')
        return redirect(url_for('admission.public_form'))

    try:
        date_of_birth = date.fromisoformat(data['dob'])
    except ValueError:
        flash('Enter a valid date of birth.', 'danger')
        return redirect(url_for('admission.public_form'))
    if date_of_birth >= date.today():
        flash('Date of birth must be in the past.', 'danger')
        return redirect(url_for('admission.public_form'))

    grade = query("SELECT id FROM grades WHERE id = %s", (data['applied_grade_id'],), fetch_one=True)
    if not grade:
        flash('Select a valid grade or class.', 'danger')
        return redirect(url_for('admission.public_form'))

    duplicate = query(
        """SELECT id FROM admission_applications
           WHERE applicant_name = %s AND dob = %s AND guardian_phone = %s
             AND status NOT IN ('Rejected', 'Enrolled')
           LIMIT 1""",
        (data['applicant_name'], date_of_birth, data['guardian_phone']),
        fetch_one=True
    )
    if duplicate:
        flash('A similar application is already under review. Contact the GR Office if you need help.', 'warning')
        return redirect(url_for('admission.public_form'))

    uploads = []
    private_folder = current_app.config.get(
        'PRIVATE_ADMISSIONS_FOLDER',
        os.path.join(current_app.instance_path, 'admissions')
    )
    for category, field_name in UPLOAD_FIELDS.items():
        upload = request.files.get(field_name)
        if not upload or not upload.filename:
            continue
        try:
            filename = save_validated_upload(
                upload,
                private_folder,
                {'pdf', 'docx', 'png', 'jpg', 'jpeg'},
                current_app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)
            )
        except UploadValidationError as error:
            flash(str(error), 'danger')
            return redirect(url_for('admission.public_form'))
        except OSError:
            current_app.logger.exception('Unable to store an admission document')
            abort(500)
        uploads.append((category, f'private/admissions/{filename}'))

    application_ref = secrets.token_urlsafe(15)
    access_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(access_token.encode('utf-8')).hexdigest()
    token_expires_at = datetime.now() + TOKEN_LIFETIME
    status = (
        'Pending Review'
        if REQUIRED_DOCUMENTS.issubset({category for category, _ in uploads})
        else 'Incomplete'
    )
    writes = [(
        """INSERT INTO admission_applications
           (application_ref, access_token_hash, token_expires_at, applicant_name,
            guardian_name, guardian_phone, contact_phone, email, address,
            previous_school, previous_grade, applied_grade_id, dob, gender, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            application_ref, token_hash, token_expires_at, data['applicant_name'],
            data['guardian_name'], data['guardian_phone'], data['contact_phone'],
            data['email'], data['address'], data['previous_school'], data['previous_grade'],
            data['applied_grade_id'], date_of_birth, data['gender'], status
        )
    )]
    writes.extend((
        """INSERT INTO admission_documents
           (application_id, category, file_path, status)
           VALUES (%s, %s, %s, 'Uploaded')""",
        lambda application_id, category=category, path=path: (application_id, category, path)
    ) for category, path in uploads)
    writes.append((
        """INSERT INTO admission_audit_log
           (application_id, actor_user_id, event_type, event_detail)
           VALUES (%s, NULL, 'APPLICATION_SUBMITTED', 'Public application submitted')""",
        lambda application_id: (application_id,)
    ))
    application_id = transaction_with_insert_id(writes, require_affected_rows=True)
    if not application_id:
        current_app.logger.error('Admission application transaction failed')
        flash('Your application could not be saved. Please try again later.', 'danger')
        return redirect(url_for('admission.public_form'))

    gr_users = query("SELECT user_id FROM gr_office", fetch=True) or []
    for gr_user in gr_users:
        query(
            """INSERT INTO notifications (user_id, message, type, link)
               VALUES (%s, %s, %s, %s)""",
            (
                gr_user['user_id'],
                'A new admission application is ready for review.',
                'info',
                url_for('admission.gr_admissions')
            )
        )

    response = current_app.make_response(render_template(
        'admission/confirmation.html',
        application_ref=application_ref,
        access_token=access_token,
        token_expires_at=token_expires_at
    ))
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'
    return response


@admission_bp.route('/admission/status', methods=['GET', 'POST'])
def status_lookup():
    if request.method == 'POST':
        session.pop('admission_application_ref', None)
        address = request.remote_addr or 'unknown'
        if _lookup_is_limited(address):
            flash('Too many unsuccessful attempts. Try again in 15 minutes.', 'danger')
            return render_template('admission/status_lookup.html'), 429

        application_ref = request.form.get('application_ref', '').strip()
        access_token = request.form.get('access_token', '').strip()
        application = query(
            """SELECT id, application_ref, access_token_hash, token_expires_at, status
               FROM admission_applications
               WHERE application_ref = %s""",
            (application_ref,),
            fetch_one=True
        )
        supplied_hash = hashlib.sha256(access_token.encode('utf-8')).hexdigest()
        expected_hash = application['access_token_hash'] if application and application['access_token_hash'] else _DUMMY_TOKEN_HASH
        valid = hmac.compare_digest(expected_hash, supplied_hash)
        if (
            not application
            or not valid
            or application['token_expires_at'] <= datetime.now()
            or application['status'] in {'Rejected', 'Enrolled'}
        ):
            _record_lookup_failure(address)
            flash('The application reference or access code is invalid or expired.', 'danger')
            return render_template('admission/status_lookup.html'), 400

        with _lookup_failures_lock:
            _lookup_failures.pop(address, None)
        session['admission_application_ref'] = application_ref
        return redirect(url_for('admission.status_view'))

    return render_template('admission/status_lookup.html')


@admission_bp.route('/admission/status/view')
def status_view():
    application = _current_application()
    if not application or application['status'] in {'Rejected', 'Enrolled'}:
        flash('Enter your application reference and access code to view status.', 'warning')
        return redirect(url_for('admission.status_lookup'))
    application = query(
        """SELECT a.application_ref, a.applicant_name, a.status, a.submitted_at,
                  a.token_expires_at, g.name AS applied_grade
           FROM admission_applications a
           JOIN grades g ON g.id = a.applied_grade_id
           WHERE a.id = %s""",
        (application['id'],),
        fetch_one=True
    )
    if not application:
        abort(404)
    documents = _latest_documents(_current_application()['id'])
    response = current_app.make_response(render_template(
        'admission/status.html',
        application=application,
        documents=documents,
        required_documents=REQUIRED_DOCUMENTS,
        upload_fields=UPLOAD_FIELDS,
        categories=DOCUMENT_CATEGORIES
    ))
    response.headers['Cache-Control'] = 'no-store, private'
    return response


@admission_bp.route('/admission/corrections', methods=['POST'])
def submit_corrections():
    application = _current_application()
    if not application or application['status'] not in {'Incomplete', 'Corrections Requested'}:
        abort(403)

    latest = _latest_documents(application['id'])
    uploads = []
    for category, field_name in UPLOAD_FIELDS.items():
        upload = request.files.get(field_name)
        if not upload or not upload.filename:
            continue
        existing = latest.get(category)
        may_replace = (
            category in REQUIRED_DOCUMENTS and not existing
        ) or (
            existing and existing['status'] in {'Rejected', 'Replacement Requested'}
        )
        if not may_replace:
            flash(f'{category} is not currently requested for replacement.', 'danger')
            return redirect(url_for('admission.status_view'))
        try:
            filename = save_validated_upload(
                upload,
                current_app.config.get(
                    'PRIVATE_ADMISSIONS_FOLDER',
                    os.path.join(current_app.instance_path, 'admissions')
                ),
                {'pdf', 'docx', 'png', 'jpg', 'jpeg'},
                current_app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)
            )
        except UploadValidationError as error:
            flash(str(error), 'danger')
            return redirect(url_for('admission.status_view'))
        except OSError:
            current_app.logger.exception('Unable to store an admission correction document')
            abort(500)
        uploads.append((category, f'private/admissions/{filename}'))

    if not uploads:
        flash('Choose a requested document to replace.', 'danger')
        return redirect(url_for('admission.status_view'))

    latest_categories = set(latest)
    latest_categories.update(category for category, _ in uploads)
    next_status = 'Pending Review' if REQUIRED_DOCUMENTS.issubset(latest_categories) else 'Incomplete'
    writes = []
    for category, path in uploads:
        writes.append((
            """INSERT INTO admission_documents
               (application_id, category, file_path, status)
               VALUES (%s, %s, %s, 'Uploaded')""",
            (application['id'], category, path)
        ))
    writes.append((
        """UPDATE admission_applications SET status = %s
           WHERE id = %s AND status IN ('Incomplete', 'Corrections Requested')""",
        (next_status, application['id'])
    ))
    writes.append(_audit_write(
        application['id'], None, 'DOCUMENTS_REPLACED', 'Applicant uploaded requested documents'
    ))
    if not transaction(writes):
        flash('Your replacement documents could not be recorded. Please try again.', 'danger')
        return redirect(url_for('admission.status_view'))

    flash('Your documents were submitted for review.', 'success')
    return redirect(url_for('admission.status_view'))


@admission_bp.route('/gr/admissions')
@login_required(['GR_Office'])
def gr_admissions():
    if not query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True):
        abort(403)
    query_text = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    filters = []
    params = []
    if query_text:
        filters.append('(a.application_ref LIKE %s OR a.applicant_name LIKE %s)')
        params.extend([f'%{query_text}%'] * 2)
    valid_statuses = {
        'Incomplete', 'Pending Review', 'Corrections Requested',
        'Approved', 'Rejected', 'Enrolled'
    }
    if status in valid_statuses:
        filters.append('a.status = %s')
        params.append(status)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ''
    applications = query(
        f"""SELECT a.id, a.application_ref, a.applicant_name, a.status, a.submitted_at,
                   g.name AS applied_grade,
                   (SELECT COUNT(*) FROM admission_documents d WHERE d.application_id = a.id) AS document_count,
                   (SELECT COUNT(*) FROM admission_documents d
                    WHERE d.application_id = a.id AND d.status = 'Approved'
                      AND d.id = (SELECT MAX(latest.id) FROM admission_documents latest
                                  WHERE latest.application_id = d.application_id AND latest.category = d.category)
                   ) AS approved_documents
            FROM admission_applications a
            JOIN grades g ON g.id = a.applied_grade_id
            {where_clause}
            ORDER BY a.submitted_at DESC LIMIT 200""",
        tuple(params),
        fetch=True
    ) or []
    counts = {}
    for item in ('Incomplete', 'Pending Review', 'Corrections Requested', 'Approved', 'Enrolled'):
        result = query(
            "SELECT COUNT(*) AS count FROM admission_applications WHERE status = %s",
            (item,),
            fetch_one=True
        )
        counts[item] = result['count'] if result else 0
    total_result = query("SELECT COUNT(*) AS count FROM admission_applications", fetch_one=True)
    intake = _intake()
    return render_template(
        'gr_office/admissions.html',
        applications=applications,
        counts=counts,
        total=total_result['count'] if total_result else 0,
        intake_open=bool(intake and intake['is_open']),
        public_url=url_for('admission.public_form', _external=True),
        query_text=query_text,
        selected_status=status
    )


@admission_bp.route('/gr/admissions/intake', methods=['POST'])
@login_required(['GR_Office'])
def toggle_intake():
    if not query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True):
        abort(403)
    action = request.form.get('action')
    if action not in {'open', 'close'}:
        abort(400)
    is_open = action == 'open'
    if not transaction([(
        """UPDATE admission_intake SET is_open = %s, updated_by = %s
           WHERE id = 1""",
        (is_open, session['user_id'])
    )]):
        flash('Admission intake setting could not be updated. Check the application log for a database error.', 'danger')
    else:
        log_activity(
            session['user_id'],
            'ADMISSION_INTAKE_OPENED' if is_open else 'ADMISSION_INTAKE_CLOSED',
            'Admission intake status changed'
        )
        flash('Admission intake opened.' if is_open else 'Admission intake closed.', 'success')
    return redirect(url_for('admission.gr_admissions'))


@admission_bp.route('/gr/admissions/<int:application_id>')
@login_required(['GR_Office'])
def application_detail(application_id):
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not gr_record:
        abort(403)
    application = query(
        """SELECT a.*, g.name AS applied_grade
           FROM admission_applications a
           JOIN grades g ON g.id = a.applied_grade_id
           WHERE a.id = %s""",
        (application_id,),
        fetch_one=True
    )
    if not application:
        abort(404)
    documents = query(
        """SELECT * FROM admission_documents
           WHERE application_id = %s ORDER BY category, id DESC""",
        (application_id,),
        fetch=True
    ) or []
    for document in documents:
        document['file_available'] = bool(_admission_document_path(document['file_path']))
    latest = _latest_documents(application_id)
    required_approved = all(
        category in latest and latest[category]['status'] == 'Approved'
        for category in REQUIRED_DOCUMENTS
    )
    admin_notification = query(
        """SELECT id FROM admission_audit_log
           WHERE application_id = %s AND event_type = 'APPLICATION_SENT_TO_ADMIN'
           LIMIT 1""",
        (application_id,),
        fetch_one=True
    )
    return render_template(
        'gr_office/admission_detail.html',
        application=application,
        documents=documents,
        required_documents=REQUIRED_DOCUMENTS,
        required_approved=required_approved,
        admin_notified=bool(admin_notification)
    )


@admission_bp.route('/gr/admissions/document/<int:document_id>')
@login_required(['GR_Office'])
def admission_document(document_id):
    if not query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True):
        abort(403)
    document = query(
        """SELECT d.file_path, d.category, a.id AS application_id
           FROM admission_documents d
           JOIN admission_applications a ON a.id = d.application_id
           WHERE d.id = %s""",
        (document_id,),
        fetch_one=True
    )
    file_path = _admission_document_path(document['file_path']) if document else None
    if not file_path:
        abort(404, description='This admission document is no longer available.')
    return send_file(
        file_path,
        as_attachment=request.args.get('download') == '1',
        download_name=f"application-{document['application_id']}-{secrets.token_hex(3)}{file_path.suffix}"
    )


@admission_bp.route('/gr/admissions/<int:application_id>/document/<int:document_id>/review', methods=['POST'])
@login_required(['GR_Office'])
def review_admission_document(application_id, document_id):
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not gr_record:
        abort(403)
    decision = request.form.get('decision')
    remarks = request.form.get('remarks', '').strip()
    decisions = {
        'approve': 'Approved',
        'reject': 'Rejected',
        'replace': 'Replacement Requested',
    }
    if decision not in decisions:
        abort(400)
    if decision in {'reject', 'replace'} and not remarks:
        flash('Provide a reason when rejecting a document or requesting a replacement.', 'danger')
        return redirect(url_for('admission.application_detail', application_id=application_id))
    document = query(
        """SELECT id, category FROM admission_documents
           WHERE id = %s AND application_id = %s""",
        (document_id, application_id),
        fetch_one=True
    )
    if not document:
        abort(404)
    if not query(
        """SELECT id FROM admission_applications
           WHERE id = %s AND status NOT IN ('Rejected', 'Enrolled')""",
        (application_id,),
        fetch_one=True
    ):
        abort(409)
    next_status = decisions[decision]
    latest = _latest_documents(application_id)
    latest[document['category']] = {'status': next_status}
    application_status = _application_status_for_documents(latest)
    if not transaction([
        (
            """UPDATE admission_documents
               SET status = %s, remarks = %s, reviewed_by_gr_id = %s, reviewed_at = NOW()
               WHERE id = %s AND application_id = %s""",
            (next_status, remarks or None, gr_record['id'], document_id, application_id)
        ),
        (
            """UPDATE admission_applications
               SET status = %s, reviewed_by_gr_id = %s, reviewed_at = NOW()
               WHERE id = %s AND status NOT IN ('Rejected', 'Enrolled')""",
            (application_status, gr_record['id'], application_id)
        ),
        _audit_write(application_id, session['user_id'], 'DOCUMENT_REVIEWED', document['category']),
    ]):
        flash('Document review could not be saved.', 'danger')
    else:
        log_activity(session['user_id'], 'ADMISSION_DOCUMENT_REVIEWED', f'Reviewed document {document_id}')
        flash('Document review saved.', 'success')
    return redirect(url_for('admission.application_detail', application_id=application_id))


@admission_bp.route('/gr/admissions/<int:application_id>/review', methods=['POST'])
@login_required(['GR_Office'])
def review_application(application_id):
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not gr_record:
        abort(403)
    action = request.form.get('action')
    note = request.form.get('note', '').strip()
    if action not in {'request_corrections', 'send_to_admin', 'reject'}:
        abort(400)
    if action in {'request_corrections', 'reject'} and not note:
        flash('Provide a reason for this decision.', 'danger')
        return redirect(url_for('admission.application_detail', application_id=application_id))
    application = query(
        """SELECT id, status FROM admission_applications
           WHERE id = %s AND status NOT IN ('Rejected', 'Enrolled')""",
        (application_id,),
        fetch_one=True
    )
    if not application:
        abort(404)
    latest = _latest_documents(application_id)
    admin_users = []
    if action == 'send_to_admin':
        if not all(
            category in latest and latest[category]['status'] == 'Approved'
            for category in REQUIRED_DOCUMENTS
        ):
            flash('The three required documents must all be approved before application approval.', 'danger')
            return redirect(url_for('admission.application_detail', application_id=application_id))
        if query(
            """SELECT id FROM admission_audit_log
               WHERE application_id = %s AND event_type = 'APPLICATION_SENT_TO_ADMIN'
               LIMIT 1""",
            (application_id,),
            fetch_one=True
        ):
            flash('This approved application has already been sent to IT Admin.', 'info')
            return redirect(url_for('admission.application_detail', application_id=application_id))
        admin_users = query(
            "SELECT id FROM users WHERE user_type = 'IT_Admin' AND is_active = 1",
            fetch=True
        ) or []
        if not admin_users:
            flash('No active IT Admin account is available to receive this application.', 'danger')
            return redirect(url_for('admission.application_detail', application_id=application_id))
        status = 'Approved'
        event = 'APPLICATION_SENT_TO_ADMIN'
    elif action == 'reject':
        status = 'Rejected'
        event = 'APPLICATION_REJECTED'
    else:
        if not any(
            document.get('status') in {'Rejected', 'Replacement Requested'}
            for document in latest.values()
        ):
            flash('Mark a document as needing replacement before requesting corrections.', 'warning')
            return redirect(url_for('admission.application_detail', application_id=application_id))
        status = _application_status_for_documents(latest)
        status = 'Corrections Requested'
        event = 'CORRECTIONS_REQUESTED'
    writes = [
        (
            """UPDATE admission_applications
               SET status = %s, internal_note = %s, reviewed_by_gr_id = %s, reviewed_at = NOW(),
                   access_token_hash = CASE WHEN %s = 'Rejected' THEN NULL ELSE access_token_hash END
               WHERE id = %s AND status NOT IN ('Rejected', 'Enrolled')
                 AND (%s <> 'APPLICATION_SENT_TO_ADMIN' OR NOT EXISTS (
                     SELECT 1 FROM admission_audit_log
                     WHERE application_id = %s AND event_type = 'APPLICATION_SENT_TO_ADMIN'
                 ))""",
            (status, note or None, gr_record['id'], status, application_id, event, application_id)
        ),
        _audit_write(application_id, session['user_id'], event, None),
    ]
    if action == 'send_to_admin':
        application_ref = query(
            "SELECT application_ref FROM admission_applications WHERE id = %s",
            (application_id,),
            fetch_one=True
        )
        if not application_ref:
            abort(404)
        for admin in admin_users:
            writes.append((
                """INSERT INTO notifications (user_id, message, type, link)
                   VALUES (%s, %s, %s, %s)""",
                (
                    admin['id'],
                    f"Approved admission {application_ref['application_ref']} is ready for Student account creation.",
                    'info',
                    url_for('admin.users')
                )
            ))
    if not transaction(writes, require_affected_rows=True):
        flash('The application review could not be saved.', 'danger')
    else:
        log_activity(session['user_id'], event, f'Reviewed admission application {application_id}')
        if status in {'Rejected', 'Corrections Requested', 'Incomplete'}:
            application_row = query(
                "SELECT applicant_name FROM admission_applications WHERE id = %s",
                (application_id,),
                fetch_one=True
            )
            if application_row:
                # Applicants receive correction access through their private access code.
                current_app.logger.info('Admission application %s requires applicant action', application_id)
        if action == 'send_to_admin':
            flash('Application approved and sent to IT Admin for Student account creation.', 'success')
        else:
            flash('Application review saved.', 'success')
    return redirect(url_for('admission.application_detail', application_id=application_id))
