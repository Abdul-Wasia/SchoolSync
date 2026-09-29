with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the section comparison tab section (it should be after the attendance trend)
# Look for the tab content with id="sectionComparisonTab"
# It should be after the attendance trend tab section

# Let's find the exact line numbers
content = ''.join(lines)
idx = content.find('<!-- Section Comparison Tab -->')
if idx >= 0:
    # Find the line number
    line_num = content[:idx].count('\n') + 1
    print(f"Section comparison found at line {line_num}")
    
    # Now find where this section ends (next tab or end of block)
    # We'll replace from the comment to the end of the tab-content div
    # Find the closing </div> for tab-content
    sub = content[idx:]
    # Find the closing pattern
    end_marker = '</div>\n    {% endblock %}'
    end_idx = sub.find(end_marker)
    if end_idx >= 0:
        # Get the section to replace
        section_text = sub[:end_idx + len(end_marker)]
        # Determine replacement
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
        
        # Replace
        new_lines = lines[:idx//len('\n')+1]  # This approach is getting complicated
        print("Complex replacement needed")
    else:
        print("Could not find end marker")
else:
    print("Section comparison not found, checking differently...")
    
# Let's just search for and replace by content pattern
print("Total lines:", len(lines))
for i, line in enumerate(lines):
    if 'Section Comparison' in line or 'section_comparison' in line:
        print(f"Line {i+1}: {line.rstrip()[:80]}")