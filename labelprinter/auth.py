"""Password gate: a signed 7-day cookie, constant-time password check, and a failed-login throttle."""
import hashlib
import hmac
import os
import time
from pathlib import Path

COOKIE = "lp_session"
EXPIRY_SECONDS = 7 * 24 * 3600
MAX_FAILURES = 10
FAILURE_WINDOW = 600  # seconds


def get_session_key(data_dir: Path) -> bytes:
    """32 random bytes kept in data/.session-key, so logins survive a server restart."""
    data_dir.mkdir(exist_ok=True)
    key_file = data_dir / ".session-key"
    if key_file.exists() and len(key_file.read_bytes()) == 32:
        return key_file.read_bytes()
    key = os.urandom(32)
    key_file.write_bytes(key)
    return key


def _sign(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(key: bytes, now: float | None = None) -> str:
    expiry = str(int((time.time() if now is None else now) + EXPIRY_SECONDS))
    return f"{expiry}.{_sign(key, expiry)}"


def valid_token(token: str | None, key: bytes, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expiry, _, sig = token.strip().strip('"').partition(".")
    if not expiry.isdigit() or not hmac.compare_digest(sig, _sign(key, expiry)):
        return False
    return int(expiry) > (time.time() if now is None else now)


def password_ok(given: str, expected: str) -> bool:
    """Compared as bytes: compare_digest rejects non-ASCII str."""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class Throttle:
    """At most MAX_FAILURES wrong passwords per client in FAILURE_WINDOW seconds."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, who: str) -> list[float]:
        now = self._clock()
        kept = [t for t in self._failures.get(who, []) if now - t < FAILURE_WINDOW]
        self._failures[who] = kept
        return kept

    def blocked(self, who: str) -> bool:
        return len(self._recent(who)) >= MAX_FAILURES

    def record_failure(self, who: str) -> None:
        self._recent(who).append(self._clock())
