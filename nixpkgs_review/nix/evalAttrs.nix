{ allowAliases ? false, attr-json }:

with builtins;
let
  pkgs = import <nixpkgs> { config = { checkMeta = true; allowUnfree = true; inherit allowAliases; }; };
  inherit (pkgs) lib;

  attrs = fromJSON (readFile attr-json);
  getProperties = name:
    let
      attrPath = lib.splitString "." name;
      pkg = lib.attrByPath attrPath null pkgs;
      debugAttr = attr: lib.concatStringsSep "   " (lib.mapAttrsToList
        (name: value: "${name}=${value}")
        (lib.mapAttrs
          (name: value:
            if (isAttrs value && lib.hasAttr "outPath" value) then
              value.outPath
            else
              "")
          attr
        )
      );
      maybePath =
        if lib.strings.isCoercibleToString pkg then
          tryEval "${pkg}"
        else
          throw "Tried building attr set with the following content: ${debugAttr pkg}";
    in
    rec {
      exists = lib.hasAttrByPath attrPath pkgs;
      broken = !exists || !maybePath.success;
      path = if !broken then maybePath.value else null;
      drvPath = if !broken then pkg.drvPath else null;
    };
in
pkgs.lib.genAttrs attrs getProperties
