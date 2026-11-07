{ pkgs }:
let
  mkPackage =
    name: tests:
    pkgs.stdenvNoCC.mkDerivation (finalAttrs: {
      inherit name;
      dontUnpack = true;
      buildPhase = "touch $out";
      passthru.tests = tests finalAttrs.finalPackage;
    });

  leaf = mkPackage "leaf" (_: { });
in
{
  inherit (pkgs) lib;

  selfReferencing = mkPackage "self-referencing" (pkg: {
    self = pkg;
    nested.test = leaf;
  });

  overridden = mkPackage "overridden" (pkg: {
    inherited = pkg.overrideAttrs { doCheck = true; };
  });

  single = mkPackage "single" (_: leaf);
  group.package = mkPackage "grouped" (_: { nested.test = leaf; });
}
