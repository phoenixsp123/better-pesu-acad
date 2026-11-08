/* =====================================================================
   Better PESU Acad — Primary Application Script
   Full implementation of the Study Space with PDF Viewer & Pomodoro Timer,
   Course Materials Tree, Fullscreen Focus Mode, and Academic Companion Hubs.
   ===================================================================== */

const $ = id => document.getElementById(id);
const openModal = id => { $(id)?.classList.remove('hidden'); };
const closeModal = id => { $(id)?.classList.add('hidden'); };
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

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

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
  $('study-fullscreen')?.classList.remove('hidden');
  $('bookmark-current')?.classList.remove('hidden');
  $('btn-open-native')?.classList.remove('hidden');
  $('btn-reveal-finder')?.classList.remove('hidden');
  $('btn-save-copy')?.classList.remove('hidden');
  $('viewer-placeholder')?.classList.add('hidden');
  $('document-title').textContent = title;
  $('document-path').textContent = breadcrumb;
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

// Fullscreen Focus View (Bulletproof In-App & OS Fullscreen)
const studyWorkspace = document.querySelector('.workspace');
const studyFullscreenButton = $('study-fullscreen');
let isFocusMode = false;

function setStudyFocusMode(enabled) {
  isFocusMode = enabled;
  studyWorkspace.classList.toggle('study-fullscreen', isFocusMode);
  document.body.classList.toggle('focus-mode-active', isFocusMode);

  if (studyFullscreenButton) {
    studyFullscreenButton.textContent = isFocusMode ? '⤢ Exit Focus' : '⛶ Focus View';
    studyFullscreenButton.title = isFocusMode ? 'Exit focus mode (Esc)' : 'Fullscreen distraction-free study mode';
  }

  // Attempt OS/browser fullscreen if supported as progressive enhancement
  if (isFocusMode) {
    try {
      if (document.fullscreenEnabled && !document.fullscreenElement && studyWorkspace.requestFullscreen) {
        studyWorkspace.requestFullscreen().catch(() => {});
      }
    } catch (_) {}
  } else {
    try {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
    } catch (_) {}
  }
}

studyFullscreenButton?.addEventListener('click', () => {
  if (!$('pdf-viewer').classList.contains('hidden')) {
    setStudyFocusMode(!isFocusMode);
  }
});

$('study-exit')?.addEventListener('click', () => {
  setStudyFocusMode(false);
});

// Escape key to exit focus mode
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && isFocusMode) {
    e.preventDefault();
    setStudyFocusMode(false);
  }
});

document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement && isFocusMode) {
    setStudyFocusMode(false);
  }
});

// Document Actions: Native Preview, Reveal in Finder, and Save Copy
$('btn-open-native')?.addEventListener('click', async () => {
  if (!currentDoc) return;
  try {
    if (window.pywebview?.api?.open_file_native) {
      await window.pywebview.api.open_file_native(currentDoc);
    } else {
      await fetch('/api/files/open-native', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentDoc })
      });
    }
  } catch (err) {
    console.error('Failed to open native viewer:', err);
  }
});

$('btn-reveal-finder')?.addEventListener('click', async () => {
  if (!currentDoc) return;
  try {
    if (window.pywebview?.api?.reveal_in_finder) {
      await window.pywebview.api.reveal_in_finder(currentDoc);
    } else {
      await fetch('/api/files/reveal-in-finder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentDoc })
      });
    }
  } catch (err) {
    console.error('Failed to reveal in Finder:', err);
  }
});

$('btn-save-copy')?.addEventListener('click', async () => {
  if (!currentDoc) return;
  const fileName = currentDoc.split(/[\\/]/).pop() || 'lecture.pdf';
  try {
    if (window.pywebview?.api?.save_file_copy) {
      const ok = await window.pywebview.api.save_file_copy(currentDoc);
      if (ok) {
        $('file-count').textContent = `Saved copy of ${fileName}`;
      }
    } else {
      // Safe blob download without top-level window navigation
      const res = await fetch(fileURL(currentDoc));
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
      $('file-count').textContent = `Downloaded copy of ${fileName}`;
    }
  } catch (err) {
    console.error('Failed to save copy:', err);
  }
});

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
    if (el) {
      const isCurrent = (mod === moduleName);
      if (isCurrent) {
        el.classList.add('active');
        el.classList.remove('hidden');
      } else {
        el.classList.remove('active');
        el.classList.add('hidden');
      }
    }
  });

  document.querySelectorAll('.module-nav-btn').forEach(b => {
    b.classList.toggle('active', b.id === `tab-nav-${moduleName}`);
  });
  document.querySelectorAll('.nav-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.view === moduleName);
  });

  // Library sidebar tree is visible when in study mode
  const libSection = $('sidebar-library-section');
  if (libSection) libSection.hidden = (moduleName !== 'study');

  if (moduleName === 'attendance') loadAttendanceHub();
  if (moduleName === 'timetable') loadTimetableDay(0);
  if (moduleName === 'assignments') loadAssignmentsList();
  if (moduleName === 'grades') loadGpaPredictor();
  if (moduleName === 'analytics') loadAnalyticsData();
  if (moduleName === 'settings') checkSystemAndAuth();
}

