/* =====================================================================
   Better PESU Acad — Primary Application Script
   Full implementation of the Study Space with PDF Viewer & Pomodoro Timer,
   Course Materials Tree, Fullscreen Focus Mode, and Academic Companion Hubs.
   ===================================================================== */

const $ = id => document.getElementById(id);
const nav = $('navigation');

let selectedFile = null;
let courses = {};
let totalFiles = 0;
let currentDoc = null;
let catalog = new Map();
let activeLibraryTab = 'library';
let activeModule = 'study';

// Helper to create buttons
const createButton = (className, label, handler) => {
  const button = document.createElement('button');
  button.className = className;
  button.textContent = label;
  button.addEventListener('click', handler);
  return button;
};

const fileURL = path => '/files/' + path.replace(/^slides[\\/]/i, '').split(/[\\/]/).map(encodeURIComponent).join('/');

// =========================================================
// 1. PRIMARY STUDY WORKSPACE & PDF VIEWER
// =========================================================

function openFile(file, title, breadcrumb, button) {
  if (!file.path || !String(file.name || file.path).toLowerCase().endsWith('.pdf')) return;
  selectedFile?.classList.remove('selected');
  selectedFile = button;
  button?.classList.add('selected');

  currentDoc = file.path;
  const url = fileURL(file.path);

  const viewer = $('pdf-viewer');
  viewer.src = url;
  viewer.classList.remove('hidden');
  $('study-fullscreen').classList.remove('hidden');
  $('viewer-placeholder').classList.add('hidden');
  $('document-title').textContent = title;
  $('document-path').textContent = breadcrumb;

  $('open-link').href = url;
  $('download-link').href = url;
  $('open-link').classList.remove('hidden');
  $('download-link').classList.remove('hidden');
  $('file-count').textContent = 'PDF ready to study';

  updateBookmarkButton();
  recordRecentFile(file.path, title, breadcrumb);
}

