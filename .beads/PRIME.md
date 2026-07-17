# Beads + bh work — repo conventions

This repo tracks work with **bd** (beads) and integrates it with git through **`bh`**. Two
rules before anything else:

- **Drive the lifecycle with `bh work`, not raw `bd` / `git`.** `bh work` takes a bead from
  assigned → merged and applies this repo's config defaults (identity, commit signing,
  validation, review gate) for you.
- **Read beads with the first-class verbs** — `bh work ready|issue|list` (dependency-ordered,
  byte/JSON-stable output), not raw `bd` queries.
- **File epics/molecules with `bh plan file`, never hand-create them with `bh bd create`.** The
  planner compiler builds the full envelope a dispatcher needs to dispatch — the
  `provider:`/`org:`/`repo:` triplet + dimension labels, the bd swarm, and a per-root kickoff
  gate — which a hand-rolled `bh bd create` epic lacks.
- **`bh bd` is a gated last-resort fallback**, off by default (`passthrough.bd_enabled`): it
  exits non-zero with a steering message until you set `WS_BD_PASS_ENABLED=1` (or `WS_DEBUG=1`).
  Reach for it only for one-off issue surgery the convention verbs above don't cover.
- **Raw `git` is only for local work** — the actual change *inside* a worktree. Never use
  raw `git` / `bd` / `gh` to drive the lifecycle (claim, submit, merge), or you bypass the
  defaults the tooling sets up for you.

Beads is **issues only** — knowledge/memory lives in the project's own system (no
`bd remember`).

## Load the skill for your role

Each role skill states its duties and the verbs it uses; all of them build on the shared
**`work`** skill (the `bh work` verb reference).

| Role | Identity | Alias | Skill | Duty |
|---|---|---|---|---|
| Dispatcher | `disp/` | overseer | `dispatcher` | deliver an epic: assign beads to developers, watch gates, re-dispatch (collapsed mode inlines the implementation) |
| Developer | `dev/` | polecat | `developer` | take one assigned bead to a reviewable state |
| Reviewer | `rev/` | — | `reviewer` | walk an approved branch, resolve or bounce the review gate |
| Merger | `merge/` | the Refinery | `merger` | serialize merges to the integration branch, preserve history |

The full seat roster (Control supervisor/director/custodian/controller, Planning planner/analyst,
Assurance warden) is in the canon `docs/design/roles-rbac-matrix.md`. Gas-Town names are optional,
non-normative aliases.

## Conventions

- Every issue's home is the `provider:`/`org:`/`repo:` triplet — `bh plan file` injects it when
  it compiles a molecule; `bh labels validate` checks it. Dependencies are declared in the
  molecule spec (`deps:`) and filed by `bh plan file`, not hand-added.
- `bh plan verify <epic>` is the planner's done-gate: it checks a filed molecule against the
  planning-plane conventions (bd swarm, per-root kickoff gate, triplet + closed-dimension
  labels) — the same check `bh work start`/`assign`/`claim` run before dispatch.
- `bh work` reads per-rig defaults from config — load the `work` skill for details.

### Intake + outbound state vocabulary

Cross-rig report state (epic) is modelled with native
`bd set-state <bead> <dim>=<value>` (event-sourced, with the `<dim>:<value>` label cache),
**never ad-hoc labels**. The module `beadhive/state.py` is the single owner of the closed
vocabulary — downstream beads reuse it rather than re-inventing states:

| Dimension | Value | Meaning |
|---|---|---|
| `intake` | `untriaged` | untriaged inbound — set when a report lands, **cleared on triage** |
| `intake` | `accepted` / `rejected` / `rerouted` / `promoted` | the terminal value a triage disposition transitions to (clears `untriaged`) |
| `outbound` | `pending` | staged outbound candidate — captured with **zero public exposure** |
| `publish` | `approved` | the contributor filed it upstream (behind the human publish gate) |
| `origin` | `report` \| `github` \| `import` | the intake **CHANNEL** a bead entered through — a durable, source-agnostic provenance tag (orthogonal to the `intake` *queue* state) |

