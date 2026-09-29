from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, date
from database.connection import query
from routes.auth_routes import login_required, log_activity
import os
from werkzeug.utils import secure_filename
from config import Config

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
                                    dob, gender, address, parent_contact, admission_date, status, verification_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PendingLogin', 'Pending')""",
            (student_system_id, name, father_name, section_id, roll_number, dob, gender, address, parent_contact, admission_date)
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
    gr_id = gr_record['id'] if gr_record else None
    
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
            
            if file and file.filename:
                filename = secure_filename(f"{student['student_system_id']}_{doc_type}_{file.filename}")
                upload_path = os.path.join(Config.UPLOAD_FOLDER, 'documents', filename)
                os.makedirs(os.path.dirname(upload_path), exist_ok=True)
                file.save(upload_path)
                file_path = f'uploads/documents/{filename}'
                
                query(
                    """INSERT INTO document_verification (student_id, document_type, document_path, verification_status, verified_by_gr_id, verified_date, remarks)
                       VALUES (%s, %s, %s, 'Pending', %s, NOW(), %s)""",
                    (student_id, doc_type, file_path, gr_id, remarks)
                )
                flash('Document uploaded.', 'success')
                
        elif action == 'verify_doc':
            doc_id = request.form.get('doc_id', type=int)
            query(
                "UPDATE document_verification SET verification_status = 'Verified', verified_by_gr_id = %s, verified_date = NOW() WHERE id = %s",
                (gr_id, doc_id)
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
    
    doc_types = ['Birth Certificate', 'Previous School Record', 'ID Proof', 'Address Proof', 'Other']
    
    return render_template('gr_office/register.html', student=student, documents=documents, 
                         doc_types=doc_types, mode='verify')

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