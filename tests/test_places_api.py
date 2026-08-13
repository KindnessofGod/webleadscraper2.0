from src.grid import GridCell
from src.places_api import _to_lead

CELL = GridCell(id="vi_0_0", zone="victoria_island", lat=6.4225, lon=3.4055, row=0, col=0)

FULL_PLACE = {
    "id": "ChIJabc123",
    "displayName": {"text": "Bright Smile Dental"},
    "primaryTypeDisplayName": {"text": "Dentist"},
    "formattedAddress": "12 Adeola Odeku St, Victoria Island, Lagos",
    "nationalPhoneNumber": "0803 123 4567",
    "websiteUri": "https://brightsmile.ng",
    "googleMapsUri": "https://maps.google.com/?cid=123",
    "location": {"latitude": 6.4301, "longitude": 3.4211},
    "rating": 4.6,
    "userRatingCount": 213,
    "businessStatus": "OPERATIONAL",
}


def test_maps_all_fields():
    lead = _to_lead(FULL_PLACE, CELL)
    assert lead.business_name == "Bright Smile Dental"
    assert lead.category_raw == "Dentist"
    assert lead.address == "12 Adeola Odeku St, Victoria Island, Lagos"
    assert lead.phone_raw == "0803 123 4567"
    assert lead.website == "https://brightsmile.ng"
    assert lead.place_id == "ChIJabc123"
    assert lead.lat == 6.4301
    assert lead.lon == 3.4211
    assert lead.rating == 4.6
    assert lead.review_count == 213
    assert lead.permanently_closed is False


def test_websiteless_business_has_none_website():
    """The Tier 1 qualification signal: no websiteUri field at all."""
    place = {k: v for k, v in FULL_PLACE.items() if k != "websiteUri"}
    assert _to_lead(place, CELL).website is None


def test_permanently_closed_flag():
    place = dict(FULL_PLACE, businessStatus="CLOSED_PERMANENTLY")
    assert _to_lead(place, CELL).permanently_closed is True


def test_missing_location_falls_back_to_cell_center():
    place = {k: v for k, v in FULL_PLACE.items() if k != "location"}
    lead = _to_lead(place, CELL)
    assert lead.lat == CELL.lat
    assert lead.lon == CELL.lon


def test_place_without_name_is_skipped():
    assert _to_lead({"id": "x", "displayName": {"text": "  "}}, CELL) is None
    assert _to_lead({"id": "x"}, CELL) is None


def test_sparse_place_maps_without_error():
    lead = _to_lead({"id": "x", "displayName": {"text": "Corner Shop"}}, CELL)
    assert lead.business_name == "Corner Shop"
    assert lead.phone_raw is None
    assert lead.rating is None
    assert lead.permanently_closed is False
