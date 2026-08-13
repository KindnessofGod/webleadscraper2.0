from src.phone import is_valid_nigerian_phone, normalize_phone


def test_normalize_local_format():
    assert normalize_phone("08031234567") == "+2348031234567"


def test_normalize_with_spaces_and_dashes():
    assert normalize_phone("0803-123-4567") == "+2348031234567"
    assert normalize_phone("0803 123 4567") == "+2348031234567"


def test_normalize_international_format():
    assert normalize_phone("+2348031234567") == "+2348031234567"
    assert normalize_phone("2348031234567") == "+2348031234567"


def test_normalize_bare_national_number():
    assert normalize_phone("8031234567") == "+2348031234567"


def test_normalize_invalid_length_returns_none():
    assert normalize_phone("12345") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_valid_mobile_prefixes():
    assert is_valid_nigerian_phone("08031234567") is True
    assert is_valid_nigerian_phone("09011234567") is True
    assert is_valid_nigerian_phone("07011234567") is True


def test_invalid_landline_style_number():
    # leading national digit 0/1-6 isn't a recognized mobile range
    assert is_valid_nigerian_phone("012345678") is False


def test_malformed_number_is_invalid():
    assert is_valid_nigerian_phone("not a phone") is False
    assert is_valid_nigerian_phone(None) is False
