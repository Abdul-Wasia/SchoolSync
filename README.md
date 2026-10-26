# SchoolSync

SchoolSync is a full-featured school management system built with Flask, designed for managing academic operations, student records, attendance, assignments, fees, admissions, and communication in one place.

This project is a complete ERP-style solution for schools, with role-based dashboards and automation to simplify administrative workflows.

## Built By

Abdul Wasia  
BE Computer Systems Engineering  
Spring 2026

## Project Overview

SchoolSync helps schools manage:

- Student information and academic records
- Teacher and subject management
- Attendance tracking and teacher/student panels
- Assignment and submission handling
- Fees and finance-related records
- Admission workflow and document review
- Notifications, feedback, and audit actions
- AI-powered academic assistant for course materials

## Features

### Core Management Features
- Multi-role dashboard system for Admin, GR Office, Finance, Teacher, Principal, and Student
- Role-based access control and session-based authentication
- MySQL-backed data model with relational tables
- Student and teacher profile management
- Course and subject mapping
- Attendance tracking with lock rules and admin override support
- Assignment upload, review, and submission system
- Fee structure and student fee tracking
- Leave application workflow
- Exam schedule management
- Notification system for different roles
- Audit logging for sensitive actions
- Digital Notice Board & Circulars Hub with priority alerts (Urgent/High/Normal)
- Academic Calendar & School Events/Holidays Planner
- Official Student Certificate Generator (Bonafide, Character, Transfer & Leaving Certificates)
- Class Monthly Attendance Register (Master Sheet 1–31 grid with summary statistics)
- Student Emergency Contact & Medical Health Profile tracking
- Student Conduct, Commendations, and Pastoral Incident Log

### Admissions Portal
- Public admission form for applicants
- GR Office review and approval flow
- Document version tracking and status updates
- One-time access code and reference-based applicant tracking
- Student enrollment and account creation workflow

### AI Assistant
- Smart assistant for Q&A based on teacher-uploaded course materials
- Supports searchable PDF, DOCX, PPTX, TXT, Markdown, and CSV files
- Helps students and teachers find information quickly from uploaded notes and resources

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python Flask |
| Database | MySQL |
| Frontend | HTML, CSS, JavaScript, Jinja2 |
| Authentication | Session-based auth + bcrypt |
| File Handling | Flask uploads, PDF/DOCX/PPTX parsing |
| AI Integration | Groq / Gemini / OpenRouter / Claude API support |

## Project Structure

```text
SchoolSync/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── .env.example
├── database/
│   ├── schema.sql
│   └── migrations/
├── routes/
│   ├── auth_routes.py
│   ├── admin_routes.py
│   ├── fa_routes.py
│   ├── teacher_routes.py
│   ├── student_routes.py
│   ├── principal_routes.py
│   ├── gr_routes.py
│   ├── admission_routes.py
│   └── ai_routes.py
├── security/
├── static/
├── templates/
├── instance/
└── tests/
```

## Requirements

Before running the project, install:

- Python 3.10+
- MySQL Server
- Virtual environment (recommended)

## Setup Instructions

1. Clone the repository

```bash
git clone https://github.com/Abdul-Wasia/SchoolSync.git
cd SchoolSync
```

2. Create and activate a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Create environment file

Copy `.env.example` to `.env` and update values:

```bash
copy .env.example .env
```

Example configuration:

```env
SECRET_KEY=your_secure_secret_key
DEBUG=True
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=SchoolSync
GROQ_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
CLAUDE_API_KEY=
```

Important:
- For local development, keep `DEBUG=True`.
- For production, set `DEBUG=False` and use a strong secret key.
- Add at least one AI provider key to enable course material AI assistant features.

5. Create the MySQL database

```sql
CREATE DATABASE SchoolSync;
```

6. Run the application

```bash
python app.py
```

Then open:

```text
http://localhost:5000
```

7. Load demo data (optional)

The project ships with a repeatable seeder that fills the database with a realistic
school: 8 sections across Grades 6–11, 48 students, 16 subject teachers, 46 subjects,
a Monday–Saturday timetable, attendance history, results, fees and announcements.

```bash
python -m database.seed_demo_data
```

The script is idempotent: it reuses existing rows, refreshes the demo timetable and
attendance, and can be run again at any time without creating duplicates. It also
re-aligns attendance rows with the current subject–teacher mapping so dashboard totals
always match per-course totals.

### Demo Accounts

| Role | Username | Password |
| --- | --- | --- |
| Principal | `principal` | `prin123` |
| Finance / Admin Office | `fa_user` | `fa123` |
| IT Admin | `admin` | `admin123` |
| Teachers | `teacher1` … `teacher16` | `teach123` |
| Students | `student1` … `student48` | `stud123` |

Each teacher is assigned the subjects and sections they actually teach, so their
dashboard shows the matching classes, timetable and attendance. Student accounts are
spread across all eight sections.

## Default Roles

The project includes these user roles:

- IT Admin
- GR Office
- Finance/Admin Office
- Teacher
- Principal
- Student

Each role has a dedicated dashboard and access permissions.

## Important Notes

### Security
- Do not expose the development `SECRET_KEY` in production.
- Keep uploaded files in the private instance directory.
- Do not expose protected upload paths directly through the web server.

### Admissions Workflow
- The admissions system uses the migration file in `database/migrations/002_admission_portal.sql`.
- Ensure the required base tables exist before using the admissions portal.

### AI Material Support
The AI assistant reads uploaded academic content including:
- PDF
- DOCX
- PPTX
- TXT
- Markdown
- CSV

Supported extraction works on text-based documents. Scanned images, videos, ZIP files, and external links are not text-extracted.

## Subject

Database Management System (DBMS)  
Semester Project

## License

This project is for academic and educational use and is intended as a university/semester project demonstration.

## Screenshots

Add screenshots here once the UI is finalized for presentation.


Important: keep all real AI credentials in your local `.env` file only. Do not commit actual API keys to the repository.

The project expects `GEMINI_API_KEY` and `OPENROUTER_API_KEY` to be loaded through the environment configuration, with `.env.example` kept as a placeholder template only.

Please check routes/ai_routes.py and the AI assistant module to ensure:

- The keys are properly loaded via python-dotenv.
- The AI chatbot feature is working correctly using either Gemini or OpenRouter.
- Existing database schema, authentication, and core routes remain unchanged."

