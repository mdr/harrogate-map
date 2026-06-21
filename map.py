"""Render a static map of roads and rail for an area of interest."""
import gzip
import math
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
import requests
from matplotlib.colors import LightSource
from rasterio.merge import merge
from shapely.geometry import LineString, Point

# Area of interest as a bounding box (west, south, east, north) in WGS84.
# Stretched far west to include Grassington (~2.00 W), Pen-y-ghent (~2.25 W),
# and Ingleborough (~2.40 W); nudged north to fit those Three Peaks summits.
BBOX = (-2.50, 53.81, -1.20, 54.25)
LABEL = "Harrogate area"

OUT = Path("map.png")

ROAD_FILTER = '["highway"~"motorway|trunk|primary|secondary"]'
RAIL_TAGS = {"railway": ["rail", "light_rail", "subway", "tram"]}
RIVER_TAGS = {"waterway": ["river", "canal"]}
RIVER_LABELS = {"River Ure", "River Wharfe", "River Nidd"}
NCN_TAGS = {"route": "bicycle"}  # cycle route relations; filtered to network=ncn
WATERBODY_TAGS = {"natural": "water", "landuse": "reservoir"}
URBAN_TAGS = {"landuse": "residential"}
FOREST_TAGS = {"landuse": "forest", "natural": "wood"}
WATERBODY_LABELS = {
    "Grimwith Reservoir",
    "Swinsty Reservoir",
    "Fewston Reservoir",
    "Thruscross Reservoir",
    "Malham Tarn",
}
STATION_TAGS = {"railway": "station"}
PLACE_TAGS = {"place": ["city", "town", "village", "hamlet"]}
PLACE_NAMES = {
    "Ripon", "Ripley", "Spofforth", "Wetherby", "Blubberhouses",
    "Pateley Bridge", "Grassington", "Farnham", "Conistone", "Arncliffe",
}

# Named points of interest. The POI_TAGS filter is broad (peaks, cliffs,
# tourism attractions, historic features); POI_NAMES then picks specific ones.
POI_TAGS = {
    "natural": ["peak", "cliff", "rock", "stone", "wood", "cave_entrance"],
    "landuse": ["forest"],
    "tourism": ["attraction", "viewpoint", "museum"],
    "historic": True,
    "leisure": ["nature_reserve"],
}
# Names must match OSM exactly. The full set covers the main Three Peaks /
# crag landmarks plus a couple of regional natural attractions.
POI_NAMES = {
    "Almscliffe Crag", "Pen-y-ghent", "Ingleborough", "Simon's Seat",
    "Burton Leonard Nature Reserve", "Staveley Nature Reserve", "Hackfall",
    "Stainburn Forest", "Ripon City Wetlands", "Quarry Moor", "Aubert Ings SSSI",
    "Rougemont Carr", "Upper Dunsforth Carrs",
    "Mossdale Caverns", "Kilnsey Park and Trout Farm",
    "Adel Dam Nature Reserve", "Nosterfield Nature Reserve",
}

# Suffixes stripped from POI labels at render time (display only — POI_NAMES
# must still match the canonical OSM name).
POI_LABEL_SUFFIXES = (" Nature Reserve", " SSSI", " and Trout Farm")

# Hand-placed POIs for features not (yet) in OSM under a queryable name.
# Each entry: display-name -> (lat, lon).
MANUAL_POIS = {
    "Bishop Monkton Railway Cutting": (54.09166, -1.52142),
}


def _polygons_only(gdf):
    """Keep only Polygon/MultiPolygon features — Point nodes in fill layers
    fall through to matplotlib's default colour cycle and render as
    misleading orange dots."""
    return gdf[gdf.geometry.type.isin(("Polygon", "MultiPolygon"))]


def load_hillshade(bbox, cache_dir=Path("cache/dem")):
    """Build a hillshade raster for the bbox from SRTM 30 m tiles.

    Returns (hillshade, extent) where hillshade is a 2D float array in [0, 1]
    and extent is (west, east, south, north) ready for ax.imshow."""
    west, south, east, north = bbox
    cache_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            name = f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}.hgt"
            local = cache_dir / name
            if not local.exists():
                url = (
                    "https://elevation-tiles-prod.s3.amazonaws.com/skadi/"
                    f"{ns}{abs(lat):02d}/{name}.gz"
                )
                print(f"downloading DEM tile {name}")
                with urllib.request.urlopen(url) as r:
                    local.write_bytes(gzip.decompress(r.read()))
            paths.append(local)

    sources = [rasterio.open(p) for p in paths]
    try:
        merged, _ = merge(sources, bounds=(west, south, east, north))
    finally:
        for s in sources:
            s.close()

    elev = merged[0].astype(np.float32)
    elev[elev < -1000] = 0  # SRTM no-data sentinel is -32768

    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(elev, vert_exag=2.0, dx=30, dy=30)
    return hs, (west, east, south, north)