document.querySelectorAll('.module-nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.id.replace('tab-nav-', '');
    switchModule(mod);
  });
});

document.querySelectorAll('.nav-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const mod = btn.dataset.view;
    switchModule(mod);
  });
});

// =========================================================
// 5. ATTENDANCE HUB
// =========================================================

let attendanceList = [];

async function loadAttendanceHub(semesterOverride) {
  const sem = semesterOverride !== undefined ? semesterOverride : ($('attendance-semester-select')?.value || '');
  try {
    const url = '/api/attendance' + (sem ? `?semester=${encodeURIComponent(sem)}` : '');
    const res = await fetch(url);
    const data = await res.json();
    attendanceList = data.records || [];
    renderAttendanceGrid();
  } catch (e) {
    console.error('Attendance fetch error:', e);
  }
}

$('attendance-semester-select')?.addEventListener('change', () => {
  loadAttendanceHub($('attendance-semester-select').value);
});

function renderAttendanceGrid() {
  const grid = $('attendance-cards-grid');
  grid.replaceChildren();

  // Compute overall semester statistics for top banner
  const totalAttended = attendanceList.reduce((acc, a) => acc + (a.attended || 0), 0);
  const totalConducted = attendanceList.reduce((acc, a) => acc + (a.conducted || 0), 0);
  const overallPct = totalConducted > 0 ? (totalAttended / totalConducted * 100).toFixed(1) : '0.0';
  const safeCount = attendanceList.filter(a => (a.current_percentage >= (a.target_percentage || 75))).length;
  const dangerCount = attendanceList.length - safeCount;

  if ($('att-overall-percentage')) $('att-overall-percentage').textContent = `${overallPct}%`;
  if ($('att-total-subjects')) $('att-total-subjects').textContent = String(attendanceList.length);
  if ($('att-safe-count')) $('att-safe-count').textContent = String(safeCount);
  if ($('att-danger-count')) $('att-danger-count').textContent = String(dangerCount);

  const badge = $('att-overall-badge');
  if (badge) {
    if (dangerCount > 0) {
      badge.textContent = `${dangerCount} SHORTAGE${dangerCount === 1 ? '' : 'S'}`;
      badge.className = 'att-status-pill danger';
    } else {
      badge.textContent = 'ELIGIBLE';
      badge.className = 'att-status-pill ok';
    }
  }

  if (!attendanceList.length) {
    grid.innerHTML = `
      <div class="empty" style="padding: 36px 20px; text-align: center; grid-column: 1 / -1; background: var(--bg-card); border-radius: 12px; border: 1px dashed var(--border);">
        <p style="margin-bottom: 14px; font-size: 15px; color: var(--text-primary); font-weight: 500;">No attendance records found for this semester.</p>
        <p class="subtle" style="margin-bottom: 20px; font-size: 13px;">Click "↻ Sync from PESU" to fetch your live courses and attendance, or add subjects manually.</p>
        <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
          <button class="sync-button" style="width: auto; padding: 9px 18px;" onclick="openModal('modal-login')">Connect PESU Account</button>
          <button class="action" onclick="openModal('modal-attendance')">+ Add Subject Manually</button>
        </div>
      </div>
    `;
    return;
  }

  attendanceList.forEach(a => {
    const card = document.createElement('div');
    card.className = 'attendance-card glass';

    const isSafe = (a.current_percentage >= (a.target_percentage || 75));
    const statusClass = isSafe ? 'safe' : 'critical';
    const statusText = isSafe ? 'SAFE (≥ 75%)' : 'SHORTAGE (< 75%)';

    const canBunk = a.classes_can_bunk;
    const needed = a.is_impossible_target ? 'Cannot reach 75%' : a.classes_needed;
    let advice = isSafe
      ? `✓ Safe to miss <strong>${canBunk}</strong> class${canBunk === 1 ? '' : 'es'}`
      : `⚠ Need <strong>${needed}</strong> consecutive class${needed === 1 ? '' : 'es'} for 75%`;

    card.innerHTML = `
      <div class="att-card-head">
        <div>
          <div class="att-title">${escapeHtml(a.subject_name)}</div>
          <div class="att-code">${escapeHtml(a.subject_code)}</div>
        </div>
        <span class="att-badge ${statusClass}">${statusText}</span>
      </div>
      <div class="att-stats-row">
        <div class="att-pct-large ${statusClass}">${a.current_percentage}%</div>
        <div class="att-status-text">${a.attended} classes attended</div>
      </div>
      <div class="att-progress-track">
        <div class="att-progress-bar ${statusClass}" style="width: ${Math.min(100, a.current_percentage)}%"></div>
      </div>
      <div class="att-card-footer">
        <span>${advice}</span>
        <button class="action att-del-btn" style="padding: 2px 7px; font-size: 10px;" title="Delete subject">✕</button>
      </div>
    `;

    card.querySelector('.att-del-btn')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (confirm(`Remove ${a.subject_code} from attendance?`)) {
        await fetch(`/api/attendance/${encodeURIComponent(a.subject_code)}`, { method: 'DELETE' });
        await loadAttendanceHub();
      }
    });

    grid.append(card);
  });
}

