#!/usr/bin/env python3
"""環節三最小登入／角色邊界。

只支援專題 Demo 所需的 admin 與 station；session 存 SQLite、瀏覽器只持有
HttpOnly cookie。這不是企業 SSO，但 Backend 會真正拒絕未登入或角色不符的 request。
"""
import contextvars
import hashlib
import logging
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import ops_db


logger = logging.getLogger(__name__)

COOKIE = "irent_session"
SESSION_HOURS = 12
PBKDF2_ROUNDS = 210_000
ROLES = {"admin", "station"}
LOGIN_WINDOW_S = 60
LOGIN_MAX_FAILURES = 5
_login_failures: dict[tuple[str, str], list[float]] = {}
_login_lock = threading.Lock()


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    name: str
    role: str
    person_id: int | None = None

    def public(self) -> dict:
        return asdict(self)


_actor: contextvars.ContextVar[Actor | None] = contextvars.ContextVar("ops_actor", default=None)
SYSTEM_ACTOR = Actor(0, "system", "System", "system")
router = APIRouter(prefix="/api/auth", tags=["auth"])


def current_actor() -> Actor | None:
    return _actor.get()


def actor_values(actor: Actor | None = None) -> tuple[int | None, str | None, str | None]:
    actor = actor or current_actor()
    return (actor.id, actor.name, actor.role) if actor else (None, None, None)


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS).hex()


def _password_config() -> list[tuple[str, str, str, str]]:
    demo = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")
    admin_user = os.environ.get("IRENT_ADMIN_USERNAME", "admin")
    station_user = os.environ.get("IRENT_STATION_USERNAME", "station")
    admin_pw = os.environ.get("IRENT_ADMIN_PASSWORD") or ("admin-demo" if demo else "")
    station_pw = os.environ.get("IRENT_STATION_PASSWORD") or ("station-demo" if demo else "")
    # 即使環境誤留範例值，非 Demo 也不啟用弱密碼。
    if not demo and admin_user == "admin" and admin_pw == "admin-demo":
        admin_pw = ""
    if not demo and station_user == "station" and station_pw == "station-demo":
        station_pw = ""
    return [
        (admin_user, "營運主管", "admin", admin_pw),
        (station_user,
         os.environ.get("IRENT_STATION_NAME", "清潔組 A"), "station", station_pw),
    ]


def demo_login_hints() -> list[dict[str, str]]:
    """只在標準 Demo 帳密真的有效時，提供登入頁的一鍵填入提示。"""
    if os.environ.get("DEMO_MODE", "").lower() not in ("1", "true", "yes"):
        return []
    expected = {
        "admin": ("admin-demo", "管理者"),
        "station": ("station-demo", "站點人員"),
    }
    return [
        {"username": username, "password": password, "label": expected[username][1]}
        for username, _name, _role, password in _password_config()
        if username in expected and password == expected[username][0]
    ]


def _station_person(conn, name: str) -> int | None:
    """Station 帳號必須連結 ops_people 才能接單；找不到就自動建立並記 warning。"""
    person = conn.execute("SELECT id FROM ops_people WHERE name=?", (name,)).fetchone()
    if person:
        return person[0]
    group = name.split(" ")[0] if " " in name else "站點人員"
    created = ops_db.add_person(conn, group, name)
    logger.warning("IRENT_STATION_NAME=%r 不在 ops_people，已自動建立（group=%s, id=%s）",
                   name, group, created["id"])
    return created["id"]


def ensure_seed_users(conn) -> None:
    """首次建立 Demo 帳號；密碼後續可由環境變數驗證時安全輪替。

    只在 process 啟動與登入時呼叫（不在每個 request），因為它可能寫入。
    """
    for username, name, role, password in _password_config():
        row = conn.execute("SELECT * FROM ops_users WHERE username=?", (username,)).fetchone()
        if not password:
            if row and row["active"]:
                conn.execute("UPDATE ops_users SET active=0 WHERE id=?", (row["id"],))
            continue
        person_id = _station_person(conn, name) if role == "station" else None
        if row:
            person_id = row["person_id"] or person_id
            current_person = conn.execute(
                "SELECT name FROM ops_people WHERE id=?", (person_id,)).fetchone() if person_id else None
            display_name = current_person[0] if current_person else name
            desired = (display_name, role, 1, person_id)
            if desired != (row["display_name"], row["role"], row["active"], row["person_id"]):
                conn.execute("UPDATE ops_users SET display_name=?, role=?, active=1, person_id=? WHERE id=?",
                             (display_name, role, person_id, row["id"]))
            continue
        salt = secrets.token_bytes(16)
        values = (username, name, role, _hash_password(password, salt), salt.hex(),
                  person_id, ops_db.now_iso())
        if ops_db.dialect() == "sqlite":
            # Two first login requests may race on a fresh Demo volume.
            conn.execute(
                "INSERT OR IGNORE INTO ops_users(username, display_name, role, password_hash, password_salt, active, person_id, created_at)"
                " VALUES (?,?,?,?,?,1,?,?)", values)
        else:
            conn.execute(
                "INSERT INTO ops_users(username, display_name, role, password_hash, password_salt, active, person_id, created_at)"
                " VALUES (%s,%s,%s,%s,%s,1,%s,%s) ON CONFLICT(username) DO NOTHING", values)


def _configured_password(username: str) -> str | None:
    return next((password for user, _, _, password in _password_config() if user == username), None)


def _login_key(request: Request, username: str) -> tuple[str, str]:
    return ((request.client.host if request.client else "unknown"), username.casefold())


