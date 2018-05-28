# nix-review

[![Build Status](https://travis-ci.org/Mic92/nix-review.svg?branch=master)](https://travis-ci.org/Mic92/nix-review)

Review pull-requests on https://github.com/NixOS/nixpkgs. 
nix-review automatically builds packages changed in the pull requests

## Features

- [ofborg](https://github.com/NixOS/ofborg) support: reuses evaluation output of CI to skip local evaluation, but
  also fallbacks if ofborg is not finished
- automatically detects target branch of pull request
- provides a `nix-shell` with all build packages in scope
- remote builder support

## Requirements

`nix-review` depends on python 3.6 or higher and nix 2.0 or higher:

Install with:

```console
$ nix-build
./result/bin/nix-review
```

### Development Environment
```console
$ nix-build -A env -o .venv
```

or just use:

```console
./bin/nix-review
```

## Usage

Change to your local nixpkgs repository checkout, i.e.:

```console
cd ~/git/nixpkgs
```

Note that your local checkout git will be not affected by `nix-review`, since it 
will use [git-worktree](https://git-scm.com/docs/git-worktree) to perform fast checkouts.

Then run `nix-review` by providing the pull request number

```console
$ nix-review pr 37242
$ git fetch --force https://github.com/NixOS/nixpkgs pull/37242/head:refs/nix-review/0
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

```
$ nix-review rev HEAD
```

Instead of `HEAD` also a commit or branch can be given.

## Remote builder:

Nix-review will pass all arguments given in `--build-arg` to `nix-build`:

```console
$ nix-review --build-args="--builders 'ssh://joerg@10.243.29.170'" pr 37244
```

This allows to parallelize builds across multiple machines.

## Github api token

In case your IP exceeds the rate limit, github will return an 403 error message.
To increase your limit first create a [personal access token](https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line/).
Then use either the `--token` parameter of the `pr` subcommand or
set the `GITHUB_OAUTH_TOKEN` environment variable.

```console
$ nix-review pr --token "5ae04810f1e9f17c3297ee4c9e25f3ac1f437c26" 37244
```

## Roadmap

- [ ] Build multiple pull requests in parallel and review in serial.
- [ ] trigger ofBorg builds (write @GrahamcOfBorg build foo into pull request discussion)
- [ ] build on multiple platforms
- [ ] test backports
- [ ] show pull request description + diff during review
- [ ] spawn nix-shell also if some packages did not build

## Run tests

Just like `nix-review` also the tests are lightning fast:

```console
$ python3 -m unittest discover .
```

We also use python3's type hints. To check them use `mypy`:

```console
$ mypy nix_review
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
