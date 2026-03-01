{ attr-json }:

with builtins;
let
  pkgs = import <nixpkgs-wrapper> {
    config = {
      allowBroken = false;
    };
  };

  inherit (pkgs) lib;

  attrs = fromJSON (readFile attr-json);
  getProperties =
    name:
    let
      attrPath = lib.splitString "." name;
      pkg = lib.attrByPath attrPath null pkgs;
      exists = lib.hasAttrByPath attrPath pkgs;
    in
    if pkg == null then
      [
        (lib.nameValuePair name {
          inherit exists;
          broken = true;
          path = null;
          drvPath = null;
        })
      ]
    else if !lib.isDerivation pkg then
      if builtins.typeOf pkg != "set" then
        # if it is not a package, ignore it (it is probably something like overrideAttrs)
        [ ]
      else
        lib.flatten (lib.mapAttrsToList (name': _: getProperties ("${name}.${name'}")) pkg)
    else
      lib.flip map pkg.outputs or [ "out" ] (
        output:
        let
          # some packages are set to null if they aren't compatible with a platform or package set
          maybePath = tryEval "${lib.getOutput output pkg}";
          broken = !exists || !maybePath.success;
        in
        lib.nameValuePair (if output == "out" then name else "${name}.${output}") {
          inherit exists broken;
          path = if !broken then maybePath.value else null;
          drvPath = if !broken then pkg.drvPath else null;
        }
      );
in

listToAttrs (concatMap getProperties attrs)
