"""DataImpulse residential proxy session management.

IMPORTANT: DataImpulse's username-parameter syntax (country targeting,
sticky-session id, port ranges) is verified against their public docs/blog
posts as of this writing but is a third-party detail that can change --
before running any real traffic, confirm the current syntax against your
own DataImpulse dashboard (docs.dataimpulse.com) and adjust
`build_username` / `STICKY_PORT_RANGE` if it has drifted. Getting this
wrong burns paid bandwidth without qualifying any leads.

Documented format (gw.dataimpulse.com:823, HTTP/SOCKS5):
  - plain: login:password
  - country targeting (free): login__cr.ng:password
  - sticky session: connect on a port in the 10000-20000 range: the same
    port keeps the same exit IP for a configurable window (default 30 min,
    max 120 min). We pick a deterministic port per session id so the same
    logical "session" always reuses the same sticky IP.
"""
from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass

STICKY_PORT_RANGE = (10000, 20000)
ROTATING_PORT = 823


@dataclass
class ProxySession:
    session_id: str
    username: str
    password: str
    host: str
    port: int
    created_at: float

    def playwright_proxy(self) -> dict:
        return {
            "server": f"http://{self.host}:{self.port}",
            "username": self.username,
            "password": self.password,
        }

    def age_minutes(self) -> float:
        return (time.time() - self.created_at) / 60


def build_username(base_username: str, country: str | None = None, session_id: str | None = None) -> str:
    parts = []
    if country:
        parts.append(f"cr.{country.lower()}")
    if session_id:
        parts.append(f"sessid.{session_id}")
    if not parts:
        return base_username
    return f"{base_username}__{';'.join(parts)}"


class ProxyPool:
    """Round-robins a fixed number of sticky proxy sessions, rotating a
    session out (new session id -> new sticky port -> fresh exit IP) once
    it exceeds `sticky_minutes` or is explicitly marked dead (e.g. after a
    CAPTCHA cooldown).
    """

    def __init__(self, host: str, base_username: str, password: str, country: str, concurrent_sessions: int, sticky_minutes: int):
        self.host = host
        self.base_username = base_username
        self.password = password
        self.country = country
        self.concurrent_sessions = concurrent_sessions
        self.sticky_minutes = sticky_minutes
        self._counter = itertools.count()
        self._sessions: dict[int, ProxySession] = {}
        self._cooldowns: dict[int, float] = {}  # slot -> resume_at timestamp

    def _new_session(self, slot: int) -> ProxySession:
        session_id = f"{int(time.time())}{next(self._counter)}"
        port = STICKY_PORT_RANGE[0] + (hash(session_id) % (STICKY_PORT_RANGE[1] - STICKY_PORT_RANGE[0]))
        username = build_username(self.base_username, self.country, session_id)
        return ProxySession(session_id=session_id, username=username, password=self.password, host=self.host, port=port, created_at=time.time())

    def get(self, slot: int | None = None) -> ProxySession:
        """Get a session for the given slot (0..concurrent_sessions-1), or a
        random slot if none given. Rotates automatically past sticky_minutes.
        """
        if slot is None:
            slot = random.randrange(self.concurrent_sessions)

        resume_at = self._cooldowns.get(slot)
        if resume_at and time.time() < resume_at:
            # this slot is cooling down after a CAPTCHA; borrow another slot
            other = (slot + 1) % self.concurrent_sessions
            return self.get(other)

        session = self._sessions.get(slot)
        if session is None or session.age_minutes() >= self.sticky_minutes:
            session = self._new_session(slot)
            self._sessions[slot] = session
        return session

    def rotate(self, slot: int) -> ProxySession:
        session = self._new_session(slot)
        self._sessions[slot] = session
        return session

    def cooldown(self, slot: int, minutes: float) -> None:
        self._cooldowns[slot] = time.time() + minutes * 60
        self.rotate(slot)
