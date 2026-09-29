-- SchoolSync Database Schema
-- MySQL 8.0+

DROP DATABASE IF EXISTS `SchoolSync`;
CREATE DATABASE `SchoolSync` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `SchoolSync`;

-- 1. users
CREATE TABLE `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(50) NOT NULL UNIQUE,
    `password` VARCHAR(255) NOT NULL,
    `user_type` ENUM('IT_Admin','GR_Office','Principal','FA','Teacher','Student') NOT NULL,
    `email` VARCHAR(100),
    `phone` VARCHAR(20),
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `last_login` TIMESTAMP NULL
) ENGINE=InnoDB;

-- 2. activity_log
CREATE TABLE `activity_log` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `action` VARCHAR(100) NOT NULL,
    `details` TEXT,
    `ip_address` VARCHAR(45),
    `logged_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 3. grades
CREATE TABLE `grades` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(50) NOT NULL UNIQUE,
    `created_by` INT,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`created_by`) REFERENCES `users`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 4. sections
CREATE TABLE `sections` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `grade_id` INT NOT NULL,
    `name` VARCHAR(10) NOT NULL,
    `capacity` INT DEFAULT 40,
    FOREIGN KEY (`grade_id`) REFERENCES `grades`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `unique_grade_section` (`grade_id`, `name`)
) ENGINE=InnoDB;

-- 5. subjects
CREATE TABLE `subjects` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `subject_name` VARCHAR(100) NOT NULL,
    `grade_id` INT NOT NULL,
    `type` ENUM('Theory','Practical') NOT NULL DEFAULT 'Theory',
    `description` TEXT,
    FOREIGN KEY (`grade_id`) REFERENCES `grades`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 6. offices
CREATE TABLE `offices` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `office_type` VARCHAR(50),
    `office_number` VARCHAR(20),
    `floor` INT,
    `capacity` INT
) ENGINE=InnoDB;

-- 7. it_admins
CREATE TABLE `it_admins` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `phone` VARCHAR(20),
    `role` VARCHAR(50) DEFAULT 'System Administrator',
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 8. gr_office
CREATE TABLE `gr_office` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `phone` VARCHAR(20),
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 9. principals
CREATE TABLE `principals` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `phone` VARCHAR(20),
    `office_id` INT,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`office_id`) REFERENCES `offices`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 10. fa
CREATE TABLE `fa` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `phone` VARCHAR(20),
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 11. teachers
CREATE TABLE `teachers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `subject` VARCHAR(100),
    `qualification` VARCHAR(100),
    `phone` VARCHAR(20),
    `email` VARCHAR(100),
    `hire_date` DATE,
    `office_id` INT,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`office_id`) REFERENCES `offices`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 12. students
CREATE TABLE `students` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL UNIQUE,
    `student_system_id` VARCHAR(20) NOT NULL UNIQUE,
    `name` VARCHAR(100) NOT NULL,
    `father_name` VARCHAR(100),
    `section_id` INT,
    `roll_number` VARCHAR(20),
    `dob` DATE,
    `gender` ENUM('Male','Female','Other'),
    `address` TEXT,
    `parent_contact` VARCHAR(20),
    `admission_date` DATE,
    `status` ENUM('PendingLogin','Active','Inactive') DEFAULT 'PendingLogin',
    `verification_status` ENUM('Pending','Verified','Rejected') DEFAULT 'Pending',
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 13. document_verification
CREATE TABLE `document_verification` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `student_id` INT NOT NULL,
    `document_type` ENUM('Birth Certificate','Previous School Record','ID Proof','Address Proof','Other') NOT NULL,
    `document_path` VARCHAR(255) NOT NULL,
    `verification_status` ENUM('Pending','Verified','Rejected') DEFAULT 'Pending',
    `verified_by_gr_id` INT,
    `verified_date` TIMESTAMP NULL,
    `remarks` TEXT,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`verified_by_gr_id`) REFERENCES `gr_office`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 14. labs
CREATE TABLE `labs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `lab_name` VARCHAR(100) NOT NULL,
    `lab_type` ENUM('Computer','Science','Language','Other') NOT NULL,
    `floor` INT,
    `capacity` INT,
    `equipment_list` TEXT
) ENGINE=InnoDB;

