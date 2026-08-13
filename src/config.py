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

    # Webshare proxy (free tier: 10 proxies / 1GB residential per month)
    webshare_host: str = os.getenv("WEBSHARE_HOST", "p.webshare.io")
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

    def active_proxy_credentials(self) -> tuple[str, str, str]:
        """Returns (host, username, password) for whichever provider
        PROXY_PROVIDER selects."""
        if self.proxy_provider == "dataimpulse":
            return self.dataimpulse_host, self.dataimpulse_username, self.dataimpulse_password
        if self.proxy_provider == "webshare":
            return self.webshare_host, self.webshare_username, self.webshare_password
        raise ValueError(f"unknown PROXY_PROVIDER: {self.proxy_provider!r} (expected 'webshare' or 'dataimpulse')")

    def grid_config(self, city: str) -> dict:
        return _load_yaml(f"grid_{city.lower()}.yaml")


def load_config() -> Config:
    return Config()
