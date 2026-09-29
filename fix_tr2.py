#!/usr/bin/env python3
import re

with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Replace 'except Exception as e:' with 'except Exception:' and remove e usage
# Actually, let me just add _ as the exception variable name
content = content.replace('except Exception as e:', 'except Exception:')

# Fix 2: Fix the course_info reference in the notification message
# Need to get course info from the assignment/subject/section
old_notif = """# Notify all students in section about new material
    students = query(
        "SELECT user_id FROM students WHERE section_id = %s AND status = 'Active'
        (section_id,),
        fetch=True
    )
    for student in students:
        query(
            "INSERT INTO notifications (user_id, message, type, link) VALUES (%s
            (student['user_id'], f'New material uploaded in {course_info.subject'
        )"""

new_notif = """# Notify all students in section about new material
    students = query(
        "SELECT user_id FROM students WHERE section_id = %s AND status = 'Active'
        (section_id,),
        fetch=True
    )
    for student in students:
        query(
            "INSERT INTO notifications (user_id, message, type, link) VALUES (%s
            (student['user_id'], f'New material uploaded in {subject_name}: {title}', 'info', url_for('teacher.course', subject_id=subject_id, section_id=section_id))
        )"""

if old_notif in content:
    content = content.replace(old_notif, new_notif)
    print("Fixed course_info reference")
else:
    print("Could not find old_notif pattern, trying alternative...")
    # Try simpler fix - just find and replace the course_info line
    if 'course_info.subject' in content:
        # Replace the specific line
        content = content.replace('f\'New material uploaded in {course_info.subject', 
                                  f\"'New material uploaded in {subject_name}\")
        print("Fixed course_info reference (alt)")
    else:
        print("Could not find course_info.subject in content")

# Write back
with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed teacher_routes.py issues")