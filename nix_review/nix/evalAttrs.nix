{ attr-json }:

with builtins;
let
  pkgs = import <nixpkgs> {};
  lib = pkgs.lib;
  attrs = fromJSON (readFile attr-json);
  getProperties = name: let
    attrPath = lib.splitString "." name;
    pkg = lib.attrByPath attrPath null pkgs;
  in rec {
    exists = pkg != null;
    broken = !exists || !(builtins.tryEval "${pkg}").success;
    path = if !broken then "${pkg}" else null;
  };
in
  lib.genAttrs attrs getProperties
