from pathlib import Path

import pytest

from mtl_park_map.etl.build import read_raw_csv

DESCRIPTION = r"\P 9h-17h LUN À VEN"
CONTENT = f"NOM_ARROND,DESCRIPTION_RPA\nCôte-des-Neiges,{DESCRIPTION}\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_reads_utf8_and_cp1252_sources(tmp_path: Path, encoding: str):
    # the city's sign CSV is UTF-8; the AMDS paid-spot CSVs are Windows-1252
    path = tmp_path / "data.csv"
    path.write_bytes(CONTENT.encode(encoding))
    df = read_raw_csv(path)
    assert df.columns == ["NOM_ARROND", "DESCRIPTION_RPA"]
    assert df.row(0) == ("Côte-des-Neiges", DESCRIPTION)


def test_all_columns_are_strings(tmp_path: Path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2.5\n", encoding="utf-8")
    assert read_raw_csv(path).row(0) == ("1", "2.5")
