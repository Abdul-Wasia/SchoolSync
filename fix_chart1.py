with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Replace lines 155-172 (indices 154-171) with new content keeping line 173 onwards
new_section = '''<!-- Attendance Trend Tab -->
<div class="tab-content" id="attendanceTrendTab">
    <div class="card">
        <div class="card-header">
            <h3>Daily Attendance Trend (Last 30 Days)</h3>
        </div>
        <div class="card-body">
            <canvas id="attendanceTrendChart" height="120"></canvas>
            <script>
            new Chart(document.getElementById('attendanceTrendChart'), {
                type: 'line',
                data: {
                    labels: {{ trend | map(attribute='date') | list | tojson }},
                    datasets: [{
                        label: 'Attendance %',
                        data: {{ trend | map(attribute='pct') | list | tojson }},
                        borderColor: '#2563EB',
                        backgroundColor: 'rgba(37,99,235,0.1)',
                        borderWidth: 2.5,
                        pointBackgroundColor: '#2563EB',
                        pointRadius: 4,
                        fill: true,
                        tension: 0.4
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

# Replace lines 155-172 (0-indexed 154-171) with new content
# Keep line 173 onwards (index 172)
new_lines = lines[:154] + [new_section] + lines[172:]

with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Replaced attendance trend chart section")