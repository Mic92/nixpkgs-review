{
  pkgs ? import <nixpkgs> { },
  withSandboxSupport ? false,
  withAutocomplete ? true,
  withNom ? false,
}:

with pkgs;
let
  withNom' =
    withNom
    && (builtins.tryEval (builtins.elem buildPlatform.system pkgs.ghc.meta.platforms)).value or false;
in
python3Packages.buildPythonApplication {
  name = "nixpkgs-review";
  src = ./.;
  format = "pyproject";
  nativeBuildInputs = [
    installShellFiles
    python3Packages.setuptools
  ] ++ lib.optional withAutocomplete python3Packages.argcomplete;
  dependencies = with python3Packages; [ argcomplete ];

  nativeCheckInputs =
    [
      python3Packages.pylint

      # needed for interactive unittests
      python3Packages.pytest
      python3Packages.pytest-xdist

      pkgs.nixVersions.stable or nix_2_4
      git
    ]
    ++ lib.optional withSandboxSupport bubblewrap
    ++ lib.optional withNom' nix-output-monitor;

  # Disable checks when building with sandbox support since bwrap doesn't work in build sandbox
  doCheck = !withSandboxSupport;

  checkPhase = ''
    # Set up test dependencies
    export TEST_BASH_PATH="${if stdenv.isLinux then pkgsStatic.bash else pkgs.bash}"
    export TEST_COREUTILS_PATH="${if stdenv.isLinux then pkgsStatic.coreutils else pkgs.coreutils}"
    export TEST_NIXPKGS_PATH="${pkgs.path}"

    # Set up Nix environment for sandbox builds
    export TEST_NIX_DIR=$TMPDIR/test-nix
    export NIX_STORE_DIR=$TEST_NIX_DIR/store
    export NIX_DATA_DIR=$TEST_NIX_DIR/share
    export NIX_LOG_DIR=$TEST_NIX_DIR/var/log/nix
    export NIX_STATE_DIR=$TEST_NIX_DIR/state
    export NIX_CONF_DIR=$TEST_NIX_DIR/etc

    mkdir -p $NIX_STORE_DIR $NIX_DATA_DIR $NIX_LOG_DIR $NIX_STATE_DIR $NIX_CONF_DIR

    # Disable substituters and sandboxing for tests
    export NIX_CONFIG="
    substituters =
    connect-timeout = 0
    sandbox = false
    sandbox-build-dir = $TEST_NIX_DIR/build
    "

    # Disable sandbox for tests (for macOS compatibility)
    export _NIX_TEST_NO_SANDBOX=1

    # Run tests
    python -m pytest tests/ -x
  '';
  makeWrapperArgs =
    let
      binPath =
        [
          pkgs.nixVersions.stable or nix_2_4
          git
        ]
        ++ lib.optional withSandboxSupport bubblewrap
        ++ lib.optional withNom' nix-output-monitor;
    in
    [
      "--prefix PATH : ${lib.makeBinPath binPath}"
      "--set-default NIX_SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt"
      # we don't have any runtime deps but nix-review shells might inject unwanted dependencies
      "--unset PYTHONPATH"
    ];

  postInstall = lib.optionalString withAutocomplete ''
    for cmd in nix-review nixpkgs-review; do
      installShellCompletion --cmd $cmd \
        --bash <(register-python-argcomplete $cmd) \
        --fish <(register-python-argcomplete $cmd -s fish) \
        --zsh <(register-python-argcomplete $cmd -s zsh)
    done
  '';

  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';
}
