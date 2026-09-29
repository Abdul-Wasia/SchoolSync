with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines, 1):
    if 'subjectPerformance' in line.lower() or 'Subject Performance' in line:
        print(f'Line {i}: {line.rstrip()[:80]}')
    if 'id="subjectPerformanceTab"' in line:
        print(f'Tab content starts at line {i}: {line.rstrip()[:80]}')