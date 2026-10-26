from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort, send_file
from datetime import datetime, date
from database.connection import query
from routes.auth_routes import login_required, log_activity
import os
from pathlib import Path
from config import Config
from security.file_uploads import UploadValidationError, save_validated_upload

gr_bp = Blueprint('gr', __name__, url_prefix='/gr')

@gr_bp.route('/dashboard')
@login_required(['GR_Office'])
def dashboard():
    students = query(
        """SELECT s.*, sec.name as section_name, g.name as grade_name,
              (SELECT COUNT(*) FROM document_verification dv WHERE dv.student_id = s.id) as doc_count,
              (SELECT COUNT(*) FROM document_verification dv WHERE dv.student_id = s.id AND dv.verification_status = 'Verified') as verified_count
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           ORDER BY g.name, sec.name, s.roll_number""",
        fetch=True
    )
    
    return render_template('gr_office/dashboard.html', students=students)

@gr_bp.route('/register', methods=['GET', 'POST'])
@login_required(['GR_Office'])
def register():
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    gr_id = gr_record['id'] if gr_record else None
    
    sections = query(
        """SELECT s.*, g.name as grade_name 
           FROM sections s 
           JOIN grades g ON s.grade_id = g.id 
           ORDER BY g.name, s.name""",
        fetch=True
    )
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        father_name = request.form.get('father_name', '').strip()
        section_id = request.form.get('section_id')
        roll_number = request.form.get('roll_number', '').strip()
        dob = request.form.get('dob')
        gender = request.form.get('gender')
        address = request.form.get('address', '').strip()
        parent_contact = request.form.get('parent_contact', '').strip()
        admission_date = request.form.get('admission_date') or date.today().isoformat()
        
        blood_group = request.form.get('blood_group', '').strip() or None
        emergency_contact_name = request.form.get('emergency_contact_name', '').strip() or None
        emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip() or None
        emergency_relation = request.form.get('emergency_relation', '').strip() or None
        medical_notes = request.form.get('medical_notes', '').strip() or None
        
        if not all([name, father_name, section_id, roll_number, dob, gender]):
            flash('All required fields must be filled.', 'danger')
            return redirect(url_for('gr.register'))
        
        # Check roll number unique in section
        if query("SELECT id FROM students WHERE section_id = %s AND roll_number = %s", (section_id, roll_number), fetch_one=True):
            flash('Roll number already exists in this section.', 'danger')
            return redirect(url_for('gr.register'))
        
        # Auto-generate student_system_id
        year = datetime.now().year
        last_student = query("SELECT id FROM students ORDER BY id DESC LIMIT 1", fetch_one=True)
        next_id = (last_student['id'] + 1) if last_student else 1
        student_system_id = f"SS-{year}-{next_id:04d}"
        
        student_id = query(
            """INSERT INTO students (student_system_id, name, father_name, section_id, roll_number, 
                                    dob, gender, blood_group, address, parent_contact, 
                                    emergency_contact_name, emergency_contact_phone, emergency_relation, medical_notes,
                                    admission_date, status, verification_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PendingLogin', 'Pending')""",
            (student_system_id, name, father_name, section_id, roll_number, 
             dob, gender, blood_group, address, parent_contact,
             emergency_contact_name, emergency_contact_phone, emergency_relation, medical_notes, admission_date)
        )
        
        if student_id:
            # Notify IT Admin
            admin_users = query("SELECT user_id FROM users WHERE user_type = 'IT_Admin'", fetch=True)
            for admin in admin_users:
                query(
                    "INSERT INTO notifications (user_id, message, type, link) VALUES (%s, %s, %s, %s)",
                    (admin['user_id'], f'New student enrolled: {name} ({student_system_id}). Create login account.', 'info', url_for('admin.users'))
                )
            
            flash(f'Student registered successfully. System ID: {student_system_id}', 'success')
            log_activity(session['user_id'], 'REGISTER_STUDENT', f'Registered student {name} with ID {student_system_id}')
        else:
            flash('Failed to register student.', 'danger')
        
        return redirect(url_for('gr.dashboard'))
    
    return render_template('gr_office/register.html', sections=sections, mode='register')

