"""Password gate: a signed 7-day cookie, constant-time password check, a failed-login throttle, and sign-out that sticks."""
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path

COOKIE = "lp_session"
EXPIRY_SECONDS = 7 * 24 * 3600
MAX_FAILURES = 10         # per client: more wrong passwords than this and that client's sign-ins are slowed (SLOW_DELAY)
MAX_GLOBAL_FAILURES = 40  # all clients together: past this, everyone's sign-ins are slowed
FAILURE_WINDOW = 600  # seconds
SLOW_DELAY = 3.0      # seconds each password check waits while slowed; one check at a time, so at most 1 guess per SLOW_DELAY (20 a minute)
SLOW_QUEUE = 4        # sign-ins allowed to wait while slowed; more than this get "busy"


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
    """expiry.session-id.signature: the id is what sign-out revokes."""
    expiry = str(int((time.time() if now is None else now) + EXPIRY_SECONDS))
    sid = secrets.token_hex(8)
    return f"{expiry}.{sid}.{_sign(key, f'{expiry}.{sid}')}"


def parse_token(token: str | None, key: bytes, now: float | None = None) -> tuple[str, int] | None:
    """(session id, expiry) of a correctly signed, unexpired token; None for anything else."""
    parts = (token or "").strip().strip('"').split(".")
    if len(parts) != 3:
        return None
    expiry, sid, sig = parts
    if not expiry.isdigit() or not hmac.compare_digest(sig, _sign(key, f"{expiry}.{sid}")):
        return None
    if int(expiry) <= (time.time() if now is None else now):
        return None
    return sid, int(expiry)


def valid_token(token: str | None, key: bytes, now: float | None = None, revoked: "Revoked | None" = None) -> bool:
    parsed = parse_token(token, key, now)
    return parsed is not None and (revoked is None or parsed[0] not in revoked)


class Revoked:
    """Session ids that signed out. Each is kept until its cookie would have expired anyway, and (with a path)
    survives a server restart, so a cookie copied before sign-out stops working."""

    def __init__(self, path: Path | None = None, clock=time.time):
        self._path, self._clock = path, clock
        self._ids: dict[str, int] = {}
        if path is not None and path.exists():
            try:
                self._ids = {str(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
            except (ValueError, OSError, AttributeError):
                self._ids = {}   # unreadable list: start empty rather than refuse to start
        self._prune()

    def _prune(self) -> None:
        now = self._clock()
        self._ids = {sid: exp for sid, exp in self._ids.items() if exp > now}

    def __contains__(self, sid: str) -> bool:
        return sid in self._ids

    def add(self, sid: str, expiry: int) -> None:
        self._prune()
        self._ids[sid] = expiry
        if self._path is not None:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._ids), encoding="utf-8")
            os.replace(tmp, self._path)


def password_ok(given: str, expected: str) -> bool:
    """Compared as bytes: compare_digest rejects non-ASCII str."""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class Throttle:
    """Counts wrong passwords in FAILURE_WINDOW seconds, per client and for everyone together. Over MAX_FAILURES for a
    client (blocked) or over MAX_GLOBAL_FAILURES overall (slow), the server checks passwords one at a time with a delay.
    Guessing is then capped at one try per SLOW_DELAY whatever the addresses, and a correct password still gets in:
    refusing outright would let anyone lock the owner out by failing on purpose (and behind a proxy every visitor shares
    one address)."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._all: deque[float] = deque()

    def _recent(self, who: str) -> list[float]:
        now = self._clock()
        kept = [t for t in self._failures.get(who, []) if now - t < FAILURE_WINDOW]
        if kept:
            self._failures[who] = kept
        else:
            self._failures.pop(who, None)  # no key for a client with nothing recent
        return kept

    def _recent_global(self) -> int:
        now = self._clock()
        while self._all and now - self._all[0] >= FAILURE_WINDOW:
            self._all.popleft()
        return len(self._all)

    def blocked(self, who: str) -> bool:
        return len(self._recent(who)) >= MAX_FAILURES

    def slow(self) -> bool:
        return self._recent_global() >= MAX_GLOBAL_FAILURES

    def record_failure(self, who: str) -> None:
        now = self._clock()
        self._recent(who)  # prune this client's expired stamps first
        self._failures.setdefault(who, []).append(now)
        self._all.append(now)
