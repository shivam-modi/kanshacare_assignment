from __future__ import annotations

from kanshacare_shared.usgs import _parse_features


def _valid_feature(fid: str = "ci1") -> dict[str, object]:
    return {
        "type": "Feature",
        "id": fid,
        "properties": {
            "mag": 2.4,
            "place": "10 km NE of Somewhere",
            "time": 1_700_000_000_000,
            "updated": 1_700_000_500_000,
            "alert": None,
            "tsunami": 0,
            "sig": 88,
            "magType": "ml",
            "type": "earthquake",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [-117.3, 33.5, 4.5],
        },
    }


def test_parses_valid_feature_collection() -> None:
    payload = {
        "type": "FeatureCollection",
        "metadata": {"count": 2},
        "features": [_valid_feature("a"), _valid_feature("b")],
    }
    result = _parse_features("hour", payload, http_status=200)
    assert len(result.features) == 2
    assert result.quarantined == []
    assert result.raw_metadata == {"count": 2}


def test_quarantines_bad_feature_but_keeps_good_ones() -> None:
    bad_feature = _valid_feature("bad")
    bad_feature["geometry"]["coordinates"] = [999, 999, 0]  # type: ignore[index]
    payload = {
        "type": "FeatureCollection",
        "metadata": {},
        "features": [_valid_feature("good"), bad_feature],
    }
    result = _parse_features("hour", payload, http_status=200)
    assert len(result.features) == 1
    assert result.features[0].id == "good"
    assert len(result.quarantined) == 1


def test_empty_feature_collection() -> None:
    payload = {"type": "FeatureCollection", "metadata": {}, "features": []}
    result = _parse_features("hour", payload, http_status=200)
    assert result.features == []
    assert result.quarantined == []


def test_missing_top_level_falls_back_to_per_feature_validation() -> None:
    # Missing 'type' on the top-level container breaks the strict path; fallback
    # validates each feature individually and returns the good ones.
    payload = {"features": [_valid_feature("only")]}
    result = _parse_features("hour", payload, http_status=200)
    assert len(result.features) == 1


def test_missing_features_key_returns_empty() -> None:
    # No `features` key at all: caller still gets a result they can log.
    result = _parse_features("hour", {"type": "FeatureCollection"}, http_status=200)
    assert result.features == []
    assert result.quarantined == []