@gr_bp.route('/verify/<int:student_id>', methods=['GET', 'POST'])
@login_required(['GR_Office'])
def verify(student_id):
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not gr_record:
        abort(403)
    gr_id = gr_record['id']
    
    student = query(
        """SELECT s.*, sec.name as section_name, g.name as grade_name
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE s.id = %s""",
        (student_id,),
        fetch_one=True
    )
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('gr.dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload_doc':
            doc_type = request.form.get('document_type')
            file = request.files.get('document')
            remarks = request.form.get('remarks', '')
            allowed_doc_types = {'Birth Certificate', 'Previous School Record', 'ID Proof', 'Address Proof', 'Other'}
            if doc_type not in allowed_doc_types:
                flash('Choose a valid document type.', 'danger')
                return redirect(url_for('gr.verify', student_id=student_id))
            if not file or not file.filename:
                flash('Choose a document file to upload.', 'danger')
                return redirect(url_for('gr.verify', student_id=student_id))

            private_folder = current_app.config.get(
                'PRIVATE_DOCUMENTS_FOLDER',
                os.path.join(current_app.instance_path, 'student_documents')
            )
            try:
                filename = save_validated_upload(
                    file,
                    private_folder,
                    {'pdf', 'docx', 'png', 'jpg', 'jpeg'},
                    Config.MAX_CONTENT_LENGTH
                )
            except UploadValidationError as error:
                flash(str(error), 'danger')
                return redirect(url_for('gr.verify', student_id=student_id))
            except OSError:
                current_app.logger.exception('Unable to store student document for student %s', student_id)
                abort(500)

            file_path = f'private/student_documents/{filename}'
            document_id = query(
                """INSERT INTO document_verification (student_id, document_type, document_path, verification_status, verified_by_gr_id, verified_date, remarks)
                   VALUES (%s, %s, %s, 'Pending', %s, NOW(), %s)""",
                (student_id, doc_type, file_path, gr_id, remarks)
            )
            if document_id:
                flash('Document uploaded.', 'success')
            else:
                current_app.logger.error(
                    'Document metadata insert failed for student %s; retained uploaded file %s',
                    student_id,
                    filename
                )
                flash('Document metadata could not be saved. The file was retained for safety.', 'danger')
                
        elif action == 'verify_doc':
            doc_id = request.form.get('doc_id', type=int)
            if not doc_id:
                flash('Document not found.', 'danger')
                return redirect(url_for('gr.verify', student_id=student_id))
            query(
                """UPDATE document_verification
                   SET verification_status = 'Verified', verified_by_gr_id = %s, verified_date = NOW()
                   WHERE id = %s AND student_id = %s""",
                (gr_id, doc_id, student_id)
            )
            flash('Document verified.', 'success')
            
        elif action == 'verify_student':
            # Check all docs verified
            pending_docs = query(
                "SELECT COUNT(*) as count FROM document_verification WHERE student_id = %s AND verification_status != 'Verified'",
                (student_id,),
                fetch_one=True
            )
            if pending_docs['count'] == 0:
                query(
                    "UPDATE students SET verification_status = 'Verified' WHERE id = %s",
                    (student_id,)
                )
                flash('Student fully verified.', 'success')
            else:
                flash('Not all documents are verified yet.', 'warning')
        
        return redirect(url_for('gr.verify', student_id=student_id))
    
    documents = query(
        "SELECT * FROM document_verification WHERE student_id = %s ORDER BY created_at DESC",
        (student_id,),
        fetch=True
    )
    for document in documents or []:
        document['file_available'] = bool(_document_upload_path(document.get('document_path')))
    
    doc_types = ['Birth Certificate', 'Previous School Record', 'ID Proof', 'Address Proof', 'Other']
    
    return render_template('gr_office/register.html', student=student, documents=documents, 
                         doc_types=doc_types, mode='verify')


def _document_upload_path(file_path):
    if not file_path:
        return None

    if file_path.startswith('private/student_documents/'):
        filename = file_path.removeprefix('private/student_documents/')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            return None
        root = Path(current_app.config.get(
            'PRIVATE_DOCUMENTS_FOLDER',
            os.path.join(current_app.instance_path, 'student_documents')
        )).resolve()
        candidate = (root / filename).resolve()
    elif file_path.startswith('uploads/documents/'):
        relative_name = file_path.removeprefix('uploads/documents/')
        if not relative_name or Path(relative_name).name != relative_name or '/' in relative_name or '\\' in relative_name:
            return None
        root = (Path(current_app.static_folder) / 'uploads' / 'documents').resolve()
        candidate = (root / relative_name).resolve()
    else:
        return None

    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@gr_bp.route('/document/<int:doc_id>')
@login_required(['GR_Office'])
def document_file(doc_id):
    gr_record = query("SELECT id FROM gr_office WHERE user_id = %s", (session['user_id'],), fetch_one=True)
    if not gr_record:
        abort(403)

    document = query(
        """SELECT dv.document_path, dv.document_type, s.id AS student_id
           FROM document_verification dv
           JOIN students s ON s.id = dv.student_id
           WHERE dv.id = %s""",
        (doc_id,),
        fetch_one=True
    )
    file_path = _document_upload_path(document['document_path']) if document else None
    if not file_path:
        abort(404, description='This document file is no longer available. Upload a replacement document.')

    return send_file(
        file_path,
        as_attachment=request.args.get('download') == '1',
        download_name=f"student-{document['student_id']}-{document['document_type']}{file_path.suffix}"
    )


@gr_bp.route('/upload-docs')
@login_required(['GR_Office'])
def upload_docs():
    students = query(
        """SELECT s.id, s.name, s.student_system_id, s.verification_status,
                  sec.name as section_name, g.name as grade_name
           FROM students s
           LEFT JOIN sections sec ON s.section_id = sec.id
           LEFT JOIN grades g ON sec.grade_id = g.id
           WHERE s.status IN ('Active', 'PendingLogin')
           ORDER BY g.name, sec.name, s.roll_number""",
        fetch=True
    )
    return render_template('gr_office/upload_docs.html', students=students)