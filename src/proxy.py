"""Residential proxy session management. Supports two providers so the
pipeline can be debugged for free before spending paid DataImpulse credit:

  - webshare    -- free plan gives 10 static proxy IPs, each with its own
                    fixed host:port, connected to *directly* (Webshare
                    dashboard: Proxy Settings -> "Direct Connection"
                    method). There is no shared gateway domain and no
                    per-request country/session targeting on this plan --
                    each of the 10 IPs is just whatever fixed IP/country
                    Webshare handed out. Good enough to verify the scraper
                    works end-to-end at zero cost; not Nigeria-specific and
                    not necessarily residential-quality, so expect a higher
                    block rate than the real pilot.
  - dataimpulse -- $1/GB pay-as-you-go, $5 minimum, non-expiring, true
                    rotating residential with free country-level targeting.
                    Use this for the real, spec-scoped pilot once the
                    scraper is verified working on Webshare's free tier.

IMPORTANT: DataImpulse's username-parameter syntax (country targeting,
sticky-session port range) is verified against their public docs as of
this writing but is a third-party detail that can drift -- before running
real traffic, confirm it against docs.dataimpulse.com and adjust
`_build_dataimpulse_username` / `DATAIMPULSE_STICKY_PORT_RANGE` if it has
changed. Getting this wrong burns paid bandwidth for nothing.

Documented DataImpulse format (gw.dataimpulse.com:823, HTTP/SOCKS5):
  - plain: login:password
  - country targeting (free): login__cr.ng:password
  - sticky session: connect on a port in the 10000-20000 range; the same
    port keeps the same exit IP for a configurable window (default 30
    min, max 120 min). We pick a deterministic port per session id.
"""
from __future__ import annotations

import itertools
import random
import time
from dataclasses import dataclass

DATAIMPULSE_STICKY_PORT_RANGE = (10000, 20000)
DATAIMPULSE_ROTATING_PORT = 823


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


# Backwards-compatible alias.
build_username = _build_dataimpulse_username


def parse_static_proxy_list(raw: str) -> list[tuple[str, int]]:
    """Parses "host:port,host:port,..." (as pasted from Webshare's Free ->
    Proxy List page) into [(host, port), ...]. Blank entries are skipped.
    """
    pairs: list[tuple[str, int]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, _, port = entry.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"invalid proxy entry {entry!r}, expected host:port")
        pairs.append((host, int(port)))
    return pairs


class ProxyPool:
    """Round-robins proxy sessions across `concurrent_sessions` slots.

    dataimpulse: gateway mode -- one host, sticky sessions minted via a
    deterministic sticky port + username suffix, rotated out after
    `sticky_minutes` or on CAPTCHA cooldown.

    webshare: static-list mode -- each slot is assigned one of the fixed
    proxy IPs from `static_proxies` (round-robin by slot index); the same
    username/password is shared across all of them (per the Webshare
    dashboard). "Rotating" here just means moving a slot to a different
    entry in the static list on cooldown -- there's no concept of a fresh
    exit IP the way DataImpulse's gateway provides one.
    """

    def __init__(
        self,
        provider: str,
        base_username: str,
        password: str,
        concurrent_sessions: int,
        sticky_minutes: int,
        host: str | None = None,
        country: str | None = None,
        static_proxies: list[tuple[str, int]] | None = None,
    ):
        if provider == "dataimpulse":
            if not host:
                raise ValueError("provider='dataimpulse' requires host=")
        elif provider == "webshare":
            if not static_proxies:
                raise ValueError(
                    "provider='webshare' requires static_proxies= (paste host:port pairs from "
                    "Webshare -> Free -> Proxy List into WEBSHARE_PROXIES in .env)"
                )
        else:
            raise ValueError(f"unknown proxy provider: {provider!r} (expected 'webshare' or 'dataimpulse')")

        self.provider = provider
        self.host = host
        self.country = country
        self.static_proxies = static_proxies or []
        self.base_username = base_username
        self.password = password
        self.concurrent_sessions = concurrent_sessions
        self.sticky_minutes = sticky_minutes
        self._counter = itertools.count()
        self._sessions: dict[int, ProxySession] = {}
        self._cooldowns: dict[int, float] = {}  # slot -> resume_at timestamp
        self._generation: dict[int, int] = {}   # slot -> how many times it's been rotated (webshare list-walk)

    def _new_session(self, slot: int) -> ProxySession:
        session_id = f"{int(time.time())}{next(self._counter)}"

        if self.provider == "dataimpulse":
            port = DATAIMPULSE_STICKY_PORT_RANGE[0] + (
                hash(session_id) % (DATAIMPULSE_STICKY_PORT_RANGE[1] - DATAIMPULSE_STICKY_PORT_RANGE[0])
            )
            username = _build_dataimpulse_username(self.base_username, self.country, session_id)
            host = self.host
        else:  # webshare static list
            generation = self._generation.get(slot, 0)
            idx = (slot + generation * self.concurrent_sessions) % len(self.static_proxies)
            host, port = self.static_proxies[idx]
            username = self.base_username  # same credentials for every static IP on this plan

        return ProxySession(session_id=session_id, username=username, password=self.password, host=host, port=port, created_at=time.time())

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
        self._generation[slot] = self._generation.get(slot, 0) + 1
        session = self._new_session(slot)
        self._sessions[slot] = session
        return session

    def cooldown(self, slot: int, minutes: float) -> None:
        self._cooldowns[slot] = time.time() + minutes * 60
        self.rotate(slot)
