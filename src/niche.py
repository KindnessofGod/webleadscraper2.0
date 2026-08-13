"""Stage E: normalize Google Maps' inconsistent raw category strings into a
controlled niche vocabulary (see config/categories.yaml: niche_map).
"""
from __future__ import annotations


def normalize_niche(category_raw: str | None, niche_map: dict, default_niche: str = "other") -> str:
    if not category_raw:
        return default_niche
    raw_lower = category_raw.strip().lower()

    if raw_lower in niche_map:
        return niche_map[raw_lower]

    # substring fallback: raw category strings from Maps often have extra
    # words ("Family medical clinic" vs the map key "medical clinic")
    for key, niche in niche_map.items():
        if key in raw_lower:
            return niche

    return default_niche
