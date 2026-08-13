import pytest

from src.proxy import (
    DATAIMPULSE_STICKY_PORT_RANGE,
    ProxyPool,
    _build_dataimpulse_username,
    parse_static_proxy_list,
)

STATIC_PROXIES = [("1.1.1.1", 6754), ("2.2.2.2", 7684), ("3.3.3.3", 6014)]


def test_dataimpulse_username_with_country_and_session():
    assert _build_dataimpulse_username("user", "ng", "abc123") == "user__cr.ng;sessid.abc123"


def test_dataimpulse_username_plain():
    assert _build_dataimpulse_username("user", None, None) == "user"


def test_parse_static_proxy_list():
    assert parse_static_proxy_list("1.1.1.1:6754, 2.2.2.2:7684") == [("1.1.1.1", 6754), ("2.2.2.2", 7684)]


def test_parse_static_proxy_list_skips_blanks():
    assert parse_static_proxy_list("1.1.1.1:6754,,  ,2.2.2.2:7684") == [("1.1.1.1", 6754), ("2.2.2.2", 7684)]


def test_parse_static_proxy_list_rejects_malformed_entry():
    with pytest.raises(ValueError):
        parse_static_proxy_list("not-a-host-port-pair")


def test_pool_rejects_unknown_provider():
    with pytest.raises(ValueError):
        ProxyPool(provider="bogus", base_username="u", password="p", concurrent_sessions=1, sticky_minutes=10)


def test_dataimpulse_requires_host():
    with pytest.raises(ValueError):
        ProxyPool(provider="dataimpulse", base_username="u", password="p", concurrent_sessions=1, sticky_minutes=10)


def test_webshare_requires_static_proxies():
    with pytest.raises(ValueError):
        ProxyPool(provider="webshare", base_username="u", password="p", concurrent_sessions=1, sticky_minutes=10)


def test_webshare_pool_assigns_static_ip_per_slot_with_shared_credentials():
    pool = ProxyPool(provider="webshare", static_proxies=STATIC_PROXIES, base_username="user", password="pw", concurrent_sessions=2, sticky_minutes=10)
    session0 = pool.get(slot=0)
    session1 = pool.get(slot=1)
    assert (session0.host, session0.port) == STATIC_PROXIES[0]
    assert (session1.host, session1.port) == STATIC_PROXIES[1]
    assert session0.username == "user"
    assert session1.username == "user"


def test_dataimpulse_pool_uses_sticky_port_range_and_dunder_username():
    pool = ProxyPool(provider="dataimpulse", host="gw.dataimpulse.com", base_username="user", password="pw", country="ng", concurrent_sessions=2, sticky_minutes=10)
    session = pool.get(slot=0)
    assert DATAIMPULSE_STICKY_PORT_RANGE[0] <= session.port < DATAIMPULSE_STICKY_PORT_RANGE[1]
    assert session.username.startswith("user__cr.ng;sessid.")


def test_pool_reuses_session_within_sticky_window():
    pool = ProxyPool(provider="webshare", static_proxies=STATIC_PROXIES, base_username="u", password="p", concurrent_sessions=1, sticky_minutes=10)
    first = pool.get(slot=0)
    second = pool.get(slot=0)
    assert first.session_id == second.session_id


def test_cooldown_rotates_session_and_borrows_other_slot():
    pool = ProxyPool(provider="webshare", static_proxies=STATIC_PROXIES, base_username="u", password="p", concurrent_sessions=2, sticky_minutes=10)
    original = pool.get(slot=0)
    pool.cooldown(slot=0, minutes=5)
    borrowed = pool.get(slot=0)
    assert borrowed.session_id != original.session_id
    assert borrowed.session_id == pool.get(slot=1).session_id


def test_webshare_rotate_walks_to_a_different_static_ip():
    pool = ProxyPool(provider="webshare", static_proxies=STATIC_PROXIES, base_username="u", password="p", concurrent_sessions=1, sticky_minutes=10)
    first = pool.get(slot=0)
    rotated = pool.rotate(slot=0)
    assert (first.host, first.port) != (rotated.host, rotated.port)
