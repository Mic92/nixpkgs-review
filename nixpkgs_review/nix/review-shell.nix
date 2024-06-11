{ system
, nixpkgs-config-path # Path to Nix file containing the Nixpkgs config
, attrs-path # Path to Nix file containing a list of attributes to build
, nixpkgs-path # Path to this review's nixpkgs
, pkgs ? import nixpkgs-path { inherit system; config = import nixpkgs-config-path; }
}:

(import nixpkgs-path { }).mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;

  packages = pkgs.buildEnv {
    name = "env";
    paths = import attrs-path pkgs;
    pathsToLink = [ "/bin" ];
    ignoreCollisions = true;
  };
}
