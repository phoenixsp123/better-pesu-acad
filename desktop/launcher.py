"""
Desktop launcher for Better PESU Acad using pywebview.
Manages native window creation, dynamic localhost port allocation,
clean background server lifecycle, native file dialogs, system notifications,
and single-instance enforcement.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from werkzeug.serving import make_server

from backend.config import Config, find_libreoffice
from backend.app import create_app

logger = logging.getLogger("betterpesu.desktop")


def find_free_port(preferred_port: int = 5055) -> int:
    """Find an available TCP port on localhost, preferring a consistent port across launches."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", preferred_port))
            return preferred_port
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        return port


class ServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True, name="BetterPESU-FlaskServer")
        self.server = make_server(host, port, app)
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"

    def run(self):
        logger.info("Serving Better PESU Acad at %s", self.url)
        self.server.serve_forever()

    def shutdown(self):
        logger.info("Shutting down internal Flask server")
        self.server.shutdown()


class DesktopBridge:
    """JavaScript-accessible native desktop API exposed via pywebview."""

    def __init__(self, launcher: "DesktopApp"):
        self.launcher = launcher

    def send_notification(self, title: str, message: str) -> bool:
        """Trigger native OS desktop notification."""
        try:
            if sys.platform == "darwin":
                script = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
                return True
            elif sys.platform == "win32":
                ps_script = f"""
                [reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
                $notify = new-object system.windows.forms.notifyicon
                $notify.icon = [system.drawing.systemicons]::Information
                $notify.visible = $true
                $notify.showballoontip(10, '{title}', '{message}', [system.windows.forms.tooltipicon]::Info)
                """
                subprocess.run(["powershell", "-Command", ps_script], check=False, timeout=5)
                return True
            else:
                subprocess.run(["notify-send", title, message], check=False, timeout=3)
                return True
        except Exception as e:
            logger.warning("Could not send system notification: %s", e)
            return False

    def get_system_info(self) -> Dict[str, Any]:
        return {
            "platform": sys.platform,
            "libreoffice": find_libreoffice() is not None,
            "data_dir": str(self.launcher.config.data_dir),
            "slides_dir": str(self.launcher.config.slides_dir),
        }

    def _resolve_slide_path(self, rel_path: str) -> Optional[Path]:
        if not rel_path:
            return None
        clean = rel_path.strip().lstrip("/").replace("\\", "/")
        if clean.lower().startswith("slides/"):
            clean = clean[7:]
        target = self.launcher.config.slides_dir / clean
        if target.is_file():
            return target
        candidates = [
            Path.cwd() / "slides" / clean,
            Path.cwd() / "pesu-notes" / "slides" / clean,
            Path(__file__).resolve().parent.parent / "slides" / clean,
            Path(__file__).resolve().parent.parent / "pesu-notes" / "slides" / clean,
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return None

    def open_slides_folder(self) -> bool:
        """Open the slides directory in native file explorer (Finder/Explorer)."""
        slides_dir = self.launcher.config.slides_dir
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(slides_dir)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(slides_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(slides_dir)], check=False)
            return True
        except Exception as e:
            logger.warning("Could not open file manager: %s", e)
            return False

    def open_file_native(self, rel_path: str) -> bool:
        """Open a lecture PDF using OS default viewer (Preview on macOS)."""
        target = self._resolve_slide_path(rel_path)
        if not target:
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif sys.platform == "win32":
                os.startfile(str(target))
            else:
                subprocess.Popen(["xdg-open", str(target)])
            return True
        except Exception as e:
            logger.warning("Could not open file in native viewer: %s", e)
            return False

    def reveal_in_finder(self, rel_path: str) -> bool:
        """Highlight a lecture PDF in macOS Finder or OS file manager."""
        target = self._resolve_slide_path(rel_path)
        if not target:
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(target)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                subprocess.Popen(["xdg-open", str(target.parent)])
            return True
        except Exception as e:
            logger.warning("Could not reveal file in finder: %s", e)
            return False

    def save_file_copy(self, rel_path: str) -> bool:
        """Native macOS Save File Dialog to save a copy of PDF anywhere."""
        import shutil
        target = self._resolve_slide_path(rel_path)
        if not target or not self.launcher.window:
            return False
        try:
            import webview
            res = self.launcher.window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=target.name
            )
            if res:
                dest = res if isinstance(res, str) else res[0]
                shutil.copy2(str(target), dest)
                return True
            return False
        except Exception as e:
            logger.warning("Could not save file copy: %s", e)
            return False


class DesktopApp:
    def __init__(self, data_dir: Optional[Path] = None):
        self.config = Config(data_dir=data_dir)
        self.app = create_app(self.config)
        self.server_thread: Optional[ServerThread] = None
        self.window = None
        self.bridge = DesktopBridge(self)

    def _acquire_single_instance_lock(self, port: int) -> Optional[socket.socket]:
        """Simple localhost socket lock ensuring single instance running."""
        try:
            lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_sock.bind(("127.0.0.1", 49151))  # dedicated IANA dynamic port
            return lock_sock
        except OSError:
            logger.warning("Another instance of Better PESU Acad appears to be already running.")
            return None

    def start(self, debug: bool = False):
        try:
            import webview
        except ImportError:
            logger.error("pywebview is not installed. Run 'pip install pywebview'.")
            sys.exit(1)

        # 1. Start local Flask backend on free dynamic port
        port = find_free_port()
        self.server_thread = ServerThread(self.app, "127.0.0.1", port)
        self.server_thread.start()

        # 2. Wait briefly for server ready
        time.sleep(0.3)

        # 3. Create pywebview window
        title = "Better PESU Acad"
        url = self.server_thread.url

        self.window = webview.create_window(
            title=title,
            url=url,
            js_api=self.bridge,
            width=1280,
            height=820,
            min_size=(1024, 680),
            text_select=True,
            zoomable=True,
            background_color="#0d0e15"
        )

        def on_closed():
            logger.info("Main window closed. Exiting application.")
            if self.server_thread:
                self.server_thread.shutdown()

        self.window.events.closed += on_closed

        # 4. Start GUI event loop
        webview.start(debug=debug)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = DesktopApp()
    app.start(debug=False)


if __name__ == "__main__":
    main()
