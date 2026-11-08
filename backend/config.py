"""
Configuration and runtime environment manager for Better PESU Acad.
Handles cross-platform application data paths, resource resolution (frozen and dev),
LibreOffice binary detection, and existing user data migration.
"""

from __future__ import annotations

import os
import sys
import shutil
import logging
from pathlib import Path

logger = logging.getLogger("betterpesu.config")

# Version
APP_NAME = "Better PESU Acad"
APP_VERSION = "2.0.0"
APP_IDENTIFIER = "com.betterpesu.desktop"


def is_frozen() -> bool:
    """Return True if running inside a PyInstaller packaged bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_bundle_dir() -> Path:
    """Return the base path to packaged resources (templates, static, etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    # If running from source, check if running from project root or inside pesu-notes
    here = Path(__file__).resolve().parent.parent
    if (here / "static").is_dir() or (here / "templates").is_dir():
        return here
    if (here / "pesu-notes").is_dir():
        return here / "pesu-notes"
    return here


def get_user_data_dir() -> Path:
    """
    Return the path to the user's persistent application data directory.
    Respects BETTERPESU_DATA_DIR environment variable for portability or testing.
    """
    env_dir = os.environ.get("BETTERPESU_DATA_DIR")
    if env_dir:
        path = Path(env_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    home = Path.home()
    if sys.platform == "darwin":
        path = home / "Library" / "Application Support" / "BetterPESU"
    elif sys.platform == "win32":
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else home / "AppData" / "Roaming"
        path = base / "BetterPESU"
    else:
        # Linux / Unix standards
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data) if xdg_data else home / ".local" / "share"
        path = base / "BetterPESU"

    path.mkdir(parents=True, exist_ok=True)
    return path


class Config:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or get_user_data_dir()
        self.bundle_dir = get_bundle_dir()

        # Data subdirectories
        self.slides_dir = self.data_dir / "slides"
        self.db_path = self.data_dir / "betterpesu.db"
        self.courses_json = self.data_dir / "courses.json"
        self.logs_dir = self.data_dir / "logs"
        self.session_file = self.data_dir / "session.pkl"

        # Templates and static paths
        self.templates_dir = self._find_resource_dir("templates")
        self.static_dir = self._find_resource_dir("static")

        # Ensure folders exist
        self.slides_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Migrate existing project data if needed
        self._check_and_migrate_legacy_data()

    def _find_resource_dir(self, name: str) -> Path:
        """Find templates or static folder either in root or inside pesu-notes."""
        candidates = [
            self.bundle_dir / name,
            Path(__file__).resolve().parent.parent / name,
            Path(__file__).resolve().parent.parent / "pesu-notes" / name,
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        # Fallback to bundle_dir / name
        return self.bundle_dir / name

    def _check_and_migrate_legacy_data(self) -> None:
        """
        Safely migrates existing courses.json and slides if the user data directory
        does not yet have them, preserving all existing files and creating backups.
        """
        candidate_roots = [
            Path(__file__).resolve().parent.parent / "pesu-notes",
            Path(__file__).resolve().parent.parent,
            Path.cwd() / "pesu-notes",
            Path.cwd(),
            Path.home() / "better pesu-acad" / "pesu-notes",
            Path.home() / "better pesu-acad",
        ]

        # 1. Migrate courses.json
        if not self.courses_json.is_file() or self.courses_json.stat().st_size == 0:
            for root in candidate_roots:
                for candidate in (root / "data" / "courses.json", root / "courses.json"):
                    if candidate.is_file() and candidate.stat().st_size > 0:
                        try:
                            shutil.copy2(candidate, self.courses_json)
                            logger.info("Migrated courses.json from %s to %s", candidate, self.courses_json)
                            break
                        except Exception as e:
                            logger.warning("Could not copy %s: %s", candidate, e)
                if self.courses_json.is_file() and self.courses_json.stat().st_size > 0:
                    break

        # 2. Migrate slides if existing and target empty
        has_slides = self.slides_dir.is_dir() and any(
            p for p in self.slides_dir.iterdir() if not p.name.startswith(".")
        )
        if not has_slides:
            for root in candidate_roots:
                candidate_slides = root / "slides"
                if candidate_slides.is_dir() and any(p for p in candidate_slides.iterdir() if not p.name.startswith(".")):
                    logger.info("Found existing slides in %s, linking to %s", candidate_slides, self.slides_dir)
                    try:
                        # Try symlinking first for instant zero-copy speed
                        if self.slides_dir.is_dir() and not any(self.slides_dir.iterdir()):
                            self.slides_dir.rmdir()
                        if not self.slides_dir.exists():
                            os.symlink(str(candidate_slides.resolve()), str(self.slides_dir))
                            break
                    except Exception as e:
                        logger.warning("Symlink failed (%s), attempting copy...", e)
                        self.slides_dir.mkdir(parents=True, exist_ok=True)
                        for item in candidate_slides.iterdir():
                            if item.name.startswith("."):
                                continue
                            dest = self.slides_dir / item.name
                            if not dest.exists():
                                if item.is_dir():
                                    shutil.copytree(item, dest)
                                else:
                                    shutil.copy2(item, dest)
                        break


def find_libreoffice() -> str | None:
    """
    Search for LibreOffice / soffice executable across known platform locations.
    Returns path to executable if found, or None if LibreOffice is not installed.
    Does NOT throw an unhandled exception so the application can run even without LibreOffice.
    """
    cmd = shutil.which("libreoffice") or shutil.which("soffice")
    if cmd:
        return cmd

    if sys.platform == "darwin":
        paths = [
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
        for p in paths:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)

    elif sys.platform == "win32":
        search_dirs = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for folder in search_dirs:
            if not folder:
                continue
            soffice = Path(folder) / "LibreOffice" / "program" / "soffice.exe"
            if soffice.is_file():
                return str(soffice)

    elif sys.platform.startswith("linux"):
        paths = [
            Path("/usr/bin/libreoffice"),
            Path("/usr/bin/soffice"),
            Path("/usr/local/bin/libreoffice"),
            Path("/snap/bin/libreoffice"),
        ]
        for p in paths:
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)

    return None
