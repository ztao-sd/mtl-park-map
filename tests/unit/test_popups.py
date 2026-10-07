from mtl_park_map.ui.popups import SignRow, SpotRow, sign_popup_html, spot_popup_html


def _sign(
    category: str = "permitted",
    is_reserved: bool = False,
    arrondissement: str | None = "Ville-Marie",
) -> SignRow:
    return {
        "sign_id": 7,
        "longitude": -73.5,
        "latitude": 45.5,
        "category": category,
        "is_reserved": is_reserved,
        "arrondissement": arrondissement,
        "description": r"\P 9h-17h LUN A VEN <script>",
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