These are registered as **closed dimensions** (`beadhive/state.py:STATE_DIMENSIONS`, merged in by
`registry.closed_dimensions`), so intake/outbound/origin beads validate clean under `bh labels
validate` and an unknown value (e.g. `outbound:bogus`, `origin:carrier-pigeon`) is rejected.
Queue predicates `state.is_untriaged_intake(labels)` / `state.is_promoted(labels)` /
`state.is_outbound_candidate(labels)` drive the triage, planner-adopt, and contributor queues;
`state.channel_of(labels, source_system)` (label-first, else derived from `source_system`) /
`state.origin_of(labels)` / `state.is_report_origin` resolve the intake channel.

**Provenance convention — THREE orthogonal facets (operator-approved, epic):**

1. **System-of-record** = the **native** `source_system` + `external_ref` pair — bd's "mirrors
   an external system of record" coupling, settable only at import. Reserved for **external
   mirrors** (github / legacy import); a born-native report **never** overloads it.
2. **Intake channel** = the closed `origin` dimension above (set via `bd set-state origin=…`,
   like `intake`). `bh report` files via **plain `bd create` + `bd set-state origin=report`** —
   this retired the old `import` + `source_system=report` workaround (follow-up).
   Imported beads keep their native `source_system`; `state.origin_from_source_system(...)` derives
   their channel on **read** (a uniform triage queue) **without** re-stamping an `origin` label.
3. **Reporter identity** = `bd --actor` (unchanged) — **never** a closed label (`reported-by` is
   open-ended and would fail `bh labels validate`). Do not add a reporter label dimension.

### Fielding intake (triage duty)

Incoming reports must be **fielded, not buried in backlog**. The queue is **source-agnostic**:
`bh report` (`origin:report`), GitHub-issue import (`github`) and legacy import (`import`) all land
as `intake:untriaged` and share **one** triage queue. The **intake CHANNEL** is the closed `origin`
dimension, **not** the native `source_system`: reports carry an explicit `origin:report` label,
while imported beads derive their channel from `source_system` on read
(`state.channel_of` / `origin_from_source_system`) — uniform, no double-stamping.

- **See the queue:** `bh work intake` — this rig's untriaged intake (source-agnostic; the resolved
  `origin` channel rides each row). `--source report|github|import` narrows on that channel (not raw
  `source_system`). `bd find-duplicates` runs on entry (`bh report`) **and** at triage, surfacing
  likely dupes so a colliding request never buries the queue.
- **See the fleet:** `bh hq intake` — the director's fleet-wide inbox (untriaged intake
  across every rig).
- **Dispose (type-aware):**
  - `bh work accept <id> [--type T] [--priority P]` — set type/priority, clear intake → backlog.
  - `bh work reject <id> --reason "…"` — close with a reporter-visible reason.
  - `bh work reroute <id> --to <rig>` — re-file a mis-routed report into the right rig; or
    `--super <seat>` to bounce it to the director (stays in the fleet-wide inbox).
  - `bh work promote <id>` — hand to the planner (sets `intake:promoted`, the adopt queue key;
    the planner adopts it into a gated epic molecule).

- **Future follow-up:** cross-rig `bh hq` interchange (`bh plan` / `bh work --rig <id>`) is not
  wired yet.

### Escalation chain (flat-MVP)

The chain is flat and fire-and-forget at each rung:

1. **Developer** hits a `bh` / `bd` / tool bug → `bh escalate '<what> with <tool>'` — one
   one-liner to HQ; keep working. Do not route or investigate.
2. **HQ** queues it as `intake:untriaged` with `origin:escalation`. The director sees it
   via `bh hq intake` (fleet-wide inbox).
3. **Director** is the terminal router: `bh work reroute <id> --to <rig>` re-files it
   into the right rig; `bh work reroute <id> --super <seat>` keeps it in the fleet inbox for a
   second look; `bh work accept/reject/promote` handle clear-cut cases.

No auto-routing exists yet. The director decides where every escalation lands.

**Dispatcher** fields intake for its own rig: `bh work intake` shows the rig queue;
`accept / reject / reroute / promote` dispose of each item. Cross-rig or ambiguous items go up
with `reroute --super`; the director picks them up from `bh hq intake`.

- Run `bd prime` after compaction or in a new session to reload this context.
