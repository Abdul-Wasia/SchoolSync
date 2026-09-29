with open('D:\\Project\\SchoolSync\\templates\\student\\attendance.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add heatmap CSS and JS after the detailed records section, before the closing {% endblock %}
# The detailed records section ends with {% endif %} on line 97

# Heatmap CSS (add to the existing styles or create a block)
heatmap_css = '''.heatmap-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; margin-top: 12px; }
.heatmap-day { width: 28px; height: 28px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 600; cursor: default; transition: transform 0.1s; }
.heatmap-day:hover { transform: scale(1.2); }
.heatmap-present { background: #16A34A; color: white; }
.heatmap-absent { background: #DC2626; color: white; }
.heatmap-late { background: #D97706; color: white; }
.heatmap-leave { background: #2563EB; color: white; }
.heatmap-empty { background: #F1F5F9; color: #CBD5E1; }
.heatmap-header { font-size: 10px; font-weight: 600; color: #64748B; text-align: center; }'''

# JavaScript for building the heatmap
heatmap_js = '''function buildHeatmap(records, subjects) {
    // For each subject, build a 3-month heatmap
    const months = ['Current', 'Previous', 'Last'];
    const now = new Date();
    
    subjects.forEach((subject, sIdx) => {
        const subjectRecords = records.filter(r => r.subject_id === subject.id);
        const heatmapData = {};
        
        // Build 3 months of data (backwards from current month)
        for (let i = 0; i < 3; i++) {
            const m = new Date(now);
            m.setMonth(now.getMonth() - i);
            const monthKey = m.toLocaleString('default', { month: 'name' });
            heatmapData[monthKey] = { present: 0, absent: 0, late: 0, leave: 0 };
        }
        
        // Count attendance by status for each month
        subjectRecords.forEach(r => {
            const rDate = new Date(r.date);
            const mKey = rDate.toLocaleString('default', { month: 'name' });
            if (heatmapData[mKey]) {
                const status = r.status.toLowerCase();
                if (status === 'present') heatmapData[mKey].present++;
                else if (status === 'absent') heatmapData[mKey].absent++;
                else if (status === 'late') heatmapData[mKey].late++;
                else if (status === 'leave') heatmapData[mKey].leave++;
            }
        });
        
        // Generate HTML for this subject's heatmap
        const heatmapHtml = `
            <div class="subject-heatmap" style="margin-top: 1rem;">
                <div class="heatmap-header">{{ subject.subject_name }}</div>
                <div class="heatmap-grid">
                    <div class="heatmap-header">Present</div>
                    <div class="heatmap-header">Absent</div>
                    <div class="heatmap-header">Late</div>
                    <div class="heatmap-header">Leave</div>
                    {% for monthKey in ['Current', 'Previous', 'Last'] %}
                    <div class="heatmap-header">{{ monthKey }}</div>
                    {% endfor %}
                    {% for mKey in Object.keys(heatmapData) %}
                    <div class="heatmap-row">
                        <span class="heatmap-present">{{ heatmapData[mKey].present }}</span>
                        <span class="heatmap-absent">{{ heatmapData[mKey].absent }}</span>
                        <span class="heatmap-late">{{ heatmapData[mKey].late }}</span>
                        <span class="heatmap-leave">{{ heatmapData[mKey].leave }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        `;
        
        document.querySelector('.subject-cards').insertAdjacentHTML('afterend', heatmapHtml);
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    const records = {{ detailed_records | list | tojson | safe }} || [];
    const subjects = {{ subjects | map(attribute='subject_name') | list | tojson | safe }} || [];
    buildHeatmap(records, subjects);
});
</script>'''

# Find the place to insert - after the detailed records table and before the closing
# The attendance.html ends with {% endblock %}, let me insert the heatmap JS there

# Actually, let me add the CSS and JS. First, let me find a good insertion point.
# I'll add the CSS in a style block or after the existing styles, and the JS before endblock.

# Let me search for the endblock
idx = content.find('{% endblock %}')
if idx >= 0:
    # Add heatmap JS before endblock
    content = content[:idx] + heatmap_js + '\n\n' + content[idx:]
    print("Added heatmap JS to student attendance")
    
    # Also add the CSS - let me find a good place, maybe after the .attendance-status-row styles
    # Or just add it as a style block after the extends
    # Let me add it after the closing </style> if any, or just before </head> - but we don't have that info
    # For now, just note that CSS needs to be added to style.css
    print("Note: Add heatmap CSS to static/css/style.css")
else:
    print("Could not find endblock, trying alternative...")
    # Append at the very end before the template closes
    idx2 = content.rfind('{% endblock %}')
    if idx2 >= 0:
        content = content[:idx2] + heatmap_js + '\n\n' + content[idx2:]
        print("Added heatmap JS alt method")