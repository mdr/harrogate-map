# harrogate-map

A static, print-resolution map of the Harrogate area and western Yorkshire
Dales: major roads, rail and stations, rivers and reservoirs, National Cycle
Network routes, woodland, hillshading, and a curated set of places and
landmarks. Built from OpenStreetMap (via osmnx / Overpass) and SRTM elevation
data. Published at https://mdr.github.io/harrogate-map/.

Everything lives in `map.py`. The area is set by `BBOX`, and labels are
opt-in: only names in `PLACE_NAMES`, `POI_NAMES`, `WATERBODY_LABELS` and
`RIVER_LABELS` get drawn (they must match OSM names exactly).

## Running

The environment is a Nix flake, loaded automatically by direnv:

```sh
direnv allow          # or: nix develop
render                # local render, with the home marker (needs 1Password)
python map.py         # render without the home marker
```

Either writes `map.png` (~7200×5000, 300 dpi). The first run downloads OSM and
DEM data into `cache/` (~1.4 GB, gitignored) and is slow; later runs take
about a minute. Copy `cache/` from another machine to skip the download.

## Home marker

`map.py` draws a house marker at `MAP_HOME_LOCATION` (`"lat,lon"`) when that
env var is set. The value is deliberately kept out of this public repo: the
dev shell's `render` command reads it from 1Password
(`op://Private/harrogate-map/home_location` in the personal
`my.1password.com` account) and then runs `map.py`.

## CI

`.github/workflows/render-map.yml` renders on every push to `main` and deploys
`map.png` to GitHub Pages. CI runs plain `python map.py`, so the published map
never includes the home marker.