function renderNavigation(query = '') {
  nav.replaceChildren();
  let matched = 0;
  const filter = query.trim().toLowerCase();

  for (const [semesterName, subjects] of Object.entries(courses)) {
    const semGroup = document.createElement('div');
    semGroup.className = 'nav-group';
    const semBody = document.createElement('div');
    const semButton = createButton('nav-sem', '⌄  ' + semesterName, () => {
      semBody.hidden = !semBody.hidden;
    });
    semGroup.append(semButton, semBody);
    let semHasMatch = false;

    for (const [subjectName, subject] of Object.entries(subjects || {})) {
      const subjectGroup = document.createElement('div');
      const subjectBody = document.createElement('div');
      const subjectButton = createButton('nav-sub', '◈  ' + (subject.title || subjectName), () => {
        subjectBody.hidden = !subjectBody.hidden;
      });

      const subjectSync = createButton('nav-sub-sync', '↻ Sync', async () => {
        subjectSync.disabled = true;
        $('sync-status').textContent = `Starting ${subject.title || subjectName} sync…`;
        try {
          const response = await fetch('/api/sync/subject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ semester: semesterName, subject_id: String(subject.id) })
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Could not sync subject');
          lastSyncRunning = true;
          startSyncPolling();
          await updateSyncStatus();
        } catch (error) {
          $('sync-status').textContent = error.message;
        } finally {
          subjectSync.disabled = false;
        }
      });
      subjectSync.title = `Sync ${subject.title || subjectName} only`;

      const subjectHeader = document.createElement('div');
      subjectHeader.className = 'nav-sub-header';
      subjectHeader.append(subjectButton, subjectSync);
      subjectGroup.append(subjectHeader, subjectBody);
      let subjectHasMatch = false;

      for (const [unitName, classes] of Object.entries(subject.units || {})) {
        const unitGroup = document.createElement('div');
        const unitBody = document.createElement('div');
        const unitButton = createButton('nav-unit', '•  ' + unitName, () => {
          unitBody.hidden = !unitBody.hidden;
        });
        unitGroup.append(unitButton, unitBody);
        let unitHasMatch = false;

        for (const lecture of classes || []) {
          for (const file of lecture.files || []) {
            if (String(file.type || '').toLowerCase() !== 'pdf' && !String(file.name || '').toLowerCase().endsWith('.pdf')) continue;
            const haystack = [semesterName, subjectName, subject.title, unitName, lecture.title, file.name].join(' ').toLowerCase();
            if (filter && !haystack.includes(filter)) continue;

            matched++;
            unitHasMatch = true;
            const button = createButton('nav-file', file.name || lecture.title || 'Lecture PDF', () => {
              openFile(file, file.name || lecture.title, `${semesterName} / ${subject.title || subjectName} / ${unitName}`, button);
            });
            unitBody.append(button);
          }
        }

        if (unitHasMatch) {
          subjectHasMatch = true;
          subjectBody.append(unitGroup);
          if (!filter) unitBody.hidden = true;
        }
      }

      if (subjectHasMatch) {
        semHasMatch = true;
        semBody.append(subjectGroup);
        if (!filter) subjectBody.hidden = true;
      }
    }

    if (semHasMatch) {
      nav.append(semGroup);
      if (!filter) semBody.hidden = true;
    }
  }

  if (!matched) {
    const msg = document.createElement('div');
    msg.className = 'empty';
    msg.textContent = filter ? 'No matching PDF files found.' : 'No PDF files found. Check your courses.json and slides folder.';
    nav.append(msg);
  }

  if (!filter) totalFiles = matched;
  $('file-count').textContent = `${totalFiles} lecture PDFs in your library`;
}

$('search')?.addEventListener('input', event => renderNavigation(event.target.value));

// Fullscreen Focus View
const studyWorkspace = document.querySelector('.workspace');
const studyFullscreenButton = $('study-fullscreen');

function updateStudyFullscreenUI() {
  const active = document.fullscreenElement === studyWorkspace;
  studyWorkspace.classList.toggle('study-fullscreen', active);
  studyFullscreenButton.textContent = active ? '⤢ Exit Focus' : '⛶ Focus View';
}

studyFullscreenButton?.addEventListener('click', async () => {
  try {
    if (document.fullscreenElement === studyWorkspace) {
      await document.exitFullscreen();
    } else if (!document.fullscreenElement && !$('pdf-viewer').classList.contains('hidden')) {
      await studyWorkspace.requestFullscreen();
    }
  } catch (error) {
    console.error('Fullscreen toggle error:', error);
  }
});

$('study-exit')?.addEventListener('click', async () => {
  if (document.fullscreenElement === studyWorkspace) await document.exitFullscreen();
});

document.addEventListener('fullscreenchange', updateStudyFullscreenUI);

// =========================================================
// 2. POMODORO TIMER (ORIGINAL ACCURATE WALL-CLOCK LOGIC)
// =========================================================

const presets = { focus: 25, short: 5, long: 15 };
let mode = 'focus';
let remaining = 25 * 60;
let deadline = null;
let timerInterval = null;
let sessions = Number(localStorage.getItem('betterpesu-sessions') || 0);

const format = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

function updateTimerUI() {
  $('timer-small').textContent = format(remaining);
  $('timer-big').textContent = format(remaining);
  $('timer-status').textContent = deadline ? 'Ⅱ' : '▶';
  $('toggle-timer').textContent = deadline ? 'Ⅱ Pause' : '▶ Start';
  $('sessions').textContent = `${sessions} focus session${sessions === 1 ? '' : 's'} completed`;
}

function pause() {
  if (deadline) remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  deadline = null;
  clearInterval(timerInterval);
  timerInterval = null;
  updateTimerUI();
}

function tick() {
  if (!deadline) return;
  remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  if (remaining === 0) {
    pause();
    if (mode === 'focus') {
      sessions++;
      localStorage.setItem('betterpesu-sessions', String(sessions));
      // Also log to backend analytics
      fetch('/api/study/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'focus', duration_seconds: presets.focus * 60 })
      }).catch(console.error);

      if (window.pywebview?.api?.send_notification) {
        window.pywebview.api.send_notification('Pomodoro Completed! ✦', 'Great job! Time for a break.');
      }
    }
    updateTimerUI();
  } else {
    updateTimerUI();
  }
}

function setMode(nextMode) {
  pause();
  mode = nextMode;
  remaining = presets[mode] * 60;
  document.querySelectorAll('.mode').forEach(button => {
    button.classList.toggle('active', button.dataset.mode === mode);
  });
  updateTimerUI();
}

$('timer-pill')?.addEventListener('click', () => {
  $('timer-panel').classList.toggle('hidden');
});

$('toggle-timer')?.addEventListener('click', () => {
  if (deadline) {
    pause();
  } else {
    if (remaining <= 0) remaining = presets[mode] * 60;
    deadline = Date.now() + remaining * 1000;
    timerInterval = setInterval(tick, 250);
    updateTimerUI();
  }
});

$('reset-timer')?.addEventListener('click', () => setMode(mode));

document.querySelectorAll('.mode').forEach(button => {
  button.addEventListener('click', () => setMode(button.dataset.mode));
});

$('apply-minutes')?.addEventListener('click', () => {
  const minutes = Number($('custom-minutes').value);
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 180) {
    alert('Choose a duration between 1 and 180 minutes.');
    return;
  }
  presets.focus = minutes;
  setMode('focus');
});

updateTimerUI();

// =========================================================
// 3. BOOKMARKS & RECENT
// =========================================================

