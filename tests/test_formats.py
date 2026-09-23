from app.formats import timestamp


def test_timestamp_is_hour_safe():
    assert timestamp(0) == "00:00:00"
    assert timestamp(3661.9) == "01:01:01"
