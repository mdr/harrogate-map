{
  description = "Custom map with OSMnx";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          # 1Password CLI is unfree; allow just that package.
          config.allowUnfreePredicate = pkg: builtins.elem (nixpkgs.lib.getName pkg) [ "1password-cli" ];
          overlays = [
            (final: prev: {
              python3 = prev.python3.override {
                packageOverrides = pyfinal: pyprev: {
                  # folium's test suite fails on this nixpkgs revision
                  # (pyproj can't locate its CRS database during the check
                  # phase). Skip tests — runtime is unaffected.
                  folium = pyprev.folium.overridePythonAttrs (_: { doCheck = false; });
                };
              };
            })
          ];
        };
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          osmnx
          geopandas
          shapely
          networkx
          matplotlib
          adjusttext
          ipython
        ]);
        # Local render with the home marker: pulls MAP_HOME_LOCATION from the
        # personal 1Password account so it never lives in the repo. CI just
        # runs `python map.py` and renders without it.
        render = pkgs.writeShellScriptBin "render" ''
          MAP_HOME_LOCATION="$(${pkgs._1password-cli}/bin/op read --account my.1password.com 'op://Private/harrogate-map/home_location')" \
            || { echo "render: couldn't read home location from 1Password" >&2; exit 1; }
          export MAP_HOME_LOCATION
          exec python map.py "$@"
        '';
      in {
        devShells.default = pkgs.mkShell {
          packages = [ pythonEnv pkgs._1password-cli render ];
          shellHook = ''
            echo "map dev shell — python $(python --version | cut -d' ' -f2), osmnx $(python -c 'import osmnx; print(osmnx.__version__)')"
          '';
        };
      });
}
