#!/usr/bin/env python3
import os

# Read the original file
with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# --- Replace the entire content block with Chart.js charts ---

# Chart 1: Attendance Trend (Line Chart) - replaces the trend_data manual bars
chart1 = '''<!-- Attendance Trend Tab -->
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

# Chart 2: Section Comparison (Bar Chart) - replaces the section_comparison manual bars
chart2 = '''<!-- Section Comparison Tab -->
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

# Chart 3: Subject Performance (Horizontal Bar) - replaces the subject_performance manual bars
chart3 = '''<!-- Subject Performance Tab -->
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
</div>'''

# Replace each section
print("Replacing Chart 1: Attendance Trend...")
content = content.replace(
    '''<!-- Attendance Trend Tab -->''',
    chart1,
    count=1
)

print("Replacing Chart 2: Section Comparison...")
content = content.replace(
    '''<!-- Section Comparison Tab -->''',
    chart2,
    count=1
)

print("Replacing Chart 3: Subject Performance...")
content = content.replace(
    '''<!-- Subject Performance Tab -->''',
    chart3,
    count=1
)

# Write back
with open('D:\\Project\\SchoolSync\\templates\\principal\\dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done! All Chart.js charts replaced in principal dashboard.")