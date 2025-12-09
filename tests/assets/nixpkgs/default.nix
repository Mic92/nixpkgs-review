{
  config ? { },
  system ? null, # deadnix: skip
}@args:
with import ./config.nix;
let
  currentSystem = if system != null then system else builtins.currentSystem;

  stdenv = {
    inherit mkDerivation;
  };

  mkShell = attrs: mkDerivation (attrs // {
    name = attrs.name or "shell";
    buildCommand = "echo 'mock shell' > $out";
  });

  bashInteractive = mkDerivation {
    name = "bash-interactive";
    buildCommand = ''
      mkdir -p $out/bin
      ln -s ${shell} $out/bin/bash
    '';
  };

  buildEnv = args: mkDerivation {
    inherit (args) name paths;
    buildCommand = ''
      mkdir -p $out
      ln -s $paths $out
    '';
  };
in
{
  pkg1 = mkDerivation {
    name = "pkg1";
    buildCommand = ''
      cat ${./pkg1.txt} > $out
    '';
  };

  inherit lib mkShell bashInteractive stdenv buildEnv;
}
