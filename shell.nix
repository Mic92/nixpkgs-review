{ pkgs ? import <nixpkgs> { } }:

with pkgs;
pkgs.mkShell {
  nativeBuildInputs = [
    black
    mypy
  ];
}