def fetch_ncn(bbox):
    """Fetch NCN route ways via Overpass directly. OSMnx's features_from_bbox
    doesn't return route=bicycle relations because they're collections of
    member ways with no inherent geometry — so we query the member ways
    ourselves and tag each one with the parent relation's ref."""
    west, south, east, north = bbox
    query = (
        "[out:json][timeout:180];"
        f"(rel({south},{west},{north},{east})"
        '["route"="bicycle"]["network"="ncn"];);'
        "out tags;"
        "way(r);"
        "out geom;"
    )
    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data=query,
        headers={"User-Agent": "map-experiment/0.1"},
        timeout=180,
    )
    r.raise_for_status()
    elements = r.json().get("elements", [])

    # First pass: collect ref per relation id, and the set of member way ids.
    ref_by_way = {}
    for el in elements:
        if el["type"] == "relation":
            ref = el.get("tags", {}).get("ref")
            for m in el.get("members", []):
                if m.get("type") == "way":
                    ref_by_way[m["ref"]] = ref

    rows = []
    for el in elements:
        if el["type"] == "way" and el.get("geometry"):
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(coords) >= 2:
                rows.append({
                    "ref": ref_by_way.get(el["id"]),
                    "geometry": LineString(coords),
                })
    if not rows:
        return gpd.GeoDataFrame(columns=["ref", "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def fetch(bbox: tuple[float, float, float, float]):
    roads = ox.graph_from_bbox(bbox=bbox, custom_filter=ROAD_FILTER, simplify=True)
    rail = ox.features_from_bbox(bbox=bbox, tags=RAIL_TAGS)
    rivers = ox.features_from_bbox(bbox=bbox, tags=RIVER_TAGS)
    ncn = fetch_ncn(bbox)
    waterbodies = ox.features_from_bbox(bbox=bbox, tags=WATERBODY_TAGS)
    urban = _polygons_only(ox.features_from_bbox(bbox=bbox, tags=URBAN_TAGS))
    forest = _polygons_only(ox.features_from_bbox(bbox=bbox, tags=FOREST_TAGS))
    stations = ox.features_from_bbox(bbox=bbox, tags=STATION_TAGS)
    # Drop unnamed stations (e.g. theme-park miniature railways tagged as
    # railway=station but without a name/operator).
    if "name" in stations.columns:
        stations = stations[stations["name"].notna()]
    places = ox.features_from_bbox(bbox=bbox, tags=PLACE_TAGS)
    if "name" in places.columns:
        places = places[places["name"].isin(PLACE_NAMES)]
    pois = ox.features_from_bbox(bbox=bbox, tags=POI_TAGS)
    if "name" in pois.columns:
        pois = pois[pois["name"].isin(POI_NAMES)]
    if MANUAL_POIS:
        manual = gpd.GeoDataFrame(
            {"name": list(MANUAL_POIS.keys())},
            geometry=[Point(lon, lat) for lat, lon in MANUAL_POIS.values()],
            crs="EPSG:4326",
        )
        pois = pd.concat([pois, manual], ignore_index=True)
    return (
        roads, rail, rivers, ncn, waterbodies, urban, forest,
        stations, places, pois,
    )


def render(
    roads, rail, rivers, ncn, waterbodies, urban, forest,
    stations, places, pois, hillshade, out: Path,
) -> None:
    west, south, east, north = BBOX
    aspect = (east - west) / ((north - south) * 1.7)  # rough lat compression at 54°N
    fig_w = 24
    fig_h = fig_w / aspect
    fig, ax = ox.plot_graph(
        roads,
        show=False,
        close=False,
        figsize=(fig_w, fig_h),
        node_size=0,
        edge_color="#333",
        edge_linewidth=0.7,
        bgcolor="white",
    )
    if hillshade is not None:
        hs_array, hs_extent = hillshade
        ax.imshow(
            hs_array, cmap="gray", extent=hs_extent,
            origin="upper", alpha=0.35, zorder=-1,
            interpolation="bilinear",
        )
    if not urban.empty:
        urban.plot(
            ax=ax, facecolor="#f0e0c4", edgecolor="#c9b585",
            linewidth=0.3, alpha=0.7, zorder=0,
        )
    if not forest.empty:
        forest.plot(
            ax=ax, facecolor="#c8e0b4", edgecolor="#7fa07a",
            linewidth=0.3, alpha=0.7, zorder=0,
        )
    if not waterbodies.empty:
        waterbodies.plot(
            ax=ax, facecolor="#aed6f1", edgecolor="#2980b9",
            linewidth=0.4, zorder=1,
        )
        if "name" in waterbodies.columns:
            labelled = waterbodies[waterbodies["name"].isin(WATERBODY_LABELS)]
            for _, row in labelled.iterrows():
                p = row.geometry.representative_point()
                short = row["name"].removesuffix(" Reservoir")
                ax.annotate(
                    short, (p.x, p.y),
                    ha="center", va="center",
                    fontsize=10, fontstyle="italic", color="#1a5276", zorder=6,
                )
    if not rivers.empty:
        rivers.plot(ax=ax, color="#2980b9", linewidth=1.4, zorder=2)
        if "name" in rivers.columns:
            named = rivers[rivers["name"].isin(RIVER_LABELS)].copy()
            if not named.empty:
                # One label per river, placed on the longest segment.
                named["len"] = named.geometry.length
                chosen = named.loc[named.groupby("name")["len"].idxmax()]
                for _, row in chosen.iterrows():
                    mid = row.geometry.interpolate(0.5, normalized=True)
                    ax.annotate(
                        row["name"], (mid.x, mid.y),
                        ha="center", va="center",
                        fontsize=14, fontstyle="italic", color="#1a5276", zorder=6,
                    )
    if not rail.empty:
        rail.plot(ax=ax, color="#c0392b", linewidth=2.0, zorder=3)
    if not ncn.empty:
        ncn.plot(ax=ax, color="#e67e22", linewidth=2.8, alpha=0.9, zorder=4)
        if "ref" in ncn.columns:
            named = ncn[ncn["ref"].notna()].copy()
            if not named.empty:
                named["len"] = named.geometry.length
                chosen = named.loc[named.groupby("ref")["len"].idxmax()]
                for _, row in chosen.iterrows():
                    mid = row.geometry.interpolate(0.5, normalized=True)
                    ax.annotate(
                        f"NCN {row['ref']}", (mid.x, mid.y),
                        ha="center", va="center",
                        fontsize=10, fontweight="bold", color="white",
                        bbox=dict(boxstyle="round,pad=0.25", facecolor="#e67e22",
                                  edgecolor="none"),
                        zorder=6,
                    )
    if not stations.empty:
        pts = stations.copy()
        pts["geometry"] = pts.geometry.representative_point()
        pts.plot(
            ax=ax, color="#c0392b", marker="s", markersize=45,
            edgecolor="white", linewidth=1.0, zorder=5,
        )
        for _, row in pts.iterrows():
            name = row.get("name")
            if isinstance(name, str):
                ax.annotate(
                    name, (row.geometry.x, row.geometry.y),
                    xytext=(6, 4), textcoords="offset points",
                    fontsize=9, color="#222", zorder=6,
                )

    if not places.empty:
        pts = places.copy()
        pts["geometry"] = pts.geometry.representative_point()
        pts.plot(ax=ax, color="#222", marker="o", markersize=40, zorder=7)
        for _, row in pts.iterrows():
            name = row.get("name")
            if isinstance(name, str):
                ax.annotate(
                    name, (row.geometry.x, row.geometry.y),
                    xytext=(8, 5), textcoords="offset points",
                    fontsize=13, fontweight="bold", color="#111", zorder=8,
                )

    if not pois.empty:
        pts = pois.copy()
        pts["geometry"] = pts.geometry.representative_point()
        pts.plot(ax=ax, color="#8e44ad", marker="^", markersize=80, zorder=7)
        for _, row in pts.iterrows():
            name = row.get("name")
            if isinstance(name, str):
                short = name
                for suffix in POI_LABEL_SUFFIXES:
                    short = short.removesuffix(suffix)
                ax.annotate(
                    short, (row.geometry.x, row.geometry.y),
                    xytext=(8, 5), textcoords="offset points",
                    fontsize=11, fontstyle="italic", color="#5b2c6f", zorder=8,
                )

    west, south, east, north = BBOX
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_axis_off()
    ax.margins(0)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out, dpi=300, pad_inches=0, facecolor="white")
    print(f"wrote {out.resolve()}")


if __name__ == "__main__":
    ox.settings.use_cache = True  # cache Overpass responses on disk
    ox.settings.log_console = True
    hillshade = load_hillshade(BBOX)
    render(*fetch(BBOX), hillshade, OUT)
