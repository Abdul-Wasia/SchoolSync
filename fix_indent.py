with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'r') as f:
    lines = f.readlines()

# Replace lines 263-266 (1-indexed) = indices 262-265
lines[262] = "        flash('Assignment created successfully.', 'success'),\n"
lines[263] = "        log_activity(session['user_id'], 'CREATE_ASSIGNMENT', f'Created assignment: {title}'),\n"
lines[264] = "    else:\n"
lines[265] = "        flash('Failed to create assignment.', 'danger')\n"

with open('D:\\Project\\SchoolSync\\routes\\teacher_routes.py', 'w') as f:
    f.writelines(lines)

print("Fixed indentation")