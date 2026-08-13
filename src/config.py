"""Loads .env credentials and config/*.yaml settings into a single object."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class Config:
    settings: dict = field(default_factory=lambda: _load_yaml("settings.yaml"))
    categories: dict = field(default_factory=lambda: _load_yaml("categories.yaml"))

    # Which proxy provider is active: "webshare" (free tier, for debugging
    # the scraper at zero cost) or "dataimpulse" (paid, for the real pilot).
    proxy_provider: str = os.getenv("PROXY_PROVIDER", "webshare")

    # DataImpulse proxy ($1/GB pay-as-you-go)
    dataimpulse_host: str = os.getenv("DATAIMPULSE_HOST", "gw.dataimpulse.com")
    dataimpulse_username: str = os.getenv("DATAIMPULSE_USERNAME", "")
    dataimpulse_password: str = os.getenv("DATAIMPULSE_PASSWORD", "")

    # Webshare proxy (free tier: 10 static proxy IPs, direct connection --
    # no shared gateway domain. WEBSHARE_PROXIES is a comma-separated
    # host:port list pasted from the dashboard's Free -> Proxy List page.
    webshare_proxies: str = os.getenv("WEBSHARE_PROXIES", "")
    webshare_username: str = os.getenv("WEBSHARE_USERNAME", "")
    webshare_password: str = os.getenv("WEBSHARE_PASSWORD", "")

    # Tier 2 search API
    tier2_provider: str = os.getenv("TIER2_SEARCH_PROVIDER", "serper")
    tier2_api_key: str = os.getenv("TIER2_SEARCH_API_KEY", "")

    db_path: str = os.getenv("DB_PATH", str(ROOT / "data" / "leads.db"))

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dotted lookup into settings.yaml, e.g. cfg.get('cost', 'pilot_ceiling_usd')."""
        node: Any = self.settings
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def build_proxy_pool(self, concurrent_sessions: int, sticky_minutes: int, country: str):
        """Constructs a ProxyPool for whichever provider PROXY_PROVIDER
        selects. Kept here (rather than inline in the pipeline) so the
        provider-specific credential shapes -- DataImpulse's single gateway
        host vs. Webshare's static IP list -- stay in one place.
        """
        from src.proxy import ProxyPool, parse_static_proxy_list

        if self.proxy_provider == "dataimpulse":
            return ProxyPool(
                provider="dataimpulse", host=self.dataimpulse_host,
                base_username=self.dataimpulse_username, password=self.dataimpulse_password,
                country=country, concurrent_sessions=concurrent_sessions, sticky_minutes=sticky_minutes,
            )
        if self.proxy_provider == "webshare":
            proxies = parse_static_proxy_list(self.webshare_proxies)
            if not proxies:
                raise ValueError(
                    "WEBSHARE_PROXIES is empty. Paste host:port pairs from your Webshare dashboard's "
                    "Free -> Proxy List page into .env, comma-separated, e.g. "
                    "WEBSHARE_PROXIES=31.59.20.176:6754,31.56.127.193:7684"
                )
            return ProxyPool(
                provider="webshare", static_proxies=proxies,
                base_username=self.webshare_username, password=self.webshare_password,
                concurrent_sessions=concurrent_sessions, sticky_minutes=sticky_minutes,
            )
        raise ValueError(f"unknown PROXY_PROVIDER: {self.proxy_provider!r} (expected 'webshare' or 'dataimpulse')")

    def grid_config(self, city: str) -> dict:
        return _load_yaml(f"grid_{city.lower()}.yaml")


def load_config() -> Config:
    return Config()
