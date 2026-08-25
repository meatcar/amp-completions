# Draft: unattended Amp completion maintenance

This plan turns Amp releases into reviewed completion updates with no routine
owner action. Work through the numbered steps in order. Later steps assume the
interfaces and checks from earlier steps exist.

Each step has exactly one status marker:

- `#todo`: work has not started.
- `#doing`: implementation is active. Keep at most one step in this state.
- `#qa`: implementation is complete, but its acceptance checks or review remain.
- `#done`: every acceptance check passes and the step has an atomic jj commit.

Change the marker in place as work advances. Before starting a step, confirm all
earlier steps are `#done`. Follow `AGENTS.md`, use red/green TDD for behavior
changes, and leave a blank jj working-copy commit at the tip. Run `nix fmt` after
edits and `nix flake check` plus `make check` before moving a step to `#done`.

Routine implementation choices belong to the implementer. Stop and ask the
owner only at a decision gate named below, or before changing repository
settings, credentials, or other shared state. Ask one concrete question with a
recommended answer and the evidence needed to decide.

## Sequential plan

1. #done Define the unattended-update contract

Write the policy as executable expectations before adding automation. An
update is safe when it is additive, deterministic, limited to declared
generated files and lock data, and passes every check. Command or flag
removal, parser incompatibility, a command-count drop, or an unexpectedly
large generated diff requires owner review.

Acceptance:

- Tests or fixtures encode each safe and review-required class.
- Numeric limits have named constants and test cases at their boundaries.
- The policy returns a machine-readable result and a short human reason.

Decision gate: ask the owner only if real Amp history shows the proposed
limits would create frequent false alarms. Recommend limits from that
evidence rather than asking for arbitrary numbers.

2. #todo Source Amp from `llm-agents.nix`

Add `github:numtide/llm-agents.nix` as a flake input and expose
`inputs'.llm-agents.packages.amp` to the generator through `AMP_BIN`. Do not
add it to the development shell's `PATH`, where it would override the user's
Amp command. Remove the nixpkgs `amp-cli` package and its local unfree-package
allowance. Keep the stable nixpkgs input for the rest of the shell.

Acceptance:

- `AMP_BIN` resolves to the `llm-agents.nix` store path under `nix develop`.
- Entering the shell does not change the `amp` resolved from the parent `PATH`.
- `nix flake check` passes without a broad unfree-package setting.
- `make check` passes inside the development shell.

3. #todo Make generated state self-identifying

Keep the Amp version in `amp.yaml` and add a deterministic JSON manifest
generated from the same in-memory command model. The manifest is the policy
checker's input. It should contain the Amp version and canonical command and
flag paths, but no duplicated descriptions or presentation data.

Acceptance:

- One generator invocation writes both generated files.
- Repeating generation produces byte-identical files.
- Unit tests cover nested commands, aliases, local flags, and persistent
  flags in the manifest.
- Both files identify the same Amp version.

4. #todo Make `make check` authoritative

Extend the existing command rather than creating a separate CI test path. It
must run unit tests, byte-compile Python, validate the Carapace spec,
regenerate into a temporary directory, compare generated files with the
checked-in copies, and verify a second generation is identical.

Acceptance:

- A stale `amp.yaml` or manifest makes `make check` fail with a useful diff.
- Nondeterministic output makes `make check` fail.
- Temporary files are removed on success and failure.
- The command succeeds from a clean checkout under `nix develop`.

5. #todo Add completion smoke tests

Exercise Carapace through its command interface using a small set of stable
expectations. Cover a root command, a nested command, a persistent flag, and
a known semantic value such as `--mode`. Keep parser fixtures responsible for
detailed help-layout coverage.

Acceptance:

- Each smoke test fails when its expected completion is removed.
- Tests do not access the network or user Carapace configuration.
- `make check` runs the smoke tests in an isolated temporary configuration.

6. #todo Implement the update policy checker

Compare the checked-in manifest from the base revision with the candidate
manifest. Classify the update as `safe` or `review-required`, and emit JSON
for automation plus a concise Markdown report for a pull request.

Acceptance:

- Additive commands and flags classify as safe.
- Removed or renamed command and flag paths require review.
- Version rollback, malformed manifests, count drops, and excessive diff size
  require review.
- Unknown conditions fail closed as review-required.
- Tests cover every classification reason.

7. #todo Add pull-request CI