-- 15. subject_teachers
CREATE TABLE `subject_teachers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `teacher_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    `assigned_by` INT,
    `assigned_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`assigned_by`) REFERENCES `users`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `unique_teacher_subject_section` (`teacher_id`, `subject_id`, `section_id`)
) ENGINE=InnoDB;

-- 16. class_requests
CREATE TABLE `class_requests` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `teacher_id` INT NOT NULL,
    `class_name` VARCHAR(100),
    `grade_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `reason` TEXT,
    `status` ENUM('Pending','Approved','Rejected') DEFAULT 'Pending',
    `fa_response_note` TEXT,
    `requested_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `reviewed_at` TIMESTAMP NULL,
    `reviewed_by_fa_id` INT,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`grade_id`) REFERENCES `grades`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`reviewed_by_fa_id`) REFERENCES `fa`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 17. timetable
CREATE TABLE `timetable` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `section_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `teacher_id` INT NOT NULL,
    `day` ENUM('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday') NOT NULL,
    `period` INT NOT NULL,
    `start_time` TIME NOT NULL,
    `end_time` TIME NOT NULL,
    `room_type` ENUM('Classroom','Lab') DEFAULT 'Classroom',
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `unique_section_day_period` (`section_id`, `day`, `period`)
) ENGINE=InnoDB;

-- 18. attendance
CREATE TABLE `attendance` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `student_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `teacher_id` INT NOT NULL,
    `date` DATE NOT NULL,
    `status` ENUM('Present','Absent','Late','Leave') NOT NULL,
    `marked_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `is_locked` TINYINT(1) DEFAULT 0,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `unique_attendance` (`student_id`, `section_id`, `subject_id`, `date`)
) ENGINE=InnoDB;

-- 19. teacher_attendance
CREATE TABLE `teacher_attendance` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `teacher_id` INT NOT NULL,
    `date` DATE NOT NULL,
    `status` ENUM('Present','Absent','Late','Leave') NOT NULL,
    `marked_by_fa_id` INT,
    `notes` TEXT,
    `marked_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `is_locked` TINYINT(1) DEFAULT 0,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`marked_by_fa_id`) REFERENCES `fa`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `unique_teacher_attendance` (`teacher_id`, `date`)
) ENGINE=InnoDB;

-- 20. substitutions
CREATE TABLE `substitutions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `date` DATE NOT NULL,
    `absent_teacher_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    `substitute_teacher_id` INT NOT NULL,
    `assigned_by_fa_id` INT NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`absent_teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`substitute_teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`assigned_by_fa_id`) REFERENCES `fa`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 21. assignments
CREATE TABLE `assignments` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(200) NOT NULL,
    `instructions` TEXT,
    `subject_id` INT NOT NULL,
    `teacher_id` INT NOT NULL,
    `due_date` DATETIME NOT NULL,
    `total_marks` INT DEFAULT 100,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 22. assignment_sections
CREATE TABLE `assignment_sections` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `assignment_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    FOREIGN KEY (`assignment_id`) REFERENCES `assignments`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    UNIQUE KEY `unique_assignment_section` (`assignment_id`, `section_id`)
) ENGINE=InnoDB;

-- 23. submissions
CREATE TABLE `submissions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `assignment_id` INT NOT NULL,
    `student_id` INT NOT NULL,
    `file_path` VARCHAR(255),
    `text_response` TEXT,
    `submitted_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `marks_obtained` DECIMAL(5,2),
    `graded_by` INT,
    `graded_at` TIMESTAMP NULL,
    FOREIGN KEY (`assignment_id`) REFERENCES `assignments`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`graded_by`) REFERENCES `users`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `unique_submission` (`assignment_id`, `student_id`)
) ENGINE=InnoDB;

-- 24. homework
CREATE TABLE `homework` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(200) NOT NULL,
    `instructions` TEXT,
    `subject_id` INT NOT NULL,
    `section_id` INT NOT NULL,
    `teacher_id` INT NOT NULL,
    `due_date` DATETIME NOT NULL,
    `total_marks` INT DEFAULT 100,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`teacher_id`) REFERENCES `teachers`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 25. homework_submissions
