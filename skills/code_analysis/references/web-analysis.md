# Web Application Analysis

Targets are **web applications**: HTTP (REST, GraphQL, RPC, server actions) request handlers,
background jobs and webhooks over shared stores, usually a relational database. This reference
extends `deep-analysis.md`; the evidence rules of the main guide are unchanged.

## Why web apps fit this workflow

A web app is a concurrent system even when no line of its code mentions threads. Many requests run
handlers at the same time against one database. Each handler is a sequence of statements separated by
`await`s, and **a transaction does not make those statements atomic**: other requests run between
them, and the isolation level only decides what each statement sees and when it waits or fails. The
classic web bugs are interleaving bugs: oversell, double booking, double charge, duplicate side
effects, lost updates, stuck states.

## Step 0 additions

Record in the brief:

- **Framework, ORM, database**, with the evidence (lockfiles, config).
- **Isolation level per transaction**: the database default (PostgreSQL: READ COMMITTED) and every
  per-transaction override (e.g. Prisma `$transaction(..., { isolationLevel })`, Django
  `select_for_update`, raw `SET TRANSACTION`). Cite each.
- **Stores and channels**: databases, caches (Redis), queues and job runners, webhook endpoints (in
  and out), external APIs, real-time channels. Later phases pick environment modules from this list
  (`WebDB.tla` covers PostgreSQL).
- **Deployment profile** that matters for concurrency: replica count, where cron runs, queue
  concurrency, connection pool size, provider retry policies. Unknown is fine; say so.

## Map the attack surface: the entry-point × entity write matrix

For each entity (table) the invariants care about, list **every** path that reads or writes it:
routes, GraphQL resolvers and mutations, server actions, jobs, cron, webhook handlers, admin pages,
seed or migration scripts that run in production. Read the ORM calls; cite `file:line`.

Any entity with **two or more writers**, or a **read-then-write path**, is a Scenario candidate, even
with no bug history. This finds race surfaces in young codebases.

## Patterns to hunt

- **Check-then-act across statements** (TOCTOU): availability or stock read, then a separate insert or
  update. Inside a READ COMMITTED transaction this is still racy. Look for a missing conditional update
  (`UPDATE ... WHERE stock >= n`), `SELECT ... FOR UPDATE`, or constraint.
- **Read-modify-write computed in the app**: `x = row.v + 1; update(v = x)` without a row lock. Compare
  with atomic `v = v + 1` (safe under row locks).
- **Uniqueness checked in the app but not enforced by the database**: `findFirst`/`exists` then
  `create` with no UNIQUE index behind it. Idempotency keys are the common case.
- **Idempotency outside the transaction**, or keyed lookups without a unique constraint: concurrent
  retries both pass the lookup.
- **Side effects before commit** (dual write): email, webhook, payment or cache write issued, then the
  transaction rolls back; or committed but the side effect is lost. No outbox.
- **Non-idempotent handlers under at-least-once delivery**: webhooks and jobs retried or delivered twice
  or out of order.
- **Status state machines spread across handlers** that disagree: one path allows a transition another
  path forbids; a terminal state left by one path.
- **The same check enforced differently on different entry points** (REST vs GraphQL vs admin vs job).
- **Guards that exist only in the browser** (disabled buttons, client validation): a direct API call
  bypasses them. Treat the API as the trust boundary.
- **Deadlock-prone lock orders**: two paths locking the same rows in different orders.

Mostly sequential logic (pricing, tax, time zones, slot arithmetic) and single-request security bugs
(injection, XSS, missing authorization on one call) are out of scope for model checking: record them
under the brief's test/review findings, not as Scenarios.

## Invariant families

Instantiate these against the app's entities. Each needs evidence that the app promises it: quote the
README, docs, API contract, a constraint, a test, or code enforcing it on another path. A family alone
is not evidence.

- **Exclusivity / uniqueness**: no two X share a key (a seat, a slot, an active subscription, a
  username, an idempotency key).
- **Capacity / conservation**: allocated ≤ capacity; balance ≥ 0; quantities conserved across orders,
  cancellations and refunds.
- **At-most-once and exactly-once effects**: one charge, one email, one webhook per business event.
- **State-machine legality**: only allowed status transitions; terminal states stay terminal.
- **Cross-entity consistency**: paid ⇒ captured; derived counters match their source rows.
- **Idempotency**: a retried request with the same key returns the same result with no extra effect.
- **Tenant / user isolation**: a response contains only data the caller may see, including after
  revocation (needs response capture in the harness).
- **Liveness**: pending states eventually resolve through the system's own mechanisms (expiry jobs,
  provider retries), never through assumed user behavior.

## Fault model

Request timeout plus client retry; double submit and parallel tabs; server crash between two
statements outside a transaction; transaction abort or serialization failure; webhook duplicate or
reorder; job retry or concurrent job run; external call succeeds but its response is lost.
Concurrency itself is normal operation, not a fault.

## Bug-archaeology keywords (in addition to `bug-archaeology.md`)

duplicate, double, twice, race, concurrent, idempotent, idempotency, oversell, overbook, double charge,
double booking, retry, webhook, lock, deadlock, serialization failure, `IntegrityError`, `P2002`,
`P2034`, `23505`, `40001`, `40P01`, `SELECT FOR UPDATE`, `select_for_update`, `$transaction`,
`atomic()`, isolation.

## Modeling-brief notes

- One Scenario per mechanism, each naming the entry points, the statements (in order) and the
  invariant. Cite the contract evidence for every invariant.
- List the tables and columns the invariants and guards read; everything else is abstracted away.
- State the isolation level and the deployment-profile assumptions each Scenario depends on.
