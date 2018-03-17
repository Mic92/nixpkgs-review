with import <nixpkgs> {};

python3Packages.buildPythonApplication {
  name = "nix-review";
  src = ./.;
  buildInputs = [ makeWrapper ];
  preFixup = ''
    wrapProgram $out/bin/nix-review --prefix PATH : ${nix}/bin
  '';
}
