{
  config ? (
    let configFile = builtins.getEnv "NIXPKGS_CONFIG";
    in
      if configFile != "" && builtins.pathExists configFile then
        import configFile
      else
        { }),
  system ? null, # deadnix: skip
}@args:
with import ./config.nix;
let
  currentSystem = if system != null then system else builtins.currentSystem;

  stdenv = {
    inherit mkDerivation;
  };

  bashInteractive = mkDerivation {
    name = "bash-interactive";
    buildCommand = ''
      mkdir -p $out/bin
      ln -s ${shell} $out/bin/bash
    '';
  };

in
lib.genAttrs' (lib.range 1 (config.pkgCount or 1)) (
  i:
  lib.nameValuePair "pkg${toString i}" (mkDerivation {
    name = "pkg${toString i}";
    buildCommand = ''
      cat ${./pkg1.txt} > $out
    '';
  } // {
    tests = lib.genAttrs [ "simple" "slow" ] (t: mkDerivation {
      name = "pkg${toString i}-test-${t}";
      buildCommand = "cat ${./pkg1.txt} > $out";
    });
  })) // {
  inherit lib bashInteractive stdenv;
  pkgsAlt = lib.genAttrs' (lib.range 1 (config.pkgCount or 1)) (
    i:
    lib.nameValuePair "pkg${toString i}" (mkDerivation {
      name = "alt-pkg${toString i}";
      buildCommand = ''
        cat ${./pkg1.txt} > $out
      '';
    })
  );
}