let bookmarks = JSON.parse(localStorage.getItem('betterpesu-bookmarks') || '[]');
let recent = JSON.parse(localStorage.getItem('betterpesu-recent') || '[]');

function indexCourses() {
  catalog.clear();
  const subjects = new Set();
  for (const [sem, subjectMap] of Object.entries(courses)) {
    for (const [key, subject] of Object.entries(subjectMap || {})) {
      const subjectTitle = subject.title || key;
      subjects.add(subjectTitle);
      for (const [unit, lectures] of Object.entries(subject.units || {})) {
        for (const lecture of lectures || []) {
          for (const file of lecture.files || []) {
            if (!String(file.name || '').toLowerCase().endsWith('.pdf')) continue;
            catalog.set(file.path, { file, title: file.name, breadcrumb: `${sem} / ${subjectTitle} / ${unit}` });
          }
        }
      }
    }
  }

  const select = $('assignment-subject');
  if (select) {
    select.replaceChildren(new Option('Choose subject', ''));
    for (const subject of [...subjects].sort()) select.add(new Option(subject, subject));
    select.add(new Option('Other', 'Other'));
  }
}

function updateBookmarkButton() {
  const button = $('bookmark-current');
  if (!button) return;
  button.classList.toggle('hidden', !currentDoc);
  button.textContent = bookmarks.includes(currentDoc) ? '★ Saved' : '☆ Save';
}

$('bookmark-current')?.addEventListener('click', () => {
  if (!currentDoc) return;
  if (bookmarks.includes(currentDoc)) {
    bookmarks = bookmarks.filter(p => p !== currentDoc);
  } else {
    bookmarks = [...bookmarks, currentDoc];
  }
  localStorage.setItem('betterpesu-bookmarks', JSON.stringify(bookmarks));
  updateBookmarkButton();
  if (activeLibraryTab === 'bookmarks') renderPersonalSide();
});

function recordRecentFile(path, title, breadcrumb) {
  recent = [path, ...recent.filter(p => p !== path)].slice(0, 20);
  localStorage.setItem('betterpesu-recent', JSON.stringify(recent));
  fetch('/api/recent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: path, title, breadcrumb })
  }).catch(() => {});
  if (activeLibraryTab === 'recent') renderPersonalSide();
}

function renderPersonalSide() {
  const side = $('personal-side');
  side.replaceChildren();
  const paths = activeLibraryTab === 'bookmarks' ? bookmarks : recent;

  let shown = 0;
  for (const path of paths) {
    const entry = catalog.get(path);
    if (!entry) continue;
    shown++;
    const b = createButton('nav-file', entry.title, () => {
      openFile(entry.file, entry.title, entry.breadcrumb, b);
    });
    side.append(b);
  }

  if (!shown) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = activeLibraryTab === 'bookmarks'
      ? 'No saved PDFs yet. Open a PDF and tap ☆ Save.'
      : 'No recently viewed PDFs yet.';
    side.append(empty);
  }
}

function selectLibraryTab(tab) {
  activeLibraryTab = tab;
  $('tab-library')?.classList.toggle('active', tab === 'library');
  $('tab-bookmarks')?.classList.toggle('active', tab === 'bookmarks');
  $('tab-recent')?.classList.toggle('active', tab === 'recent');

  const isLib = tab === 'library';
  $('navigation').hidden = !isLib;
  $('search').parentElement.hidden = !isLib;
  $('personal-side').hidden = isLib;

  if (!isLib) renderPersonalSide();
}

$('tab-library')?.addEventListener('click', () => selectLibraryTab('library'));
$('tab-bookmarks')?.addEventListener('click', () => selectLibraryTab('bookmarks'));
$('tab-recent')?.addEventListener('click', () => selectLibraryTab('recent'));

// =========================================================
// 4. MODULE NAVIGATION (STUDY, ATTENDANCE, TIMETABLE, ETC.)
// =========================================================

function switchModule(moduleName) {
  activeModule = moduleName;
  document.querySelectorAll('.module-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.id === `tab-nav-${moduleName}`);
  });

  const views = {
    study: 'view-study-space',
    attendance: 'view-attendance',
    timetable: 'view-timetable',
    assignments: 'view-assignments',
    grades: 'view-grades',
    analytics: 'view-analytics',
    settings: 'view-settings'
  };

  Object.entries(views).forEach(([mod, viewId]) => {
    const el = $(viewId);
    if (el) el.classList.toggle('hidden', mod !== moduleName);
  });

  // Library sidebar tree is visible when in study mode
  const libSection = $('sidebar-library-section');
  if (libSection) libSection.hidden = moduleName !== 'study';

  if (moduleName === 'attendance') loadAttendanceHub();
  if (moduleName === 'timetable') loadTimetableDay(0);
  if (moduleName === 'assignments') loadAssignmentsList();
  if (moduleName === 'analytics') loadAnalyticsData();
  if (moduleName === 'settings') checkSystemAndAuth();
}

