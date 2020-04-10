# nixpkgs-review

![Build Status](https://github.com/Mic92/nixpkgs-review/workflows/Test/badge.svg)

Review pull-requests on https://github.com/NixOS/nixpkgs.
nixpkgs-review automatically builds packages changed in the pull requests

NOTE: this project used to be called `nix-review`

## Features

- [ofborg](https://github.com/NixOS/ofborg) support: reuses evaluation output of CI to skip local evaluation, but
  also fallbacks if ofborg is not finished
- automatically detects target branch of pull request
- provides a `nix-shell` with all packages that did not fail to build
- remote builder support
- allows to build a subset of packages (great for mass-rebuilds)
- allow to build nixos tests
- colorful output
- markdown reports
- GitHub integration to post PR comments with results
- GitHub integration to approve PRs if no builds fail
- GitHub integration to merge PRs if no builds fail (requires NixPkgs maintainer permission)
- logs per built or failed package
- symlinks build packages to result directory for inspection

## Installation

`nixpkgs-review` is included in nixpkgs. Older versions of nixpkgs might still
call it `nix-review`.

To use it run without installing it, use:

```console
$ nix run nixpkgs.nixpkgs-review
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
date version of NixPkgs:

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

Change to your local nixpkgs repository checkout, i.e.:

```console
cd ~/git/nixpkgs
```

Note that your local checkout git will be not affected by `nixpkgs-review`, since it
will use [git-worktree](https://git-scm.com/docs/git-worktree) to perform fast checkouts.

Then run `nixpkgs-review` by providing the pull request number...

```console
$ nixpkgs-review pr 37242
```

... or the full pull request url:

```console
$ nixpkgs-review pr https://github.com/NixOS/nixpkgs/pull/37242
```

The output then looks as follow:

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

If you'd like to post the `nixpkgs-review` results as a formatted PR comment,
pass the `--post-result` flag:

```console
$ nixpkgs-review pr --post-result 37242
```

Often, after reviewing a diff on a pull request, you may want to say "This diff
looks good to me, approve/merge it provided that there are no package build
failures". To do so:

```console
$ nixpkgs-review pr --no-shell --post-result --approve 37242
```

Or, if you have maintainer access and would like to merge (provided no build failures):

```console
$ nixpkgs-review pr --no-shell --post-result --approve --merge 37242
```

To review a local commit without pull request, use the following command:

```console
$ nixpkgs-review rev HEAD
```

Instead of `HEAD` also a commit or branch can be given.

To review uncommited changes, use the following command:

```console
$ nixpkgs-review wip
```

Staged changes can be reviewed like this:

```console
$ nixpkgs-review wip --staged
```

## Using nix-review in scripts

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

## Remote builder:

Nix-review will pass all arguments given in `--build-arg` to `nix-build`:

```console
$ nixpkgs-review pr --build-args="--builders 'ssh://joerg@10.243.29.170'" 37244
```

As an alternative one can also specify remote builder as usual in `/etc/nix/machines`
or via the `nix.buildMachines` nixos options in `configuration.nix`.
This allows to parallelize builds across multiple machines.

## Github api token

The `pr --post-result` option requires a Github API token, and even for read-only
calls github returns 403 error messages if your IP hits the rate limit for
unauthenticated calls.

To use a token, first create a [personal access token](https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line/).
Then use either the `--token` parameter of the `pr` subcommand or set the
`GITHUB_OAUTH_TOKEN` environment variable.

```console
$ nixpkgs-review pr --token "5ae04810f1e9f17c3297ee4c9e25f3ac1f437c26" 37244
```

## Checkout strategy (recommend for r-ryantm + cachix)

By default `nixpkgs-review pr` will merge the pull request into the pull request's
target branch (most commonly master). However at times mass-rebuilding commits
have been applied in the target branch, but not yet build by hydra. Often those
are not relevant for the current review, but will significantly increase the
local build time. For this case the `--checkout` option can specified to
override the default behavior (`merge`). By setting its value to `commit`,
`nixpkgs-review` will checkout the user's pull request branch without merging it:

```console
$ nixpkgs-review pr --checkout commit 44534
```

## Only building a subset of packages

To build only certain packages use the `--package` (or `-p`) flag.

```console
$ nixpkgs-review pr -p openjpeg -p ImageMagick 49262
```

There is also `--package-regex` option that takes a regular expression
to match against the attribute name:

```console
# build only linux kernels but not the packages
$ nixpkgs-review pr --packages-regex 'linux_' 51292
```

`-p` and `--package-regex` can be used together in which case
the matching packages will merged.

## Running tests

NixOS tests can be run by using the `--package` feature and our `nixosTests` attribute set:

```console
$ nixpkgs-review pr -p nixosTests.ferm 47077
```

## Ignoring ofborg evaluations

By default, nixpkgs-review will use ofborg's evaluation result if available to
figure out what packages need to be rebuild. This can be turned off using
`--eval local`, which is useful if ofborg's evaluation result is outdated. Even
if using `--eval ofborg`, nixpkgs-review will fallback to local evaluation if
ofborg's result is not (yet) available.

## Review changes in personal forks

Both the `rev` and the `wip` subcommand support a `--remote` argument to
overwrite the upstream repository URL (defaults to
`https://github.com/NixOS/nixpkgs`). The following example will use the
`mayflower` nixpkg's fork to fetch the branch where the changes will be merged into:

```
nixpkgs-review --remote https://github.com/mayflower/nixpkgs wip
```

Note that this has been not yet implemented for pull requests i.e. `pr` subcommand.

## Roadmap

- [ ] build on multiple platforms
- [ ] test backports
- [ ] show pull request description + diff during review

## Run tests

Just like `nixpkgs-review` also the tests are lightning fast:

```console
$ python3 -m unittest discover .
```

We also use python3's type hints. To check them use `mypy`:

```console
$ mypy nixpkgs_review
```

## Related projects:

- [nox-review](https://github.com/madjar/nox):
    - works but is slow as a snail: the checkout process of nox-review is slow
      since it requires multiple git fetches. Also it cannot make use of
      ofborg's evaluation
    - it only builds all packages without providing a `nix-shell` for review
- [niff](https://github.com/FRidh/niff):
    - only provides a list of packages that have changed, but does not build packages
    - also needs to evaluate changed attributes locally instead of using ofborg