def _check_login_rate(key: tuple[str, str]) -> None:
    cutoff = time.monotonic() - LOGIN_WINDOW_S
    with _login_lock:
        recent = [at for at in _login_failures.get(key, []) if at >= cutoff]
        _login_failures[key] = recent
        if len(recent) >= LOGIN_MAX_FAILURES:
            raise HTTPException(429, "登入嘗試過於頻繁，請一分鐘後再試", headers={"Retry-After": "60"})


def _record_login(key: tuple[str, str], success: bool) -> None:
    with _login_lock:
        if success:
            _login_failures.pop(key, None)
        else:
            _login_failures.setdefault(key, []).append(time.monotonic())


def authenticate(username: str, password: str) -> Actor | None:
    with ops_db.db() as conn:
        ensure_seed_users(conn)
        row = conn.execute("SELECT * FROM ops_users WHERE username=? AND active=1", (username,)).fetchone()
        if not row:
            return None
        expected = _hash_password(password, bytes.fromhex(row["password_salt"]))
        if not secrets.compare_digest(expected, row["password_hash"]):
            # 環境變數變更後，以一次成功的新密碼登入完成 rotation。
            configured = _configured_password(username)
            if not configured or not secrets.compare_digest(password, configured):
                return None
            salt = secrets.token_bytes(16)
            conn.execute("UPDATE ops_users SET password_hash=?, password_salt=? WHERE id=?",
                         (_hash_password(password, salt), salt.hex(), row["id"]))
        return Actor(row["id"], row["username"], row["display_name"], row["role"], row["person_id"])


def create_session(actor: Actor) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=SESSION_HOURS)
    with ops_db.db() as conn:
        conn.execute("DELETE FROM ops_sessions WHERE expires_at < ?", (ops_db.now_iso(),))
        conn.execute("INSERT INTO ops_sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), actor.id, ops_db.now_iso(),
                      expires.isoformat(timespec="seconds")))
    return token, expires


def startup_seed() -> None:
    """Server 啟動時跑一次：建立 Demo 帳號、或在 DEMO_MODE 關閉後停用弱密碼帳號。

    以前是每個 request 都跑，等於每個帶 cookie 的請求（含靜態檔）都對 SQLite 寫入。
    """
    with ops_db.db() as conn:
        ensure_seed_users(conn)


def session_actor(token: str | None) -> Actor | None:
    """純讀取：request hot path 不做任何寫入。"""
    if not token:
        return None
    with ops_db.db() as conn:
        row = conn.execute(
            "SELECT u.* FROM ops_sessions s JOIN ops_users u ON u.id=s.user_id"
            " WHERE s.token_hash=? AND s.expires_at>=? AND u.active=1",
            (hashlib.sha256(token.encode()).hexdigest(), ops_db.now_iso())).fetchone()
    return Actor(row["id"], row["username"], row["display_name"], row["role"], row["person_id"]) if row else None


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    key = _login_key(request, body.username.strip())
    _check_login_rate(key)
    actor = authenticate(body.username.strip(), body.password)
    if not actor:
        _record_login(key, False)
        raise HTTPException(401, "帳號或密碼錯誤")
    _record_login(key, True)
    token, expires = create_session(actor)
    secure = os.environ.get("IRENT_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600,
                        httponly=True, secure=secure, samesite="strict", path="/")
    return {"user": actor.public()}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with ops_db.db() as conn:
            conn.execute("DELETE FROM ops_sessions WHERE token_hash=?",
                         (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    actor = session_actor(request.cookies.get(COOKIE))
    if not actor:
        raise HTTPException(401, "尚未登入")
    return {"user": actor.public()}


def _station_path_allowed(request: Request) -> bool:
    path, method = request.url.path, request.method
    if path == "/api/ops/my-tasks" and method == "GET":
        return True
    parts = path.strip("/").split("/")
    # /api/ops/tasks/{id}: lifecycle action；/photos: 完工照上傳／讀取。
    if len(parts) >= 4 and parts[:3] == ["api", "ops", "tasks"] and parts[3].isdigit():
        if len(parts) == 4 and method in ("GET", "PATCH"):
            return True
        if len(parts) >= 5 and parts[4] == "photos" and method in ("GET", "POST"):
            return True
    return False


# 需要 admin session 的監理台端點：會寫資料、會燒 Gemini 額度、或會外發通知。
# 刻意不擋（唯讀、無成本，且舊監理台在登入前就會抓）：
#   /api/health、/api/ops/health（登入頁要拿 demo_credentials）、/api/qr、
#   /api/labels/stats、/photos/*（資料集照片；整體服務本來就限內網）、/ops/* 靜態檔。
_ADMIN_API_PREFIXES = (
    "/api/ops/devtools",   # 內部開發工具（重設測試車輛、預載照片、pipeline 細節）：僅 admin，station 也不行
    "/api/decision", "/api/decisions", "/api/tasks", "/api/demo/",
    "/api/reload", "/api/rejudge", "/api/notify",
    "/api/judge", "/api/gate", "/api/live_case",   # live_case 同時涵蓋 /api/live_cases
)


async def auth_middleware(request: Request, call_next):
    actor = session_actor(request.cookies.get(COOKIE))
    request.state.ops_user = actor
    reset = _actor.set(actor)
    try:
        path = request.url.path
        protected_ops = path.startswith("/api/ops/") and path != "/api/ops/health"
        protected_admin = any(path.startswith(prefix) for prefix in _ADMIN_API_PREFIXES)
        if protected_ops or protected_admin:
            if not actor:
                return JSONResponse({"detail": "尚未登入"}, status_code=401)
            if protected_admin and actor.role != "admin":
                return JSONResponse({"detail": "此功能僅限管理者"}, status_code=403)
            if protected_ops and actor.role == "station" and not _station_path_allowed(request):
                return JSONResponse({"detail": "站點人員沒有此功能權限"}, status_code=403)
        return await call_next(request)
    finally:
        _actor.reset(reset)