$('btn-sync-attendance')?.addEventListener('click', async () => {
  const btn = $('btn-sync-attendance');
  const semSelect = $('attendance-semester-select');
  const selectedSem = semSelect?.value || '';
  btn.disabled = true;
  btn.textContent = 'Syncing…';
  try {
    const res = await fetch('/api/attendance/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semester: selectedSem || null })
    });
    const result = await res.json();
    if (res.status === 401) {
      openModal('modal-login');
      throw new Error('Please sign in to PESU Academy first.');
    }
    if (!res.ok) throw new Error(result.error || 'Sync failed');
    await loadAttendanceHub(selectedSem);
    alert(result.message || 'Attendance synced successfully!');
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

function formatTimetablePeriod(t) {
  let rawName = (t.subject_name || '').replace(/^ttSubject[_&]*/i, '').trim();
  let code = (t.subject_code || '').trim();
  let name = rawName;

  const match = rawName.match(/^([A-Z0-9]{5,12})\s*[-–—:]\s*(.+)$/i);
  if (match) {
    code = match[1].trim();
    name = match[2].trim();
  }

  // Convert shouting all-caps into clean Title Case
  if (name.length > 3 && name === name.toUpperCase()) {
    const minorWords = new Set(["and", "for", "in", "of", "to", "the", "its", "with"]);
    const acronyms = new Set(["ai", "ml", "os", "dsa", "i", "ii", "iii", "iv"]);
    name = name.split(/\s+/).map(w => {
      const lower = w.toLowerCase();
      if (acronyms.has(lower)) return lower.toUpperCase();
      if (minorWords.has(lower)) return lower;
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    }).join(' ');
  }

  const cleanTime = (s) => (s || '').replace(/^(\d{1,2}:\d{2}):\d{2}(\s*[AP]M)?$/i, '$1$2').trim();
  const st = cleanTime(t.start_time);
  const et = cleanTime(t.end_time);
  const timeStr = (st && et) ? `${st} – ${et}` : (st || `Period ${t.period_number}`);

  return { ...t, subject_code: code, subject_name: name, time_display: timeStr };
}

async function loadTimetableDay(day) {
  const grid = $('timetable-display-grid');
  try {
    const res = await fetch(`/api/timetable?day=${day}`);
    const data = await res.json();
    grid.replaceChildren();

    if (!data.timetable || !data.timetable.length) {
      grid.innerHTML = '<div class="empty">No classes scheduled for this day. Click "↻ Sync Timetable from PESU" to load your schedule.</div>';
      return;
    }

    data.timetable.forEach(rawItem => {
      const t = formatTimetablePeriod(rawItem);
      const card = document.createElement('div');
      card.className = 'tt-card glass';
      card.innerHTML = `
        <div class="tt-card-head">
          <span class="tt-period-pill">PERIOD ${t.period_number}</span>
          ${t.is_lab ? '<span class="tt-lab-badge">LAB</span>' : ''}
        </div>
        <div class="tt-card-body">
          <div class="tt-subject-title">${escapeHtml(t.subject_name)}</div>
          ${t.subject_code ? `<div class="tt-subject-code-sub">${escapeHtml(t.subject_code)}</div>` : ''}
        </div>
        <div class="tt-card-footer">
          <div class="tt-time-chip">⏱ ${escapeHtml(t.time_display)}</div>
          ${t.room ? `<div class="tt-room-chip">📍 ${escapeHtml(t.room)}</div>` : ''}
        </div>
      `;
      grid.append(card);
    });
  } catch (e) {
    console.error('Timetable error:', e);
  }
}

$('btn-sync-timetable')?.addEventListener('click', async () => {
  const btn = $('btn-sync-timetable');
  btn.disabled = true;
  btn.textContent = 'Syncing…';
  try {
    const res = await fetch('/api/timetable/sync', { method: 'POST' });
    const data = await res.json();
    if (res.status === 401) {
      openModal('modal-login');
      throw new Error('Please sign in to PESU Academy first.');
    }
    if (!res.ok) throw new Error(data.error || 'Could not sync timetable');
    const day = Number(document.querySelector('.tt-day-btn.active')?.dataset.day || 0);
    await loadTimetableDay(day);
    alert(data.message || 'Timetable synced successfully!');
  } catch (e) {
    alert(`Timetable sync error: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '↻ Sync Timetable from PESU';
  }
});

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
// 8. GRADES & GPA PREDICTOR (ISA + ESA)
// =========================================================

let gpaCourseList = [];

async function loadGpaPredictor(semesterOverride) {
  const sem = semesterOverride !== undefined ? semesterOverride : ($('gpa-semester-select')?.value || '');
  const container = $('gpa-subjects-container');
  if (!container) return;
  try {
    const url = '/api/grades/isa' + (sem ? `?semester=${encodeURIComponent(sem)}` : '');
    const res = await fetch(url);
    const data = await res.json();
    gpaCourseList = (data.marks && data.marks.length) ? data.marks : [];

    // Fallback courses if no records exist yet
    if (!gpaCourseList.length) {
      gpaCourseList = [
        { subject_code: 'UE25CS252A', subject_name: 'Data Structures and its Applications', credits: 4, isa1_score: 32, isa2_score: 35, assignment_score: 9, target_grade: 'S' },
        { subject_code: 'UE25CS242A', subject_name: 'Operating Systems', credits: 4, isa1_score: 30, isa2_score: 31, assignment_score: 8.5, target_grade: 'A' },
        { subject_code: 'UE25MA251A', subject_name: 'Mathematics III', credits: 4, isa1_score: 28, isa2_score: 33, assignment_score: 8, target_grade: 'A' }
      ];
    }
    renderGpaCourseRows();
  } catch (e) {
    console.error('Failed to load GPA predictor:', e);
  }
}

function isCieSubject(name, code, isa1Max) {
  const n = String(name || '').toUpperCase();
  const c = String(code || '').toUpperCase();
  return c.startsWith('UZ') || /\bCIE\b/i.test(c) || /\bCIE\b/i.test(n) || n.includes('INNOVATION') || Number(isa1Max) === 45;
}

function calcRowCie(isa1, isa1Max, isa2, isa2Max, asg, asgMax) {
  // PESU Scheme: ISA 1 and ISA 2 contribute 22.5 marks each = 45 marks total.
  // Assignment/Lab contributes up to 5 marks. Total CIE = 50 marks.
  const m1 = Number(isa1Max) > 0 ? Number(isa1Max) : 40.0;
  const m2 = Number(isa2Max) > 0 ? Number(isa2Max) : m1;
  const ma = Number(asgMax) > 0 ? Number(asgMax) : 10.0;

  const s1 = (isa1 !== null && isa1 !== undefined && String(isa1).trim() !== '') ? Number(isa1) : 0;
  const s2 = (isa2 !== null && isa2 !== undefined && String(isa2).trim() !== '') ? Number(isa2) : 0;
  const sa = (asg !== null && asg !== undefined && String(asg).trim() !== '') ? Number(asg) : 0;

  const c1 = (Math.max(0, Math.min(m1, s1)) / m1) * 22.5;
  const c2 = (Math.max(0, Math.min(m2, s2)) / m2) * 22.5;
  const isaContrib = Math.min(45, c1 + c2);

  // Assignment / Lab contributes up to 5 marks
  const asgContrib = Math.min(5, (Math.max(0, Math.min(ma, sa)) / ma) * 5.0);

  return Math.min(50, Math.round((isaContrib + asgContrib) * 10) / 10);
}

function getGradeInfo(total) {
  if (total >= 90) return { grade: 'S', points: 10, cls: 'grade-s' };
  if (total >= 80) return { grade: 'A', points: 9, cls: 'grade-a' };
  if (total >= 70) return { grade: 'B', points: 8, cls: 'grade-b' };
  if (total >= 60) return { grade: 'C', points: 7, cls: 'grade-c' };
  if (total >= 50) return { grade: 'D', points: 6, cls: 'grade-d' };
  if (total >= 40) return { grade: 'E', points: 5, cls: 'grade-e' };
  return { grade: 'F', points: 0, cls: 'grade-f' };
}

function renderGpaCourseRows() {
  const container = $('gpa-subjects-container');
  if (!container) return;
  container.replaceChildren();

  if (!gpaCourseList.length) {
    container.innerHTML = '<div class="empty">No courses in predictor. Click "+ Add Course" or "Fetch Marks from PESU".</div>';
    recalcGrandGpa();
    return;
  }

  gpaCourseList.forEach((course, index) => {
    const row = document.createElement('div');
    row.className = 'gpa-subject-row';
    row.dataset.index = index;

    const isCie = isCieSubject(course.subject_name, course.subject_code, course.isa1_max);
    const isa1Max = Number(course.isa1_max) > 0 ? Number(course.isa1_max) : (isCie ? 45.0 : 40.0);
    const isa2Max = Number(course.isa2_max) > 0 ? Number(course.isa2_max) : isa1Max;
    const asgMax = Number(course.assignment_max) > 0 ? Number(course.assignment_max) : 10.0;
    const esaMax = isCie ? 50.0 : 100.0;

    row.dataset.isCie = isCie ? '1' : '0';
    row.dataset.isa1Max = isa1Max;
    row.dataset.isa2Max = isa2Max;
    row.dataset.asgMax = asgMax;
    row.dataset.esaMax = esaMax;

    const isa1Display = (course.isa1_score !== null && course.isa1_score !== undefined) ? course.isa1_score : '';
    const isa2Display = (course.isa2_score !== null && course.isa2_score !== undefined) ? course.isa2_score : '';
    const asgDisplay = (course.assignment_score !== null && course.assignment_score !== undefined) ? course.assignment_score : '';

    const cie = calcRowCie(isa1Display, isa1Max, isa2Display, isa2Max, asgDisplay, asgMax);

    const target = course.target_grade || 'S';
    const cutoffs = { S: 90, A: 80, B: 70, C: 60, D: 50, E: 40 };
    const cutoff = cutoffs[target] || 90;

    // ESA is evaluated out of 100 for regular courses (50% weightage), and out of 50 for CIE courses
    const ptsNeeded50 = Math.max(0, cutoff - cie);
    const neededEsa = isCie ? ptsNeeded50 : (ptsNeeded50 * 2.0);
    const isImpossible = neededEsa > esaMax;

    let neededText = `${neededEsa.toFixed(1)} / ${esaMax}`;
    if (isImpossible) neededText = `>${esaMax} (Unattainable)`;
    else if (neededEsa === 0) neededText = `0.0 (Secured)`;

    row.innerHTML = `
      <div class="gpa-sub-title-col">
        <input class="gpa-sub-name-input row-name" value="${escapeHtml(course.subject_name || 'Subject')}" placeholder="Course Title">
        <div class="gpa-sub-code-text row-code">${escapeHtml(course.subject_code || '')}</div>
      </div>
      <input type="number" class="gpa-num-input row-cr" value="${course.credits || 4}" min="1" max="10" style="width: 45px;">
      
      <div class="gpa-cell-wrap" style="width: 80px;">
        <input type="number" step="0.5" class="gpa-num-input row-isa1" value="${isa1Display}" min="0" max="${isa1Max}" placeholder="—">
        <span class="gpa-cell-sub">/ ${isa1Max}</span>
      </div>

      <div class="gpa-cell-wrap" style="width: 80px;">
        <input type="number" step="0.5" class="gpa-num-input row-isa2" value="${isa2Display}" min="0" max="${isa2Max}" placeholder="—">
        <span class="gpa-cell-sub">/ ${isa2Max}</span>
      </div>

      <div class="gpa-cell-wrap" style="width: 80px;">
        <input type="number" step="0.5" class="gpa-num-input row-asg" value="${asgDisplay}" min="0" max="${asgMax}" placeholder="—">
        <span class="gpa-cell-sub">/ ${asgMax}</span>
      </div>

      <div class="gpa-cie-pill row-cie" style="width: 70px;">${cie}</div>

      <select class="sync-semester row-target" style="margin: 0; padding: 5px 6px; width: 65px; font-size: 12px;">
        <option value="S" ${target === 'S' ? 'selected' : ''}>S</option>
        <option value="A" ${target === 'A' ? 'selected' : ''}>A</option>
        <option value="B" ${target === 'B' ? 'selected' : ''}>B</option>
        <option value="C" ${target === 'C' ? 'selected' : ''}>C</option>
        <option value="D" ${target === 'D' ? 'selected' : ''}>D</option>
        <option value="E" ${target === 'E' ? 'selected' : ''}>E</option>
      </select>

      <div class="gpa-esa-needed-pill row-needed ${isImpossible ? 'impossible' : 'possible'}" style="width: 125px;">${neededText}</div>

      <div class="gpa-cell-wrap" style="width: 100px;">
        <input type="number" step="0.5" class="gpa-num-input row-exp-esa" placeholder="Auto" min="0" max="${esaMax}" value="${course.expected_esa !== undefined && course.expected_esa !== null ? course.expected_esa : ''}">
        <span class="gpa-cell-sub">/ ${esaMax}</span>
      </div>

      <div class="gpa-grade-badge row-badge" style="width: 65px;">-</div>
      <button class="action row-del-btn" style="padding: 4px 8px; width: 30px; font-size: 11px;" title="Remove row">✕</button>
    `;

    // Row event listeners
    const onFieldChange = () => updateRowCalculations(row);
    row.querySelectorAll('.row-name, .row-cr, .row-isa1, .row-isa2, .row-asg, .row-target, .row-exp-esa').forEach(el => {
      el.addEventListener('input', onFieldChange);
      el.addEventListener('change', onFieldChange);
    });

    row.querySelector('.row-del-btn').addEventListener('click', () => {
      row.remove();
      recalcGrandGpa();
    });

    container.append(row);
    updateRowCalculations(row, false);
  });

  recalcGrandGpa();
}

function updateRowCalculations(row, triggerGrand = true) {
  const isCie = row.dataset.isCie === '1' || isCieSubject(row.querySelector('.row-name')?.value, row.querySelector('.row-code')?.textContent, row.dataset.isa1Max);
  const isa1Max = Number(row.dataset.isa1Max) || (isCie ? 45.0 : 40.0);
  const isa2Max = Number(row.dataset.isa2Max) || isa1Max;
  const asgMax = Number(row.dataset.asgMax) || 10.0;
  const esaMax = isCie ? 50.0 : 100.0;

  row.dataset.isCie = isCie ? '1' : '0';
  row.dataset.isa1Max = isa1Max;
  row.dataset.isa2Max = isa2Max;
  row.dataset.asgMax = asgMax;
  row.dataset.esaMax = esaMax;

  const expEsaSub = row.querySelector('.row-exp-esa')?.parentElement?.querySelector('.gpa-cell-sub');
  if (expEsaSub) expEsaSub.textContent = `/ ${esaMax}`;
  const expEsaInputEl = row.querySelector('.row-exp-esa');
  if (expEsaInputEl) expEsaInputEl.max = String(esaMax);

  const isa1Sub = row.querySelector('.row-isa1')?.parentElement?.querySelector('.gpa-cell-sub');
  if (isa1Sub) isa1Sub.textContent = `/ ${isa1Max}`;
  const isa1InputEl = row.querySelector('.row-isa1');
  if (isa1InputEl) isa1InputEl.max = String(isa1Max);

  const isa2Sub = row.querySelector('.row-isa2')?.parentElement?.querySelector('.gpa-cell-sub');
  if (isa2Sub) isa2Sub.textContent = `/ ${isa2Max}`;
  const isa2InputEl = row.querySelector('.row-isa2');
  if (isa2InputEl) isa2InputEl.max = String(isa2Max);

  const isa1 = row.querySelector('.row-isa1').value.trim();
  const isa2 = row.querySelector('.row-isa2').value.trim();
  const asg = row.querySelector('.row-asg').value.trim();
  const target = row.querySelector('.row-target').value;
  const expEsaInput = row.querySelector('.row-exp-esa').value.trim();

  const cie = calcRowCie(isa1, isa1Max, isa2, isa2Max, asg, asgMax);
  row.querySelector('.row-cie').textContent = cie;

  const cutoffs = { S: 90, A: 80, B: 70, C: 60, D: 50, E: 40 };
  const cutoff = cutoffs[target] || 90;

  // ESA needed:
  // For CIE: ESA is out of 50 -> needed = cutoff - cie
  // For Regular: ESA is out of 100, scaled by 50% -> needed = (cutoff - cie) * 2
  const ptsNeeded50 = Math.max(0, cutoff - cie);
  const neededEsa = isCie ? ptsNeeded50 : (ptsNeeded50 * 2.0);
  const isImpossible = neededEsa > esaMax;

  const neededPill = row.querySelector('.row-needed');
  if (isImpossible) {
    neededPill.textContent = `>${esaMax} (Unattainable)`;
    neededPill.className = 'gpa-esa-needed-pill row-needed impossible';
  } else if (neededEsa === 0) {
    neededPill.textContent = '0.0 (Secured)';
    neededPill.className = 'gpa-esa-needed-pill row-needed possible';
  } else {
    neededPill.textContent = `${neededEsa.toFixed(1)} / ${esaMax}`;
    neededPill.className = 'gpa-esa-needed-pill row-needed possible';
  }

  // Calculate actual ESA used for predicted grade
  let actualEsaScore;
  if (expEsaInput !== '') {
    actualEsaScore = Math.max(0, Math.min(esaMax, Number(expEsaInput)));
  } else {
    actualEsaScore = isImpossible ? 0 : Math.min(esaMax, neededEsa);
  }

  // ESA contribution to the 100-mark course total:
  // For regular courses: actualEsaScore * 0.5 (scaled down from 100 to 50)
  // For CIE: actualEsaScore (out of 50)
  const esaContrib = isCie ? actualEsaScore : (actualEsaScore * 0.5);
  const total = Math.min(100, Math.max(0, cie + esaContrib));
  const info = getGradeInfo(total);

  const badge = row.querySelector('.row-badge');
  badge.textContent = info.grade;
  badge.className = `gpa-grade-badge row-badge ${info.cls}`;

  if (triggerGrand) {
    recalcGrandGpa();
  }
}

function recalcGrandGpa() {
  const container = $('gpa-subjects-container');
  if (!container) return;
  const rows = container.querySelectorAll('.gpa-subject-row');
  let totalCredits = 0;
  let weightedPoints = 0;

  rows.forEach(r => {
    const cr = Number(r.querySelector('.row-cr').value) || 4;
    const badgeText = r.querySelector('.row-badge').textContent.trim();
    const pointMap = { S: 10, A: 9, B: 8, C: 7, D: 6, E: 5, F: 0 };
    const pts = pointMap[badgeText] ?? 0;
    totalCredits += cr;
    weightedPoints += (cr * pts);
  });

  const sgpa = totalCredits > 0 ? (weightedPoints / totalCredits).toFixed(2) : '0.00';
  if ($('gpa-grand-score')) $('gpa-grand-score').textContent = sgpa;
  if ($('gpa-total-credits')) $('gpa-total-credits').textContent = String(totalCredits);

  if ($('gpa-insight-text')) {
    if (totalCredits === 0) {
      $('gpa-insight-text').textContent = 'Add courses to calculate predicted SGPA.';
    } else {
      const numSgpa = Number(sgpa);
      let insight = '';
      if (numSgpa >= 9.0) insight = 'Outstanding! Projected Distinction with top honors.';
      else if (numSgpa >= 8.0) insight = 'Great performance! Solid First Class with Distinction.';
      else if (numSgpa >= 7.0) insight = 'Good standing! Consistent First Class performance.';
      else insight = 'Focus on high-weightage ESA subjects to boost your SGPA.';
      $('gpa-insight-text').textContent = `${insight} (${weightedPoints} grade points over ${totalCredits} credits).`;
    }
  }
}

// Wire up GPA section controls
$('btn-fetch-isa-marks')?.addEventListener('click', async () => {
  const btn = $('btn-fetch-isa-marks');
  const semSelect = $('gpa-semester-select');
  const selectedSem = semSelect?.value || '';
  btn.disabled = true;
  btn.textContent = 'Fetching…';
  try {
    const res = await fetch('/api/grades/isa/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semester: selectedSem || null })
    });
    const data = await res.json();
    if (res.status === 401) {
      openModal('modal-login');
      throw new Error('Please sign in to PESU Academy first.');
    }
    if (!res.ok) throw new Error(data.error || 'Failed to fetch marks');
    alert(data.message || 'ISA marks fetched successfully!');
    await loadGpaPredictor(selectedSem);
  } catch (e) {
    alert(`Could not fetch ISA marks: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '↻ Fetch Marks from PESU';
  }
});

$('btn-add-gpa-course')?.addEventListener('click', () => {
  const container = $('gpa-subjects-container');
  if (!container) return;
  if (container.querySelector('.empty')) container.replaceChildren();

  const newCourse = {
    subject_code: '',
    subject_name: 'New Course',
    credits: 4,
    isa1_score: 30,
    isa1_max: 40.0,
    isa2_score: 30,
    isa2_max: 40.0,
    assignment_score: 8,
    assignment_max: 10.0,
    target_grade: 'A',
    expected_esa: ''
  };
  gpaCourseList.push(newCourse);
  renderGpaCourseRows();
});

$('gpa-semester-select')?.addEventListener('change', () => {
  loadGpaPredictor($('gpa-semester-select').value);
});

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
// 10. SETTINGS & SYSTEM STATUS & THEMES
// =========================================================

const THEME_NAMES = {
  slate: 'Midnight Slate',
  onyx: 'Onyx Black',
  emerald: 'Nordic Forest',
  amber: 'Warm Amber',
  iris: 'Classic Iris'
};

function applyTheme(themeId) {
  const validTheme = THEME_NAMES[themeId] ? themeId : 'slate';
  document.documentElement.setAttribute('data-theme', validTheme);
  try { localStorage.setItem('betterpesu-theme', validTheme); } catch (_) {}
  document.querySelectorAll('.theme-tile').forEach(t => {
    t.classList.toggle('active', t.dataset.themeId === validTheme);
  });
  const nameEl = $('current-theme-name');
  if (nameEl) nameEl.textContent = THEME_NAMES[validTheme];
}

function applyGlow(enabled) {
  document.body.classList.toggle('no-glow', !enabled);
  try { localStorage.setItem('betterpesu-glow', enabled ? 'true' : 'false'); } catch (_) {}
  const glowToggle = $('toggle-ambient-glow');
  if (glowToggle) glowToggle.checked = enabled;
}

// Attach theme events
document.querySelectorAll('.theme-tile').forEach(tile => {
  tile.addEventListener('click', () => {
    applyTheme(tile.dataset.themeId);
  });
});

$('toggle-ambient-glow')?.addEventListener('change', e => {
  applyGlow(e.target.checked);
});

// Initialize theme immediately
try {
  const savedTheme = localStorage.getItem('betterpesu-theme') || 'slate';
  applyTheme(savedTheme);
  const savedGlow = localStorage.getItem('betterpesu-glow');
  applyGlow(savedGlow !== 'false');
} catch (_) {
  applyTheme('slate');
  applyGlow(true);
}

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
    const globalLoginBtn = $('btn-global-login');
    const userBadge = $('nav-user-badge');
    const userNameSpan = $('nav-user-name');
    const sideAuthBtn = $('sidebar-auth-btn');
    const authBadge = $('settings-auth-status-badge');

    if (authData.profile?.name) {
      const p = authData.profile;
      if (authBadge) {
        authBadge.textContent = 'Connected';
        authBadge.style.color = '#34d399';
        authBadge.style.borderColor = 'rgba(52, 211, 153, 0.3)';
        authBadge.style.background = 'rgba(52, 211, 153, 0.15)';
      }
      $('sidebar-student-name').textContent = p.name;
      if (userNameSpan) userNameSpan.textContent = p.name.split(' ')[0] || p.name;
      if (userBadge) userBadge.classList.remove('hidden');
      if (globalLoginBtn) globalLoginBtn.classList.add('hidden');
      if (sideAuthBtn) {
        sideAuthBtn.textContent = 'Log Out';
        sideAuthBtn.onclick = doLogout;
      }
      profCard.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
          <div style="font-size: 15px; font-weight: 700; color: var(--text-main);">${escapeHtml(p.name)}</div>
          <span class="badge-safe">Active Session</span>
        </div>
        <div class="profile-card-grid">
          <div class="profile-meta-item">
            <span class="profile-meta-label">SRN / Roll</span>
            <span class="profile-meta-val">${escapeHtml(p.srn || '–')}</span>
          </div>
          <div class="profile-meta-item">
            <span class="profile-meta-label">PRN</span>
            <span class="profile-meta-val">${escapeHtml(p.prn || '–')}</span>
          </div>
          <div class="profile-meta-item">
            <span class="profile-meta-label">Program & Branch</span>
            <span class="profile-meta-val">${escapeHtml(p.branch || 'Engineering')}</span>
          </div>
          <div class="profile-meta-item">
            <span class="profile-meta-label">Current Semester</span>
            <span class="profile-meta-val">${escapeHtml(p.semester || '–')}</span>
          </div>
          <div class="profile-meta-item">
            <span class="profile-meta-label">Campus</span>
            <span class="profile-meta-val">${escapeHtml(p.campus || 'PES University')}</span>
          </div>
        </div>
      `;
      loginBtn.classList.add('hidden');
      logoutBtn.classList.remove('hidden');
    } else {
      if (authBadge) {
        authBadge.textContent = 'Not Connected';
        authBadge.style.color = '#f87171';
        authBadge.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        authBadge.style.background = 'rgba(239, 68, 68, 0.15)';
      }
      $('sidebar-student-name').textContent = 'PESU Student';
      if (userBadge) userBadge.classList.add('hidden');
      if (globalLoginBtn) globalLoginBtn.classList.remove('hidden');
      if (sideAuthBtn) {
        sideAuthBtn.textContent = 'Connect';
        sideAuthBtn.onclick = () => openModal('modal-login');
      }
      profCard.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:6px;">
          <div style="font-weight:600; color:var(--text-main);">No Account Connected</div>
          <p class="subtle" style="margin:0;">Connect your student account to sync semester slides, view attendance history, timetable, and CIE/ISA marks directly.</p>
        </div>
      `;
      loginBtn.classList.remove('hidden');
      logoutBtn.classList.add('hidden');
    }
  } catch (e) {
    console.error('Settings check error:', e);
  }
}

$('btn-sync-all-settings')?.addEventListener('click', async () => {
  const btn = $('btn-sync-all-settings');
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '↻ Syncing All Academic Data…';
  try {
    await Promise.allSettled([
      fetch('/api/attendance/sync', { method: 'POST' }),
      fetch('/api/timetable/sync', { method: 'POST' }),
      fetch('/api/grades/isa/sync', { method: 'POST' })
    ]);
    await loadAttendanceHub();
    await loadTimetableDay(activeTimetableDay);
    await loadGpaPredictor();
    alert('Academic sync complete! Attendance, timetable, and marks are refreshed.');
  } catch (err) {
    alert('Sync error: ' + (err.message || 'Failed'));
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
});

$('btn-open-folder')?.addEventListener('click', () => {
  if (window.pywebview?.api?.open_slides_folder) {
    window.pywebview.api.open_slides_folder();
  } else {
    alert('Data folder: ' + $('settings-data-path').textContent);
  }
});

async function doLogout() {
  if (confirm('Log out and clear session cookies?')) {
    await fetch('/api/auth/logout', { method: 'POST' });
    await checkSystemAndAuth();
    await updateSemesterOptions();
    await loadAttendanceHub();
  }
}

$('btn-global-login')?.addEventListener('click', () => openModal('modal-login'));
$('btn-quick-logout')?.addEventListener('click', doLogout);
$('btn-login-modal')?.addEventListener('click', () => openModal('modal-login'));
$('btn-logout')?.addEventListener('click', doLogout);

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
    await checkSystemAndAuth();
    await updateSemesterOptions();
    try {
      await fetch('/api/attendance/sync', { method: 'POST' });
      await fetch('/api/timetable/sync', { method: 'POST' });
      await fetch('/api/grades/isa/sync', { method: 'POST' });
      await loadAttendanceHub();
      await loadTimetableDay(0);
      await loadGpaPredictor();
    } catch (_) {}
    alert('Logged in successfully! Your profile, timetable, and attendance are connected.');
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
  const attSelect = $('attendance-semester-select');
  const gpaSelect = $('gpa-semester-select');

  try {
    const response = await fetch('/api/semesters', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Semester discovery failed');

    // 1. Sync dropdown
    syncSemester.replaceChildren(new Option('All semesters', ''));
    for (const semester of result.semesters) {
      syncSemester.add(new Option(semester, semester));
    }
    if ([...syncSemester.options].some(option => option.value === previous)) {
      syncSemester.value = previous;
    }
    syncSemester.disabled = lastSyncRunning;

    // 2. Attendance semester dropdown
    if (attSelect) {
      const prevAtt = attSelect.value;
      attSelect.replaceChildren(new Option('All Semesters', ''));
      for (const sem of result.semesters) {
        attSelect.add(new Option(sem, sem));
      }
      if (prevAtt && [...attSelect.options].some(opt => opt.value === prevAtt)) {
        attSelect.value = prevAtt;
      } else if (result.semesters.length > 0) {
        // Automatically default to student's latest active semester (e.g. Sem-3)
        attSelect.value = result.semesters[result.semesters.length - 1];
        loadAttendanceHub(attSelect.value);
      }
    }

    // 3. GPA semester dropdown
    if (gpaSelect) {
      const prevGpa = gpaSelect.value;
      gpaSelect.replaceChildren();
      for (const sem of result.semesters) {
        gpaSelect.add(new Option(sem, sem));
      }
      if (prevGpa && [...gpaSelect.options].some(opt => opt.value === prevGpa)) {
        gpaSelect.value = prevGpa;
      } else if (result.semesters.length > 0) {
        // Automatically default to student's latest active semester (e.g. Sem-3)
        gpaSelect.value = result.semesters[result.semesters.length - 1];
        loadGpaPredictor(gpaSelect.value);
      }
    }
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
    if (response.status === 401) {
      openModal('modal-login');
      throw new Error('Please connect your PESU Academy account to sync materials.');
    }
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
