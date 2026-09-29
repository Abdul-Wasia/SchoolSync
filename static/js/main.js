// ===== MODAL =====
function showModal(id) {
    var m = document.getElementById(id);
    if (m) m.classList.add('show');
}

function hideModal(id) {
    var m = document.getElementById(id);
    if (m) m.classList.remove('show');
}

// Close modal on overlay click
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('show')) {
        e.target.classList.remove('show');
    }
});

// ===== TABS =====
function showTab(tabId, btn) {
    var parent = btn.closest('.tab-bar') || btn.parentElement;
    parent.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');

    var container = parent.parentElement;
    container.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
    var target = document.getElementById(tabId);
    if (target) target.classList.add('active');
}

// ===== SIDEBAR TOGGLE =====
function toggleSidebar() {
    var sidebar = document.getElementById('sidebar');
    var backdrop = document.getElementById('sidebarBackdrop');
    var isMobile = window.innerWidth <= 768;
    if (isMobile) {
        sidebar.classList.toggle('mobile-open');
        if (backdrop) backdrop.classList.toggle('show');
    } else {
        sidebar.classList.toggle('collapsed');
        document.body.classList.toggle('sidebar-collapsed');
        localStorage.setItem('sidebarCollapsed',
            sidebar.classList.contains('collapsed'));
    }
}

// Restore sidebar state on page load
document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
        var sidebar = document.getElementById('sidebar');
        if (sidebar) {
            sidebar.classList.add('collapsed');
            document.body.classList.add('sidebar-collapsed');
        }
    }
});

// ===== USER DROPDOWN =====
function toggleUserMenu() {
    var dd = document.getElementById('userDropdown');
    dd.classList.toggle('open');
}

// ===== GLOBAL USER MENU (Logo Dropdown) =====
function toggleGlobalUserMenu() {
    var menu = document.getElementById('globalUserMenu');
    if (menu) menu.classList.toggle('open');
}

// ── DARK MODE — Complete Working Implementation ─────────────

function initDarkMode() {
  var saved = localStorage.getItem('schoolsync_theme');
  if (!saved) saved = 'light';
  applyTheme(saved);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);

  var btn = document.getElementById('darkModeBtn');
  var icon = document.getElementById('darkModeIcon');

  if (icon) {
    if (theme === 'dark') {
      icon.className = 'fas fa-sun';
      icon.style.color = '#FCD34D';
    } else {
      icon.className = 'fas fa-moon';
      icon.style.color = '#F1F5F9';
    }
  }

  localStorage.setItem('schoolsync_theme', theme);
}

function toggleDarkMode() {
  var current = document.documentElement.getAttribute('data-theme') || 'light';
  var next = (current === 'dark') ? 'light' : 'dark';
  applyTheme(next);
}

document.addEventListener('DOMContentLoaded', function() {
  initDarkMode();
});

// Close user menus on outside click
document.addEventListener('click', function(e) {
    // Close avatar dropdown
    if (!e.target.closest('.nav-user-menu')) {
        var dd = document.getElementById('userDropdown');
        if (dd) dd.classList.remove('open');
    }
    // Close global logo menu
    if (!e.target.closest('.logo-dropdown-container')) {
        var menu = document.getElementById('globalUserMenu');
        if (menu) menu.classList.remove('open');
    }
});

// ===== CLOSE MODALS ON BACKDROP CLICK =====
document.addEventListener('click', function(e) {
    // Close modal overlay on backdrop click
    if (e.target.classList.contains('modal-overlay') && e.target.classList.contains('show')) {
        e.target.classList.remove('show');
    }
});

// ===== NOTIFICATIONS =====
function toggleNotifications() {
    var dd = document.getElementById('notificationMenu');
    if (dd) {
        dd.classList.toggle('show');
        if (dd.classList.contains('show')) loadNotifications();
    }
}

function loadNotifications() {
    fetch('/notifications')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('notification-list');
            var badge = document.getElementById('notif-badge');
            if (!list) return;

            if (!data || data.length === 0) {
                list.innerHTML = '<div class="notification-empty"><i class="fas fa-bell-slash"></i><p>No notifications</p></div>';
                if (badge) badge.style.display = 'none';
                return;
            }

            var unread = data.filter(function(n) { return !n.is_read; });
            if (badge) {
                badge.textContent = unread.length;
                badge.style.display = unread.length > 0 ? 'flex' : 'none';
            }

            list.innerHTML = data.slice(0, 10).map(function(n) {
                return '<div class="notification-item ' + (!n.is_read ? 'unread' : '') + '" onclick="readNotif(' + n.id + ', \'' + (n.link || '#') + '\')">' +
                    '<div class="notif-icon"><i class="fas fa-' + (n.type === 'warning' ? 'exclamation' : n.type === 'success' ? 'check' : 'info') + '"></i></div>' +
                    '<div class="notif-content">' +
                    '<div class="notif-message">' + n.message + '</div>' +
                    '<div class="notif-time">' + timeAgo(n.created_at) + '</div>' +
                    '</div></div>';
            }).join('');
        })
        .catch(function() {});
}

