# Amp completions

Shell completion for the [Amp CLI](https://ampcode.com/manual), generated from
Amp's own help output and distributed as a
[Carapace spec](https://carapace-sh.github.io/carapace-bin/spec.html).

## Install

Install and configure [Carapace](https://carapace-sh.github.io/carapace-bin/setup.html),
then copy the spec into its user spec directory:

```sh
make install
```

Open a new shell after installing the spec. Carapace supports Bash, Zsh, Fish,
Nushell, PowerShell, and several other shells.

## Generated files

`amp.yaml` and `amp-manifest.json` are generated together from Amp's help
output. Do not edit either file by hand. `amp.yaml` is the Carapace spec;
`amp-manifest.json` records command, alias, and flag paths for update policy
checks.

The pinned Amp package comes from the
[`llm-agents.nix`](https://github.com/numtide/llm-agents.nix) flake input. The
development shell exposes that package as `AMP_BIN` without adding an `amp`
command to `PATH`.

To update the pin and regenerate both files:

```sh
nix flake update llm-agents
nix develop --command make generate
nix flake check
nix develop --command make check
```

The generator recursively calls `amp --help` and each subcommand's help. It
does not run during completion. `make check` rejects stale or nondeterministic
generated files and runs the test suite.

Use another Amp executable when needed:

```sh
AMP_BIN=/path/to/amp make generate
AMP_BIN=/path/to/amp make check
```

The generated command tree and flags follow Amp's help output. Semantic values
that cannot be inferred reliably, such as agent modes and visibility levels,
are maintained in `generate.py`.

## Automation

The `Update Amp` workflow checks `llm-agents.nix` at minute 17 of every hour.
When it finds a new Amp version, it updates the reusable
`automation/amp-update` branch, regenerates the files, runs the checks, and
opens or refreshes one pull request.

The `Update flake inputs` workflow runs every Monday at 05:37 UTC. It updates
the root `nixpkgs`, `flake-parts`, `flake-root`, and `treefmt-nix` inputs on the
reusable `automation/flake-update` branch. It rejects changes to `llm-agents`
or files other than `flake.lock`, then opens a pull request for review with the
`flake-update` label. Renovate handles only SHA-pinned GitHub Actions and does
not update Nix inputs or merge pull requests.

Every generated pull request has `amp-update`. An additive update that passes
the unattended policy also has `safe-update` and merges after the required
`validate` check passes. A pull request without `safe-update` stays open. Its
policy report lists the removed commands, flags, aliases, or other condition
that needs a decision. `amp-update-failure` marks the issue created after the
same version fails at the same step twice. A later successful run closes that
issue.

The workflows use no repository secrets. They use GitHub's per-run token with
these permissions:

- Validation has `contents: read` to check out the repository.
- Update has `contents: write` to maintain the candidate branch,
  `pull-requests: write` to create, label, and queue its pull request,
  `actions: write` to rerun the pull-request validation suppressed for
  GitHub-authored commits, and `issues: write` for repeated-failure reports.

### Maintainer operations

Run detection immediately:

```sh
gh workflow run update-amp.yml --ref main
gh run list --workflow update-amp.yml --limit 5
```

A failed candidate is not pushed. Fix the reported step, then rerun the
workflow. It reuses the existing branch and pull request. Repeated failures
also link their run from one `amp-update-failure` issue.

For a pull request with `amp-update` but no `safe-update`, read the policy
report before merging. If an upstream removal is expected, verify the named
paths and merge after `validate` passes. If the report names parser
incompatibility, nondeterminism, an undeclared file, or an unexpected lock
change, fix the generator or workflow and rerun instead.
