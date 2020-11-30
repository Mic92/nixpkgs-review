{ pkgs ?  import <nixpkgs> {} }:

with pkgs;
python3.pkgs.buildPythonApplication rec {
  name = "nixpkgs-review";
  src = ./.;
  buildInputs = [ makeWrapper ];
  checkInputs = [
    mypy
    python3.pkgs.black
    python3.pkgs.flake8
    python3.pkgs.pytest
    glibcLocales
  ];
  checkPhase = ''
    echo -e "\x1b[32m## run unittest\x1b[0m"
    py.test .
    echo -e "\x1b[32m## run black\x1b[0m"
    LC_ALL=en_US.utf-8 black --check .
    echo -e "\x1b[32m## run flake8\x1b[0m"
    flake8 nixpkgs_review
    echo -e "\x1b[32m## run mypy\x1b[0m"
    mypy --strict nixpkgs_review
  '';
  makeWrapperArgs = [
    "--prefix PATH : ${stdenv.lib.makeBinPath [ nixFlakes git ]}"
    "--set NIX_SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt"
    # we don't have any runtime deps but nix-review shells might inject unwanted dependencies
    "--unset PYTHONPATH"
  ];
  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';

  passthru.env = buildEnv { inherit name; paths = buildInputs ++ checkInputs; };
}
