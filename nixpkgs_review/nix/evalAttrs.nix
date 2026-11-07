{
  attr-json,
  include-tests ? false,
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
    fake =
      extra:
      derivation {
        name = "fake";
        system = "fake";
        builder = "fake";
      }
      // extra;

    pkgOrFake =
      name: pkg:
      let
        maybeDerivation = tryEval (lib.isDerivation pkg);
        maybePath = tryEval pkg.outPath;
        extra = {
          exists = true;
          broken = !maybeDerivation.success || !maybeDerivation.value || !maybePath.success;
        };
      in
      lib.nameValuePair name (
        builtins.addErrorContext "while evaluating the attribute `${name}`" (
          if extra.broken then fake extra else pkg // extra
        )
      );

    getProperties =
      include-tests': name:
      let
        attrPath = lib.splitString "." name;
        maybePkg = tryEval (lib.attrByPath attrPath null pkgs);
        pkg = maybePkg.value;
        exists = lib.hasAttrByPath attrPath pkgs;
      in
      # some packages are set to null or throw if they aren't compatible with a platform or package set
      if !maybePkg.success || pkg == null then
        [
          (lib.nameValuePair name (fake {
            inherit exists;
            broken = true;
          }))
        ]
      else if !lib.isDerivation pkg then
        if !lib.isAttrs pkg then
          # if it is not a package, ignore it (it is probably something like overrideAttrs)
          [ ]
        else
          lib.flatten (lib.mapAttrsToList (name': _: getProperties include-tests' "${name}.${name'}") pkg)
      else
        [ (pkgOrFake name pkg) ]
        # Tests can inherit their parent's tests via overrideAttrs, or refer to
        # the parent itself (causing infinite recursion).
        # Avoid infinite recursion by not including tests of tests.
        ++ lib.optionals (include-tests' && pkg ? tests) (getProperties false "${name}.tests");
  in
  listToAttrs (concatMap (getProperties include-tests) attrs) // { recurseForDerivations = true; }
) (fromJSON (readFile attr-json))
