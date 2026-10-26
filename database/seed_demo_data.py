"""Populate SchoolSync with a realistic Pakistani school demo dataset.

Usage (from the project root):

    python -m database.seed_demo_data

The script is safe to run more than once. It keeps existing rows where it can
and only fills in / refreshes the demo records it owns (timetable, teacher
assignments, attendance and results).

What it creates
---------------
* 8 sections across Grades 6-11, with 6 students in every section
* A subject list for every grade and a specialist teacher for every subject
* A Monday-Saturday timetable with 8 periods a day and no teacher clashes
* Historical student attendance, teacher attendance, results, fees,
  homework, assignments and announcements

Demo credentials
----------------
Teachers : teacher1 ... teacher16 / teach123
Students : student1 ... student48 / stud123
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import mysql.connector

# Allow "python database/seed_demo_data.py" as well as "-m database.seed_demo_data".
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config  # noqa: E402
from database.connection import hash_password  # noqa: E402


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
PERIODS = [
    (1, "08:00:00", "08:45:00"),
    (2, "08:45:00", "09:30:00"),
    (3, "09:30:00", "10:15:00"),
    (4, "10:15:00", "11:00:00"),
    (5, "11:30:00", "12:15:00"),
    (6, "12:15:00", "13:00:00"),
    (7, "13:00:00", "13:45:00"),
    (8, "13:45:00", "14:30:00"),
]

TODAY = date.today()

# ---------------------------------------------------------------------------
# Curriculum plan
# ---------------------------------------------------------------------------

GRADE_SUBJECTS = {
    "Grade 6": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Science", "Theory"),
        ("Islamiat", "Theory"),
        ("Social Studies", "Theory"),
    ],
    "Grade 7": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Science", "Theory"),
        ("Islamiat", "Theory"),
        ("Social Studies", "Theory"),
    ],
    "Grade 8": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Science", "Theory"),
        ("Computer Science", "Practical"),
        ("Islamiat", "Theory"),
        ("Pakistan Studies", "Theory"),
    ],
    "Grade 9": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Physics", "Theory"),
        ("Chemistry", "Theory"),
        ("Biology", "Theory"),
        ("Islamiat", "Theory"),
        ("Pakistan Studies", "Theory"),
        ("Computer Science", "Practical"),
    ],
    "Grade 10": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Physics", "Theory"),
        ("Chemistry", "Theory"),
        ("Biology", "Theory"),
        ("Islamiat", "Theory"),
        ("Pakistan Studies", "Theory"),
        ("Computer Science", "Practical"),
    ],
    "Grade 11": [
        ("Mathematics", "Theory"),
        ("English", "Theory"),
        ("Urdu", "Theory"),
        ("Physics", "Theory"),
        ("Chemistry", "Theory"),
        ("Biology", "Theory"),
        ("Islamiat", "Theory"),
        ("Pakistan Studies", "Theory"),
        ("Computer Science", "Practical"),
    ],
}

# Weekly periods per subject. Every list must add up to 6 days x 8 periods.
GRADE_PERIODS = {
    "Grade 6": {"Mathematics": 8, "English": 8, "Urdu": 8, "Science": 8, "Islamiat": 8, "Social Studies": 8},
    "Grade 7": {"Mathematics": 8, "English": 8, "Urdu": 8, "Science": 8, "Islamiat": 8, "Social Studies": 8},
    "Grade 8": {
        "Mathematics": 8, "English": 8, "Urdu": 7, "Science": 7,
        "Computer Science": 7, "Islamiat": 6, "Pakistan Studies": 5,
    },
    "Grade 9": {
        "Mathematics": 6, "English": 6, "Urdu": 6, "Physics": 5, "Chemistry": 5,
        "Biology": 5, "Islamiat": 5, "Pakistan Studies": 5, "Computer Science": 5,
    },
    "Grade 10": {
        "Mathematics": 6, "English": 6, "Urdu": 6, "Physics": 5, "Chemistry": 5,
        "Biology": 5, "Islamiat": 5, "Pakistan Studies": 5, "Computer Science": 5,
    },
    "Grade 11": {
        "Mathematics": 6, "English": 6, "Urdu": 6, "Physics": 5, "Chemistry": 5,
        "Biology": 5, "Islamiat": 5, "Pakistan Studies": 5, "Computer Science": 5,
    },
}

TEACHER_PLANS = {
    "Grade 6": {
        "Mathematics": "teacher11", "English": "teacher12", "Urdu": "teacher13",
        "Science": "teacher14", "Islamiat": "teacher15", "Social Studies": "teacher10",
    },
    "Grade 7": {
        "Mathematics": "teacher11", "English": "teacher12", "Urdu": "teacher13",
        "Science": "teacher14", "Islamiat": "teacher15", "Social Studies": "teacher10",
    },
    "Grade 8": {
        "Mathematics": "teacher1", "English": "teacher3", "Urdu": "teacher4",
        "Science": "teacher5", "Computer Science": "teacher2",
        "Islamiat": "teacher6", "Pakistan Studies": "teacher7",
    },
    "Grade 9": {
        "Mathematics": "teacher1", "English": "teacher3", "Urdu": "teacher4",
        "Physics": "teacher8", "Chemistry": "teacher9", "Biology": "teacher5",
        "Islamiat": "teacher6", "Pakistan Studies": "teacher7", "Computer Science": "teacher2",
    },
    "Grade 10": {
        "Mathematics": "teacher11", "English": "teacher12", "Urdu": "teacher13",
        "Physics": "teacher8", "Chemistry": "teacher9", "Biology": "teacher5",
        "Islamiat": "teacher6", "Pakistan Studies": "teacher7", "Computer Science": "teacher2",
    },
    "Grade 11": {
        "Mathematics": "teacher11", "English": "teacher12", "Urdu": "teacher13",
        "Physics": "teacher8", "Chemistry": "teacher9", "Biology": "teacher5",
        "Islamiat": "teacher6", "Pakistan Studies": "teacher7", "Computer Science": "teacher16",
    },
}

# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

TEACHERS = [
    # username, name, subject, qualification, phone, email, hire_date
    ("teacher1", "Imran Ahmed", "Mathematics", "M.Sc Mathematics", "0300-4512301", "imran.ahmed@schoolsync.pk", "2015-04-12"),
    ("teacher2", "Sadia Khan", "Computer Science", "MCS", "0301-4522302", "sadia.khan@schoolsync.pk", "2017-08-01"),
    ("teacher3", "Ayesha Siddiqui", "English", "M.A English Literature", "0302-4532303", "ayesha.siddiqui@schoolsync.pk", "2016-01-18"),
    ("teacher4", "Muhammad Aslam", "Urdu", "M.A Urdu", "0303-4542304", "muhammad.aslam@schoolsync.pk", "2014-09-05"),
    ("teacher5", "Fatima Noor", "Biology", "M.Sc Zoology", "0304-4552305", "fatima.noor@schoolsync.pk", "2018-02-14"),
    ("teacher6", "Bilal Hussain", "Islamiat", "M.A Islamic Studies", "0305-4562306", "bilal.hussain@schoolsync.pk", "2013-06-20"),
    ("teacher7", "Nadia Rehman", "Pakistan Studies", "M.A History", "0306-4572307", "nadia.rehman@schoolsync.pk", "2019-03-11"),
    ("teacher8", "Usman Tariq", "Physics", "M.Sc Physics", "0307-4582308", "usman.tariq@schoolsync.pk", "2016-10-03"),
    ("teacher9", "Hina Malik", "Chemistry", "M.Sc Chemistry", "0308-4592309", "hina.malik@schoolsync.pk", "2017-05-22"),
    ("teacher10", "Kamran Sheikh", "Social Studies", "M.A Sociology", "0309-4602310", "kamran.sheikh@schoolsync.pk", "2020-01-07"),
    ("teacher11", "Rabia Aslam", "Mathematics", "M.Sc Mathematics", "0310-4612311", "rabia.aslam@schoolsync.pk", "2018-08-16"),
    ("teacher12", "Sana Yousaf", "English", "M.A English", "0311-4622312", "sana.yousaf@schoolsync.pk", "2019-09-02"),
    ("teacher13", "Shahid Mehmood", "Urdu", "M.A Urdu", "0312-4632313", "shahid.mehmood@schoolsync.pk", "2015-11-25"),
    ("teacher14", "Tariq Jameel", "Science", "M.Sc Botany", "0313-4642314", "tariq.jameel@schoolsync.pk", "2020-02-10"),
    ("teacher15", "Abdul Rehman", "Islamiat", "M.A Islamic Studies", "0314-4652315", "abdul.rehman@schoolsync.pk", "2021-04-19"),
    ("teacher16", "Zeeshan Ali", "Computer Science", "BS Computer Science", "0315-4662316", "zeeshan.ali@schoolsync.pk", "2022-08-01"),
]

MALE_NAMES = [
    "Muhammad Hamza", "Ali Raza", "Hassan Ahmed", "Abdullah Sheikh", "Umar Farooq",
    "Bilal Akhtar", "Saad Mahmood", "Ahmad Nawaz", "Talha Iqbal", "Zain Abbas",
    "Hamza Saeed", "Faizan Ali", "Usman Ghani", "Arham Malik", "Shayan Qureshi",
    "Daniyal Khan", "Ibrahim Yousaf", "Haris Nadeem", "Ayan Shah", "Rehan Butt",
    "Muneeb Tariq", "Waleed Anwar", "Sameer Chaudhry", "Junaid Rasheed",
]
FEMALE_NAMES = [
    "Ayesha Bibi", "Fatima Zahra", "Hira Noor", "Mahnoor Fatima", "Zainab Ali",
    "Maryam Khan", "Amna Siddiqui", "Sana Javed", "Iqra Aslam", "Laiba Ahmed",
    "Rida Hussain", "Noor ul Ain", "Eman Fatima", "Areeba Shahid", "Komal Nawaz",
    "Mehwish Iqbal", "Anaya Malik", "Aleena Tariq", "Sadia Yousaf", "Mishal Rehman",
    "Hafsa Naeem", "Warda Saleem", "Saba Riaz", "Arooj Fatima",
]
FATHERS = [
    "Muhammad Asif", "Abdul Ghaffar", "Rashid Mahmood", "Naveed Akhtar", "Shahid Iqbal",
    "Tariq Mehmood", "Imtiaz Hussain", "Javed Anwar", "Khalid Mahmood", "Naeem Ahmed",
    "Rizwan Ali", "Sohail Raza", "Pervez Akhtar", "Zafar Iqbal", "Arshad Ali",
    "Waseem Abbas", "Faisal Nadeem", "Aamir Shahzad", "Yasir Mehmood", "Kamran Rasheed",
    "Adnan Yousaf", "Sajid Hussain", "Majid Khan", "Nadeem Aslam",
]
CITIES = [
    ("Lahore", "House 24, Street 7, Gulberg III, Lahore"),
    ("Karachi", "Flat 5B, Block 4, Gulshan-e-Iqbal, Karachi"),
    ("Islamabad", "House 12, Street 9, F-8/3, Islamabad"),
    ("Rawalpindi", "House 88, Satellite Town, Rawalpindi"),
    ("Faisalabad", "House 41, Peoples Colony No. 1, Faisalabad"),
    ("Multan", "House 17, Gulgasht Colony, Multan"),
    ("Peshawar", "House 6, Hayatabad Phase 2, Peshawar"),
    ("Sialkot", "House 33, Cantt Road, Sialkot"),
]

# Grade -> birth year used for demo dates of birth.
GRADE_BIRTH_YEAR = {
    "Grade 6": 2014,
    "Grade 7": 2013,
    "Grade 8": 2012,
    "Grade 9": 2011,
    "Grade 10": 2010,
    "Grade 11": 2009,
}

# ---------------------------------------------------------------------------
# Small database helper
# ---------------------------------------------------------------------------


class Database:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=Config.DB_HOST,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            autocommit=False,
        )
        self.cursor = self.conn.cursor(dictionary=True)

    def all(self, sql, params=()):
        self.cursor.execute(sql, params)
        return self.cursor.fetchall()

    def one(self, sql, params=()):
        self.cursor.execute(sql, params)
        return self.cursor.fetchone()

    def run(self, sql, params=()):
        self.cursor.execute(sql, params)
        return self.cursor.lastrowid

    def many(self, sql, rows, chunk=500):
        rows = list(rows)
        for start in range(0, len(rows), chunk):
            self.cursor.executemany(sql, rows[start:start + chunk])

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.cursor.close()
        self.conn.close()


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------


def normalise_school(db):
    """Fix the two stray demo labels so the school reads coherently."""
    db.run(
        "UPDATE grades SET name = %s WHERE id = 6 AND name = %s",
        ("Grade 11", "6 semester"),
    )
    db.run(
        "UPDATE subjects SET subject_name = %s, type = %s WHERE id = 6 AND subject_name = %s",
        ("Islamiat", "Theory", "Comprative Education"),
    )
    db.run(
        "UPDATE subjects SET type = 'Practical' WHERE subject_name = 'Computer Science'",
    )
    db.run(
        "UPDATE sections SET name = 'A' WHERE grade_id = 6 AND name <> 'A'",
    )


def ensure_sections(db, grade_ids):
    wanted = {
        "Grade 6": ["A"],
        "Grade 7": ["A"],
        "Grade 8": ["A", "B", "C"],
        "Grade 9": ["A"],
        "Grade 10": ["A"],
        "Grade 11": ["A"],
    }
    sections = {}
    for grade_name, names in wanted.items():
        grade_id = grade_ids[grade_name]
        for name in names:
            row = db.one(
                "SELECT id FROM sections WHERE grade_id = %s AND name = %s",
                (grade_id, name),
            )
            if row:
                section_id = row["id"]
                db.run("UPDATE sections SET capacity = 40 WHERE id = %s", (section_id,))
            else:
                section_id = db.run(
                    "INSERT INTO sections (grade_id, name, capacity) VALUES (%s, %s, %s)",
                    (grade_id, name, 40),
                )
            sections[(grade_name, name)] = section_id
    return sections


def ensure_subjects(db, grade_ids):
    subjects = {}
    for grade_name, rows in GRADE_SUBJECTS.items():
        grade_id = grade_ids[grade_name]
        for subject_name, subject_type in rows:
            row = db.one(
                "SELECT id FROM subjects WHERE grade_id = %s AND subject_name = %s",
                (grade_id, subject_name),
            )
            if row:
                subject_id = row["id"]
                db.run(
                    "UPDATE subjects SET type = %s WHERE id = %s",
                    (subject_type, subject_id),
                )
            else:
                subject_id = db.run(
                    "INSERT INTO subjects (subject_name, grade_id, type, description) VALUES (%s, %s, %s, %s)",
                    (subject_name, grade_id, subject_type, f"{subject_name} for {grade_name}"),
                )
            subjects[(grade_name, subject_name)] = subject_id
    return subjects


def ensure_teachers(db):
    teacher_ids = {}
    for username, name, subject, qualification, phone, email, hire_date in TEACHERS:
        row = db.one("SELECT id FROM users WHERE username = %s", (username,))
        if row:
            user_id = row["id"]
            db.run(
                """UPDATE users
                   SET user_type = 'Teacher', email = %s, phone = %s, is_active = 1
                   WHERE id = %s""",
                (email, phone, user_id),
            )
        else:
            user_id = db.run(
                """INSERT INTO users (username, password, user_type, email, phone, is_active)
                   VALUES (%s, %s, 'Teacher', %s, %s, 1)""",
                (username, hash_password("teach123"), email, phone),
            )
        teacher = db.one("SELECT id FROM teachers WHERE user_id = %s", (user_id,))
        if teacher:
            teacher_id = teacher["id"]
            db.run(
                """UPDATE teachers
                   SET name = %s, subject = %s, qualification = %s,
                       phone = %s, email = %s, hire_date = %s
                   WHERE id = %s""",
                (name, subject, qualification, phone, email, hire_date, teacher_id),
            )
        else:
            teacher_id = db.run(
                """INSERT INTO teachers
                   (user_id, name, subject, qualification, phone, email, hire_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (user_id, name, subject, qualification, phone, email, hire_date),
            )
        teacher_ids[username] = teacher_id
    return teacher_ids


