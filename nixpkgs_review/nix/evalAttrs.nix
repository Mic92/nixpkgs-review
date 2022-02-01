{ allowAliases ? false, attr-json }:

with builtins;
let
  pkgs = import <nixpkgs> { config = { checkMeta = true; allowUnfree = true; inherit allowAliases; }; };
  lib = pkgs.lib;

  attrs = fromJSON (readFile attr-json);
  getProperties = name: let
    attrPath = lib.splitString "." name;
    pkg = lib.attrByPath attrPath null pkgs;
    # some packages are set to null if they aren't compatible with a platform or package set
    maybePath = if pkg == null then
        { success = false; value = null; }
      else
        builtins.tryEval "${pkg}";
  in rec {
    exists = lib.hasAttrByPath attrPath pkgs;
    broken = !exists || !maybePath.success;
    path = if !broken then maybePath.value else null;
    drvPath = if !broken then pkg.drvPath else null;
  };
in
  pkgs.lib.genAttrs attrs getProperties
