{
  description = "nixpkgs-review";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      platforms = nixpkgs.legacyPackages.x86_64-linux.python3.meta.platforms;
      bubblewrapPlatforms = nixpkgs.legacyPackages.x86_64-linux.bubblewrap.meta.platforms;
      forAllSystems = nixpkgs.lib.genAttrs platforms;
    in
    nixpkgs.lib.recursiveUpdate
      ({
        packages = forAllSystems (system: {
          nixpkgs-review = nixpkgs.legacyPackages.${system}.callPackage ./. { };
          default = self.packages.${system}.nixpkgs-review;
        });
        devShells = forAllSystems (system: {
          default = (self.packages.${system}.nixpkgs-review-sandbox or self.packages.${system}.nixpkgs-review).override { withNom = true; };
        });
      })
      ({
        packages = nixpkgs.lib.genAttrs bubblewrapPlatforms (system: {
          nixpkgs-review-sandbox = nixpkgs.legacyPackages.${system}.callPackage ./. { withSandboxSupport = true; };
        });
      });
}
