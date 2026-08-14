from src.apify_import import row_city, row_query, row_to_lead

# Field names as the mainstream Apify Maps actors emit them (JSON export).
APIFY_JSON = {
    "title": "Bright Smile Dental",
    "categoryName": "Dentist",
    "address": "12 Adeola Odeku St, Victoria Island, Lagos",
    "phone": "0803 123 4567",
    "website": "https://brightsmile.ng",
    "url": "https://maps.google.com/?cid=123",
    "placeId": "ChIJabc123",
    "location": {"lat": 6.4301, "lng": 3.4211},
    "totalScore": 4.6,
    "reviewsCount": 213,
    "permanentlyClosed": False,
    "city": "Lagos",
    "searchString": "dentist in Victoria Island",
}

# CSV export of the same record: everything is a string and nested objects
# are flattened with "/".
APIFY_CSV = {
    "title": "Bright Smile Dental",
    "categoryName": "Dentist",
    "phone": "0803 123 4567",
    "website": "",
    "placeId": "ChIJabc123",
    "location/lat": "6.4301",
    "location/lng": "3.4211",
    "totalScore": "4.6",
    "reviewsCount": "213",
    "permanentlyClosed": "false",
}


def test_maps_apify_json_record():
    lead = row_to_lead(APIFY_JSON)
    assert lead.business_name == "Bright Smile Dental"
    assert lead.category_raw == "Dentist"
    assert lead.phone_raw == "0803 123 4567"
    assert lead.website == "https://brightsmile.ng"
    assert lead.place_id == "ChIJabc123"
    assert lead.lat == 6.4301
    assert lead.lon == 3.4211
    assert lead.rating == 4.6
    assert lead.review_count == 213
    assert lead.permanently_closed is False


def test_csv_export_coerces_strings_and_flattened_paths():
    lead = row_to_lead(APIFY_CSV)
    assert lead.lat == 6.4301
    assert lead.lon == 3.4211
    assert lead.rating == 4.6
    assert lead.review_count == 213
    assert lead.permanently_closed is False
    # Empty CSV cell must read as "no website" -- this is the Tier 1 signal.
    assert lead.website is None


def test_alternate_actor_field_names():
    lead = row_to_lead(
        {"name": "Corner Shop", "phoneNumber": "0802 000 0000", "rating": 3.9, "reviews": 7}
    )
    assert lead.business_name == "Corner Shop"
    assert lead.phone_raw == "0802 000 0000"
    assert lead.rating == 3.9
    assert lead.review_count == 7


def test_placeholder_strings_count_as_missing():
    """Apify writes "null"/"N/A" rather than omitting a key."""
    lead = row_to_lead(dict(APIFY_JSON, website="null", phone="N/A"))
    assert lead.website is None
    assert lead.phone_raw is None


def test_permanently_closed_truthy_forms():
    assert row_to_lead(dict(APIFY_JSON, permanentlyClosed=True)).permanently_closed is True
    assert row_to_lead(dict(APIFY_JSON, permanentlyClosed="true")).permanently_closed is True
    assert row_to_lead(dict(APIFY_JSON, permanentlyClosed="")).permanently_closed is False


def test_record_without_name_is_skipped():
    assert row_to_lead({"placeId": "x"}) is None
    assert row_to_lead({"title": "   ", "placeId": "x"}) is None


def test_city_and_query_extraction():
    assert row_city(APIFY_JSON) == "Lagos"
    assert row_query(APIFY_JSON) == "dentist in Victoria Island"
    # Falls back to None so the caller can substitute its --city / --category.
    assert row_city({"title": "X"}) is None
