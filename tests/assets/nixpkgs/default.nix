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
    name = args.name or "env";
    buildCommand = "mkdir -p $out";
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
