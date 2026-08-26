# Amp completions

Shell completion for the [Amp CLI](https://ampcode.com/manual), generated from
Amp's own help output and distributed as a checked-in
[Carapace spec](https://carapace-sh.github.io/carapace-bin/spec.html).

It works with Bash, Zsh, Fish, Nushell, PowerShell, and other shells supported
by Carapace. Completion is static: pressing Tab does not start Amp, Python, or
any network request.

```text
amp th<Tab>        → thread, threads
amp --mode m<Tab>  → medium
```

## Install

First [install and configure Carapace](https://carapace-sh.github.io/carapace-bin/setup.html).
Then clone this repository and install the spec:

```sh
git clone https://github.com/meatcar/amp-completions.git
cd amp-completions
make install
```

Open a new shell after installation. `make install` copies `amp.yaml` to the
Carapace user spec directory under `${XDG_CONFIG_HOME:-$HOME/.config}`.

## How it works

`generate.py` recursively reads `amp --help` and each subcommand's help into
one command model. That model produces two files:

- `amp.yaml` is the completion spec installed by users.
- `amp-manifest.json` records canonical command and flag paths for update
  safety checks.

Both files identify the Amp version that produced them. The generator also
supplies semantic values that help output cannot describe, such as agent modes
and visibility levels.

The pinned Amp executable comes from
[`llm-agents.nix`](https://github.com/numtide/llm-agents.nix). Generated output
is deterministic and checked in, so changes are reviewable without running
Amp during completion.

## Development

Use the Nix development shell to regenerate and validate the spec:

```sh
nix develop --command make generate
nix develop --command make check
nix flake check
```

To test another Amp build:

```sh
AMP_BIN=/path/to/amp make generate
AMP_BIN=/path/to/amp make check
```

Do not edit `amp.yaml` or `amp-manifest.json` by hand. `make check` rejects
stale or nondeterministic generated files and runs the parser, policy,
workflow, and completion tests.

## Automated updates

- [Update Amp](.github/workflows/update-amp.yml) checks hourly. Additive
  command and flag changes merge after validation. Removals and other
  compatibility changes stay open with a concrete review question.
- [Update flake inputs](.github/workflows/update-flake-inputs.yml) updates the
  non-Amp root inputs weekly. It cannot change `llm-agents` or files other than
  `flake.lock`.
- Renovate updates SHA-pinned GitHub Actions. It does not update Nix inputs or
  merge pull requests. Current and pending updates appear in the
  [Dependency Dashboard](https://github.com/meatcar/amp-completions/issues/14).

All update candidates run the same checks as pull requests before they are
pushed. The workflows use scoped GitHub tokens and no repository secrets.

### Maintainer notes

Run either updater manually:

```sh
gh workflow run update-amp.yml --ref main
gh workflow run update-flake-inputs.yml --ref main
```

Rerun the owning workflow to rebuild a failed, stale, or conflicting candidate
from current `main`; do not edit generated branches. `flake-update` and
Renovate pull requests always require review. Amp pull requests without
`safe-update` require a compatibility decision.

The reusable `automation/amp-update` and `automation/flake-update` branches may
appear beside `main` after squash merges. Either may be deleted when it has no
open pull request; its workflow recreates it when needed.

## License

[MIT](LICENSE)
