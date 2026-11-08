from pathlib import Path
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from flask import Flask, jsonify, render_template, send_from_directory, request

BASE = Path(__file__).resolve().parent
app = Flask(__name__)
DATA = BASE / 'data' / 'courses.json'
SLIDES = BASE / 'slides'

# Sync runs only on the student's own computer, never on a public server.
_sync_lock = threading.Lock()
_sync_state = {'running': False, 'phase': 'idle', 'error': None, 'last_synced': None, 'progress': None, 'eta_seconds': None,
               'current_subject': None, 'processed': 0, 'total': None,
               'downloaded': 0, 'skipped': 0, 'failed_files': 0, 'converted': 0}

def _local_request():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return False
    host = request.host.split(':')[0].strip('[]').lower()
    if host not in ('localhost', '127.0.0.1', '::1'):
        return False
    origin = request.headers.get('Origin')
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc != request.host:
            return False
    if request.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
        return False
    return request.headers.get('X-BetterPESU-Action') == 'sync'

# Cache the PESU-provided semester names briefly to avoid repeated logins.
_semester_lock = threading.Lock()
_semester_cache = {'names': None, 'expires': 0}

def _available_semesters():
    with _semester_lock:
        if _semester_cache['names'] is not None and time.monotonic() < _semester_cache['expires']:
            return list(_semester_cache['names'])
        result = subprocess.run(
            [sys.executable, str(BASE / 'scraper' / 'downloader.py'), '--list-semesters'],
            cwd=str(BASE), capture_output=True, text=True, timeout=60, check=True,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'},
        )
        names = json.loads(result.stdout)
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError('Invalid semester listing')
        _semester_cache.update(names=names, expires=time.monotonic() + 300)
        return list(names)

@app.get('/api/semesters')
def semesters():
    # This endpoint triggers PESU authentication, so serve only local requests.
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'Local access only.'}), 403
    try:
        return jsonify({'semesters': _available_semesters()})
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        app.logger.warning('Semester discovery failed: %s', type(exc).__name__)
        return jsonify({'error': 'Could not load semesters from PESU Academy. Check .env credentials, network, and scraper logs.'}), 503

def _receive_progress(line, phase, started_at, previous_phase_time):
    prefix = 'BETTERPESU_PROGRESS:'
    if not line.startswith(prefix):
        return
    try:
        event = json.loads(line[len(prefix):])
    except (ValueError, TypeError):
        return
    name = event.get('event')
    with _sync_lock:
        if phase == 'downloading':
            if name == 'download_plan':
                _sync_state['total'] = event.get('total')
            elif name in ('subject_start', 'subject_complete', 'file'):
                _sync_state['current_subject'] = event.get('subject')
                for key in ('downloaded', 'skipped'):
                    if key in event:
                        _sync_state[key] = event[key]
                if 'failed' in event:
                    _sync_state['failed_files'] = event['failed']
                if name == 'subject_complete':
                    _sync_state['processed'] = event['done']
                    total = event['total']
                    _sync_state['total'] = total
                    # Download phase occupies 0-85%; completion is measured by subjects.
                    if total:
                        _sync_state['progress'] = round(85 * event['done'] / total, 1)
                        elapsed = time.monotonic() - started_at
                        _sync_state['eta_seconds'] = max(0, round(
                            elapsed / event['done'] * (total - event['done'])
                        )) if event['done'] and event['done'] < total else None
            return
        if name == 'conversion_plan':
            _sync_state.update(processed=0, total=event.get('total'),
                               progress=85, eta_seconds=None, current_subject=None)
        elif name == 'conversion_file':
            done, total = event['done'], event['total']
            _sync_state.update(processed=done, total=total, converted=event['converted'],
                               progress=round(85 + 15 * done / total, 1) if total else 100)
            elapsed = time.monotonic() - previous_phase_time
            _sync_state['eta_seconds'] = (max(0, round(elapsed / done * (total - done)))
                                          if done and done < total else None)


