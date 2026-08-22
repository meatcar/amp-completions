# Handoff

## Objective

Build and publish shell completion for the Amp CLI. The chosen shape is a
standalone repository that generates a Carapace YAML spec from Amp's recursive
`--help` output. Carapace supplies the shell integrations. Generation happens
ahead of time, never during Tab completion.

The repository is `/git/hub/meatcar/amp-completions`. Start with `jj status` and
read [README.md](README.md) for the public contract and commands.

## Current state

The repository is initialized with jj/Git. All files are uncommitted in the
initial working-copy commit.

Implemented:

- `generate.py` recursively discovers commands, aliases, local flags, required
  flag values, and optional flag values.
- `amp.yaml` is generated for Amp `0.0.1787155755-g62ff24`.
- Known values are supplied for `--mode`, `--visibility`, and `--features`.
- Home-directory paths are normalized to `~` before publication.
- `tests/test_generate.py` covers parsing and rendering behavior.
- `Makefile` provides `generate`, `test`, `check`, and `install` targets.

Verification completed:

```sh
make check
```

This runs five unit tests, byte-compiles the Python, and validates `amp.yaml`
with `carapace --run`. A temporary Carapace config also confirmed:

```text
amp th       -> thread, threads
amp --mode m -> medium
```

Regenerating `amp.yaml` twice produced the same SHA-256 hash.

## Decisions and constraints

- Keep the project standalone, but use Carapace as the first output format.
- Keep `amp.yaml` checked in so installation requires neither Python nor Amp.
- Use only the Python standard library for generation.
- Parse only each command's `Options:` section. Root options become Carapace
  persistent flags; nested `Global options:` sections are intentionally ignored.
- Amp has two option-help layouts. Most descriptions are on following lines,
  while commands such as `amp version --help` put the description inline.
  Preserve tests for both.
- Strip backticks from flag descriptions during rendering. Cobra/pflag treats
  backtick-delimited words as metavariable names, which previously corrupted
  the rendered `--orb-execute` help.
- Amp's help format is regular but not a documented API. Parser fixtures and
  deterministic generation are the compatibility boundary.

## Likely next work

1. Review the initial implementation and generated spec for missing command or
   flag shapes.
2. Add positional completion. Start with safe static classes such as files and
   directories, then consider live Amp data only where Amp exposes fast,
   machine-readable output.
3. Add CI that regenerates and validates the spec against the current Amp CLI.
4. Decide release and installation channels. The current installation copies
   `amp.yaml` to `${XDG_CONFIG_HOME:-$HOME/.config}/carapace/specs/amp.yaml`.
5. Commit the initial repository when the diff is accepted. Follow the user's
   jj conventions and leave a blank working-copy commit at the tip.

Do not add a standalone completion daemon or shell-specific renderers unless
Carapace proves insufficient. The current YAML spec already supports Bash,
Zsh, Fish, Nushell, PowerShell, and other Carapace targets.

## Suggested skills

Call these with the Skill tool when their branch begins:

- `jj` before any VCS command.
- `jj-commit` when preparing the initial commit.
- `tdd` when extending parser or completion behavior.
- `open-source-contributions` when preparing the repository for public release.
- `context7-mcp` when checking current Carapace APIs or spec syntax.
