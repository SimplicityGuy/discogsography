# AGF — Agentic Git Flow

This repo is a **`bh` rig**: all work is tracked as beads and driven through `bh`, not raw
`git` / `bd` / `gh`. This page describes the bead-driven workflow end to end. For verb-level
mechanics see `.beads/PRIME.md` and the `bh:work` skill; run `bh rig ready` to check the repo's
AGF setup.

## The rule: no bead, no work

Every change — feature, fix, chore, docs — must have a bead filed for it before work starts.
Small, single-shot changes are a plain **issue** bead. Larger work (spans multiple files/areas,
needs several independent workstreams, or is naturally decomposable) is filed as an **epic**
bead with **task/bug children**, one bead per independently-mergeable unit of work.

When a bead is first filed, the filer asks whatever clarifying questions are needed to pin down
scope — this happens once, at filing time, not repeatedly afterward.

## Before execution starts

Before a claimed bead moves into active implementation, whoever is about to execute it resolves
any remaining ambiguity about the deliverable with clarifying questions, until the acceptance
criteria are unambiguous. Execution does not start on a bead whose "done" state is still fuzzy.

## Dispatch: one agent, one worktree, one branch

Once a bead (or an epic's children) is ready, work is dispatched to a team of agents — one
agent per bead. Each agent works in its **own git worktree**, on its **own ephemeral branch**
(`wt/bead/<id>`), never touching another bead's branch or the shared working tree. For an epic,
every child bead's branch forks off the epic's own container branch
(`wt/bead/epic/<epic-id>`), not off `main` — so children build on each other's epic-scoped
context without polluting `main` until the whole epic is ready.

Each agent commits freely inside its own worktree, self-refines its history into clean
conventional-commit digests, runs the bead's validation command until green, and submits for
review. Review is a gate: approved work is handed to a merger; changes-requested work is
returned to the same agent to address and resubmit.

## Landing an epic

All of an epic's children merge **serially**, one at a time, with `--no-ff`, into the epic's
own container branch (`wt/bead/epic/<epic-id>`) first — never straight to `main`. This keeps
the epic's integration history readable (one merge commit per child) and lets later children
build on earlier ones inside the epic branch.

Only once **every** child of the epic has landed cleanly on the epic branch does the epic branch
itself go up for integration into `main`:

1. Open a pull request from the epic branch (or the single bead branch, for standalone issues)
   into `main`.
2. Invoke code review on the PR.
3. Wait for CI to go green. If CI fails, investigate the failure and fix it on the branch —
   don't merge red.
4. Once CI is green and review has approved, merge the PR into `main`.
5. Close the bead (and, for an epic, its children) with closing comments that record what
   landed and why.

## Keep the beads database in sync

The beads database (`bd` / dolt-backed) is the shared source of truth for every rig. Push it to
the remote periodically (`bd dolt push`) — not just at the end of an epic — so other seats
(dispatcher, reviewer, merger, other agents) always see current state.

## Lifecycle at a glance

```mermaid
flowchart TD
    A[Idea / need] --> B{File a bead}
    B -->|small, single-shot| C[Issue bead]
    B -->|larger, decomposable| D[Epic bead + task/bug children]
    C --> E[Clarifying questions at filing]
    D --> E
    E --> F[Clarify deliverable before execution starts]
    F --> G[Dispatch: one agent per bead, own worktree + wt/bead/id branch]
    D -.epic children fork off.-> H[wt/bead/epic/id container branch]
    G --> I[Implement, refine, validate]
    I --> J[Submit for review]
    J -->|changes requested| G
    J -->|approved| K[Merge child --no-ff into epic branch, serially]
    K -->|more children pending| G
    K -->|all children landed| L[Open PR: epic/bead branch to main]
    L --> M[Code review + CI]
    M -->|CI red / changes requested| L
    M -->|CI green + approved| N[Merge to main]
    N --> O[Close bead(s) with closing comments]
    O --> P[bd dolt push]
```

## Key commands

- `bh work ready` / `bh work assign` / `bh work claim` — surface and take a bead
- `bh work submit` / `bh work review` — hand off to review, resolve the gate
- `bh work merge` — land an approved branch (epic child → epic branch, or epic/bead → `main`)
- `bh work finish` — close out a bead once merged
- `bd dolt push` — publish the beads database to the remote

See the `bh:work` skill for the full verb reference and flags; this page only covers the
workflow shape, not the CLI surface.