document.querySelectorAll('.module-nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.id.replace('tab-nav-', '');
    switchModule(mod);
  });
});

// =========================================================
// 5. ATTENDANCE HUB & BUNK CALCULATOR
// =========================================================

let attendanceList = [];

async function loadAttendanceHub() {
  try {
    const res = await fetch('/api/attendance');
    const data = await res.json();
    attendanceList = data.records || [];
    renderAttendanceGrid();
    updateSimulatorDropdown();
  } catch (e) {
    console.error('Attendance fetch error:', e);
  }
}

function renderAttendanceGrid() {
  const grid = $('attendance-cards-grid');
  grid.replaceChildren();

  if (!attendanceList.length) {
    grid.innerHTML = '<div class="empty">No attendance records. Click "+ Add Subject" or sync from PESU Academy.</div>';
    return;
  }

  attendanceList.forEach(a => {
    const card = document.createElement('div');
    card.className = 'attendance-card glass';

    const canBunk = a.classes_can_bunk;
    const needed = a.is_impossible_target ? 'Impossible' : a.classes_needed;
    let advice = '';

    if (a.current_percentage >= a.target_percentage) {
      advice = `✓ You can bunk <strong>${canBunk}</strong> more class${canBunk === 1 ? '' : 'es'} safely.`;
    } else {
      advice = `⚠ Attend <strong>${needed}</strong> consecutive class${needed === 1 ? '' : 'es'} to reach ${a.target_percentage}%.`;
    }

    card.innerHTML = `
      <div class="att-card-head">
        <div>
          <span class="att-code">${a.subject_code}</span>
          <div class="att-title">${a.subject_name}</div>
        </div>
        <span class="att-badge ${a.status}">${a.status.toUpperCase()}</span>
      </div>
      <div class="att-stats">
        <div class="att-pct">${a.current_percentage}%</div>
        <div class="att-counts">
          <div>${a.attended} / ${a.conducted} classes</div>
          <div>Target: ${a.target_percentage}%</div>
        </div>
      </div>
      <div class="att-progress-track">
        <div class="att-progress-bar ${a.status}" style="width: ${Math.min(100, a.current_percentage)}%"></div>
      </div>
      <div class="att-advice">${advice}</div>
    `;

    card.addEventListener('click', () => {
      $('sim-subject-select').value = a.subject_code;
      $('sim-input-attended').value = a.attended;
      $('sim-input-conducted').value = a.conducted;
      $('sim-input-target').value = a.target_percentage;
      runSimulator();
    });

    grid.append(card);
  });
}

function updateSimulatorDropdown() {
  const select = $('sim-subject-select');
  if (!select) return;
  select.replaceChildren(new Option('Custom inputs', ''));
  attendanceList.forEach(a => select.add(new Option(`${a.subject_code} - ${a.subject_name}`, a.subject_code)));

  select.onchange = () => {
    const found = attendanceList.find(x => x.subject_code === select.value);
    if (found) {
      $('sim-input-attended').value = found.attended;
      $('sim-input-conducted').value = found.conducted;
      $('sim-input-target').value = found.target_percentage;
      runSimulator();
    }
  };
}

document.querySelectorAll('.sim-tab-btn').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.sim-tab-btn').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const tabName = tab.dataset.simTab;
    $('sim-body-bunk').classList.toggle('hidden', tabName !== 'bunk');
    $('sim-body-target').classList.toggle('hidden', tabName !== 'target');
    $('sim-body-chain').classList.toggle('hidden', tabName !== 'chain');
    runSimulator();
  });
});

['sim-input-attended', 'sim-input-conducted', 'sim-input-target', 'sim-bunk-count'].forEach(id => {
  $(id)?.addEventListener('input', runSimulator);
});

async function runSimulator() {
  const attended = Number($('sim-input-attended').value);
  const conducted = Number($('sim-input-conducted').value);
  const target = Number($('sim-input-target').value);
  const bunkCount = Number($('sim-bunk-count').value);

  const res = await fetch('/api/attendance/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attended, conducted, target_percentage: target, bunk_count: bunkCount })
  });
  const data = await res.json();
  const a = data.analysis;

  $('sim-bunk-result').innerHTML = `If you bunk <strong>${bunkCount}</strong> classes, attendance will be <strong>${a.current_percentage}%</strong>.`;
  const neededStr = a.is_impossible_target ? 'Cannot reach 100%' : `${a.classes_needed} classes`;
  $('sim-target-result').innerHTML = `Attend <strong>${neededStr}</strong> to reach ${target}%. Max bunk: <strong>${a.classes_can_bunk}</strong>.`;

  const matrix = $('sim-matrix-grid');
  matrix.replaceChildren();
  (data.bunk_matrix || []).forEach(m => {
    const cell = document.createElement('div');
    cell.className = 'matrix-cell';
    cell.innerHTML = `<span>Miss +${m.miss_count}</span><strong>${m.projected_percentage}%</strong>`;
    matrix.append(cell);
  });
}