def _sync_worker(selection=None):
    try:
        sync_started = time.monotonic()
        for phase, script in (('downloading', 'downloader.py'), ('converting', 'converter.py')):
            phase_started = time.monotonic()
            with _sync_lock:
                _sync_state.update(phase=phase, eta_seconds=None,
                                   current_subject=None)
                if phase == 'converting':
                    _sync_state.update(progress=85, processed=0, total=None)
            command = [sys.executable, str(BASE / 'scraper' / script)]
            if selection:
                command.extend(['--semester', selection['semester']])
                if selection.get('subject_id'):
                    command.extend(['--subject-id', selection['subject_id']])
            elif script == 'downloader.py':
                command.append('--all-semesters')

            # Read structured progress as it is emitted, without buffering the whole output.
            process = subprocess.Popen(
                command, cwd=str(BASE), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'},
            )
            recent_output = []
            def read_output():
                for line in process.stdout:
                    line = line.rstrip('\n')
                    _receive_progress(line, phase, sync_started, phase_started)
                    if not line.startswith('BETTERPESU_PROGRESS:'):
                        recent_output.append(line)
                        if len(recent_output) > 20:
                            recent_output.pop(0)
            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            try:
                return_code = process.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                reader.join(timeout=3)
                raise
            reader.join(timeout=3)
            if return_code:
                app.logger.error('%s failed; recent output: %s', script, '\n'.join(recent_output))
                raise subprocess.CalledProcessError(return_code, command)
        with _sync_lock:
            _sync_state.update(last_synced=datetime.now(timezone.utc).isoformat(),
                               phase='complete', progress=100, eta_seconds=0,
                               current_subject=None)
    except subprocess.TimeoutExpired:
        with _sync_lock:
            _sync_state.update(phase='failed', error='Sync timed out. Check your downloader and network.',
                               eta_seconds=None)
    except subprocess.CalledProcessError:
        with _sync_lock:
            _sync_state.update(phase='failed', error='Downloader or converter failed. Check the Flask terminal.',
                               eta_seconds=None)
    except (OSError, ValueError) as exc:
        app.logger.exception('Could not complete sync')
        with _sync_lock:
            _sync_state.update(phase='failed', error='Could not run the sync scripts.',
                               eta_seconds=None)
    finally:
        with _sync_lock:
            _sync_state['running'] = False

@app.post('/api/sync')
def start_sync():
    if not _local_request():
        return jsonify({'error': 'Sync is allowed only from this local website.'}), 403
    missing = [name for name in ('downloader.py', 'converter.py')
               if not (BASE / 'scraper' / name).is_file()]
    if missing:
        return jsonify({'error': 'Missing scraper/' + ', '.join(missing)}), 400
    payload = request.get_json(silent=True) or {}
    semester = payload.get('semester')
    selection = None
    if semester is not None:
        if not isinstance(semester, str) or not semester.strip():
            return jsonify({'error': 'Invalid semester.'}), 400
        try:
            available = _available_semesters()
        except (subprocess.SubprocessError, OSError, ValueError):
            return jsonify({'error': 'Could not verify semesters with PESU Academy.'}), 503
        if semester not in available:
            return jsonify({'error': 'Semester not available on your PESU account.'}), 400
        selection = {'semester': semester}
    with _sync_lock:
        if _sync_state['running']:
            return jsonify({'error': 'Sync already running.'}), 409
        _sync_state.update(running=True, phase='starting', error=None, selection=selection,
                           progress=None, eta_seconds=None, current_subject=None,
                           processed=0, total=None, downloaded=0, skipped=0,
                           failed_files=0, converted=0)
        threading.Thread(target=_sync_worker, args=(selection,), daemon=True).start()
        return jsonify(dict(_sync_state)), 202

@app.post('/api/sync/subject')
def start_subject_sync():
    if not _local_request():
        return jsonify({'error': 'Local access only.'}), 403
    payload = request.get_json(silent=True) or {}
    semester, subject_id = payload.get('semester'), payload.get('subject_id')
    if not isinstance(semester, str) or not isinstance(subject_id, str):
        return jsonify({'error': 'Semester and subject ID are required.'}), 400
    if not DATA.is_file():
        return jsonify({'error': 'Sync materials first to build the subject list.'}), 400
    try:
        with DATA.open(encoding='utf-8') as handle:
            catalog = json.load(handle)
    except (OSError, ValueError):
        return jsonify({'error': 'Cannot read course catalog.'}), 500
    if not any(str(item.get('id')) == subject_id for item in catalog.get(semester, {}).values()):
        return jsonify({'error': 'Subject not found in your course catalog.'}), 400
    with _sync_lock:
        if _sync_state['running']:
            return jsonify({'error': 'A sync is already running.'}), 409
        selection = {'semester': semester, 'subject_id': subject_id}
        _sync_state.update(running=True, phase='starting', error=None, selection=selection,
                           progress=None, eta_seconds=None, current_subject=None,
                           processed=0, total=None, downloaded=0, skipped=0,
                           failed_files=0, converted=0)
        threading.Thread(target=_sync_worker, args=(selection,), daemon=True).start()
        return jsonify(dict(_sync_state)), 202

@app.get('/api/sync/status')
def sync_status():
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'error': 'Local access only.'}), 403
    with _sync_lock:
        return jsonify(dict(_sync_state))


@app.get('/')
def home():
    return render_template('index.html')

@app.get('/api/courses')
def courses():
    if not DATA.is_file():
        return jsonify({})
    try:
        with DATA.open(encoding='utf-8') as f:
            return jsonify(json.load(f))
    except (ValueError, OSError):
        return jsonify({'error': 'Could not read courses.json'}), 500

@app.get('/files/<path:filename>')
def files(filename):
    # Flask's safe_join inside send_from_directory prevents path traversal.
    return send_from_directory(SLIDES, filename, as_attachment=False)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
