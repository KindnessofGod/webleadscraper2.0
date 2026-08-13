"""Residential proxy session management. Supports two providers so the
pipeline can be debugged for free before spending paid DataImpulse credit:

  - webshare   -- permanent free tier (10 proxies / 1GB residential per
                  month, no card required). Use this to shake out scraper
                  selector bugs at zero cost.
  - dataimpulse -- $1/GB pay-as-you-go, $5 minimum, non-expiring. Use this
                  for the real pilot once the scraper is verified working
                  on Webshare's free tier.

IMPORTANT: both providers' username-parameter syntax (country targeting,
sticky-session id, port ranges) is verified against their public docs as
of this writing but is a third-party detail that can drift -- before
running any real traffic, confirm the current syntax against your own
dashboard (Webshare's "Endpoint Generator", or docs.dataimpulse.com) and
adjust the relevant `_build_*_username` function if it has changed.
Getting this wrong burns bandwidth without qualifying any leads.

Documented formats:
  DataImpulse (gw.dataimpulse.com:823, HTTP/SOCKS5):
    - plain: login:password
    - country targeting (free): login__cr.ng:password
    - sticky session: connect on a port in the 10000-20000 range; the same
      port keeps the same exit IP for a configurable window (default 30
      min, max 120 min). We pick a deterministic port per session id.

  Webshare (p.webshare.io, default port 80; residential plans only):
    - plain: login:password
    - country targeting: login-ng:password
    - sticky session: login-ng-<session_id>:password (same session_id ->
      same exit IP for that session's lifetime)
    - explicitly rotating: login-ng-rotate:password (new IP every request)
    Session control lives in the username, not the port -- unlike
    DataImpulse, all requests go through the same port.
"""
from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass

DATAIMPULSE_STICKY_PORT_RANGE = (10000, 20000)
DATAIMPULSE_ROTATING_PORT = 823
WEBSHARE_PORT = 80


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


def _build_dataimpulse_username(base_username: str, country: str | None, session_id: str | None) -> str:
    parts = []
    if country:
        parts.append(f"cr.{country.lower()}")
    if session_id:
        parts.append(f"sessid.{session_id}")
    if not parts:
        return base_username
    return f"{base_username}__{';'.join(parts)}"


def _build_webshare_username(base_username: str, country: str | None, session_id: str | None) -> str:
    parts = [base_username]
    if country:
        parts.append(country.lower())
    if session_id:
        parts.append(session_id)
    return "-".join(parts)


# Backwards-compatible alias (existing callers / tests may reference this).
build_username = _build_dataimpulse_username


class ProxyPool:
    """Round-robins a fixed number of sticky proxy sessions, rotating a
    session out (new session id -> fresh exit IP) once it exceeds
    `sticky_minutes` or is explicitly marked dead (e.g. after a CAPTCHA
    cooldown). Provider-agnostic: pass provider="webshare" or
    provider="dataimpulse".
    """

    def __init__(
        self,
        provider: str,
        host: str,
        base_username: str,
        password: str,
        country: str,
        concurrent_sessions: int,
        sticky_minutes: int,
    ):
        if provider not in ("webshare", "dataimpulse"):
            raise ValueError(f"unknown proxy provider: {provider!r} (expected 'webshare' or 'dataimpulse')")
        self.provider = provider
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

        if self.provider == "dataimpulse":
            port = DATAIMPULSE_STICKY_PORT_RANGE[0] + (
                hash(session_id) % (DATAIMPULSE_STICKY_PORT_RANGE[1] - DATAIMPULSE_STICKY_PORT_RANGE[0])
            )
            username = _build_dataimpulse_username(self.base_username, self.country, session_id)
        else:  # webshare
            port = WEBSHARE_PORT
            username = _build_webshare_username(self.base_username, self.country, session_id)

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
