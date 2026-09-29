with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Section comparison starts at line 253 (1-indexed) = index 252
# It ends before the next tab or endblock. Let's find the actual end.
# From the debug, line 253 is the comment, and the section goes till around line 270.

# Let's just replace from line 253 to line 270 (approx) with the Chart.js version
# The new content should replace lines 253-270

new_section = '''<!-- Section Comparison Tab -->
<div class="tab-content" id="sectionComparisonTab">
    <div class="card">
        <div class="card-header">
            <h3>Section Comparison (Last 30 Days)</h3>
        </div>
        <div class="card-body">
            <canvas id="sectionChart" height="120"></canvas>
            <script>
            const sectionLabels = {{ sections_data | map(attribute='section_name') | list | tojson }};
            const sectionData   = {{ sections_data | map(attribute='avg_att') | list | tojson }};
            new Chart(document.getElementById('sectionChart'), {
                type: 'bar',
                data: {
                    labels: sectionLabels,
                    datasets: [{
                        label: 'Avg Attendance %',
                        data: sectionData,
                        backgroundColor: sectionData.map(v => v >= 75 ? 'rgba(22,163,74,0.8)' : v >= 60 ? 'rgba(217,119,6,0.8)' : 'rgba(220,38,38,0.8)',
                        borderRadius: 8,
                        borderSkipped: false
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: ctx => ctx.parsed.y + '%'
                            }
                        }
                    },
                    scales: {
                        y: {
                            min: 0, max: 100,
                            ticks: { callback: v => v + '%' },
                            grid: { color: 'rgba(0,0,0,0.05)' }
                        },
                        x: {
                            grid: { display: false }
                        }
                    }
                }
            });
            </script>
        </div>
    </div>
</div>'''

# Replace lines 253-270 (0-indexed 252-269) approximately
# Let's find the exact replacement range
# The section starts at line 253, we need to find where it ends
# It ends before the next tab content or the low attendance tab

# Let me just replace from line 253 onwards until we hit the next major section
# We'll find the "Low Attendance Tab" comment
content_all = ''.join(lines)
low_att_idx = content_all.find('<!-- Low Attendance Tab -->')
if low_att_idx >= 0:
    # Replace from line 253 to just before Low Attendance Tab
    # Get the lines section
    section_lines = lines[252:low_att_idx//4]  # rough calculation
    # Actually, let's just build the new lines list directly
    
    # Find the actual line number for low attendance
    actual_low_line = None
    for i, line in enumerate(lines):
        if 'Low Attendance Tab' in line:
            actual_low_line = i
            break
    
    if actual_low_line:
        # Replace lines 252 to actual_low_line - 1
        new_lines = lines[:252] + [new_section] + lines[actual_low_line:]
        
        with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("Replaced section comparison chart")
    else:
        print("Could not find low attendance tab")
else:
    print("Low attendance tab not found either")