## Codebase: Python + Carapace + Nix

```
flake.nix          # inputs only
.envrc             # env init
nix/flake-modules/ # flake parts: devshell.nix, treefmt.nix
generate.py        # Amp help parser and Carapace spec generator
amp.yaml           # generated, checked-in completion spec
```

## Principles

- Red/Green TDD. Conventional Commits: consistent scopes, short titles. Atomic, testable, logically distinct commits.
- Ask before network or out-of-workspace actions.

## Commands (repo root)

- `direnv exec .`: run commands
- `nix fmt`: format (run after every source edit)
- `nix flake check`: validate flake outputs
- `make check`: run unit tests and validate `amp.yaml`

## Nix

- Formatters (`treefmt-nix`): `nixfmt`, `deadnix`+`statix` (lint), `oxfmt`.

## Python

- Use only the standard library.
- Keep generation deterministic.
- Parse only documented fixture shapes; Amp's help output is the compatibility boundary.
