from dataclasses import dataclass
from pathlib import Path

import mtl_park_map as mtl_park_map_
from mtl_park_map.lib.app_type import StrPath

PACKAGE_ROOT_DIR = Path(mtl_park_map_.__file__).parent
# Data was hoisted to the repo-level shared data/ dir when this prototype was
# stashed under legacy/qt_app/. This file is at
# legacy/qt_app/mtl_park_map/app/qt/config.py, so parents[5] is the repo root.
RESOURCE_DIR = Path(__file__).resolve().parents[5] / 'data'
RAW_RESOURCE_DIR = RESOURCE_DIR / 'raw'
CURATED_RESOURCE_DIR = RESOURCE_DIR / 'curated'


@dataclass
class Config:
    parking_sign_curated_pickle: StrPath = CURATED_RESOURCE_DIR / 'parking_sign_curated.pickle'