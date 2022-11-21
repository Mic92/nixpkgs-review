{
  description = "nixpkgs-review";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs, flake-utils }:
    nixpkgs.lib.foldr nixpkgs.lib.recursiveUpdate { } [
      (flake-utils.lib.eachDefaultSystem (system: {
        packages.nixpkgs-review = import ./. {
          pkgs = nixpkgs.legacyPackages.${system};
        };

        packages.default = self.packages.${system}.nixpkgs-review;
      }))

      (flake-utils.lib.eachSystem [ "aarch64-linux" "i686-linux" "x86_64-linux" ] (system: {
        packages.nixpkgs-review-sandbox = import ./. {
          pkgs = nixpkgs.legacyPackages.${system};
          withSandboxSupport = true;
        };
      }))
    ];
}
