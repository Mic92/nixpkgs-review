/*
Invocation:
Invocation; note that the number of processes spawned is four times
the number of cores -- this helps in two ways:
1. Keeping cores busy while I/O operations are in flight
2. Since the amount of time needed for the jobs is *not* balanced
   this minimizes the "tail latency" for the very last job to finish
   (on one core) by making the job size smaller.
*/
# see pkgs/top-level/nohydra
{
  checkMeta,
  includeBroken ? true,
  path,
  systems,
  localSystem,
  myChunk,
  numChunks,
  attrPathFile,
}: let
  pkgs = import <nixpkgs> {
    system = localSystem;
  };
  inherit (pkgs) lib;

  attrPaths = builtins.fromJSON (builtins.readFile attrPathFile);
  chunkSize = (lib.length attrPaths) / numChunks;
  myPaths = let
    dropped = lib.drop (chunkSize * myChunk) attrPaths;
  in
    if myChunk == numChunks - 1
    then dropped
    else lib.take chunkSize dropped;

  unfiltered = import (path + "/pkgs/top-level/release-outpaths.nix") {
    inherit
      checkMeta
      path
      includeBroken
      systems
      ;
  };

  f = i: m: a:
    lib.mapAttrs (
      name: values:
        if a ? ${name}
        then
          if lib.any (value: lib.length value <= i + 1) values
          then a.${name}
          else f (i + 1) values a.${name}
        else null
    ) (lib.groupBy (a: lib.elemAt a i) m);

  filtered = f 0 myPaths unfiltered;

  recurseEverywhere = val:
    if lib.isDerivation val || !(lib.isAttrs val)
    then val
    else (builtins.mapAttrs (_: v: recurseEverywhere v) val) // {recurseForDerivations = true;};
in
  recurseEverywhere filtered
