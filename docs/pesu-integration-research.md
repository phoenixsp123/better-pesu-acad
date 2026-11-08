# PESU Developer Ecosystem & Integration Research

**Document Version:** 1.0.0  
**Project:** Better PESU Acad — Desktop Student Companion  
**Date:** November 2026  
**Status:** Verified & Documented  

---

## 1. Executive Summary

This document details the technical research into existing PES University developer community tools, undocumented university endpoints, authentication mechanics, attendance calculation models, and integration strategies for the **Better PESU Acad** desktop application.

We conducted source code audits and protocol inspections across the following repositories:
1. `pesu-dev/auth` (Mobile API credential verification & profile extraction)
2. `pesu-dev/oauth2` (Unofficial OpenID Connect authorization server specification)
3. `GlowingScrewdriver/attendance_calci` (Browser extension for attendance simulation and bunk calculations)
4. `pesu-dev/pesuacademy` (Historical Python scraping client and endpoint reference)
5. `Better PESU Acad` (Baseline web app: Spring Security form authentication, course scraping, LibreOffice conversion)

---

## 2. Source-by-Source Technical Audit

### 2.1 `pesu-dev/auth`
- **Primary Endpoint:** `https://www.pesuacademy.com/MAcademy/mobile/mobilelogin/auth`
- **Dispatcher Endpoint:** `https://www.pesuacademy.com/MAcademy/mobile/dispatcher`
- **Protocol:** JSON over HTTPS with custom header `X-Client-Type: MOBILE`.
- **Authentication Flow:**
  - POSTs `j_username`, `j_password`, `j_appId="YES"`, and `instId="1,6,7,14"`.
  - On success, PESU Academy returns a bearer access token and initial user metadata.
  - Profile details are fetched via `dispatcher` with form payload `{"action": "27", "mode": "1", "menuId": "11172"}` and the bearer token.
- **Data Returned:**
  - Name (First, Middle, Last)
  - Student identifiers: PRN, SRN
  - Academic metadata: Program (e.g. B.Tech), Branch, Semester (`class_name`), Section (`section_name`)
  - Contact: PESU official email, mobile number
  - Campus: Campus Name ("PES University (Ring Road)", "PES University (Electronic City)") and inferred campus code.
- **Key Constraints & Limitations:**
  - **Does NOT return course materials, attendance records, timetable, or examination results.**
  - Undocumented mobile API subject to unannounced breaking changes when university releases new mobile app builds.
  - Useful as a secondary/modular profile retriever and credential validator.

### 2.2 `pesu-dev/oauth2`
- **Protocol:** OpenID Connect (OIDC) Authorization Code Flow with **PKCE** (RFC 7636, S256).
- **Core Endpoints:**
  - `GET /.well-known/openid-configuration` (Discovery)
  - `GET /jwks.json` (Public RS256 key set)
  - `GET /authorize` (Interactive authorization screen with PKCE challenge)
  - `POST /token` (Code exchange with PKCE verifier)
  - `GET / POST /userinfo` (Bearer token authentication)
- **Supported Scopes (v1 MVP):**
  - `openid`, `profile`, `email`, `phone`, `offline_access`.
- **Claims Exposed:**
  - `sub`: Opaque identifier (`usr_...`).
  - `profile`: Student name, PRN, SRN, program, branch, semester, section, campus.
  - `email`, `phone`: When authorized.
- **Critical Architectural Finding:**
  - **PESU OAuth2 is strictly an Identity Provider (IdP)**. As documented in its canonical spec (`docs/superpowers/specs/2026-09-03-oidc-authorization-server-design.md`), API resource scopes for academic records (attendance, course slides, grades) are explicit non-goals in v1.
  - **OIDC access tokens cannot authorize downloads of course slides or fetch university attendance.**
  - Production publishing requires manual verification by community administrators; unapproved clients operate in a restricted "testing" mode.
  - **Conclusion for Better PESU Acad:** We provide a pluggable OAuth2/OIDC client for Sign In with PESU to retrieve the student profile without handling raw credentials when available, but direct university session access remains necessary for syncing course materials and attendance.

