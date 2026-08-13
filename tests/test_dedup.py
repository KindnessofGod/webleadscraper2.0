from src.dedup import dedup_leads, normalize_name


def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("Sunrise Clinic Ltd.") == "sunrise clinic"
    assert normalize_name("A&B Law Firm, Nigeria") == "a b law firm"


def _lead(id_, name, phone=None, city="Lagos"):
    return {
        "id": id_,
        "business_name": name,
        "normalized_name": normalize_name(name),
        "phone_normalized": phone,
        "city": city,
    }


def test_same_phone_merges_as_duplicate():
    leads = [
        _lead(1, "Sunrise Medical Clinic", phone="+2348031234567"),
        _lead(2, "Sunrise Medical Clinic Ltd", phone="+2348031234567"),
    ]
    result = dedup_leads(leads)
    canonical = [l for l in result if not l["is_duplicate"]]
    dupes = [l for l in result if l["is_duplicate"]]
    assert len(canonical) == 1
    assert len(dupes) == 1
    assert canonical[0]["dedup_group_id"] == dupes[0]["dedup_group_id"]


def test_similar_names_same_city_merge():
    leads = [
        _lead(1, "Victoria Island Law Firm"),
        _lead(2, "Victoria Island Law Firm Ltd"),
    ]
    result = dedup_leads(leads, name_threshold=0.85)
    assert sum(l["is_duplicate"] for l in result) == 1


def test_distinct_businesses_not_merged():
    leads = [
        _lead(1, "Sunrise Medical Clinic", phone="+2348031111111"),
        _lead(2, "Ikeja Law Chambers", phone="+2348032222222"),
    ]
    result = dedup_leads(leads)
    assert sum(l["is_duplicate"] for l in result) == 0
    assert result[0]["dedup_group_id"] != result[1]["dedup_group_id"]


def test_borderline_similarity_flagged_for_review_not_merged():
    leads = [
        _lead(1, "Metro Health Clinic"),
        _lead(2, "Metro Fitness Clinic"),
    ]
    result = dedup_leads(leads, name_threshold=0.95, review_threshold=0.60)
    assert sum(l["is_duplicate"] for l in result) == 0
    assert any(l["dedup_review"] for l in result)


def test_empty_input():
    assert dedup_leads([]) == []
