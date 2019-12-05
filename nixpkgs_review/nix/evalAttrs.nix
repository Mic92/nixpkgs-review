attr-json:

with builtins;
let
  pkgs = import <nixpkgs> {};
  lib = pkgs.lib;

  attrs = fromJSON (readFile attr-json);
  getProperties = name: let
    path = lib.splitString "." name;
    pkg = lib.attrByPath path null pkgs;
    maybePath = builtins.tryEval "${pkg}";
  in rec {
    exists = pkg != null;
    broken = !exists || !maybePath.success;
    path = if !broken then maybePath.value else null;
    drvPath = if !broken then pkg.drvPath else null;
  };
in
  pkgs.lib.genAttrs attrs getProperties
