import pytest

from mtl_park_map.ui.popups import (
    compass_name,
    RuleRow,
    SignRow,
    SpotRow,
    StripRow,
    sign_popup_html,
    spot_popup_html,
    strip_popup_html,
)


def _sign(
    category: str = "permitted",
    is_reserved: bool = False,
    arrondissement: str | None = "Ville-Marie",
    fleche: str | None = "0",
    arrow_street: str | None = None,
    arrow_bearing: float | None = None,
) -> SignRow:
    return {
        "sign_id": 7,
        "longitude": -73.5,
        "latitude": 45.5,
        "category": category,
        "is_reserved": is_reserved,
        "arrondissement": arrondissement,
        "description": "P 60 min 9h-17h LUN A VEN <script>",
        "fleche": fleche,
        "arrow_street": arrow_street,
        "arrow_bearing": arrow_bearing,
    }


def _spot(
    is_free: bool = False,
    tariff_hourly: float | None = 425.0,
    spot_type: str | None = "Double",
    street: str | None = "Rue <Saint-Denis>",
    periods: tuple[str, ...] = ("LUN À VEN 9 h - 21 h", "SAM 9 h - 18 h"),
) -> SpotRow:
    return {
        "place_id": "A024",
        "longitude": -73.5,
        "latitude": 45.5,
        "is_free": is_free,
        "tariff_hourly": tariff_hourly,
        "spot_type": spot_type,
        "street": street,
        "periods": list(periods),
    }


def test_sign_popup_escapes_and_labels():
    html = sign_popup_html(_sign())
    assert "Permitted" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "Ville-Marie" in html
    assert "Reserved" not in html


def test_sign_popup_reserved_and_missing_arrondissement():
    html = sign_popup_html(_sign(is_reserved=True, arrondissement=None, category="prohibited"))
    assert "Prohibited" in html
    assert "Reserved" in html


def test_spot_popup_paid_with_tariff_and_periods():
    html = spot_popup_html(_spot(), evaluated=True)
    assert "Paid" in html
    assert "$4.25/h" in html  # source tariff is in cents
    assert "Rue &lt;Saint-Denis&gt;" in html
    assert "LUN À VEN 9 h - 21 h" in html and "SAM 9 h - 18 h" in html
    assert "A024" in html


def test_spot_popup_free():
    assert "Free" in spot_popup_html(_spot(is_free=True), evaluated=True)


def test_spot_popup_without_complete_window_has_no_status():
    html = spot_popup_html(_spot(is_free=True), evaluated=False)
    assert "at the selected time" not in html
    assert "<b>Paid spot</b>" in html


def test_spot_popup_missing_optional_fields():
    html = spot_popup_html(
        _spot(tariff_hourly=None, street=None, spot_type=None, periods=()), evaluated=True
    )
    assert "$" not in html
    assert "None" not in html


def _strip(
    is_restricted: bool, active: tuple[int, ...], inferred: tuple[int, ...] = ()
) -> StripRow:
    def rule(code_id: int, description: str) -> RuleRow:
        return {
            "code_id": code_id,
            "description": description,
            "hour_ranges": [],
            "day_ranges": [],
            "month_ranges": [],
            "inferred": code_id in inferred,
        }

    return {
        "strip_id": 3,
        "street": "Rue <Rachel> Est",
        "side": 1,
        "length_m": 46.6,
        "longitudes": [-73.58, -73.579],
        "latitudes": [45.52, 45.52],
        "min_lon": -73.58,
        "min_lat": 45.52,
        "max_lon": -73.579,
        "max_lat": 45.52,
        "pole_longitudes": [-73.58],
        "pole_latitudes": [45.5201],
        "rules": [rule(5, r"\P 8h-11h MARDI"), rule(9, r"\P 9h-23h EXCEPTE S3R")],
        "active_code_ids": list(active),
        "is_restricted": is_restricted,
        "is_inferred": set(inferred) == {5, 9},
    }


def test_strip_popup_restricted_marks_active_rules():
    html = strip_popup_html(_strip(True, (9,)))
    assert "<b>No parking</b> at the selected time" in html
    assert "Rue &lt;Rachel&gt; Est" in html and "~47 m" in html
    # the rule in force is emphasised, the other listed plainly
    assert r"<b>\P 9h-23h EXCEPTE S3R</b>" in html
    assert r"\P 8h-11h MARDI" in html and r"<b>\P 8h-11h MARDI</b>" not in html


def test_strip_popup_parkable_has_caveat():
    html = strip_popup_html(_strip(False, ()))
    assert "<b>Parking OK</b> at the selected time" in html
    # strips only model no-parking signs with arrows
    assert "no-parking signs" in html


def test_sign_popup_arrow_with_derived_direction():
    html = sign_popup_html(_sign(fleche="3", arrow_street="Rue <Rachel> Est", arrow_bearing=315.0))
    assert "Arrow: → right" in html
    assert "points north-west along Rue &lt;Rachel&gt; Est" in html


def test_sign_popup_double_arrow_names_both_directions():
    html = sign_popup_html(_sign(fleche="8", arrow_street="Rue Rachel Est", arrow_bearing=315.0))
    assert "Arrow: ↔ both ways" in html
    assert "north-west and south-east along Rue Rachel Est" in html


def test_sign_popup_arrow_without_snapped_street():
    html = sign_popup_html(_sign(fleche="2"))
    assert "Arrow: ← left" in html and "along" not in html


def test_sign_popup_no_or_unknown_arrow():
    assert "No arrow" in sign_popup_html(_sign(fleche="0"))
    assert "No arrow" in sign_popup_html(_sign(fleche=None))
    assert "Unrecognised arrow code 22" in sign_popup_html(_sign(fleche="22"))


@pytest.mark.parametrize(
    ("bearing", "name"),
    [(0.0, "north"), (44.0, "north-east"), (90.0, "east"), (181.0, "south"), (290.0, "west"), (338.0, "north")],
)
def test_compass_name(bearing: float, name: str):
    assert compass_name(bearing) == name


def test_strip_popup_marks_inferred_rules():
    html = strip_popup_html(_strip(True, (9,), inferred=(5,)))
    assert r"\P 8h-11h MARDI <i>(extent inferred)</i>" in html
    assert "Extent inferred" not in html  # not the whole strip


def test_strip_popup_explains_a_wholly_inferred_strip():
    html = strip_popup_html(_strip(True, (9,), inferred=(5, 9)))
    assert "Extent inferred from no-parking signs without arrows" in html
