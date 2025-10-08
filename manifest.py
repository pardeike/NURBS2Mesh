"""
Manifest helpers for Blender add-ons.

Provides a utility to read ``blender_manifest.toml`` and produce a
``bl_info`` dictionary so the add-on metadata lives in a single place.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import tomllib

__all__ = ["parse_manifest"]

_MANIFEST_NAME = "blender_manifest.toml"


def _manifest_path() -> Path:
    return Path(__file__).with_name(_MANIFEST_NAME)


@lru_cache(maxsize=1)
def _raw_manifest() -> Dict[str, Any]:
    path = _manifest_path()
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _parse_version_tuple(value: str) -> Tuple[int, int, int]:
    parts = [int(segment) for segment in value.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def parse_manifest(overrides: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """
    Build a ``bl_info`` dictionary from ``blender_manifest.toml``.

    Parameters
    ----------
    overrides:
        Optional mapping of additional or overriding ``bl_info`` fields.

    Returns
    -------
    dict
        A ``bl_info`` dictionary suitable for registering the add-on.

    Raises
    ------
    KeyError
        If a required manifest key is missing.
    """

    data = dict(_raw_manifest())
    required_keys = (
        "name",
        "maintainer",
        "version",
        "tagline",
        "blender_version_min",
    )
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise KeyError(f"Manifest missing required keys: {', '.join(missing)}")

    name = str(data["name"])
    maintainer = str(data["maintainer"])
    description = str(data["tagline"])
    version_tuple = _parse_version_tuple(str(data["version"]))

    blender_min = str(data["blender_version_min"])
    blender_parts = [int(segment) for segment in blender_min.split(".")]
    while len(blender_parts) < 3:
        blender_parts.append(0)
    blender_tuple = tuple(blender_parts[:3])

    bl_info: Dict[str, Any] = {
        "name": name,
        "author": maintainer,
        "version": version_tuple,
        "blender": blender_tuple,
        "description": description,
    }

    if "location" in data:
        bl_info["location"] = str(data["location"])
    if "category" in data:
        bl_info["category"] = str(data["category"])
    if "tags" in data:
        bl_info["keywords"] = [str(tag) for tag in data["tags"]]
    if "doc_url" in data:
        bl_info["doc_url"] = str(data["doc_url"])

    if overrides:
        bl_info.update(dict(overrides))

    return bl_info