function readNotif(id, link) {
    fetch('/notifications/read/' + id, { method: 'POST' })
        .then(function() {
            if (link && link !== '#') window.location.href = link;
            else loadNotifications();
        });
}

function markAllRead() {
    fetch('/notifications/read-all', { method: 'POST' })
        .then(function() { loadNotifications(); });
}

// Close notification dropdown on outside click
document.addEventListener('click', function(e) {
    var nw = document.getElementById('notificationDropdown');
    var dd = document.getElementById('notificationMenu');
    if (nw && dd && !nw.contains(e.target)) {
        dd.classList.remove('show');
    }
});

// ===== ALERTS AUTO-DISMISS =====
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.alert-dismissible').forEach(function(a) {
        setTimeout(function() {
            a.style.transition = 'opacity 0.3s, transform 0.3s';
            a.style.opacity = '0';
            a.style.transform = 'translateY(-10px)';
            setTimeout(function() { a.remove(); }, 300);
        }, 5000);
    });
});

// ===== ANIMATE NUMBERS =====
function animateNumber(el, target) {
    var start = 0;
    var duration = 800;
    var startTime = null;

    function step(timestamp) {
        if (!startTime) startTime = timestamp;
        var progress = Math.min((timestamp - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.floor(eased * target);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-count]').forEach(function(el) {
        animateNumber(el, parseInt(el.getAttribute('data-count')) || 0);
    });
});

// ===== CASCADING DROPDOWNS (FETCH-BASED) =====
function cascadeSections(gradeId, targetSel) {
    if (!targetSel) return;
    targetSel.innerHTML = '<option value="">Loading Sections...</option>';
    if (!gradeId) {
        targetSel.innerHTML = '<option value="">Select Section</option>';
        return;
    }
    fetch('/api/sections/' + gradeId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            targetSel.innerHTML = '<option value="">Select Section</option>';
            data.forEach(function(s) {
                var opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = s.name;
                targetSel.appendChild(opt);
            });
        })
        .catch(function() {
            targetSel.innerHTML = '<option value="">Error loading</option>';
        });
}

function cascadeSubjects(gradeId, targetSel) {
    if (!targetSel) return;
    targetSel.innerHTML = '<option value="">Loading Subjects...</option>';
    if (!gradeId) {
        targetSel.innerHTML = '<option value="">Select Subject</option>';
        return;
    }
    fetch('/api/subjects/' + gradeId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            targetSel.innerHTML = '<option value="">Select Subject</option>';
            data.forEach(function(s) {
                var opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = s.subject_name;
                targetSel.appendChild(opt);
            });
        })
        .catch(function() {
            targetSel.innerHTML = '<option value="">Error loading</option>';
        });
}

function cascadeSectionsAndSubjects(gradeId) {
    var sectionSel = document.querySelector('select[name="section_id"]') || document.getElementById('section_id');
    var subjectSel = document.querySelector('select[name="subject_id"]') || document.getElementById('subject_id');
    cascadeSections(gradeId, sectionSel);
    if (subjectSel) {
        cascadeSubjects(gradeId, subjectSel);
    }
}

function cascadeByGrade(gradeId, sectionSelId, subjectSelId) {
    var sectionSel = document.getElementById(sectionSelId);
    var subjectSel = document.getElementById(subjectSelId);
    if (sectionSel) cascadeSections(gradeId, sectionSel);
    if (subjectSel) cascadeSubjects(gradeId, subjectSel);
}

// Legacy filter fallback
function filterSections(gradeId) {
    var sectionSel = document.querySelector('select[name="section_id"]') || document.getElementById('section_id');
    if (!sectionSel) return;
    var options = sectionSel.querySelectorAll('option[data-grade]');
    if (options.length > 0) {
        sectionSel.value = '';
        options.forEach(function(o) {
            o.style.display = (!gradeId || o.getAttribute('data-grade') === gradeId) ? '' : 'none';
        });
    } else {
        cascadeSections(gradeId, sectionSel);
    }
}

function filterSubjects(sectionId) {
    var subjectSel = document.querySelector('select[name="subject_id"]') || document.getElementById('subject_id');
    if (!subjectSel) return;
    var options = subjectSel.querySelectorAll('option[data-section]');
    if (options.length > 0) {
        subjectSel.value = '';
        options.forEach(function(o) {
            o.style.display = (!sectionId || o.getAttribute('data-section') === sectionId) ? '' : 'none';
        });
    }
}

function filterAndSubmit() {
    var gradeSel = document.querySelector('select[name="grade_id"]');
    if (gradeSel) filterSections(gradeSel.value);
}

