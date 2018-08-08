{ attr-json }:

with builtins;
let
  pkgs = import <nixpkgs> {};
  attrs = fromJSON (readFile attr-json);
  getProperties = name: rec {
    exists = hasAttr name pkgs;
    broken = !exists || !(builtins.tryEval "${pkgs.${name}}").success;
    path = if !broken then "${pkgs.${name}}" else null;
  };
in
  pkgs.lib.genAttrs attrs getProperties
