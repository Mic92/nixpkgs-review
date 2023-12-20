{ system
, nixpkgs-config-path # Path to Nix file containing the Nixpkgs config
, attrs-path # Path to Nix file containing a list of attributes to build
, nixpkgs-path # Path to this review's nixpkgs
, pkgs ? import nixpkgs-path { inherit system; config = import nixpkgs-config-path; }
, lib ? pkgs.lib
}:

let
  attrs = import attrs-path pkgs;
  env = pkgs.buildEnv {
    name = "env";
    paths = attrs;
    ignoreCollisions = true;
  };
in
(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  packages = if builtins.length attrs > 50 then [ env ] else attrs;
}