Create one validation workflow that enters the Nix shell and runs the same
repository commands used locally. Pin third-party actions by commit SHA. Use
read-only permissions and concurrency cancellation for superseded commits.

Acceptance:

- The workflow runs `nix flake check` and `make check`.
- A generated-file mismatch fails CI.
- Workflow permissions are read-only.
- A test pull request demonstrates both a failing and passing run.

8. #todo Detect upstream Amp updates

Add an hourly scheduled workflow with a manual trigger. Read the version from
`numtide/llm-agents.nix` at `packages/amp/hashes.json` and compare it with the
checked-in manifest. Exit successfully without creating branches when the
versions match.

Acceptance:

- The no-change path performs no repository write.
- A version mismatch produces a clear workflow output consumed by the next
  step.
- Network and parse failures are distinguishable from "no update."
- Concurrent detector runs cannot create duplicate work.

9. #todo Generate one update pull request

On a detected update, update only the `llm-agents` lock entry, regenerate the
checked-in files, run all checks, and create or refresh one bot branch and
pull request. Include old and new Amp versions plus the policy report. Reuse
the same branch while an update is open.

Acceptance:

- Repeated runs update one pull request rather than creating duplicates.
- The pull request changes only the allowed lock and generated files.
- Failed generation or validation never pushes a candidate branch.
- The pull request links the corresponding `llm-agents.nix` Amp update.

Decision gate: if GitHub suppresses required checks for pull requests created
with `GITHUB_TOKEN`, present the smallest working choice between an explicit
`workflow_dispatch` validation run and a narrowly scoped GitHub App. Do not
introduce a personal access token by default.

10. #todo Auto-merge safe updates

Apply an `amp-update` label to every generated update. Add `safe-update` only
when the policy checker returns safe. Enable auto-merge after required checks
pass. Leave review-required pull requests open with the exact reasons and no
repeated notifications.

Acceptance:

- A representative additive update merges without owner action.
- A representative removal remains open and cannot receive `safe-update`.
- A failed or missing required check prevents merging.
- The bot cannot approve unrelated pull requests.

11. #todo Add quiet failure escalation

Keep transient failures in workflow logs. After two consecutive failures for
the same Amp version and reason, create or update one issue. Close that issue
automatically after a successful update or when the upstream version changes
and no longer reproduces the failure.

Acceptance:

- One failure creates no issue.
- Repeated identical failures maintain one issue.
- The issue includes the Amp version, failing step, relevant log link, and one
  recommended next action.
- Recovery closes the matching issue without touching unrelated issues.

12. #todo Configure repository protections

Prepare the exact repository settings needed for required checks and
auto-merge. Keep write permissions scoped to the update workflow. This step
changes shared GitHub state and therefore requires explicit owner approval
immediately before applying it.

Acceptance:

- The owner approves the proposed settings as one concrete change set.
- The default branch requires the validation workflow.
- Force pushes and branch deletion are blocked on the default branch.
- GitHub Actions may create pull requests but cannot bypass required checks.

13. #todo Run an end-to-end update rehearsal

Temporarily base a test branch on an older `llm-agents.nix` Amp revision, then
run the detector and updater against the current revision. Exercise one safe
path and one review-required fixture without weakening policy checks.

Acceptance:

- Detection, regeneration, policy classification, pull-request creation,
  validation, and safe auto-merge all run in sequence.
- The review-required rehearsal stops before merge and explains why.
- No temporary branches, issues, labels, or fixtures remain afterward.
- The default branch contains no rehearsal-only exceptions.

14. #todo Document operation and ownership

Update the README with the generated-file contract, the upstream Amp source,
and the meaning of automation labels. Add a short maintainer section that
explains how to rerun detection, recover a failed update, and recognize a
decision-required pull request.

Acceptance:

- A new maintainer can reproduce an update with documented commands.
- Documentation points to `make check` rather than duplicating its internals.
- Every secret, permission, label, and scheduled workflow has a named purpose.
- `nix fmt`, `nix flake check`, and `make check` pass on the final stack.

15. #todo Close the plan

Observe at least one real upstream Amp update. Confirm that a safe update
reaches the default branch without owner action, or that a review-required
update asks one concrete question with enough evidence to answer it.

Acceptance:

- The real update follows the documented path.
- Any defect found during observation has a regression test.
- All earlier steps are `#done`.
- Replace this draft with durable maintenance documentation or remove it once
  its remaining information exists elsewhere.
