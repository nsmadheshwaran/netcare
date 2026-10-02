import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: int, token_version: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "tv": token_version, "iat": now,
               "exp": now + timedelta(minutes=s.access_token_minutes), "typ": "access"}
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "access" else None


class LoginLimiter:
    """In-process sliding-window limiter for failed logins.

    Single-process only; behind multiple workers use a shared store (see SECURITY.md).
    """

    def __init__(self):
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, window: int) -> deque:
        q = self._fails[key]
        cutoff = time.monotonic() - window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        s = get_settings()
        with self._lock:
            return len(self._prune(key, s.login_window_seconds)) >= s.login_max_attempts

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_limiter = LoginLimiter()
