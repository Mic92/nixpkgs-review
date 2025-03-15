{
  description = "nixpkgs-review";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";

    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } (
      { lib, ... }:
      {
        imports = [ ./treefmt.nix ];
        systems = [
          "aarch64-linux"
          "x86_64-linux"
          "riscv64-linux"

          "x86_64-darwin"
          "aarch64-darwin"
        ];
        perSystem =
          {
            config,
            pkgs,
            self',
            ...
          }:
          {
            packages =
              {
                nixpkgs-review = pkgs.callPackage ./. { };
                default = config.packages.nixpkgs-review;
              }
              // lib.optionalAttrs (pkgs.stdenv.isLinux) {
                nixpkgs-review-sandbox = pkgs.callPackage ./. { withSandboxSupport = true; };
              };
            devShells = {
              default = (self'.packages.nixpkgs-review-sandbox or self'.packages.nixpkgs-review).override {
                withNom = true;
              };
            };
          };
      }
    );
}
