# Better PESU Acad — Desktop Student Companion

An installable, cross-platform desktop application for PES University students designed for focused studying, seamless lecture note synchronization, intelligent attendance tracking, timetable scheduling, and academic planning.

---

## ✦ Key Highlights

- **Native Desktop Application:** Built with Python, Flask, and `pywebview`, packaged with PyInstaller into a standalone executable (macOS `.app`, Windows `.exe`, Linux binary). No manual terminal commands or virtual environments needed for end users.
- **Dedicated Attendance Hub & Bunk Calculator:** Accurate mathematical simulation of attendance percentages, bunk thresholds ("How many classes can I miss?"), target achievement calculations ("How many classes must I attend?"), what-if sequence projections, and CSV import/export.
- **Offline-First Lecture Library:** Fast browsing of semesters, subjects, units, and classes with integrated PDF preview, full-text search, and bookmarking.
- **Fullscreen Focus Mode:** Distraction-free study workspace with an integrated Pomodoro timer (focus, short break, long break, custom intervals) and completed session logging.
- **Timetable & Planner:** Daily class schedules, lab markers, and assignment tracking with priority, due date indicators, and completion status.
- **SGPA & CIE Evaluator:** Autonomous grade-point calculator and Continuous Internal Evaluation estimator distinguishing official from hypothetical performance.
- **Background Synchronization:** Packaging-compatible background synchronization engine with honest progress, cancelability, backoff retries, and PPTX-to-PDF conversion via LibreOffice.
- **Local & Private:** Zero third-party telemetry. All passwords, session tokens, database files, and lecture PDFs remain strictly on the student's personal computer.

---

## 1. Prerequisites

- **Python 3.10+** (if running from source or building bundles)
- **LibreOffice** (optional, recommended for automatic PowerPoint-to-PDF conversion)