def ensure_students(db, sections, grade_ids):
    """Create six students per section, keeping Ali Khan and Fatima Ali."""
    existing = db.all(
        """SELECT id, user_id, section_id, roll_number, name
           FROM students WHERE status = 'Active'"""
    )
    section_rolls = defaultdict(set)
    for student in existing:
        if student["section_id"]:
            section_rolls[student["section_id"]].add(str(student["roll_number"]))

    student_ids = []
    male_idx = 0
    female_idx = 0
    sequence = 3  # SS-2026-0001 and 0002 already exist.

    section_order = sorted(sections.items(), key=lambda item: item[1])
    for (grade_name, section_name), section_id in section_order:
        current = [
            student for student in existing if student["section_id"] == section_id
        ]
        missing = 6 - len(current)
        for offset in range(missing):
            roll = None
            for candidate in range(1, 40):
                candidate_roll = f"{candidate:02d}"
                if candidate_roll not in section_rolls[section_id]:
                    roll = candidate_roll
                    break
            section_rolls[section_id].add(roll)

            if (male_idx + female_idx) % 2 == 0:
                name = MALE_NAMES[male_idx % len(MALE_NAMES)]
                male_idx += 1
                gender = "Male"
            else:
                name = FEMALE_NAMES[female_idx % len(FEMALE_NAMES)]
                female_idx += 1
                gender = "Female"

            username = f"student{sequence}"
            father = FATHERS[(sequence * 3) % len(FATHERS)]
            city, address = CITIES[(sequence * 5) % len(CITIES)]
            phone = f"03{sequence % 5 + 1:01d}-{4000000 + sequence * 137:07d}"
            parent_phone = f"03{sequence % 5 + 1:01d}-{5000000 + sequence * 211:07d}"
            birth_year = GRADE_BIRTH_YEAR[grade_name]
            dob = date(birth_year, (sequence % 12) + 1, (sequence % 27) + 1)
            system_id = f"SS-2026-{sequence:04d}"
            email = f"{username}@schoolsync.pk"

            user = db.one("SELECT id FROM users WHERE username = %s", (username,))
            if user:
                user_id = user["id"]
                db.run(
                    """UPDATE users
                       SET user_type = 'Student', email = %s, phone = %s, is_active = 1
                       WHERE id = %s""",
                    (email, phone, user_id),
                )
            else:
                user_id = db.run(
                    """INSERT INTO users (username, password, user_type, email, phone, is_active)
                       VALUES (%s, %s, 'Student', %s, %s, 1)""",
                    (username, hash_password("stud123"), email, phone),
                )

            student = db.one("SELECT id FROM students WHERE user_id = %s", (user_id,))
            if student:
                student_id = student["id"]
                db.run(
                    """UPDATE students
                       SET student_system_id = %s, name = %s, father_name = %s,
                           section_id = %s, roll_number = %s, dob = %s, gender = %s,
                           address = %s, parent_contact = %s, admission_date = %s,
                           status = 'Active', verification_status = 'Verified'
                       WHERE id = %s""",
                    (
                        system_id, name, father, section_id, roll, dob, gender,
                        f"{address} ({city})", parent_phone, "2024-08-05",
                        student_id,
                    ),
                )
            else:
                student_id = db.run(
                    """INSERT INTO students
                       (user_id, student_system_id, name, father_name, section_id,
                        roll_number, dob, gender, address, parent_contact,
                        admission_date, status, verification_status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active', 'Verified')""",
                    (
                        user_id, system_id, name, father, section_id, roll,
                        dob, gender, f"{address} ({city})", parent_phone, "2024-08-05",
                    ),
                )
            student_ids.append(student_id)
            sequence += 1
    return student_ids


