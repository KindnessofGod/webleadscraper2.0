from src.proxy import (
    WEBSHARE_PORT,
    DATAIMPULSE_STICKY_PORT_RANGE,
    ProxyPool,
    _build_dataimpulse_username,
    _build_webshare_username,
)


def test_dataimpulse_username_with_country_and_session():
    assert _build_dataimpulse_username("user", "ng", "abc123") == "user__cr.ng;sessid.abc123"


def test_dataimpulse_username_plain():
    assert _build_dataimpulse_username("user", None, None) == "user"


def test_webshare_username_with_country_and_session():
    assert _build_webshare_username("user", "ng", "abc123") == "user-ng-abc123"


def test_webshare_username_plain():
    assert _build_webshare_username("user", None, None) == "user"


def test_pool_rejects_unknown_provider():
    import pytest

    with pytest.raises(ValueError):
        ProxyPool(provider="bogus", host="h", base_username="u", password="p", country="ng", concurrent_sessions=1, sticky_minutes=10)


def test_webshare_pool_uses_fixed_port_and_hyphen_username():
    pool = ProxyPool(provider="webshare", host="p.webshare.io", base_username="user", password="pw", country="ng", concurrent_sessions=2, sticky_minutes=10)
    session = pool.get(slot=0)
    assert session.port == WEBSHARE_PORT
    assert session.username.startswith("user-ng-")


def test_dataimpulse_pool_uses_sticky_port_range_and_dunder_username():
    pool = ProxyPool(provider="dataimpulse", host="gw.dataimpulse.com", base_username="user", password="pw", country="ng", concurrent_sessions=2, sticky_minutes=10)
    session = pool.get(slot=0)
    assert DATAIMPULSE_STICKY_PORT_RANGE[0] <= session.port < DATAIMPULSE_STICKY_PORT_RANGE[1]
    assert session.username.startswith("user__cr.ng;sessid.")


def test_pool_reuses_session_within_sticky_window():
    pool = ProxyPool(provider="webshare", host="h", base_username="u", password="p", country="ng", concurrent_sessions=1, sticky_minutes=10)
    first = pool.get(slot=0)
    second = pool.get(slot=0)
    assert first.session_id == second.session_id


def test_cooldown_rotates_session_and_borrows_other_slot():
    pool = ProxyPool(provider="webshare", host="h", base_username="u", password="p", country="ng", concurrent_sessions=2, sticky_minutes=10)
    original = pool.get(slot=0)
    pool.cooldown(slot=0, minutes=5)
    borrowed = pool.get(slot=0)
    assert borrowed.session_id != original.session_id
    assert borrowed.session_id == pool.get(slot=1).session_id
