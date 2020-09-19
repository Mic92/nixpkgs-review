{
  description = "nixpkgs-review";

  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system: {
      packages.nixpkgs-review = import ./. {
        pkgs = nixpkgs.legacyPackages.${system};
      };

      defaultPackage = self.packages.${system}.nixpkgs-review;
    });
}