def ensure_assignments(db, sections, subjects, teacher_ids):
    """Assign exactly one specialist teacher to every subject in every section."""
    assignment_map = {}  # (section_id, subject_id) -> teacher_id
    for (grade_name, section_name), section_id in sections.items():
        for subject_name, _ in GRADE_SUBJECTS[grade_name]:
            subject_id = subjects[(grade_name, subject_name)]
            teacher_username = TEACHER_PLANS[grade_name][subject_name]
            teacher_id = teacher_ids[teacher_username]

            # Keep a single teacher per subject/section.
            db.run(
                """DELETE FROM subject_teachers
                   WHERE section_id = %s AND subject_id = %s AND teacher_id <> %s""",
                (section_id, subject_id, teacher_id),
            )
            db.run(
                """INSERT INTO subject_teachers (teacher_id, subject_id, section_id, assigned_by)
                   VALUES (%s, %s, %s, 1)
                   ON DUPLICATE KEY UPDATE assigned_by = 1""",
                (teacher_id, subject_id, section_id),
            )
            assignment_map[(section_id, subject_id)] = teacher_id
    return assignment_map


def build_timetable(sections, subjects):
    """Build a conflict-free Monday-Saturday timetable with 8 periods a day."""
    section_plan = {}
    for (grade_name, section_name), section_id in sections.items():
        entries = []
        for subject_name, periods in GRADE_PERIODS[grade_name].items():
            entries.append(
                {
                    "subject_name": subject_name,
                    "subject_id": subjects[(grade_name, subject_name)],
                    "teacher_username": TEACHER_PLANS[grade_name][subject_name],
                    "remaining": periods,
                }
            )
        section_plan[section_id] = entries

    section_items = list(section_plan.items())
    for attempt in range(400):
        rng = random.Random(attempt)
        busy = set()
        rows = []
        failed = False
        order = section_items[:]
        rng.shuffle(order)

        for section_id, entries in order:
            remaining = {entry["subject_id"]: entry["remaining"] for entry in entries}
            by_id = {entry["subject_id"]: entry for entry in entries}
            for day in DAYS:
                taught_today = Counter()
                for period, start_time, end_time in PERIODS:
                    candidates = [
                        subject_id for subject_id, count in remaining.items()
                        if count > 0
                        and (by_id[subject_id]["teacher_username"], day, period) not in busy
                    ]
                    if not candidates:
                        failed = True
                        break
                    fresh = [subject_id for subject_id in candidates if taught_today[subject_id] == 0]
                    pool = fresh or candidates
                    most_needed = max(remaining[subject_id] for subject_id in pool)
                    pool = [subject_id for subject_id in pool if remaining[subject_id] == most_needed]
                    subject_id = rng.choice(pool)

                    entry = by_id[subject_id]
                    busy.add((entry["teacher_username"], day, period))
                    remaining[subject_id] -= 1
                    taught_today[subject_id] += 1
                    rows.append(
                        {
                            "section_id": section_id,
                            "subject_id": subject_id,
                            "teacher_username": entry["teacher_username"],
                            "day": day,
                            "period": period,
                            "start_time": start_time,
                            "end_time": end_time,
                            "room_type": "Lab" if entry["subject_name"] == "Computer Science" else "Classroom",
                        }
                    )
                if failed:
                    break
            if failed or any(count > 0 for count in remaining.values()):
                failed = True
                break
        if not failed:
            return rows
    raise RuntimeError("Could not build a conflict-free timetable after 400 attempts.")


