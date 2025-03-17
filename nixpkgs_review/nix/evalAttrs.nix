{
  attr-json,
  include-passthru-tests,
}:

with builtins;
mapAttrs (
  system: attrs:
  let
    pkgs = import <nixpkgs> {
      inherit system;
      config = import (getEnv "NIXPKGS_CONFIG") // {
        allowBroken = false;
      };
    };

    inherit (pkgs) lib;

    # nix-eval-jobs only shows derivations, so create an empty one to return
    fake = derivation {
      name = "fake";
      system = "fake";
      builder = "fake";
    };

    getProperties =
      name:
      let
        attrPath = lib.splitString "." name;
        maybePkg = tryEval (lib.attrByPath attrPath null pkgs);
        pkg = maybePkg.value;
        exists = lib.hasAttrByPath attrPath pkgs;
      in
      # some packages are set to null or throw if they aren't compatible with a platform or package set
      if !maybePkg.success || pkg == null then
        [
          (lib.nameValuePair name (
            fake
            // {
              inherit exists;
              broken = true;
            }
          ))
        ]
      else if !lib.isDerivation pkg then
        if builtins.typeOf pkg != "set" then
          # if it is not a package, ignore it (it is probably something like overrideAttrs)
          [ ]
        else
          lib.flatten (lib.mapAttrsToList (name': _: getProperties ("${name}.${name'}")) pkg)
      else
        let
          maybePath = tryEval "${pkg}";
          broken = !maybePath.success;
        in
        [ (lib.nameValuePair name (pkg // { inherit exists broken; })) ]
        ++ lib.optionals include-passthru-tests (
          lib.flip lib.mapAttrsToList pkg.passthru.tests or { } (
            test: drv:
            let
              maybePath = tryEval drv.outPath;
              broken = !maybePath.success || !lib.isDerivation drv;
            in
            lib.nameValuePair "${name}.passthru.tests.${test}" (
              drv
              // {
                inherit exists broken;
                recurseForDerivations = false; # dont recurse into 'broken' tests
              }
            )
          )
        );
  in
  listToAttrs (concatMap getProperties attrs) // { recurseForDerivations = true; }
) (fromJSON (readFile attr-json))