$('btn-run-chain')?.addEventListener('click', async () => {
  const chainStr = $('sim-chain-input').value;
  const actions = chainStr.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  const attended = Number($('sim-input-attended').value);
  const conducted = Number($('sim-input-conducted').value);

  const res = await fetch('/api/attendance/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attended, conducted, chain: actions })
  });
  const data = await res.json();

  const out = $('sim-chain-output');
  out.replaceChildren();
  (data.results || []).forEach(step => {
    const row = document.createElement('div');
    row.style.fontSize = '11px';
    row.style.padding = '4px 0';
    row.innerHTML = `Step ${step.step} (${step.action}): <strong>${step.attended}/${step.conducted} (${step.percentage}%)</strong>`;
    out.append(row);
  });
});

$('btn-sync-attendance')?.addEventListener('click', async () => {
  const btn = $('btn-sync-attendance');
  btn.disabled = true;
  btn.textContent = 'Syncing…';
  try {
    const res = await fetch('/api/attendance/sync', { method: 'POST' });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || 'Sync failed');
    await loadAttendanceHub();
    alert('Attendance synced successfully!');
  } catch (e) {
    alert(`Could not sync attendance: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '↻ Sync from PESU';
  }
});

$('btn-manual-attendance')?.addEventListener('click', () => openModal('modal-attendance'));
$('btn-export-attendance-csv')?.addEventListener('click', () => window.location.href = '/api/attendance/export');
$('btn-import-attendance-csv')?.addEventListener('click', () => openModal('modal-csv'));

$('form-attendance')?.addEventListener('submit', async e => {
  e.preventDefault();
  const payload = {
    subject_code: $('att-code').value.trim(),
    subject_name: $('att-title').value.trim(),
    attended: Number($('att-attended').value),
    conducted: Number($('att-conducted').value),
    target_percentage: Number($('att-target').value)
  };
  await fetch('/api/attendance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  closeModal('modal-attendance');
  e.target.reset();
  loadAttendanceHub();
});

$('btn-do-csv')?.addEventListener('click', async () => {
  const file = $('csv-file-input').files[0];
  if (!file) return alert('Select a CSV file first');
  const text = await file.text();
  await fetch('/api/attendance/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ csv_content: text })
  });
  closeModal('modal-csv');
  loadAttendanceHub();
});

// =========================================================
// 6. TIMETABLE
// =========================================================

document.querySelectorAll('.tt-day-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tt-day-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadTimetableDay(Number(btn.dataset.day));
  });
});

async function loadTimetableDay(day) {
  const grid = $('timetable-display-grid');
  try {
    const res = await fetch(`/api/timetable?day=${day}`);
    const data = await res.json();
    grid.replaceChildren();

    if (!data.timetable || !data.timetable.length) {
      grid.innerHTML = '<div class="empty">No classes scheduled for this day.</div>';
      return;
    }

    data.timetable.forEach(t => {
      const card = document.createElement('div');
      card.className = 'tt-card';
      card.innerHTML = `
        <span class="tt-badge">PERIOD ${t.period_number} ${t.is_lab ? '· LAB' : ''}</span>
        <div class="tt-title">${t.subject_name}</div>
        <div class="tt-sub">${t.start_time || 'Period ' + t.period_number} ${t.room ? '· ' + t.room : ''}</div>
      `;
      grid.append(card);
    });
  } catch (e) {
    console.error('Timetable error:', e);
  }
}

$('btn-add-period')?.addEventListener('click', async () => {
  const name = prompt('Enter Course / Period Name:');
  if (!name) return;
  const day = Number(document.querySelector('.tt-day-btn.active')?.dataset.day || 0);
  await fetch('/api/timetable', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day_of_week: day, period_number: 1, subject_name: name })
  });
  loadTimetableDay(day);
});

// =========================================================
// 7. ASSIGNMENTS PLANNER
// =========================================================

let assignmentsList = [];

async function loadAssignmentsList() {
  try {
    const res = await fetch('/api/assignments');
    const data = await res.json();
    assignmentsList = data.assignments || [];
    renderAssignmentsList();
  } catch (e) {
    console.error('Assignments error:', e);
  }
}

function renderAssignmentsList(filter = 'all') {
  const container = $('assignment-list');
  container.replaceChildren();

  const filtered = assignmentsList.filter(a => {
    if (filter === 'pending') return a.status !== 'completed';
    if (filter === 'completed') return a.status === 'completed';
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = '<div class="personal-muted">No assignments found.</div>';
    return;
  }

  filtered.forEach(a => {
    const row = document.createElement('div');
    row.className = 'personal-item';

    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = a.status === 'completed';
    check.onchange = async () => {
      await fetch(`/api/assignments/${a.id}/toggle`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed: check.checked })
      });
      loadAssignmentsList();
    };

    const info = document.createElement('div');
    info.style.flex = '1';
    info.innerHTML = `
      <div class="${a.status === 'completed' ? 'assignment-done' : ''}">${a.title}</div>
      <div class="assignment-date ${a.status_class}">${a.subject} · ${a.due_date} · ${a.status_label || 'Upcoming'}</div>
    `;

    const del = createButton('personal-button', '✕', async () => {
      await fetch(`/api/assignments/${a.id}`, { method: 'DELETE' });
      loadAssignmentsList();
    });

    row.append(check, info, del);
    container.append(row);
  });
}

document.querySelectorAll('.asg-filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.asg-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderAssignmentsList(btn.dataset.filter);
  });
});

$('assignment-form')?.addEventListener('submit', async e => {
  e.preventDefault();
  const payload = {
    title: $('assignment-title').value.trim(),
    subject: $('assignment-subject').value,
    due_date: $('assignment-date').value,
    priority: $('assignment-priority').value
  };
  await fetch('/api/assignments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  e.target.reset();
  loadAssignmentsList();
});

// =========================================================
// 8. GRADES & CIE EVALUATOR
// =========================================================

function setupGradesSection() {
  const container = $('sgpa-rows');
  const addRow = (title = 'Subject', credits = 4, grade = 'S') => {
    const row = document.createElement('div');
    row.className = 'sgpa-row';
    row.innerHTML = `
      <input class="search-box-input-full sgpa-sub-title" value="${title}">
      <input type="number" class="custom-input-sm sgpa-sub-cr" value="${credits}" min="1" max="10">
      <select class="sync-semester sgpa-sub-gr" style="margin:0; padding:6px;">
        <option value="S" ${grade === 'S' ? 'selected' : ''}>S (10)</option>
        <option value="A" ${grade === 'A' ? 'selected' : ''}>A (9)</option>
        <option value="B" ${grade === 'B' ? 'selected' : ''}>B (8)</option>
        <option value="C" ${grade === 'C' ? 'selected' : ''}>C (7)</option>
        <option value="D" ${grade === 'D' ? 'selected' : ''}>D (6)</option>
      </select>
      <button class="action" style="padding:6px 9px;">✕</button>
    `;
    row.querySelector('button').onclick = () => row.remove();
    container.append(row);
  };

  addRow('Operating System', 4, 'S');
  addRow('Data Structures', 4, 'A');
  addRow('Mathematics III', 4, 'B');

  $('btn-add-sgpa-row')?.addEventListener('click', () => addRow('New Course', 4, 'A'));

  $('btn-calc-sgpa')?.addEventListener('click', async () => {
    const rows = container.querySelectorAll('.sgpa-row');
    const subjects = [];
    rows.forEach(r => {
      subjects.push({
        title: r.querySelector('.sgpa-sub-title').value,
        credits: Number(r.querySelector('.sgpa-sub-cr').value),
        grade: r.querySelector('.sgpa-sub-gr').value
      });
    });
    const res = await fetch('/api/grades/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subjects })
    });
    const data = await res.json();
    $('sgpa-score-box').textContent = `Estimated SGPA: ${data.sgpa ?? '—'}`;
  });

  $('cie-form')?.addEventListener('submit', async e => {
    e.preventDefault();
    const payload = {
      isa1: Number($('cie-isa1').value),
      isa2: Number($('cie-isa2').value),
      assignment: Number($('cie-asg').value),
      project_or_lab: Number($('cie-lab').value)
    };
    const res = await fetch('/api/grades/internals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await res.json();
    $('cie-result-box').textContent = `CIE Score: ${result.total_obtained} / ${result.max_marks} (${result.percentage}%) · ${result.status}`;
  });
}

setupGradesSection();

// =========================================================
// 9. STUDY ANALYTICS
// =========================================================

async function loadAnalyticsData() {
  try {
    const res = await fetch('/api/study/stats');
    const stats = await res.json();
    $('stat-total-mins').textContent = `${stats.total_focus_minutes || 0} min`;
    $('stat-today-mins').textContent = `${stats.today_focus_minutes || 0} min`;
    $('stat-completed-sessions').textContent = stats.total_completed_sessions || 0;

    const trendBox = $('analytics-trend-bars');
    trendBox.replaceChildren();
    const maxVal = Math.max(60, ...(stats.daily_trend || []).map(d => d.total_sec / 60));

    (stats.daily_trend || []).forEach(d => {
      const mins = Math.round(d.total_sec / 60);
      const hPercent = Math.max(5, Math.round((mins / maxVal) * 100));
      const col = document.createElement('div');
      col.className = 'trend-bar-col';
      col.innerHTML = `
        <div class="trend-bar-fill" style="height: ${hPercent}%" title="${mins} mins"></div>
        <span style="font-size:10px; color:#81769d;">${d.day.slice(5)}</span>
      `;
      trendBox.append(col);
    });
  } catch (e) {
    console.error('Analytics error:', e);
  }
}

// =========================================================
// 10. SETTINGS & SYSTEM STATUS
// =========================================================

async function checkSystemAndAuth() {
  try {
    const statusRes = await fetch('/api/system/status');
    const statusData = await statusRes.json();
    $('settings-data-path').textContent = statusData.data_directory;

    const loBadge = $('settings-lo-badge');
    if (statusData.libreoffice_available) {
      loBadge.textContent = 'Installed (Ready)';
      loBadge.style.color = '#34d399';
    } else {
      loBadge.textContent = 'Not Found';
      loBadge.style.color = '#f87171';
    }

    const authRes = await fetch('/api/auth/status');
    const authData = await authRes.json();

    const profCard = $('settings-profile-card');
    const loginBtn = $('btn-login-modal');
    const logoutBtn = $('btn-logout');

    if (authData.profile?.name) {
      const p = authData.profile;
      $('sidebar-student-name').textContent = p.name;
      profCard.innerHTML = `
        <div style="font-size:13px; line-height:1.6;">
          <strong>${p.name}</strong> (${p.srn || 'PESU Student'})<br>
          <span class="subtle">${p.branch || ''} · ${p.semester || ''} · ${p.campus || ''}</span>
        </div>
      `;
      loginBtn.classList.add('hidden');
      logoutBtn.classList.remove('hidden');
    } else {
      $('sidebar-student-name').textContent = 'PESU Student';
      profCard.innerHTML = `<p class="subtle">Sign in to automatically sync your slides and attendance.</p>`;
      loginBtn.classList.remove('hidden');
      logoutBtn.classList.add('hidden');
    }
  } catch (e) {
    console.error('Settings check error:', e);
  }
}

$('btn-open-folder')?.addEventListener('click', () => {
  if (window.pywebview?.api?.open_slides_folder) {
    window.pywebview.api.open_slides_folder();
  } else {
    alert('Data folder: ' + $('settings-data-path').textContent);
  }
});

$('btn-login-modal')?.addEventListener('click', () => openModal('modal-login'));

$('btn-logout')?.addEventListener('click', async () => {
  if (confirm('Log out and clear session cookies?')) {
    await fetch('/api/auth/logout', { method: 'POST' });
    checkSystemAndAuth();
  }
});

$('form-login')?.addEventListener('submit', async e => {
  e.preventDefault();
  const username = $('login-username').value.trim();
  const password = $('login-password').value.trim();
  const errBox = $('login-error');
  const btn = $('btn-do-login');

  errBox.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Logging in…';

  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Login failed');
    closeModal('modal-login');
    checkSystemAndAuth();
    updateSemesterOptions();
    alert('Logged in successfully!');
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Log In';
  }
});

// =========================================================
// 11. MATERIALS SYNC POLLING & SEMESTERS
// =========================================================

const syncButton = $('sync-button');
const syncStatus = $('sync-status');
const syncSemester = $('sync-semester');
let lastSyncRunning = false;
let checkingSyncStatus = false;
let syncPollingTimer = null;

async function updateSemesterOptions() {
  const previous = syncSemester.value;
  syncSemester.disabled = true;
  syncSemester.replaceChildren(new Option('Loading semesters…', ''));
  try {
    const response = await fetch('/api/semesters', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Semester discovery failed');
    syncSemester.replaceChildren(new Option('All semesters', ''));
    for (const semester of result.semesters) {
      syncSemester.add(new Option(semester, semester));
    }
    if ([...syncSemester.options].some(option => option.value === previous)) {
      syncSemester.value = previous;
    }
    syncSemester.disabled = lastSyncRunning;
  } catch (error) {
    syncSemester.replaceChildren(new Option('All semesters', ''));
    syncSemester.disabled = false;
  }
  updateSyncButtonLabel();
}

function updateSyncButtonLabel() {
  if (lastSyncRunning) return;
  syncButton.textContent = syncSemester.value ? '↻ Sync Selected Semester' : '↻ Sync Materials';
}

syncSemester.addEventListener('change', updateSyncButtonLabel);
updateSemesterOptions();

function startSyncPolling() {
  if (syncPollingTimer === null) syncPollingTimer = setInterval(updateSyncStatus, 2000);
}

function stopSyncPolling() {
  if (syncPollingTimer !== null) clearInterval(syncPollingTimer);
  syncPollingTimer = null;
}

function formatSyncETA(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return 'Estimating…';
  const value = Math.max(0, Math.round(seconds));
  return value >= 60 ? `~${Math.floor(value / 60)}m ${value % 60}s left` : `~${value}s left`;
}

function renderSyncProgress(state) {
  const panel = $('sync-progress-panel');
  panel.hidden = !state.running && !['complete', 'failed'].includes(state.phase);
  if (panel.hidden) return;

  const percent = typeof state.progress === 'number' ? Math.min(100, Math.max(0, state.progress)) : null;
  $('sync-percent').textContent = percent == null ? '—' : `${Math.round(percent)}%`;
  $('sync-progress-fill').style.width = `${percent || 0}%`;

  const label = state.phase === 'complete' ? 'Sync complete'
    : state.phase === 'failed' ? 'Sync failed'
    : state.phase === 'converting' ? 'Converting PowerPoint slides' : 'Checking and downloading';
  $('sync-progress-label').textContent = label;
  $('sync-current-subject').textContent = state.current_subject || '';

  const total = Number.isInteger(state.total) ? state.total : null;
  $('sync-count').textContent = total === null ? 'Discovering materials…'
    : state.phase === 'converting' ? `${state.processed} / ${total} PPTX files`
    : `${state.processed} / ${total} subjects checked`;

  $('sync-eta').textContent = state.phase === 'complete' ? 'Finished'
    : state.phase === 'failed' ? 'Stopped' : formatSyncETA(state.eta_seconds);

  $('sync-files-count').textContent = `${state.downloaded || 0} new · ${state.skipped || 0} skipped · ${state.converted || 0} converted`
    + (state.failed_files ? ` · ${state.failed_files} failed` : '');
}

async function updateSyncStatus() {
  if (checkingSyncStatus) return;
  checkingSyncStatus = true;
  try {
    const response = await fetch('/api/sync/status', { cache: 'no-store' });
    if (!response.ok) throw new Error('Status unavailable');
    const state = await response.json();
    renderSyncProgress(state);

    syncButton.disabled = Boolean(state.running);
    document.querySelectorAll('.nav-sub-sync').forEach(button => { button.disabled = Boolean(state.running); });
    syncButton.textContent = state.running ? '↻ Syncing…' : (syncSemester.value ? '↻ Sync Selected Semester' : '↻ Sync Materials');
    syncSemester.disabled = Boolean(state.running);

    const names = {
      idle: 'Never synced in this session',
      starting: 'Starting…',
      downloading: 'Downloading materials…',
      converting: 'Converting PPTX to PDF…',
      complete: 'Sync complete',
      failed: 'Sync failed'
    };
    const last = state.last_synced ? ` · Last synced ${new Date(state.last_synced).toLocaleString()}` : '';
    const scope = state.selection ? (state.selection.subject_id ? 'Selected subject · ' : 'Selected semester · ') : '';
    syncStatus.textContent = scope + (state.error || names[state.phase] || 'Ready') + last;

    if (lastSyncRunning && !state.running && state.phase === 'complete') {
      const selectedPath = currentDoc;
      const coursesResponse = await fetch('/api/courses', { cache: 'no-store' });
      if (coursesResponse.ok) {
        courses = await coursesResponse.json();
        indexCourses();
        renderNavigation($('search').value);
        if (activeLibraryTab !== 'library') renderPersonalSide();
        if (selectedPath && catalog.has(selectedPath)) updateBookmarkButton();
      }
    }
    lastSyncRunning = Boolean(state.running);
    if (state.running) startSyncPolling();
    else stopSyncPolling();
  } catch (error) {
    syncStatus.textContent = 'Could not check sync status.';
    if (!lastSyncRunning) stopSyncPolling();
  } finally {
    checkingSyncStatus = false;
  }
}

syncButton.addEventListener('click', async () => {
  syncButton.disabled = true;
  syncStatus.textContent = 'Starting sync…';
  try {
    const response = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semester: syncSemester.value || null })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not start sync');
    lastSyncRunning = true;
    startSyncPolling();
    await updateSyncStatus();
  } catch (error) {
    syncStatus.textContent = error.message;
    syncButton.disabled = false;
  }
});

updateSyncStatus();

// =========================================================
// 12. INITIALIZATION
// =========================================================

fetch('/api/courses')
  .then(r => r.json())
  .then(data => {
    courses = data;
    indexCourses();
    renderNavigation($('search').value);
    if (activeLibraryTab !== 'library') renderPersonalSide();
  })
  .catch(console.error);

checkSystemAndAuth();

function openModal(id) { $(id)?.classList.remove('hidden'); }
function closeModal(id) { $(id)?.classList.add('hidden'); }
