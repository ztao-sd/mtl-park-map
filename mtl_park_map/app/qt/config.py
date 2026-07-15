from dataclasses import dataclass
from pathlib import Path

import mtl_park_map as mtl_park_map_
from mtl_park_map.lib.app_type import StrPath

PACKAGE_ROOT_DIR = Path(mtl_park_map_.__file__).parent
RESOURCE_DIR = PACKAGE_ROOT_DIR / 'resource'
RAW_RESOURCE_DIR = RESOURCE_DIR / 'raw'
CURATED_RESOURCE_DIR = RESOURCE_DIR / 'curated'


@dataclass
class Config:
    parking_sign_curated_pickle: StrPath = CURATED_RESOURCE_DIR / 'parking_sign_curated.pickle'