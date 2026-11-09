"""
Authentication and Session Manager for Better PESU Acad.
Provides modular authentication:
1. Direct PESU Academy web session (for slide downloads & live attendance)
2. Mobile API profile sync (for student name, SRN, PRN, branch, semester, section, campus)
3. OpenID Connect / OAuth2 PKCE adapter (for Sign in with PESU)
4. Offline / Guest mode support
Never logs passwords or session tokens.
"""

from __future__ import annotations

import os
import pickle
import re
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from backend.db import Database

logger = logging.getLogger("betterpesu.auth")

PESU_HOST = "https://www.pesuacademy.com"
PESU_ACADEMY = f"{PESU_HOST}/Academy"
MOBILE_LOGIN_URL = f"{PESU_HOST}/MAcademy/mobile/mobilelogin/auth"
MOBILE_DISPATCHER_URL = f"{PESU_HOST}/MAcademy/mobile/dispatcher"

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{PESU_ACADEMY}/s/studentProfilePESU",
}

MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Client-Type": "MOBILE",
}


@dataclass
class AuthResult:
    success: bool
    message: str
    profile: Optional[Dict[str, Any]] = None
    session_cookies: Optional[Dict[str, str]] = None


class AuthManager:
    def __init__(self, session_file: Path | str, db: Database):
        self.session_file = Path(session_file)
        self.db = db
        self.session = requests.Session()
        self.session.headers.update(WEB_HEADERS)
        self._load_saved_session()

    def _load_saved_session(self) -> bool:
        """Attempt to restore persisted cookies from user data directory."""
        if not self.session_file.is_file():
            return False
        try:
            with open(self.session_file, "rb") as f:
                cookies = pickle.load(f)
                self.session.cookies.update(cookies)
            return True
        except Exception as e:
            logger.warning("Could not load saved session: %s", e)
            return False

    def save_session(self) -> None:
        """Persist session cookies into user data directory."""
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(self.session_file) + ".part"
            with open(tmp, "wb") as f:
                pickle.dump(self.session.cookies, f)
            os.replace(tmp, self.session_file)
        except Exception as e:
            logger.warning("Could not save session cookies: %s", e)

    def clear_session(self) -> None:
        """Wipe cookies, saved session file, and profile records."""
        self.session.cookies.clear()
        if self.session_file.is_file():
            try:
                self.session_file.unlink()
            except OSError:
                pass
        self.db.clear_profile()

    def is_session_valid(self) -> bool:
        """Verify whether the current session cookies can access PESU Academy."""
        if not self.session.cookies:
            return False
        try:
            r = self.session.get(
                f"{PESU_ACADEMY}/s/studentProfilePESU",
                headers=WEB_HEADERS,
                timeout=8,
                allow_redirects=False
            )
            # 200 with HTML containing student info indicates active session; 302 to login indicates expired
            return r.status_code == 200 and "j_spring_security_check" not in r.text
        except Exception:
            return False

    def authenticate_direct(
        self,
        username: str,
        password: str,
        fetch_profile: bool = True
    ) -> AuthResult:
        """
        Authenticate with PESU Academy using credentials.
        Returns AuthResult indicating success/failure.
        """
        if not username or not password:
            return AuthResult(success=False, message="Username and password are required.")

        try:
            # 1. Fetch CSRF token from login page
            init_res = self.session.get(f"{PESU_ACADEMY}/", timeout=12)
            soup = BeautifulSoup(init_res.text, "html.parser")
            csrf_elem = soup.find("input", {"name": "_csrf"})
            if not csrf_elem or not csrf_elem.get("value"):
                return AuthResult(success=False, message="Could not retrieve CSRF security token from PESU Academy.")
            csrf = csrf_elem["value"]

            # 2. POST credentials
            login_res = self.session.post(
                f"{PESU_ACADEMY}/j_spring_security_check",
                data={
                    "j_username": username,
                    "j_password": password,
                    "_csrf": csrf,
                },
                timeout=15,
                allow_redirects=True
            )

            # Check if login page was redisplayed
            if "j_username" in login_res.text and ("Invalid Username/Password" in login_res.text or "login" in login_res.url):
                return AuthResult(success=False, message="Invalid PESU username or password.")

            self.save_session()

            profile_data = None
            if fetch_profile:
                # 3. Retrieve profile details via mobile dispatcher API or profile HTML
                profile_data = self.fetch_profile_mobile(username, password)
                if not profile_data:
                    profile_data = self._parse_profile_from_web(login_res.text, username)
                if profile_data:
                    self.db.save_profile(profile_data)

            return AuthResult(
                success=True,
                message="Successfully authenticated with PESU Academy.",
                profile=profile_data
            )

        except requests.exceptions.Timeout:
            return AuthResult(success=False, message="Connection timed out while contacting PESU Academy.")
        except requests.exceptions.RequestException as e:
            logger.error("Network error during login: %s", type(e).__name__)
            return AuthResult(success=False, message="Network error. Please check your internet connection.")
        except Exception as e:
            logger.exception("Unexpected error during login")
            return AuthResult(success=False, message=f"Authentication error: {str(e)}")

    def fetch_profile_mobile(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Fetch rich profile using the mobile API inspected in pesu-dev/auth.
        """
        try:
            m_session = requests.Session()
            m_session.headers.update(MOBILE_HEADERS)
            res = m_session.post(
                MOBILE_LOGIN_URL,
                data={
                    "j_username": username,
                    "j_password": password,
                    "j_appId": "YES",
                    "instId": "1,6,7,14",
                },
                timeout=10
            )
            if res.status_code != 200:
                return None
            data = res.json()
            if not data.get("status"):
                return None

            token = data.get("access_token") or data.get("token")
            # Query profile dispatcher
            headers = {**MOBILE_HEADERS}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            prof_res = m_session.post(
                MOBILE_DISPATCHER_URL,
                data={"action": "27", "mode": "1", "menuId": "11172"},
                headers=headers,
                timeout=10
            )
            if prof_res.status_code != 200:
                return None
            pdata = prof_res.json()
            student = pdata.get("studentProfile") or pdata.get("data") or {}

            info = student.get("studentInfo") or student
            name = (
                student.get("name")
                or f"{info.get('firstName', '')} {info.get('lastName', '')}".strip()
                or username
            )

            campus_code = student.get("campus") or info.get("campus")
            campus_name = "PES University (Ring Road)" if campus_code == 1 else "PES University (Electronic City)"

            return {
                "name": name,
                "srn": info.get("srn") or student.get("srn") or username,
                "prn": info.get("prn") or student.get("prn") or "",
                "branch": info.get("branch") or student.get("branch") or "",
                "semester": info.get("className") or student.get("semester") or "",
                "section": info.get("sectionName") or student.get("section") or "",
                "campus": campus_name,
                "email": info.get("email") or student.get("email") or "",
                "auth_provider": "pesu_direct"
            }
        except Exception as e:
            logger.debug("Mobile profile fetch fallback: %s", e)
            return None

    def _parse_profile_from_web(self, html: str, fallback_username: str) -> Dict[str, Any]:
        """Extract profile information from web portal HTML."""
        soup = BeautifulSoup(html, "html.parser")
        name_tag = soup.find(id="studentName") or soup.find(class_="user-profile-name")
        name = name_tag.get_text(strip=True) if name_tag else fallback_username

        srn_tag = soup.find(id="studentSRN") or soup.find(text=re.compile(r"PES\dUG\d\d[A-Z]{2}\d{3}"))
        raw_srn = srn_tag.strip() if srn_tag and isinstance(srn_tag, str) else fallback_username
        srn = re.sub(r'^(?:SRN\s*:\s*|Roll\s*:\s*)', '', raw_srn, flags=re.IGNORECASE).strip()

        # Look for PRN pattern
        prn_match = re.search(r'\b(PES\d{8,14})\b', html)
        prn = prn_match.group(1) if prn_match else ""

        # Campus
        campus = "PES University (Electronic City)" if "PES2" in srn.upper() else "PES University (Ring Road)"

        return {
            "name": name,
            "srn": srn,
            "prn": prn,
            "branch": "",
            "semester": "",
            "section": "",
            "campus": campus,
            "email": "",
            "auth_provider": "pesu_web"
        }
