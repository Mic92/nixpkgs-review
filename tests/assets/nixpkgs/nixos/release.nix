{ nixpkgs ? <nixpkgs> }:
{
  options = derivation {
    name = "options";
    system = builtins.currentSystem;
    builder = "/bin/sh";
    args = [ "-c" "echo 'mock options' > $out" ];
  };
}