// ===== ATTENDANCE =====
function updateAttCounts() {
    var p = 0, a = 0, l = 0, lv = 0;
    // Count from checked radio buttons (new system)
    document.querySelectorAll('input[name^="status_"]:checked').forEach(function(inp) {
        var v = inp.value;
        if (v === 'Present') p++;
        else if (v === 'Absent') a++;
        else if (v === 'Late') l++;
        else if (v === 'Leave') lv++;
    });
    // Also count from hidden inputs (legacy)
    document.querySelectorAll('input[name^="status_"][type="hidden"]').forEach(function(inp) {
        if (inp.value === 'Present') p++;
        else if (inp.value === 'Absent') a++;
        else if (inp.value === 'Late') l++;
        else if (inp.value === 'Leave') lv++;
    });
    var ep = document.getElementById('count-present') || document.getElementById('countPresent') || document.getElementById('presentCount');
    var ea = document.getElementById('count-absent') || document.getElementById('countAbsent') || document.getElementById('absentCount');
    var el2 = document.getElementById('count-late') || document.getElementById('countLate') || document.getElementById('lateCount');
    var elv = document.getElementById('count-leave') || document.getElementById('countLeave');
    if (ep) ep.textContent = p;
    if (ea) ea.textContent = a;
    if (el2) el2.textContent = l;
    if (elv) elv.textContent = lv;
}

function rowColor(id, status) {
    var row = document.getElementById('row-' + id);
    if (!row) return;
    row.className = 'row-' + status.toLowerCase();
}

function markAllStatus(status) {
    document.querySelectorAll('.attendance-radio').forEach(function(group) {
        var radio = group.querySelector('input[value="' + status + '"]');
        if (radio) {
            radio.checked = true;
            var row = radio.closest('tr');
            if (row) row.className = 'row-' + status.toLowerCase();
        }
    });
    updateAttCounts();
}

// ===== CONFIRM DELETE =====
function confirmDelete(msg) {
    return confirm(msg || 'Are you sure you want to delete this?');
}

// ===== COPY TEXT =====
function copyText(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
    }
}

// ===== TOAST =====
function showToast(msg, type) {
    type = type || 'info';
    var c = document.querySelector('.toast-container');
    if (!c) {
        c = document.createElement('div');
        c.className = 'toast-container';
        document.body.appendChild(c);
    }
    var t = document.createElement('div');
    t.className = 'toast ' + type;
    t.innerHTML = '<i class="fas fa-' + (type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle') + '"></i> ' + msg;
    c.appendChild(t);
    setTimeout(function() {
        t.style.opacity = '0';
        t.style.transform = 'translateX(40px)';
        setTimeout(function() { t.remove(); }, 300);
    }, 3000);
}

// ===== SUBJECT COLOR =====
function subjectColor(name) {
    if (!name) return 'linear-gradient(135deg, #6B7280, #9CA3AF)';
    var n = name.toLowerCase();
    if (n.includes('math')) return 'linear-gradient(135deg, #2563EB, #3B82F6)';
    if (n.includes('computer') || n.includes('cs') || n.includes('it')) return 'linear-gradient(135deg, #16A34A, #22C55E)';
    if (n.includes('english')) return 'linear-gradient(135deg, #7C3AED, #8B5CF6)';
    if (n.includes('physics')) return 'linear-gradient(135deg, #EA580C, #F97316)';
    if (n.includes('chemistry')) return 'linear-gradient(135deg, #0891B2, #06B6D4)';
    if (n.includes('biology') || n.includes('science')) return 'linear-gradient(135deg, #059669, #10B981)';
    if (n.includes('urdu')) return 'linear-gradient(135deg, #DB2777, #EC4899)';
    if (n.includes('history')) return 'linear-gradient(135deg, #B45309, #D97706)';
    if (n.includes('geography')) return 'linear-gradient(135deg, #0D9488, #14B8A6)';
    return 'linear-gradient(135deg, #6B7280, #9CA3AF)';
}

// ===== TIME AGO =====
function timeAgo(timestamp) {
    var diff = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(timestamp).toLocaleDateString();
}

// ===== SET TODAY'S DATE =====
document.addEventListener('DOMContentLoaded', function() {
    var today = new Date().toISOString().split('T')[0];
    document.querySelectorAll('input[type="date"]:not([value])').forEach(function(inp) {
        if (!inp.value) inp.value = today;
    });
});

// ===== FILTER MODAL SECTIONS =====
function filterModalSections(gradeId) {
    var sel = document.getElementById('modal-section-id') || document.getElementById('modal_section_id');
    if (!sel) return;
    var options = sel.querySelectorAll('option[data-grade]');
    sel.value = '';
    options.forEach(function(o) {
        o.style.display = (!gradeId || o.getAttribute('data-grade') === gradeId) ? '' : 'none';
    });
}

// ===== INIT ATTENDANCE COUNTS =====
document.addEventListener('DOMContentLoaded', function() {
    updateAttCounts();
    document.querySelectorAll('.attendance-radio input').forEach(function(r) {
        r.addEventListener('change', function() {
            updateAttCounts();
            var row = r.closest('tr');
            if (row) row.className = 'row-' + r.value.toLowerCase();
        });
    });
});

// ===== AUTO-LOAD NOTIFICATIONS ON PAGE LOAD =====
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('notification-list')) {
        loadNotifications();
        setInterval(loadNotifications, 60000);
    }
});
