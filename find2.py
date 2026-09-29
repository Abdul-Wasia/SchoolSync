with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r') as f:
    content = f.read()

idx = content.find('id="subjectPerformanceTab"')
print('Found at index:', idx)
if idx >= 0:
    print('Context:', content[idx:idx+100])