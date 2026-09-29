with open('D:\\Project\\SchoolSync\\templates\\student\\dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add the donut chart after the quick actions section, before the closing {% endblock %}
# Find the quick actions div and add chart after it

chart_js = '''<!-- Attendance Donut Chart -->
<div class="card" style="margin-top: 1.5rem;">
    <div class="card-header">
        <h3><i class="fas fa-user-check"></i> My Attendance</h3>
    </div>
    <div class="card-body text-center">
        <canvas id="myAttChart" width="160" height="160"></canvas>
    </div>
</div>

<script>
new Chart(document.getElementById('myAttChart'), {
    type: 'doughnut',
    data: {
        labels: ['Present', 'Absent', 'Late', 'Leave'],
        datasets: [{
            data: [{{ attendance_stats.present or 0 }}, {{ attendance_stats.absent or 0 }}, {{ attendance_stats.late or 0 }}, {{ attendance_stats.leave or 0 }}],
            backgroundColor: ['#16A34A','#DC2626','#D97706','#2563EB'],
            borderWidth: 0,
            hoverOffset: 6
        }]
    },
    options: {
        cutout: '72%',
        plugins: {
            legend: {
                position: 'bottom',
                labels: { padding: 12, font: { size: 11 } }
            }
        }
    }
});
</script>'''

# Find the quick actions div and insert the chart after it
# The quick actions div ends with </div> on line 135ish
# Let me find where to insert

# Insert before the closing {% endblock %}
# Actually, let me find the card with Quick Actions and insert after it

# The quick actions card ends at line 136 with </div>
# Let me find the pattern
idx = content.find('<!-- Quick Actions -->')
if idx >= 0:
    # Find the closing </div> of the action-grid
    # Insert the chart before the closing of the main content block
    # Actually, let me just append before the endblock
    end_idx = content.find('{% endblock %}')
    if end_idx >= 0:
        content = content[:end_idx] + chart_js + '\n\n' + content[end_idx:]
        print("Added donut chart to student dashboard")
    else:
        print("Could not find endblock")
else:
    print("Could not find quick actions marker")
    # Just append at the end before endblock
    end_idx = content.find('{% endblock %}')
    if end_idx >= 0:
        content = content[:end_idx] + chart_js + '\n\n' + content[end_idx:]
        print("Added donut chart to student dashboard (alt method)")