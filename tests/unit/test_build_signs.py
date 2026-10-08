from pathlib import Path

import pytest

from mtl_park_map import settings
from mtl_park_map.etl.build import build_signs

HEADER = "POTEAU_ID_POT,CODE_RPA,DESCRIPTION_RPA,Longitude,Latitude,NOM_ARROND,FLECHE_PAN,DESCRIPTION_REP"
ROWS = [
    "101,SP-1,\\P 9h-17h LUN A VEN,-73.56,45.50,Ville-Marie,2,Réel",
    "102,SP-2,P 60 min,-73.57,45.51,Ville-Marie,0,Enlevé",
    "103,SP-3,\\A EN TOUT TEMPS,-73.58,45.52,Ville-Marie,3,En conception",
    "104,SP-4,P 15 min,-73.59,45.53,Ville-Marie,0,Archive",
]


@pytest.fixture
def sign_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "signalisation_stationnement.csv"
    path.write_text("\n".join([HEADER, *ROWS]) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "SIGN_CSV", path)
    return path


def test_only_installed_signs_are_kept(sign_csv: Path):
    # removed ("Enlevé"), planned ("En conception") and archived signs are not on
    # the street, so they must not be shown
    signs, codes = build_signs()
    assert signs.height == 1
    assert codes["code_rpa"].to_list() == ["SP-1"]
    row = signs.row(0, named=True)
    assert (row["category"], row["fleche"], row["pole_id"]) == ("prohibited", "2", 101)
    assert codes["kind"].to_list() == ["no_parking"]
