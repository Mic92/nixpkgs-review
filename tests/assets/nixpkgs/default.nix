{ config ? {} }:
let
  pkgs = import @NIXPKGS@ {
    inherit config;
  };
in {
  pkg1 = pkgs.stdenv.mkDerivation {
    name = "pkg1";
    dontUnpack = true;
    installPhase = ''
      install -D ${./pkg1.txt} $out/foo
    '';
  };
  # hack to not break evaluation with nixpkgs_review/nix/*.nix
  inherit (pkgs) lib stdenv bashInteractive;
}
