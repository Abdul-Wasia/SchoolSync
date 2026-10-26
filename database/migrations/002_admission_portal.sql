-- Phase 5 admission portal. Apply once to an existing SchoolSync database.
-- This migration is additive and does not modify existing student or document rows.

CREATE TABLE IF NOT EXISTS admission_intake (
    id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
    is_open TINYINT(1) NOT NULL DEFAULT 0,
    updated_by INT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_admission_intake_user
        FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

INSERT IGNORE INTO admission_intake (id, is_open)
VALUES (1, 0);

CREATE TABLE IF NOT EXISTS admission_applications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_ref VARCHAR(32) NOT NULL UNIQUE,
    access_token_hash CHAR(64) NULL,
    token_expires_at DATETIME NOT NULL,
    applicant_name VARCHAR(100) NOT NULL,
    guardian_name VARCHAR(100) NOT NULL,
    guardian_phone VARCHAR(20) NOT NULL,
    contact_phone VARCHAR(20) NOT NULL,
    email VARCHAR(100) NULL,
    address TEXT NOT NULL,
    previous_school VARCHAR(150) NOT NULL,
    previous_grade VARCHAR(50) NOT NULL,
    applied_grade_id INT NOT NULL,
    dob DATE NOT NULL,
    gender ENUM('Male','Female','Other') NOT NULL,
    status ENUM(
        'Incomplete',
        'Pending Review',
        'Corrections Requested',
        'Approved',
        'Rejected',
        'Enrolled'
    ) NOT NULL DEFAULT 'Incomplete',
    internal_note TEXT NULL,
    reviewed_by_gr_id INT NULL,
    reviewed_at TIMESTAMP NULL,
    student_id INT NULL UNIQUE,
    enrolled_by INT NULL,
    enrolled_at TIMESTAMP NULL,
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_admission_application_grade
        FOREIGN KEY (applied_grade_id) REFERENCES grades(id),
    CONSTRAINT fk_admission_application_reviewer
        FOREIGN KEY (reviewed_by_gr_id) REFERENCES gr_office(id) ON DELETE SET NULL,
    CONSTRAINT fk_admission_application_student
        FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL,
    CONSTRAINT fk_admission_application_enroller
        FOREIGN KEY (enrolled_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_admission_status_date (status, submitted_at),
    INDEX idx_admission_grade (applied_grade_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS admission_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id BIGINT UNSIGNED NOT NULL,
    category VARCHAR(60) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    status ENUM(
        'Uploaded',
        'Under Review',
        'Approved',
        'Rejected',
        'Replacement Requested'
    ) NOT NULL DEFAULT 'Uploaded',
    remarks TEXT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_by_gr_id INT NULL,
    reviewed_at TIMESTAMP NULL,
    CONSTRAINT fk_admission_document_application
        FOREIGN KEY (application_id) REFERENCES admission_applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_admission_document_reviewer
        FOREIGN KEY (reviewed_by_gr_id) REFERENCES gr_office(id) ON DELETE SET NULL,
    INDEX idx_admission_document_latest (application_id, category, id),
    INDEX idx_admission_document_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS admission_audit_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id BIGINT UNSIGNED NOT NULL,
    actor_user_id INT NULL,
    event_type VARCHAR(60) NOT NULL,
    event_detail VARCHAR(255) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_admission_audit_application
        FOREIGN KEY (application_id) REFERENCES admission_applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_admission_audit_actor
        FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_admission_audit_application (application_id, created_at)
) ENGINE=InnoDB;

-- Rollback only after exporting any admission records that must be retained:
-- DROP TABLE admission_audit_log;
-- DROP TABLE admission_documents;
-- DROP TABLE admission_applications;
-- DROP TABLE admission_intake;
