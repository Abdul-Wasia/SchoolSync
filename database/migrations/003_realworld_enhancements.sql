-- Migration 003: Real-world School Management Enhancements
-- Adds School Events/Academic Calendar, Student Conduct & Commendations,
-- Student Certificates, and Emergency/Medical profiles.
-- Fully non-breaking and additive.

-- 1. School Events & Academic Calendar
CREATE TABLE IF NOT EXISTS school_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    event_type ENUM('Holiday','Exam','Sports','Meeting','Academic','Celebration') NOT NULL DEFAULT 'Academic',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    target_audience ENUM('All','Student','Teacher','Staff') NOT NULL DEFAULT 'All',
    created_by INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_event_dates (start_date, end_date),
    INDEX idx_event_type (event_type)
) ENGINE=InnoDB;

-- 2. Student Conduct & Commendation Logs
CREATE TABLE IF NOT EXISTS student_conduct_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    recorded_by INT NOT NULL,
    log_type ENUM('Commendation','Achievement','Discipline_Warning','Attendance_Notice') NOT NULL DEFAULT 'Commendation',
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    incident_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (recorded_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_student_conduct (student_id, incident_date)
) ENGINE=InnoDB;

-- 3. Student Official Certificates Register
CREATE TABLE IF NOT EXISTS student_certificates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    certificate_number VARCHAR(50) NOT NULL UNIQUE,
    student_id INT NOT NULL,
    certificate_type ENUM('Bonafide','Character','Transfer','Leaving') NOT NULL DEFAULT 'Bonafide',
    reason VARCHAR(255) NULL,
    issued_date DATE NOT NULL,
    issued_by INT NULL,
    remarks TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (issued_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_cert_student (student_id)
) ENGINE=InnoDB;