CREATE TABLE `homework_submissions` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `homework_id` INT NOT NULL,
    `student_id` INT NOT NULL,
    `text_response` TEXT,
    `file_path` VARCHAR(255),
    `submitted_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    `marks_obtained` DECIMAL(5,2),
    `graded_by` INT,
    `graded_at` TIMESTAMP NULL,
    FOREIGN KEY (`homework_id`) REFERENCES `homework`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`graded_by`) REFERENCES `users`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `unique_homework_submission` (`homework_id`, `student_id`)
) ENGINE=InnoDB;

-- 26. results
CREATE TABLE `results` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `student_id` INT NOT NULL,
    `subject_id` INT NOT NULL,
    `exam_type` ENUM('Quiz','Assignment','Mid-Term','Final-Term') NOT NULL,
    `marks_obtained` DECIMAL(5,2) NOT NULL,
    `total_marks` DECIMAL(5,2) NOT NULL,
    `grade` VARCHAR(2),
    `exam_date` DATE NOT NULL,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`subject_id`) REFERENCES `subjects`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 27. notifications
CREATE TABLE `notifications` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `message` TEXT NOT NULL,
    `type` VARCHAR(50),
    `is_read` TINYINT(1) DEFAULT 0,
    `link` VARCHAR(255),
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 28. announcements
CREATE TABLE `announcements` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(200) NOT NULL,
    `content` TEXT NOT NULL,
    `posted_by` INT NOT NULL,
    `target_role` ENUM('All','Student','Teacher','FA','Principal','GR_Office','IT_Admin') NOT NULL DEFAULT 'All',
    `grade_id` INT,
    `section_id` INT,
    `is_active` TINYINT(1) DEFAULT 1,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`posted_by`) REFERENCES `users`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`grade_id`) REFERENCES `grades`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`section_id`) REFERENCES `sections`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 29. fee_structure
CREATE TABLE `fee_structure` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `grade_id` INT NOT NULL UNIQUE,
    `amount` DECIMAL(10,2) NOT NULL,
    `created_by` INT,
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`grade_id`) REFERENCES `grades`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`created_by`) REFERENCES `users`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB;

-- 30. student_fees
CREATE TABLE `student_fees` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `student_id` INT NOT NULL,
    `month_year` VARCHAR(7) NOT NULL,
    `status` ENUM('Paid','Unpaid') DEFAULT 'Unpaid',
    `marked_by_fa_id` INT,
    `marked_at` TIMESTAMP NULL,
    FOREIGN KEY (`student_id`) REFERENCES `students`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`marked_by_fa_id`) REFERENCES `fa`(`id`) ON DELETE SET NULL,
    UNIQUE KEY `unique_student_fee` (`student_id`, `month_year`)
) ENGINE=InnoDB;

-- OTP table for password reset
CREATE TABLE `otp_codes` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `email` VARCHAR(100) NOT NULL,
    `code` VARCHAR(6) NOT NULL,
    `is_used` TINYINT(1) DEFAULT 0,
    `expires_at` TIMESTAMP NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================
-- SAMPLE DATA
-- ============================================

-- Users (passwords are plain text for simplicity - in production use hashing)
INSERT INTO `users` (`username`, `password`, `user_type`, `email`, `phone`, `is_active`, `created_at`) VALUES
('admin', 'admin123', 'IT_Admin', 'admin@schoolsync.com', '03001111111', 1, NOW()),
('gr_office', 'gr123', 'GR_Office', 'gr@schoolsync.com', '03002222222', 1, NOW()),
('principal', 'prin123', 'Principal', 'principal@schoolsync.com', '03003333333', 1, NOW()),
('fa_user', 'fa123', 'FA', 'fa@schoolsync.com', '03004444444', 1, NOW()),
('teacher1', 'teach123', 'Teacher', 'teacher1@schoolsync.com', '03005555555', 1, NOW()),
('teacher2', 'teach123', 'Teacher', 'teacher2@schoolsync.com', '03006666666', 1, NOW()),
('student1', 'stud123', 'Student', 'student1@schoolsync.com', '03007777777', 1, NOW()),
('student2', 'stud123', 'Student', 'student2@schoolsync.com', '03008888888', 1, NOW());

-- Role tables
INSERT INTO `it_admins` (`user_id`, `name`, `phone`, `role`) VALUES
(1, 'System Admin', '03001111111', 'System Administrator');

INSERT INTO `gr_office` (`user_id`, `name`, `phone`) VALUES
(2, 'GR Officer', '03002222222');

INSERT INTO `principals` (`user_id`, `name`, `phone`) VALUES
(3, 'Principal Ahmed', '03003333333');

INSERT INTO `fa` (`user_id`, `name`, `phone`) VALUES
(4, 'Faculty Advisor', '03004444444');

INSERT INTO `teachers` (`user_id`, `name`, `subject`, `qualification`, `phone`, `email`, `hire_date`) VALUES
(5, 'John Smith', 'Mathematics', 'M.Sc Mathematics', '03005555555', 'teacher1@schoolsync.com', '2020-01-15'),
(6, 'Sarah Johnson', 'Computer Science', 'MCS', '03006666666', 'teacher2@schoolsync.com', '2021-03-20');

-- Grades
INSERT INTO `grades` (`name`, `created_by`) VALUES
('Grade 6', 1),
('Grade 7', 1),
('Grade 8', 1),
('Grade 9', 1),
('Grade 10', 1);

-- Sections for Grade 8 (id=3)
INSERT INTO `sections` (`grade_id`, `name`, `capacity`) VALUES
(3, 'A', 40),
(3, 'B', 40),
(3, 'C', 40);

-- Subjects for Grade 8 (id=3)
INSERT INTO `subjects` (`subject_name`, `grade_id`, `type`, `description`) VALUES
('Mathematics', 3, 'Theory', 'Core mathematics including algebra, geometry, and statistics'),
('Computer Science', 3, 'Practical', 'Programming fundamentals and computer literacy'),
('English', 3, 'Theory', 'English language and literature'),
('Urdu', 3, 'Theory', 'Urdu language and literature'),
('Science', 3, 'Theory', 'General science including physics, chemistry, biology');

-- Students (references section_id from sections above)
INSERT INTO `students` (`user_id`, `student_system_id`, `name`, `father_name`, `section_id`, `roll_number`, `dob`, `gender`, `address`, `parent_contact`, `admission_date`, `status`, `verification_status`) VALUES
(7, 'SS-2026-0001', 'Ali Khan', 'Ahmed Khan', 1, '01', '2010-05-15', 'Male', '123 Main St', '03009999999', '2023-08-01', 'Active', 'Verified'),
(8, 'SS-2026-0002', 'Fatima Ali', 'Ali Hassan', 1, '02', '2010-08-22', 'Female', '456 Oak Ave', '03008888888', '2023-08-01', 'Active', 'Verified');

-- Assign teachers to subjects
INSERT INTO `subject_teachers` (`teacher_id`, `subject_id`, `section_id`, `assigned_by`) VALUES
(1, 1, 1, 1),  -- John Smith -> Mathematics Grade 8-A
(1, 1, 2, 1),  -- John Smith -> Mathematics Grade 8-B
(2, 2, 1, 1);  -- Sarah Johnson -> Computer Science Grade 8-A

-- Sample timetable slot
INSERT INTO `timetable` (`section_id`, `subject_id`, `teacher_id`, `day`, `period`, `start_time`, `end_time`, `room_type`) VALUES
(1, 1, 1, 'Monday', 1, '08:00:00', '08:45:00', 'Classroom');

-- Sample assignment
INSERT INTO `assignments` (`title`, `instructions`, `subject_id`, `teacher_id`, `due_date`, `total_marks`) VALUES
('Algebra Homework', 'Complete exercises 1-10 from chapter 3', 1, 1, DATE_ADD(NOW(), INTERVAL 7 DAY), 50);

INSERT INTO `assignment_sections` (`assignment_id`, `section_id`) VALUES
(1, 1);

-- Sample attendance record
INSERT INTO `attendance` (`student_id`, `section_id`, `subject_id`, `teacher_id`, `date`, `status`) VALUES
(1, 1, 1, 1, CURDATE(), 'Present');

-- Sample fee structure
INSERT INTO `fee_structure` (`grade_id`, `amount`, `created_by`) VALUES
(3, 5000.00, 1);