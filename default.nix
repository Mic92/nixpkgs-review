{ pkgs ? import <nixpkgs> { }
, withSandboxSupport ? false
}:

with pkgs;
python3.pkgs.buildPythonApplication rec {
  name = "nixpkgs-review";
  src = ./.;
  buildInputs = [ makeWrapper ];
  checkInputs = [
    mypy
    python3.pkgs.black
    python3.pkgs.flake8
    glibcLocales

    # needed for interactive unittests
    python3.pkgs.pytest
    pkgs.nixVersions.nix_2_4 or nix_2_4
    git
  ];

  checkPhase = ''
    ${if pkgs.lib.versionAtLeast python3.pkgs.black.version "20" then ''
      echo -e "\x1b[32m## run black\x1b[0m"
      LC_ALL=en_US.utf-8 black --check .
    '' else ''
      echo -e "\033[0;31mskip running black (version too old)\x1b[0m"
    ''}
    echo -e "\x1b[32m## run flake8\x1b[0m"
    flake8 .
    echo -e "\x1b[32m## run mypy\x1b[0m"
    mypy --strict nixpkgs_review
  '';
  makeWrapperArgs =
    let
      binPath = [ pkgs.nixVersions.nix_2_4 or nix_2_4 git ]
        ++ lib.optional withSandboxSupport bubblewrap;
    in
    [
      "--prefix PATH : ${lib.makeBinPath binPath}"
      "--set NIX_SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt"
      # we don't have any runtime deps but nix-review shells might inject unwanted dependencies
      "--unset PYTHONPATH"
    ];
  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';

  passthru.env = buildEnv { inherit name; paths = buildInputs ++ checkInputs; };
}