### Installing LibreOffice
- **macOS:** Download from [libreoffice.org](https://www.libreoffice.org/download/download-libreoffice/) or install via Homebrew:
  ```bash
  brew install --cask libreoffice
  ```
- **Windows:** Download the installer from [libreoffice.org](https://www.libreoffice.org/download/download-libreoffice/).
- **Linux:**
  ```bash
  sudo apt update && sudo apt install libreoffice
  ```

---

## 2. Quick Start & Installation

### Installing on macOS (Direct Application)
The standalone macOS application bundle is pre-built and ready. To install it into your system's `/Applications` folder:
```bash
./scripts/install_macos.sh
```
Or manually:
```bash
cp -R "dist/Better PESU Acad.app" /Applications/
xattr -cr "/Applications/Better PESU Acad.app"
```
Once copied, launch it via:
- **Spotlight:** Press `Cmd + Space`, type `Better PESU Acad`, and hit Enter.
- **Launchpad:** Click the **Better PESU Acad** icon.
- **Finder:** Open `/Applications/Better PESU Acad.app`.
- **Terminal:** `open -a "Better PESU Acad"`

### Installing on Windows (One-Click Setup)
1. Download `BetterPESU-Setup.exe` from the latest GitHub Release.
2. Double-click `BetterPESU-Setup.exe` and follow the prompt (no administrator permissions required).
3. The app will be installed to your local programs folder, with Desktop and Start Menu shortcuts automatically created.
4. Launch via Start Menu / Search: **Better PESU Acad**.

### Running from Source
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the desktop application
python app.py

# Or run in browser/headless server mode:
python app.py --server-only --port 5000
```

---

## 3. Packaging & Building Standalone Desktop Applications

Standalone packages bundle all Python runtimes, libraries, templates, and static assets into a native binary.

### macOS (.app Bundle)
Run the automated build script on macOS:
```bash
./scripts/build_macos.sh
```
The output bundle will be located at:
```text
dist/Better PESU Acad.app
```
To launch:
```bash
open "dist/Better PESU Acad.app"
```

### Windows (Executable & Setup Wizard)
Run on Windows 10/11:
```cmd
scripts\build_windows.bat
```
The standalone executable folder will be located at `dist\BetterPESU\BetterPESU.exe`.

To build the one-click installer (`BetterPESU-Setup.exe`):
```cmd
iscc installer.iss
```
The installer will be generated at `dist-installer\BetterPESU-Setup.exe`. Alternatively, run the automated **Build Windows Installer** workflow on GitHub Actions.

### Linux (Binary)
Run on Linux:
```bash
./scripts/build_linux.sh
```
The binary will be located at:
```text
dist/BetterPESU/BetterPESU
```

---

## 4. Architecture & Module Overview

```text
better-pesu-acad/
├── app.py                     # Unified entry point (Desktop GUI or --server-only)
├── BetterPESU.spec            # Cross-platform PyInstaller packaging specification
├── requirements.txt           # Project dependencies
├── backend/
│   ├── config.py              # OS-specific application data directory and LibreOffice detection
│   ├── db.py                  # SQLite storage layer (profile, attendance, assignments, bookmarks, timer)
│   ├── app.py                 # Main Flask server with protected localhost endpoints
│   ├── academic/
│   │   ├── attendance.py      # Attendance calculation formulas, bunk matrices, and CSV I/O
│   │   ├── grades.py          # SGPA, CGPA, and CIE internal marks calculations
│   │   ├── planner.py         # Assignment lifecycle and timetable scheduling
│   │   └── provider.py        # Live attendance & timetable scraping from PESU Academy
│   ├── auth/
│   │   └── manager.py         # Modular authentication (Web session, mobile profile, token storage)
│   └── jobs/
│       ├── sync_manager.py    # Thread-safe background sync coordinator
│       ├── downloader_engine.py# Materials downloader with duplicate check
│       └── converter_engine.py # Headless LibreOffice conversion worker
├── desktop/
│   └── launcher.py            # pywebview desktop window runner, dynamic port binder, desktop bridge
├── templates/
│   └── index.html             # Single-page application HTML template
├── static/
│   ├── app.js                 # Complete reactive frontend controller
│   └── style.css              # Purple-accented dark and light glassmorphic UI
├── tests/
│   ├── test_attendance_calculator.py
│   ├── test_academic_planner.py
│   ├── test_backend_api.py
│   ├── test_db.py
│   ├── test_scraper_regression.py
│   └── test_sync_manager.py
├── scripts/
│   ├── build_macos.sh         # macOS application bundle builder
│   ├── build_windows.bat      # Windows packaging batch script
│   └── build_linux.sh         # Linux build script
└── docs/
    └── pesu-integration-research.md # In-depth technical research on PESU APIs & ecosystem
```

---

## 5. Attendance Math & Formulas

Let:
- $A$: Number of classes attended
- $T$: Number of classes conducted
- $p$: Target fraction (e.g. $0.75$ for 75%)

### Current Attendance
$$\text{Attendance} = \frac{A}{T} \times 100 \quad (T > 0)$$

### Missing $k$ Future Classes
$$\text{Projected} = \frac{A}{T + k} \times 100$$

### Classes Needed to Reach Target
$$n = \max\left(0, \left\lceil \frac{pT - A}{1 - p} \right\rceil\right) \quad (\text{for } p < 1.0)$$
*Note: If target is 100% and $A < T$, reaching 100% is mathematically impossible; the application explicitly warns the student.*

### Maximum Classes Can Bunk Retaining Target
$$k = \max\left(0, \left\lfloor \frac{A}{p} - T \right\rfloor\right)$$

---

## 6. Running Tests

Run the full automated test suite:
```bash
pytest tests/
```
All 25 unit and regression tests will execute, validating:
- Attendance formulas, bunk calculations, and boundary edge cases
- Academic planner and grade calculations
- Local SQLite database operations
- REST endpoints and directory traversal prevention
- Downloader and converter regression integrity

---

## 7. Privacy, Security & Disclaimers

1. **Unofficial Application:** This software is an independent student productivity tool and is not affiliated with, authorized, or maintained by PES University or PESU Academy.
2. **Local Storage:** Credentials, session cookies, database files, and lecture PDFs are stored strictly in your operating system's standard user data folder (`~/Library/Application Support/BetterPESU` on macOS, `%APPDATA%\BetterPESU` on Windows).
3. **No External Proxies:** The application communicates directly with `pesuacademy.com`. No credentials or student records are ever transmitted to third-party proxy servers.
4. **Localhost Bound:** The internal server binds only to `127.0.0.1` on dynamically allocated ephemeral ports with origin and header verification.
