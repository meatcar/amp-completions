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

## Update

Install the Amp version you want to describe, then regenerate the spec:

```sh
make generate
make check
```

The generator recursively calls `amp --help` and each subcommand's `--help`.
It does not run while completing commands.

Use another Amp executable when needed:

```sh
python3 generate.py --amp /path/to/amp
```

The generated command tree and flags follow Amp's help output. Semantic values
that cannot be inferred reliably, such as agent modes and visibility levels,
are maintained in `generate.py`.
