<!-- bh:agf:start (managed by `bh hive init` — edit outside these markers; `-f` refreshes) -->
## AGF — Agentic Git Flow

This repo is onboarded as a **`bh` hive** and develops via **AGF**: work is tracked in beads
and driven through `bh`, **not** raw `git` / `bd` / `gh`.

- **Is this repo set up for AGF?** → run `bh hive ready` (add `-v` for the line-item breakdown).
- **Lifecycle, roles, conventions:** see `docs/AGF.md` and the bh plugin's role skills.
- Drive beads with `bh work`; load the role skill for your seat (coordinator / developer / merger).
- Batch/collapsed work lives in ONE shared `wt/batch/<group>` worktree and completes as a UNIT:
  `bh work submit --group` then `bh work merge --group` — per-bead `submit`/`check` don't apply.
<!-- bh:agf:end -->

<!-- bv-agent-instructions-v3 -->

---

## Beads workflow (beadhive)

> **Editing note.** `bv` locates this section by its **marker comments and version number
> only — never by content**. The prose may diverge freely from `bv`'s stock text, but the
> two `<!-- ... -->` marker lines must stay byte-identical and must not be renumbered, or
> `bv` resumes prompting `Run 'bv --agents-add' ...` at startup. Splice programmatically;
> do not retype the markers. **Do not run `bv --agents-update`** — it replaces everything
> between the markers with stock boilerplate, discarding this hive-specific content.

Work in this repo is tracked as **beads** and driven through **`bh`** (beadhive). `bv` is
the triage engine. Every command below is verified to run in this hive.

### Reading (all read-only, all `--json`-capable)

```bash
bh work ready                 # beads with no unmet blockers, dependency-ordered
bh work list --status open    # filter by state
bh work issue <id>            # one bead's fields (labels, model:/harness:)
bh work brief <id>            # requirements/goals + the validation command
bh work show <id>             # the bead BRANCH's commit history (not the bead's fields)
```

`bh work show` and `bh work issue` are different surfaces — `show` renders
`base..wt/bead/<type>/<id>`, which is what you use to judge history noise before
submitting.

Reach for `bh` rather than `bd`: a `PreToolUse` hook warns that direct `bd` is not
hive-aware and can hit the wrong database. The `bh bd` passthrough is **disabled** in this
hive (`passthrough.bd_enabled`, default off) and exits non-zero instead of forwarding, so
it is not an available path either.

### Filing

- **Epics / molecules** → `bh plan file`, or drive the `bh:planner` skill. Hand-rolled
  epics fail the molecule convention check, so do not assemble one bead at a time.
- **A single standalone bead** → the `bh` MCP **`bd_create`** tool, which batch-creates
  from structured items and applies this hive's provider/org/repo labels.

### Lifecycle

```bash
bh work claim <id>            # worker ack: provision the worktree -> in_progress
bh work check <id>            # run the hive's validation command
bh work submit <id>           # hand off to review: opens the review gate
bh work approve <id>          # resolve a HUMAN review gate
bh work merge <id>            # merge owner: serialize integration onto the base
bh work resume <id>           # re-attach after changes-requested
bh work abandon <id> [--rm]   # release the claim
```

Two behaviors that surprise people:

- **`submit` publishes the branch only when the review gate is `gh:run` or `gh:pr`.** With
  the default in-process **human** gate it does *not* push, so no PR appears and the pull
  request is opened by hand.
- **`submit` rejects noisy history** — more than `max_commits` over base, or
  non-conventional subjects. `bh work show <id>` inspects it and `bh work refine <id>`
  (`--autosquash`, `--plan`, `--since`) squashes local checkpoints back under the bar
  behind a backup branch.

### Triage with `bv`

**Bare `bv` launches an interactive TUI that blocks the session — always use a
`--robot-*` flag.**

```bash
bv --robot-triage                  # the mega-command: start here
bv --robot-next                    # just the single top pick
bv --robot-triage --format toon     # token-optimized output
```

| Flag | Returns |
|---|---|
| `--robot-plan` | Parallel execution tracks with unblocks lists |
| `--robot-priority` | Priority misalignment detection with confidence |
| `--robot-insights` | PageRank, betweenness, HITS, eigenvector, critical path, cycles, k-core |
| `--robot-alerts` | Stale issues, blocking cascades, priority mismatches |
| `--robot-suggest` | Hygiene: duplicates, missing deps, label suggestions, cycle breaks |
| `--robot-diff --diff-since <ref>` | Changes since a ref |
| `--robot-graph [--graph-format=json\|dot\|mermaid]` | Dependency graph export |

Scoping: `--label <name>`, `--as-of <ref>`, `--recipe actionable`, `--recipe high-impact`.

`bv` reads an **exported snapshot**, not the live database, so it can lag. Confirm state
with `bh work issue <id>` before acting, and ignore any `claim_command` it emits —
claiming here is `bh work claim`. Only `quick_ref.top_picks` represents claimable work;
`recommendations` can include blocked or already-assigned beads for graph reasons.

### Key concepts

- **Priorities** are numbers: `0` critical, `1` high, `2` medium, `3` low, `4` backlog.
- **Types** (from `bd types`, which is authoritative — `bd create --help` lists an
  incomplete subset): `task`, `bug`, `feature`, `chore`, `epic`, `decision`, `spike`,
  `story`, `milestone`. There is no `docs` or `question` type; those are rejected.
- **Dependencies** block work; `bh work ready` already filters unmet blockers out.
- **One worktree per bead**, provisioned by `claim`/`assign`. Never share a worktree
  between concurrent agents — and likewise never share a test database or a Redis logical
  DB, or parallel runs corrupt each other. The durable artifact is the
  `wt/bead/<type>/<id>` branch, not the directory.
- **Work in the bead worktree, never the main clone.** `claim` prints the path.

### Dolt remote

The bead corpus is **not** stored in git — `.beads/` is gitignored and the corpus lives on
the dolt remote (`refs/dolt/data`). Local closes are not durable until pushed:

```bash
bd dolt push        # publish local bead changes to the remote
```

`bd dolt commit` usually reports `Nothing to commit`, because bh auto-commits corpus
mutations; the push is the step that matters. Note `bh sync` is unrelated — it rebuilds
the hub, it is not a corpus flush.

### Git policy

`bv` never writes, and `bh work` owns every git operation around the lifecycle — raw `git`
is for the change *inside* the worktree only. This repository's own git rules take
precedence over any generic workflow advice from tooling output: every change gets a bead
first, work happens in bh-managed worktrees, changes land via a PR, and nothing is
committed or pushed unless explicitly asked.
<!-- end-bv-agent-instructions -->
