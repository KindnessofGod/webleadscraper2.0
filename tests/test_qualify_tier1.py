from unittest.mock import patch

import requests

from src.qualify_tier1 import TIER1_PASS, TIER1_REJECT, TIER1_REJECT_CLOSED, qualify_tier1, website_resolves


def test_no_website_passes():
    lead = {"business_name": "Sunrise Clinic", "website": None, "permanently_closed": False}
    assert qualify_tier1(lead, timeout_seconds=5, treat_unresolvable_as_qualified=True) == TIER1_PASS


def test_permanently_closed_rejected_regardless_of_website():
    lead = {"business_name": "Old Clinic", "website": None, "permanently_closed": True}
    assert qualify_tier1(lead, timeout_seconds=5, treat_unresolvable_as_qualified=True) == TIER1_REJECT_CLOSED


@patch("src.qualify_tier1.website_resolves", return_value=True)
def test_resolvable_website_rejects(mock_resolves):
    lead = {"business_name": "Modern Clinic", "website": "http://modernclinic.ng", "permanently_closed": False}
    assert qualify_tier1(lead, timeout_seconds=5, treat_unresolvable_as_qualified=True) == TIER1_REJECT


@patch("src.qualify_tier1.website_resolves", return_value=False)
def test_unresolvable_website_passes_when_configured(mock_resolves):
    lead = {"business_name": "Dead Site Clinic", "website": "http://deadsite.ng", "permanently_closed": False}
    assert qualify_tier1(lead, timeout_seconds=5, treat_unresolvable_as_qualified=True) == TIER1_PASS


@patch("src.qualify_tier1.website_resolves", return_value=False)
def test_unresolvable_website_rejects_when_configured_strict(mock_resolves):
    lead = {"business_name": "Dead Site Clinic", "website": "http://deadsite.ng", "permanently_closed": False}
    assert qualify_tier1(lead, timeout_seconds=5, treat_unresolvable_as_qualified=False) == TIER1_REJECT


def test_website_resolves_handles_request_exception():
    with patch("requests.head", side_effect=requests.RequestException("boom")):
        assert website_resolves("http://example.com", timeout_seconds=1) is False


def test_website_resolves_true_for_2xx():
    class FakeResp:
        status_code = 200

    with patch("requests.head", return_value=FakeResp()):
        assert website_resolves("example.com", timeout_seconds=1) is True