def write_timetable(db, rows, teacher_ids):
    db.run("DELETE FROM timetable")
    db.many(
        """INSERT INTO timetable
           (section_id, subject_id, teacher_id, day, period, start_time, end_time, room_type)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            (
                row["section_id"], row["subject_id"], teacher_ids[row["teacher_username"]],
                row["day"], row["period"], row["start_time"], row["end_time"], row["room_type"],
            )
            for row in rows
        ],
    )


def seed_attendance(db, sections, timetable_rows, assignment_map, teacher_ids):
    """Create attendance for the last 30 days, following the timetable."""
    timetable_by_section = defaultdict(list)
    for row in timetable_rows:
        timetable_by_section[row["section_id"]].append(row)

    # Leave teacher1's classes unmarked today so the teacher demo has live work.
    open_today = {teacher_ids["teacher1"]}

    students = db.all(
        """SELECT id, section_id FROM students
           WHERE status = 'Active' AND section_id IS NOT NULL
           ORDER BY section_id, roll_number"""
    )
    reliability = {}
    for index, student in enumerate(students):
        if index % 9 == 4:
            reliability[student["id"]] = 0.58
        elif index % 6 == 3:
            reliability[student["id"]] = 0.71
        else:
            reliability[student["id"]] = 0.88 + (index % 4) * 0.02

    attendance_rows = []
    for offset in range(29, -1, -1):
        day = TODAY - timedelta(days=offset)
        if day.weekday() == 6:  # Sunday
            continue
        day_name = day.strftime("%A")
        for section_id, slots in timetable_by_section.items():
            # Attendance is per subject per date, so collapse double periods.
            seen_subjects = set()
            section_students = [
                student for student in students if student["section_id"] == section_id
            ]
            for slot in slots:
                if slot["day"] != day_name:
                    continue
                subject_id = slot["subject_id"]
                if subject_id in seen_subjects:
                    continue
                seen_subjects.add(subject_id)
                teacher_id = assignment_map[(section_id, subject_id)]
                if day == TODAY and teacher_id in open_today:
                    continue
                for student in section_students:
                    rng = random.Random(f"{student['id']}-{subject_id}-{day.isoformat()}")
                    base = reliability[student["id"]]
                    draw = rng.random()
                    if draw < base:
                        status = "Present"
                    elif draw < base + 0.05:
                        status = "Late"
                    elif draw < base + 0.08:
                        status = "Leave"
                    else:
                        status = "Absent"
                    if day == TODAY:
                        marked_at = datetime.now().replace(microsecond=0)
                    else:
                        marked_at = datetime.combine(day, time(8, 0)) + timedelta(
                            minutes=30 + (student["id"] * 7 + subject_id * 3) % 40
                        )
                    attendance_rows.append(
                        (student["id"], section_id, subject_id, teacher_id, day, status, marked_at)
                    )

    db.many(
        """INSERT IGNORE INTO attendance
           (student_id, section_id, subject_id, teacher_id, date, status, marked_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        attendance_rows,
    )

    # Rows inserted on an earlier run may still point at the teacher who used
    # to handle the subject. Keep the denormalised teacher_id aligned with the
    # current subject_teachers mapping so dashboard totals match course totals.
    db.run(
        """UPDATE attendance a
           JOIN subject_teachers st
             ON st.section_id = a.section_id AND st.subject_id = a.subject_id
           SET a.teacher_id = st.teacher_id
           WHERE a.teacher_id <> st.teacher_id"""
    )
    return len(attendance_rows)


def seed_teacher_attendance(db, teacher_ids):
    fa = db.one("SELECT id FROM fa ORDER BY id LIMIT 1")
    fa_id = fa["id"] if fa else None
    rows = []
    for offset in range(29, -1, -1):
        day = TODAY - timedelta(days=offset)
        if day.weekday() == 6:
            continue
        for username, teacher_id in teacher_ids.items():
            rng = random.Random(f"ta-{teacher_id}-{day.isoformat()}")
            draw = rng.random()
            if draw < 0.92:
                status = "Present"
            elif draw < 0.95:
                status = "Late"
            elif draw < 0.97:
                status = "Leave"
            else:
                status = "Absent"
            rows.append((teacher_id, day, status, fa_id, "Recorded by Faculty Advisor"))
    db.many(
        """INSERT IGNORE INTO teacher_attendance
           (teacher_id, date, status, marked_by_fa_id, notes)
           VALUES (%s, %s, %s, %s, %s)""",
        rows,
    )
    return len(rows)


def seed_results(db, sections, subjects):
    students = db.all(
        """SELECT id, section_id FROM students
           WHERE status = 'Active' AND section_id IS NOT NULL
           ORDER BY id"""
    )
    section_grade = {}
    for (grade_name, _), section_id in sections.items():
        section_grade[section_id] = grade_name

    exams = [
        ("Quiz", 20, date(2026, 9, 21)),
        ("Mid-Term", 100, date(2026, 10, 5)),
    ]
    existing = {
        (row["student_id"], row["subject_id"], row["exam_type"], row["exam_date"])
        for row in db.all(
            "SELECT student_id, subject_id, exam_type, exam_date FROM results"
        )
    }

    rows = []
    for index, student in enumerate(students):
        grade_name = section_grade.get(student["section_id"])
        if not grade_name:
            continue
        ability = 0.55 + ((index * 13) % 40) / 100
        for subject_name, _ in GRADE_SUBJECTS[grade_name]:
            subject_id = subjects[(grade_name, subject_name)]
            for exam_type, total, exam_date in exams:
                key = (student["id"], subject_id, exam_type, exam_date)
                if key in existing:
                    continue
                rng = random.Random(f"res-{student['id']}-{subject_id}-{exam_type}")
                ratio = min(0.99, max(0.30, ability + rng.uniform(-0.08, 0.08)))
                marks = round(total * ratio, 2)
                percentage = marks / total * 100
                if percentage >= 90:
                    letter = "A+"
                elif percentage >= 80:
                    letter = "A"
                elif percentage >= 70:
                    letter = "B"
                elif percentage >= 60:
                    letter = "C"
                elif percentage >= 50:
                    letter = "D"
                else:
                    letter = "F"
                rows.append(
                    (student["id"], subject_id, exam_type, marks, total, letter, exam_date)
                )
    db.many(
        """INSERT INTO results
           (student_id, subject_id, exam_type, marks_obtained, total_marks, grade, exam_date)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        rows,
    )
    return len(rows)


def seed_fees(db, sections):
    amounts = {
        "Grade 6": 4500, "Grade 7": 4800, "Grade 8": 5500,
        "Grade 9": 6000, "Grade 10": 6500, "Grade 11": 7000,
    }
    for (grade_name, _), _ in sections.items():
        grade = db.one("SELECT id FROM grades WHERE name = %s", (grade_name,))
        if grade:
            db.run(
                """INSERT INTO fee_structure (grade_id, amount, created_by)
                   VALUES (%s, %s, 1)
                   ON DUPLICATE KEY UPDATE amount = VALUES(amount)""",
                (grade["id"], amounts[grade_name]),
            )

    fa = db.one("SELECT id FROM fa ORDER BY id LIMIT 1")
    fa_id = fa["id"] if fa else None
    current = TODAY.replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    months = [previous.strftime("%Y-%m"), current.strftime("%Y-%m")]

    students = db.all(
        "SELECT id FROM students WHERE status = 'Active' ORDER BY id"
    )
    rows = []
    for student in students:
        for month_index, month in enumerate(months):
            rng = random.Random(f"fee-{student['id']}-{month}")
            status = "Paid" if rng.random() < (0.82 if month_index == 0 else 0.72) else "Unpaid"
            marked_at = datetime.combine(TODAY - timedelta(days=12 - month_index * 8), time(11, 0))
            rows.append((student["id"], month, status, fa_id if status == "Paid" else None,
                         marked_at if status == "Paid" else None))
    db.many(
        """INSERT INTO student_fees (student_id, month_year, status, marked_by_fa_id, marked_at)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE status = VALUES(status),
               marked_by_fa_id = VALUES(marked_by_fa_id),
               marked_at = VALUES(marked_at)""",
        rows,
    )
    return len(rows)


def seed_announcements(db):
    announcements = [
        ("Parent-Teacher Meeting", "The parent-teacher meeting for all sections will be held on Saturday at 10:00 AM in the main hall. Parents are requested to attend.", "All", None, None),
        ("Mid-Term Result Announcement", "Mid-term results have been published. Students can view their subject-wise marks from the Results page.", "Student", None, None),
        ("Science Exhibition", "The annual science exhibition will take place next month. Interested students should register with their class teacher.", "Student", None, None),
        ("Staff Development Workshop", "A workshop on classroom assessment will be held for all faculty members on Friday afternoon.", "Teacher", None, None),
    ]
    for title, content, role, grade_id, section_id in announcements:
        if not db.one("SELECT id FROM announcements WHERE title = %s", (title,)):
            db.run(
                """INSERT INTO announcements
                   (title, content, posted_by, target_role, grade_id, section_id, is_active)
                   VALUES (%s, %s, 1, %s, %s, %s, 1)""",
                (title, content, role, grade_id, section_id),
            )


def seed_calendar_events(db):
    today = date.today()
    events = [
        ("Annual Sports Week", "Inter-house athletic meets and sports competitions.", "Sports", today + timedelta(days=5), today + timedelta(days=9), "All"),
        ("Iqbal Day National Holiday", "School closed in observance of Iqbal Day.", "Holiday", today + timedelta(days=14), today + timedelta(days=14), "All"),
        ("Midterm Parent-Teacher Meeting", "Academic progress consultation for Grades 6 through 11.", "Meeting", today + timedelta(days=20), today + timedelta(days=20), "All"),
        ("Final-Term Examination Period", "Comprehensive examinations as per scheduled timetable.", "Exam", today + timedelta(days=35), today + timedelta(days=45), "Student"),
        ("Quaid-e-Azam Day & Winter Vacations", "Winter vacation begins following institutional ceremonies.", "Holiday", today + timedelta(days=58), today + timedelta(days=68), "All"),
    ]
    for title, desc, ev_type, s_date, e_date, aud in events:
        if not db.one("SELECT id FROM school_events WHERE title = %s", (title,)):
            db.run(
                """INSERT INTO school_events
                   (title, description, event_type, start_date, end_date, target_audience, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, 1)""",
                (title, desc, ev_type, s_date, e_date, aud)
            )


def seed_conduct_logs(db):
    first_students = db.all("SELECT id, name FROM students LIMIT 5")
    if not first_students:
        return
    sample_logs = [
        ("Excellence in Science Project", "Developed an outstanding sustainable water recycling model in the science fair.", "Achievement"),
        ("Head Prefect Merit Award", "Awarded special commendation for outstanding leadership, integrity, and class discipline.", "Commendation"),
        ("1st Prize in Debate Competition", "Represented the academy and secured first prize in the Regional English Speech Contest.", "Achievement"),
    ]
    for idx, (title, desc, l_type) in enumerate(sample_logs):
        if idx < len(first_students):
            stu = first_students[idx]
            if not db.one("SELECT id FROM student_conduct_logs WHERE student_id = %s AND title = %s", (stu['id'], title)):
                db.run(
                    """INSERT INTO student_conduct_logs
                       (student_id, recorded_by, log_type, title, description, incident_date)
                       VALUES (%s, 1, %s, %s, %s, CURDATE())""",
                    (stu['id'], l_type, title, desc)
                )


def seed_exam_schedule(db, grade_ids, subjects):
    exams = [
        ("Mathematics", "Mid-Term", date(2026, 11, 10)),
        ("English", "Mid-Term", date(2026, 11, 12)),
        ("Science", "Mid-Term", date(2026, 11, 14)),
        ("Physics", "Mid-Term", date(2026, 11, 10)),
        ("Chemistry", "Mid-Term", date(2026, 11, 12)),
    ]
    for grade_name, grade_id in grade_ids.items():
        for subject_name, exam_type, exam_date in exams:
            subject_id = subjects.get((grade_name, subject_name))
            if not subject_id:
                continue
            if db.one(
                """SELECT id FROM exam_schedule
                   WHERE subject_id = %s AND grade_id = %s AND exam_type = %s AND exam_date = %s""",
                (subject_id, grade_id, exam_type, exam_date),
            ):
                continue
            db.run(
                """INSERT INTO exam_schedule
                   (subject_id, grade_id, exam_type, exam_date, start_time, end_time, room, created_by)
                   VALUES (%s, %s, %s, %s, '09:00:00', '11:00:00', 'Main Hall', 1)""",
                (subject_id, grade_id, exam_type, exam_date),
            )


def seed_homework_and_assignments(db, sections, subjects, assignment_map):
    for (grade_name, section_name), section_id in sections.items():
        for subject_name, title in (
            ("Mathematics", "Chapter Practice Problems"),
            ("English", "Reading Comprehension Worksheet"),
        ):
            subject_id = subjects[(grade_name, subject_name)]
            teacher_id = assignment_map[(section_id, subject_id)]
            if not db.one(
                """SELECT id FROM homework
                   WHERE section_id = %s AND subject_id = %s AND title = %s""",
                (section_id, subject_id, title),
            ):
                db.run(
                    """INSERT INTO homework
                       (title, instructions, subject_id, section_id, teacher_id, due_date, total_marks)
                       VALUES (%s, %s, %s, %s, %s, %s, 20)""",
                    (
                        title,
                        f"Complete the {subject_name} worksheet and submit it in class.",
                        subject_id, section_id, teacher_id,
                        datetime.combine(TODAY + timedelta(days=5), time(23, 59)),
                    ),
                )

        for subject_name, title, days_ahead, total_marks in (
            ("English", "Essay: My Favourite Season", 7, 20),
            ("Mathematics", "Algebra Worksheet", 4, 25),
        ):
            subject_id = subjects[(grade_name, subject_name)]
            teacher_id = assignment_map[(section_id, subject_id)]
            assignment = db.one(
                """SELECT id FROM assignments
                   WHERE teacher_id = %s AND subject_id = %s AND title = %s""",
                (teacher_id, subject_id, title),
            )
            if assignment:
                assignment_id = assignment["id"]
            else:
                assignment_id = db.run(
                    """INSERT INTO assignments
                       (title, instructions, subject_id, teacher_id, due_date, total_marks)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        title,
                        f"Prepare your {subject_name} work neatly and submit before the due date.",
                        subject_id, teacher_id,
                        datetime.combine(TODAY + timedelta(days=days_ahead), time(23, 59)),
                        total_marks,
                    ),
                )
            db.run(
                """INSERT IGNORE INTO assignment_sections (assignment_id, section_id)
                   VALUES (%s, %s)""",
                (assignment_id, section_id),
            )

            students = db.all(
                """SELECT id FROM students
                   WHERE section_id = %s AND status = 'Active'
                   ORDER BY roll_number LIMIT 3""",
                (section_id,),
            )
            for index, student in enumerate(students):
                db.run(
                    """INSERT IGNORE INTO submissions
                       (assignment_id, student_id, text_response, submitted_at, marks_obtained, graded_by, graded_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        assignment_id,
                        student["id"],
                        "Please find my submitted work attached.",
                        datetime.now() - timedelta(days=2),
                        round(total_marks * (0.72 + index * 0.07), 2) if index < 2 else None,
                        1 if index < 2 else None,
                        datetime.now() - timedelta(days=1) if index < 2 else None,
                    ),
                )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    db = Database()
    try:
        print("Normalising demo labels ...")
        normalise_school(db)

        grades = {row["name"]: row["id"] for row in db.all("SELECT id, name FROM grades")}
        required_grades = set(GRADE_SUBJECTS)
        missing_grades = required_grades - set(grades)
        if missing_grades:
            raise RuntimeError(f"Missing grades in database: {sorted(missing_grades)}")

        print("Ensuring sections ...")
        sections = ensure_sections(db, grades)

        print("Ensuring subjects ...")
        subjects = ensure_subjects(db, grades)

        print("Ensuring teachers ...")
        teacher_ids = ensure_teachers(db)

        print("Ensuring students ...")
        ensure_students(db, sections, grades)

        print("Assigning subject teachers ...")
        assignment_map = ensure_assignments(db, sections, subjects, teacher_ids)

        print("Building conflict-free timetable ...")
        timetable_rows = build_timetable(sections, subjects)
        write_timetable(db, timetable_rows, teacher_ids)

        print("Seeding student attendance ...")
        attendance_count = seed_attendance(db, sections, timetable_rows, assignment_map, teacher_ids)

        print("Seeding teacher attendance ...")
        teacher_attendance_count = seed_teacher_attendance(db, teacher_ids)

        print("Seeding results ...")
        results_count = seed_results(db, sections, subjects)

        print("Seeding fees ...")
        fee_count = seed_fees(db, sections)

        print("Seeding announcements, exams, homework and assignments ...")
        seed_announcements(db)
        seed_calendar_events(db)
        seed_conduct_logs(db)
        seed_exam_schedule(db, grades, subjects)
        seed_homework_and_assignments(db, sections, subjects, assignment_map)

        db.commit()

        print("\nDemo data ready.")
        print(f"  Sections       : {len(sections)}")
        print(f"  Subjects       : {len(subjects)}")
        print(f"  Teachers       : {len(teacher_ids)}")
        print(f"  Students       : {len(db.all('SELECT id FROM students WHERE status = %s', ('Active',)))}")
        print(f"  Timetable slots: {len(timetable_rows)}")
        print(f"  Attendance rows: {attendance_count} (attempted)")
        print(f"  Teacher days   : {teacher_attendance_count} (attempted)")
        print(f"  Result rows    : {results_count} (attempted)")
        print(f"  Fee rows       : {fee_count} (attempted)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
