from src.grid import cells_for_zone, cells_for_grid_config


def test_cells_for_zone_covers_bbox():
    bbox = {"min_lat": 6.418, "max_lat": 6.445, "min_lon": 3.401, "max_lon": 3.435}
    cells = cells_for_zone("victoria_island", bbox, cell_km=1.0)

    assert len(cells) > 0
    for cell in cells:
        assert bbox["min_lat"] <= cell.lat <= bbox["max_lat"]
        assert bbox["min_lon"] <= cell.lon <= bbox["max_lon"]
        assert cell.id.startswith("victoria_island_")


def test_smaller_cells_produce_more_cells():
    bbox = {"min_lat": 6.4, "max_lat": 6.5, "min_lon": 3.3, "max_lon": 3.4}
    coarse = cells_for_zone("z", bbox, cell_km=5.0)
    fine = cells_for_zone("z", bbox, cell_km=1.0)
    assert len(fine) > len(coarse)


def test_maps_search_url_contains_query_and_coords():
    bbox = {"min_lat": 6.4, "max_lat": 6.41, "min_lon": 3.3, "max_lon": 3.31}
    cell = cells_for_zone("z", bbox, cell_km=1.0)[0]
    url = cell.maps_search_url("clinic", zoom=15)
    assert "clinic" in url
    assert f"{cell.lat}" in url
    assert f"{cell.lon}" in url
    assert url.endswith("15z")


def test_pilot_only_filters_zones():
    grid_config = {
        "zoom": 15,
        "zones": [
            {"name": "a", "bbox": {"min_lat": 6.4, "max_lat": 6.41, "min_lon": 3.3, "max_lon": 3.31}, "cell_km": 1.0, "pilot": True},
            {"name": "b", "bbox": {"min_lat": 6.4, "max_lat": 6.41, "min_lon": 3.3, "max_lon": 3.31}, "cell_km": 1.0, "pilot": False},
        ],
    }
    pilot_cells = cells_for_grid_config(grid_config, pilot_only=True)
    all_cells = cells_for_grid_config(grid_config, pilot_only=False)
    assert all(c.zone == "a" for c in pilot_cells)
    assert len(all_cells) > len(pilot_cells)
