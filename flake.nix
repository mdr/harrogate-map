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
      in {
        devShells.default = pkgs.mkShell {
          packages = [ pythonEnv ];
          shellHook = ''
            echo "map dev shell — python $(python --version | cut -d' ' -f2), osmnx $(python -c 'import osmnx; print(osmnx.__version__)')"
          '';
        };
      });
}
