from src.niche import normalize_niche

NICHE_MAP = {
    "medical clinic": "healthcare",
    "clinic": "healthcare",
    "law firm": "legal",
    "real estate agency": "real_estate",
}


def test_exact_match():
    assert normalize_niche("Medical Clinic", NICHE_MAP) == "healthcare"


def test_case_insensitive():
    assert normalize_niche("LAW FIRM", NICHE_MAP) == "legal"


def test_substring_fallback():
    assert normalize_niche("Family Medical Clinic & Diagnostics", NICHE_MAP) == "healthcare"


def test_unmapped_category_falls_back_to_default():
    assert normalize_niche("Car Wash", NICHE_MAP) == "other"
    assert normalize_niche("Car Wash", NICHE_MAP, default_niche="misc") == "misc"


def test_missing_category_returns_default():
    assert normalize_niche(None, NICHE_MAP) == "other"
    assert normalize_niche("", NICHE_MAP) == "other"
