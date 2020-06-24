attr-json:

with builtins;
let
  pkgs = import <nixpkgs> {};
  lib = pkgs.lib;

  attrs = fromJSON (readFile attr-json);
  getProperties = name: let
    attrPath = lib.splitString "." name;
    pkg = lib.attrByPath attrPath null pkgs;
    maybePath = builtins.tryEval pkg.drvPath;
    exists = lib.hasAttrByPath attrPath pkgs;
  #in rec {
  #  #path = if !broken then maybePath.value else null;
  #  inherit name;
  #  drvPath = if !broken then pkg.drvPath else null;
  #  #tests = if !broken && pkg ? tests && builtins.isAttrs pkg.tests then
  #  #  builtins.attrNames pkg.tests
  #  #else
  #  #  [];
  #};
  in if exists && maybePath.success then maybePath else null;
in map getProperties attrs
  #pkgs.lib.genAttrs attrs getProperties
