with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'r') as f:
    content = f.read()

# Fix 1: Replace 'except Exception as e:' with 'except Exception:'
content = content.replace('except Exception as e:', 'except Exception:')

# Fix 2: Fix the course_info.subject reference
# Find and replace the specific pattern
old_pattern = "f'New material uploaded in {course_info.subject"
new_pattern = "'New material uploaded in subject_name"
content = content.replace(old_pattern, new_pattern)

with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'w') as f:
    f.write(content)

print('Done fixing')