### 2.3 `GlowingScrewdriver/attendance_calci`
- **Purpose:** Chrome/Firefox extension injecting simulation controls directly into PESU Academy's `#studentAttendanceSemester` table.
- **Mathematical Formulas Verified:**
  Let:
  - $A$: Number of classes attended
  - $T$: Number of classes conducted (total)
  - $p$: Target attendance fraction ($0 < p < 1$, e.g. $0.75$ for 75%)

  1. **Current Attendance Percentage:**
     $$\text{Percent} = \frac{A}{T} \times 100 \quad (T > 0)$$
     If $T = 0$, attendance is undefined (conventionally treated as 100% or not applicable).

  2. **Bunking $k$ future classes ($k \ge 0$):**
     $$\text{Projected} = \frac{A}{T + k} \times 100$$

  3. **Attending $n$ consecutive future classes ($n \ge 0$):**
     $$\text{Projected} = \frac{A + n}{T + n} \times 100$$

  4. **Minimum classes $n$ needed to reach or restore target $p$:**
     $$\frac{A + n}{T + n} \ge p \iff A + n \ge pT + pn \iff n(1 - p) \ge pT - A$$
     For $p < 1.0$:
     $$n = \max\left(0, \left\lceil \frac{pT - A}{1 - p} \right\rceil\right)$$
     *Edge Case:* If $p \ge 1.0$ (100%):
     - If $A = T$, $n = 0$.
     - If $A < T$, $100\%$ is mathematically impossible because $\lim_{n \to \infty} \frac{A+n}{T+n} = 1.0$ from below; it strictly never reaches 1.0 once a single class is missed.

  5. **Maximum classes $k$ that can be missed while staying above or equal to target $p$:**
     $$\frac{A}{T + k} \ge p \iff p(T + k) \le A \iff pk \le A - pT \iff k \le \frac{A}{p} - T$$
     $$k = \max\left(0, \left\lfloor \frac{A}{p} - T \right\rfloor\right)$$
     If current attendance is already below target ($A / T < p$), $k = 0$.

### 2.4 `pesu-dev/pesuacademy` (Historical Reference) & Live PESU Academy Scraping
- **Authentication:** Spring Security form-based login at `/Academy/j_spring_security_check` with `_csrf` token parsed from `/Academy/`.
- **Session Preservation:** Cookies stored in session; subsequent requests must use `Referer: https://www.pesuacademy.com/Academy/s/studentProfilePESU` and `X-Requested-With: XMLHttpRequest`.
- **Known Menu IDs & Controller Modes:**
  - Courses: `menuId=653`, `controllerMode=6403`, `actionType=38`
  - Course Units: `actionType=42`, `actionType=43`
  - Course Documents/Materials: `actionType=60`
  - Attendance: `menuId=660`, `controllerMode=6407`, `actionType=8`, `batchClassId=<semester_id>`
  - Timetable: `menuId=669`, `controllerMode=6415`, `actionType=5`
  - Results / SGPA: `menuId=652`, `controllerMode=6402`, `actionType=9` (ISA/ESA) / `actionType=53` (Provisional)
  - Announcements: `menuId=667`, `controllerMode=6411`, `actionType=5`

---

## 3. Integration Strategy for Better PESU Acad Desktop

### 3.1 Modular Authentication Architecture
To prevent tight coupling to unstable endpoints or exposing student credentials:
1. **Local Direct PESU Academy Session (Default & Compatibility):**
   - The user enters credentials locally in the desktop app.
   - Credentials are used directly against `https://www.pesuacademy.com` to establish an authenticated session cookie jar.
   - Credentials are never logged, never transmitted to any third-party proxy, and may be optionally remembered via local OS-level secure storage or user-controlled configuration.
2. **Mobile API Profile Extractor:**
   - On successful login, the app retrieves the official student profile (name, SRN, PRN, branch, semester, section, campus).
3. **Pluggable OAuth2 / OIDC Adapter:**
   - Architecture includes an OpenID Connect client supporting Authorization Code Flow + PKCE with local loopback callback (`http://127.0.0.1:<port>/oauth/callback`).
   - If an official or community PESU OAuth2 endpoint is configured in Settings, the user can authenticate their identity via OAuth2.
4. **Offline / Guest Mode:**
   - Full access to previously downloaded slides, local assignments, personal notes, study timer, and offline attendance calculator without requiring an account.

### 3.2 Attendance Strategy
1. **Automated Scraping Provider:**
   - Queries `menuId=660` when authenticated with the student's session.
   - Parses the attendance table rows: Subject Code, Subject Title, Attended/Total (`X/Y`), and Percentage.
   - Stores attendance snapshots in local SQLite with timestamps.
2. **Manual Entry & CSV Import/Export:**
   - If university attendance endpoints fail, are under maintenance, or if the user is offline, the app provides a manual attendance entry interface with CSV import/export.
   - The user can adjust attended/total numbers, edit subject targets, and perform what-if bunking calculations.

### 3.3 Security, Privacy & Compliance Guidelines
- **Unofficial Status:** The desktop application is completely unofficial and independent. Explicit disclaimers are presented in the onboarding flow and settings.
- **Localhost-Only Backend:** The internal Python server binds strictly to `127.0.0.1` on a dynamically assigned port with an internal session secret / CSRF token to prevent local cross-origin attacks from malicious browser tabs.
- **Data Isolation:** User data is saved in standard OS app data directories (`~/Library/Application Support/BetterPESU` on macOS, `%APPDATA%\BetterPESU` on Windows, `~/.local/share/BetterPESU` on Linux), with existing repository files (`data/courses.json` and `slides/`) migrated safely without destruction.
