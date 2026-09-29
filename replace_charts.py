import re

# Read the file
with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# --- Replace Attendance Trend Chart ---
old_trend = """<!-- Attendance Trend Tab -->
<div class="tab-content" id="attendanceTrendTab">
    <div class="grid-2">
        <div class="card">
            <div class="card-header">
                <h3>Daily Attendance Trend</h3>
            </div>
            <div class="card-body">
                <div class="chart-container">
                    {% for day in trend_data %}
                    <div class="chart-bar-wrapper">
                        <div class="chart-bar bg-primary" style="height: {{ day.pct }}%;" title="{{ day.date }}: {{ day.pct }}%"></div>
                        <span class="chart-label">{{ day.date }}</span>
                        <span class="chart-value">{{ day.pct }}%</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>"""

new_trend = """<!-- Attendance Trend Tab -->
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
</div>"""

if old_trend in content:
    content = content.replace(old_trend, new_trend)
    print("Replaced attendance trend chart")
else:
    print("ERROR: Attendance trend old string not found!")

# --- Replace Section Comparison Chart ---
old_section = """<!-- Section Comparison Tab -->
<div class="tab-content" id="sectionComparisonTab">
    <div class="card">
        <div class="card-header">
            <h3>Section-wise Attendance Comparison (Last 30 Days)</h3>
        </div>
        <div class="card-body">
            {% if section_comparison %}
            <div class="chart-container">
                {% for sec in section_comparison %}
                <div class="chart-bar-wrapper horizontal">
                    <div class="chart-label">{{ sec.grade_name }} - {{ sec.section_name }}</div>
                    <div class="chart-bar-horizontal bg-success" style="width: {{ sec.avg_percentage }}%;" title="{{ sec.avg_percentage }}%"></div>
                    <span class="chart-value">{{ sec.avg_percentage }}%</span>
                </div>
                {% endfor %}
            </div>
            <div class="table-responsive" style="margin-top: 1.5rem;">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Grade</th>
                            <th>Section</th>
                            <th>Students</th>
                            <th>Total Records</th>
                            <th>Avg Attendance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for sec in section_comparison %}
                        <tr>
                            <td>{{ sec.grade_name }}</td>
                            <td>{{ sec.section_name }}</td>
                            <td>{{ sec.students_tracked }}</td>
                            <td>{{ sec.total_records }}</td>
                            <td><span class="badge badge-{{ 'success' if sec.avg_percentage >= 75 else 'warning' if sec.avg_percentage >= 60 else 'danger' }}">{{ sec.avg_percentage }}%</span></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty-state">
                <i class="fas fa-layer-group"></i>
                <p>No section data available</p>
            </div>
            {% endif %}
        </div>
    </div>
</div>"""

new_section = """<!-- Section Comparison Tab -->
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
</div>"""

if old_section in content:
    content = content.replace(old_section, new_section)
    print("Replaced section comparison chart")
else:
    print("ERROR: Section comparison old string not found!")

# --- Replace Subject Performance Chart ---
old_subject = """<!-- Subject Performance Tab -->
<div class="tab-content" id="subjectPerformanceTab">
    <div class="card">
        <div class="card-header">
            <h3>Subject-wise Performance (Average Marks)</h3>
        </div>
        <div class="card-body">
            {% if subject_performance %}
            <div class="chart-container">
                {% for sub in subject_performance %}
                <div class="chart-bar-wrapper horizontal">
                    <div class="chart-label">{{ sub.subject_name }} ({{ sub.grade_name }})</div>
                    <div class="chart-bar-horizontal bg-info" style="width: {{ sub.avg_percentage }}%;" title="{{ sub.avg_percentage }}%"></div>
                    <span class="chart-value">{{ sub.avg_percentage }}%</span>
                </div>
                {% endfor %}
            </div>
            <div class="table-responsive" style="margin-top: 1.5rem;">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Subject</th>
                            <th>Grade</th>
                            <th>Exams</th>
                            <th>Avg Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for sub in subject_performance %}
                        <tr>
                            <td>{{ sub.subject_name }}</td>
                            <td>{{ sub.grade_name }}</td>
                            <td>{{ sub.exam_count }}</td>
                            <td><span class="badge badge-{{ 'success' if sub.avg_percentage >= 75 else 'warning' if sub.avg_percentage >= 60 else 'danger' }}">{{ sub.avg_percentage }}%</span></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="empty-state">
                <i class="fas fa-book"></i>
                <p>No subject performance data</p>
            </div>
            {% endif %}
        </div>
    </div>
</div>"""

new_subject = """<!-- Subject Performance Tab -->
<div class="tab-content" id="subjectPerformanceTab">
    <div class="card">
        <div class="card-header">
            <h3>Subject Performance (Average Marks)</h3>
        </div>
        <div class="card-body">
            <canvas id="subjectChart" height="120"></canvas>
            <script>
            new Chart(document.getElementById('subjectChart'), {
                type: 'bar',
                data: {
                    labels: {{ subject_perf | map(attribute='subject_name') | list | tojson }},
                    datasets: [{
                        label: 'Average Marks %',
                        data: {{ subject_perf | map(attribute='avg_pct') | list | tojson }},
                        backgroundColor: 'rgba(37,99,235,0.75)',
                        borderRadius: 6
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            min: 0, max: 100,
                            ticks: { callback: v => v + '%' }
                        }
                    }
                }
            });
            </script>
        </div>
    </div>
</div>"""

if old_subject in content:
    content = content.replace(old_subject, new_subject)
    print("Replaced subject performance chart")
else:
    print("ERROR: Subject performance old string not found!")

# Write back
with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done replacing charts in principal dashboard")