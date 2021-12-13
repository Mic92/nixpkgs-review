{
  description = "nixpkgs-review";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system: {
      packages = {
        nixpkgs-review = import ./. {
          pkgs = nixpkgs.legacyPackages.${system};
        };
        nixpkgs-review-sandbox = import ./. {
          pkgs = nixpkgs.legacyPackages.${system};
          withSandboxSupport = true;
        };
      };

      defaultPackage = self.packages.${system}.nixpkgs-review;
    });
}
