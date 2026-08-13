"""Grid-cell generation for Stage A (works around the ~200-result Google Maps
cap per query by splitting each zone into smaller cells and issuing one
search per cell per category).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

KM_PER_DEGREE_LAT = 111.0


@dataclass(frozen=True)
class GridCell:
    id: str
    zone: str
    lat: float
    lon: float
    row: int
    col: int

    def maps_search_url(self, query: str, zoom: int) -> str:
        from urllib.parse import quote

        return f"https://www.google.com/maps/search/{quote(query)}/@{self.lat},{self.lon},{zoom}z"


def _km_per_degree_lon(lat_deg: float) -> float:
    return KM_PER_DEGREE_LAT * math.cos(math.radians(lat_deg))


def cells_for_zone(zone_name: str, bbox: dict, cell_km: float) -> list[GridCell]:
    """Split a lat/lon bounding box into a grid of cells, each `cell_km` wide,
    returning one GridCell per cell centered in the cell.
    """
    min_lat, max_lat = bbox["min_lat"], bbox["max_lat"]
    min_lon, max_lon = bbox["min_lon"], bbox["max_lon"]

    lat_step_deg = cell_km / KM_PER_DEGREE_LAT
    mid_lat = (min_lat + max_lat) / 2
    lon_step_deg = cell_km / _km_per_degree_lon(mid_lat)

    n_rows = max(1, math.ceil((max_lat - min_lat) / lat_step_deg))
    n_cols = max(1, math.ceil((max_lon - min_lon) / lon_step_deg))

    cells = []
    for row in range(n_rows):
        for col in range(n_cols):
            lat = min_lat + (row + 0.5) * lat_step_deg
            lon = min_lon + (col + 0.5) * lon_step_deg
            lat = min(lat, max_lat)
            lon = min(lon, max_lon)
            cells.append(
                GridCell(id=f"{zone_name}_{row}_{col}", zone=zone_name, lat=round(lat, 6), lon=round(lon, 6), row=row, col=col)
            )
    return cells


def cells_for_grid_config(grid_config: dict, pilot_only: bool = False) -> list[GridCell]:
    """Expand every zone in a loaded grid_<city>.yaml config into GridCells.
    pilot_only=True restricts to zones flagged `pilot: true` (Section 4 spec:
    pilot run scoped to 2-3 grid cells).
    """
    cells: list[GridCell] = []
    for zone in grid_config["zones"]:
        if pilot_only and not zone.get("pilot", False):
            continue
        cells.extend(cells_for_zone(zone["name"], zone["bbox"], zone["cell_km"]))
    return cells
