{
  description = "nixpkgs-review";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs }:
    let
      linuxPlatforms = [ "x86_64-linux" "aarch64-linux" "i686-linux" "armv7l-linux" "riscv64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs (linuxPlatforms ++ [ "x86_64-darwin" "aarch64-darwin" ]);
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
        packages = nixpkgs.lib.genAttrs linuxPlatforms (system: {
          nixpkgs-review-sandbox = nixpkgs.legacyPackages.${system}.callPackage ./. { withSandboxSupport = true; };
        });
      });
}
