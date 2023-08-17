# nixpkgs-review

![Build Status](https://github.com/Mic92/nixpkgs-review/workflows/Test/badge.svg)

Review pull-requests on https://github.com/NixOS/nixpkgs.
nixpkgs-review automatically builds packages changed in the pull requests.

NOTE: this project used to be called `nix-review`

## Features

- [ofborg](https://github.com/NixOS/ofborg) support: reuses evaluation output of CI to skip local evaluation, but
  also falls back if ofborg is not finished
- provides a `nix-shell` with all packages that did not fail to build
- remote builder support
- allows to build a subset of packages (great for mass-rebuilds)
- allow to build nixos tests
- markdown reports
- GitHub integration:
  - post PR comments with results
  - approve or merge PRs (the last one requires maintainer permission)
  - show PR comments/reviews
- logs per built or failed package
- symlinks built packages to result directory for inspection

## Installation

`nixpkgs-review` is included in nixpkgs. Older versions of nixpkgs might still
call it `nix-review`.

To use it without installing it, use:

```console
$ nix run nixpkgs#nixpkgs-review
```

To install it:

```console
$ nix-env -f '<nixpkgs>' -iA nixpkgs-review
```

To run it from the git repository:

```console
$ nix-build
$ ./result/bin/nixpkgs-review
```

Note that this asserts formatting with the latest version of
[black](https://github.com/psf/black), so you may need to specify a more up to
date version of nixpkgs:

```console
$ nix-build -I nixpkgs=https://github.com/NixOS/nixpkgs-channels/archive/nixpkgs-unstable.tar.gz
$ ./result/bin/nixpkgs-review
```

### Development Environment

For IDEs:

```console
$ nix-build -A env -o .venv
```

or just use:

```console
./bin/nixpkgs-review
```

## Usage

First, change to your local nixpkgs repository directory, i.e.:

```console
cd ~/git/nixpkgs
```

Note that your local checkout git will not be affected by `nixpkgs-review`, since it
will use [git-worktree](https://git-scm.com/docs/git-worktree) to perform fast checkouts.

Then run `nixpkgs-review` by providing the pull request number…

```console
$ nixpkgs-review pr 37242
```

…or the full pull request URL:

```console
$ nixpkgs-review pr https://github.com/NixOS/nixpkgs/pull/37242
```

The output will then look as follows:

```console
$ git fetch --force https://github.com/NixOS/nixpkgs pull/37242/head:refs/nixpkgs-review/0
$ git worktree add /home/joerg/git/nixpkgs/.review/pr-37242 1cb9f643480612696de93fb2f2a2f3340d0e3156
Preparing /home/joerg/git/nixpkgs/.review/pr-37242 (identifier pr-37242)
Checking out files: 100% (14825/14825), done.
HEAD is now at 1cb9f643480 redis: 4.0.7 -> 4.0.8
Building in /tmp/nox-review-4ml2epyy: redis
$ nix-build --no-out-link --keep-going --max-jobs 4 --option build-use-sandbox true <nixpkgs> -A redis
/nix/store/jbp7m1gshmk8an8sb14glwijgw1chvvq-redis-4.0.8
$ nix-shell -p redis
[nix-shell:~/git/nixpkgs]$ /nix/store/jbp7m1gshmk8an8sb14glwijgw1chvvq-redis-4.0.8/bin/redis-cli --version
redis-cli 4.0.8
```

To review a local commit without pull request, use the following command:

```console
$ nixpkgs-review rev HEAD
```

Instead of `HEAD` a commit or branch can also be given.

To review uncommitted changes, use the following command:

```console
$ nixpkgs-review wip
```

Staged changes can be reviewed like this:

```console
$ nixpkgs-review wip --staged
```

If you'd like to post the `nixpkgs-review` results as a formatted PR comment,
pass the `--post-result` flag:

```console
$ nixpkgs-review pr --post-result 37242
```

Instead of posting a PR comment, nixpkgs-review can also print the report to
the terminal using the `--print-result` flag. This flag will work for the `rev`
and `wip` command..

```console
$ nixpkgs-review pr --print-result 37242
```

Often, after reviewing a diff on a pull request, you may want to say "This diff
looks good to me, approve/merge it provided that there are no package build
failures". To do so, run the following subcommands from within the nix-shell provided
by nixpkgs-review.

```console
$ nixpkgs-review pr 37242
nix-shell> nixpkgs-review approve
# Or, if you have maintainer access and would like to merge (provided no build failures):
nix-shell> nixpkgs-review merge
# It is also possible to upload the result report from here
nix-shell> nixpkgs-review post-result
# Review-comments can also be shown
nix-shell> nixpkgs-review comments
```

`nixpkgs-review` will by default use [nix-output-monitor](https://github.com/maralorn/nix-output-monitor) if found in `$PATH`.
If you have `nom` installed but don't want to use it, you can pass `nix` to `--build-graph` to use `nix build` instead of `nom build`.

Some pull requests may require configuration for nixpkgs to test out. You can
use the `--extra-nixpkgs-config` flag to supply extra configuration for nixpkgs.

```console
$ nixpkgs-review pr 37242 --extra-nixpkgs-config '{ cudaSupport = true; }'
```

## Using nixpkgs-review in scripts or other programs

After building, `nixpkgs-review` will normally start a `nix-shell` with the
packages built, to allow for interactive testing. To use `nixpkgs-review`
non-interactively in scripts, use the `--no-shell` command, which can allow for
batch processing of multiple reviews or use in scripts/bots.

Example testing multiple unrelated PRs and posting the build results as PR
comments for later review:

```bash
for pr in 807{60..70}; do
    nixpkgs-review pr --no-shell --post-result $pr && echo "PR $pr succeeded" || echo "PR $pr failed"
done
```

`nixpkgs-review` also accepts a `--run` flag that allows to run a custom command
inside the nix-shell instead of an interactive session:

``` console
$ nixpkgs-review pr --run 'jq < report.json' 113814
# ...
{
  "blacklisted": [],
  "broken": [],
  "built": [
    "cargo-deny"
  ],
  "failed": [],
  "non-existent": [],
  "pr": 113814,
  "system": "x86_64-linux",
  "tests": []
}
```

## Review multiple pull requests at once

nixpkgs-review accept multiple pull request numbers at once:

```console
$ nixpkgs-review pr 94524 94494 94522 94493 94520
```

This will first evaluate & build all pull requests in serial.
Then a nix-shell will be opened for each of them after the previous
shell has been closed.

Tip: Since it's hard to keep track of the numbers, for each opened
shell the corresponding pull request URL is shown.


## Remote builder

Nix-review will pass all arguments given in `--build-arg` to `nix-build`:

```console
$ nixpkgs-review pr --build-args="--builders 'ssh://joerg@10.243.29.170'" 37244
```

As an alternative, one can also specify remote builder as usual in `/etc/nix/machines`
or via the `nix.buildMachines` nixos options in `configuration.nix`.
This allows to parallelize builds across multiple machines.

## GitHub api token

Some commands (i.e., `post-result` or `merge`) require a GitHub API token, and
even for read-only calls, GitHub returns 403 error messages if your IP hits the
rate limit for unauthenticated calls.

To use a token, first create a [personal access token](https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line/). If you plan to post comments with the reports generated, you need to add the ``repo:public_repo`` scope.

Then use either the `GITHUB_TOKEN` environment variable or the `--token` parameter of the `pr` subcommand.

```console
$ GITHUB_TOKEN=5ae04810f1e9f17c3297ee4c9e25f3ac1f437c26 nixpkgs-review pr  37244
```

Additionally, nixpkgs-review will also read the oauth_token stored by [hub](https://hub.github.com/) and [gh](https://cli.github.com/).


## Checkout strategy (recommend for r-ryantm + cachix)

By default, `nixpkgs-review pr` will merge the pull request into the pull request's
target branch (most commonly master). However, at times mass-rebuilding commits
have been applied in the target branch, but not yet built by hydra. Often those
are not relevant for the current review, but will significantly increase the
local build time. For this case, the `--checkout` option can be specified to
override the default behavior (`merge`). By setting its value to `commit`,
`nixpkgs-review` will checkout the user's pull request branch without merging it:

```console
$ nixpkgs-review pr --checkout commit 44534
```

## Only building a subset of packages

To build only certain packages, use the `--package` (or `-p`) flag.

```console
$ nixpkgs-review pr -p openjpeg -p ImageMagick 49262
```

There is also the `--package-regex` option that takes a regular expression
to match against the attribute name.

```console
# build only linux kernels but not the packages
$ nixpkgs-review pr --package-regex 'linux_' 51292
```

To skip building certain packages, use the `--skip-package` (or `-P`) flag.

```console
$ nixpkgs-review pr -P ImageMagick 49262
```

There is also the `--skip-package-regex` option that takes a regular expression
to match against the attribute name.
Unlike the `--package-regex` option, a full match is required, which means you probably want to work with `.*` or `\w+`.

```console
# skip building linux kernels but not the packages
$ nixpkgs-review pr --skip-package-regex 'linux_.*' 51292
```

`-p`, `-P`, `--package-regex` and `--skip-package-regex` can be used together, in which case
the matching packages will be merged.

Full documentation for regex matching syntax can be found
[here](https://docs.python.org/3/library/re.html#regular-expression-syntax).

## Running tests

NixOS tests can be run by using the `--package` feature and our `nixosTests` attribute set:

```console
$ nixpkgs-review pr -p nixosTests.ferm 47077
```

## Ignoring ofborg evaluations

By default, nixpkgs-review will use ofborg's evaluation result if available to
figure out what packages need to be rebuilt. This can be turned off using
`--eval local`, which is useful if ofborg's evaluation result is outdated. Even
if using `--eval ofborg`, nixpkgs-review will fall back to local evaluation if
ofborg's result is not (yet) available.

## Review changes in personal forks

Both the `rev` and the `wip` subcommand support a `--remote` argument to
overwrite the upstream repository URL (defaults to
`https://github.com/NixOS/nixpkgs`). The following example will use
`mayflower`'s nixpkgs fork to fetch the branch where the changes will be merged into:

```console
$ nixpkgs-review --remote https://github.com/mayflower/nixpkgs wip
```

Note that this has been not yet implemented for pull requests, i.e., `pr` subcommand.

## Review changes for other operating systems/architectures

The `--system` flag allows setting a system different from the current one.
Note that the result nix-shell may not be able to execute all hooks correctly
since the architecture/operating system mismatches.

```console
$ nixpkgs-review pr --system aarch64-linux 98734
```

## Review changes inside sandbox [EXPERIMENTAL]

The `--sandbox` flag setups a sandbox using
[bubblewrap](https://github.com/containers/bubblewrap). This is the same tool
used by Flatpak and OSTree, and offers an unprivileged sandbox based on user
namespaces.

Keep in mind that `--sandbox` flag is not necessary tuned for privacy or
security. Instead, it uses a pretty lax sandbox where it is possible to leak
data sensitive by environment variables or stateful filesystems (like `/run`).
The reason for this is because many packages would break otherwise, and this
would make this flag useless for review purposes.

The objective of `--sandbox` is to protect your system against accidental
modification and to offer a clean(ish) system state where packages can be
tested. For example, it mounts a `tmpfs` in-place of your `HOME` directory,
avoiding situations where a dirty configuration on your `HOME` directory can
lead to a broken package during testing. It also protects your `HOME` and system
against undesired files created during package testing.

This flag is still in an experimental stage. Please note that it isn't
exhaustive tested against nixpkgs, so some packages may break under it. Before
disapproving a PR because the program is broken under the sandbox, try without
this flag first to make sure that the issue is not the sandbox. If the issue is
caused because of the sandbox, please open an issue including the PR number in
nixpkgs so we can try to fix this issue.

```console
$ nix-shell -p bubblewrap # or install it using NixOS/Home-Manager/etc.
$ nixpkgs-review --sandbox pr 98734
```

## Roadmap

- [ ] build on multiple platforms
- [ ] test backports
- [ ] show pull request description + diff during review

## Run tests

To run tests use:

```console
$ pytest
```

We also use python3's type hints. To check them, use `mypy`:

```console
$ mypy nixpkgs_review
```

## Related projects:

- [nox-review](https://github.com/madjar/nox):
    - works but is as slow as a snail: the checkout process of nox-review is slow
      since it requires multiple git fetches. Also it cannot make use of
      ofborg's evaluation
    - it only builds all packages without providing a `nix-shell` for review
- [niff](https://github.com/FRidh/niff):
    - only provides a list of packages that have changed, but does not build packages
    - also needs to evaluate changed attributes locally instead of using ofborg
