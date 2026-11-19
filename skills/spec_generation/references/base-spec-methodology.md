# Base Spec Methodology: Web Apps on WebDB

How to write the model (`<App>.tla`, wrapped by `base.tla`) from a Modeling Brief.

## Principle: Scope-Driven, Code-Faithful

The model's **scope** follows the requested behavior, contracts and Scenarios in the brief. Include
the handlers and state needed for that scope even without a suspected defect. The **logic** of each
step must follow the implementation's control flow exactly: its conditions, branches and state
updates, for the statements the app really sends.

**Every logic block within a step must be annotated with source code line references.**

## Model Shape

```tla
EXTENDS WebDB, TLC

AppTables == {"Seat", "Booking"}
AppUniqueCols == [tb \in AppTables |->            \* unique indexes after the PK, in creation order
    CASE tb = "Booking" -> << {"seatId"} >> [] OTHER -> << >>]
AppRowDomain == [tb \in AppTables |-> {}]          \* only SERIALIZABLE transactions use it

VARIABLES pc, rq, lv, rs, nextId
appVars == <<pc, rq, lv, rs, nextId>>
vars == <<dbVars, appVars>>
```

- **Actors are requests** (and job runs, webhook deliveries): WebDB's `Txns` constant, one database
  session each. Per actor: `pc` (handler step), `rq` (inputs), `lv` (locals), `rs` (response).
- `Arrive(r, input)`: an idle actor starts a handler with an input record (route, auth token, path
  and body fields, headers). Requests rejected before any SQL (no auth header, body validation)
  respond directly from `Arrive`. `Respond(r)`: the response is sent.
- **Ids from sequences** are app-level counters (`nextId[tb]`) that do not roll back, as in PostgreSQL.
- **Unique constraints**: `UniqueCols` in index-creation order (the primary key is checked first).
  Read them from the migrations.
- **Isolation level**: the database default (PostgreSQL: READ COMMITTED) unless the code overrides it
  for the transaction; cite it.
- `RowDomain`: for apps that never use SERIALIZABLE, `[tb \in Tables |-> {}]`. Otherwise every row
  value the model can produce.
- Foreign-key checks take KEY SHARE locks that WebDB does not model. Say in the model whether that
  matters (it does not when no path updates a referenced key column).

## One Step per Statement

Each SQL statement the handler issues is one step, in the order the code issues it:

| Statement | WebDB call | Steps |
|---|---|---|
| `SELECT` (no locking) | `Select(r, tb, P)` | 1 |
| `UPDATE`, `DELETE`, `SELECT ... FOR UPDATE` | `WriteStart(r, kind, tb, P)` then `WriteFinish(r, P, F)`; kind `"update"`, `"delete"`, `"lock"` | 2: the statement can wait on row locks while others run |
| `INSERT` | `InsertStart(r, tb, key, row)` then `InsertFinish(r)` | 2: unique checks can wait |
| `BEGIN` / `COMMIT` / `ROLLBACK` | `Begin(r, iso)`, `Commit(r)`, `Rollback(r)` | 1 each |

Statements outside `Begin` are autocommit. `P` is a predicate `LAMBDA k, row : ...`; `F` an update
`LAMBDA k, row : [row EXCEPT !.held = @ + 1]`.

```tla
\* routes/book.ts:L41 - read the seat inside the transaction (READ COMMITTED)
Book_ReadSeat(r) ==
    /\ pc[r] = "bk_read"
    /\ Select(r, "Seat", LAMBDA k, row : k = rq[r].seatId)
    /\ IF res'[r].rows = {}
       THEN ToRollback(r, "bk_rollback", 404)                     \* L42-L43: unknown seat
       ELSE IF (CHOOSE p \in res'[r].rows : TRUE)[2].held >= (CHOOSE p \in res'[r].rows : TRUE)[2].capacity
       THEN ToRollback(r, "bk_rollback", 409)                     \* L44-L45: sold out
       ELSE Go(r, "bk_hold") /\ UNCHANGED rs
    /\ UNCHANGED <<rq, lv, nextId>>

\* routes/book.ts:L47 - held = held + 1 (relative: re-evaluated under the row lock)
Book_Hold_start(r) ==
    /\ pc[r] = "bk_hold"
    /\ WriteStart(r, "update", "Seat", LAMBDA k, row : k = rq[r].seatId)
    /\ Go(r, "bk_hold_f")
    /\ UNCHANGED <<rq, lv, rs, nextId>>

Book_Hold_finish(r) ==
    /\ pc[r] = "bk_hold_f"
    /\ \/ /\ WriteFinish(r, LAMBDA k, row : k = rq[r].seatId, LAMBDA k, row : [row EXCEPT !.held = @ + 1])
          /\ IF res'[r].ok THEN Go(r, "bk_insert") /\ UNCHANGED rs
             ELSE ToRollback(r, "bk_rollback", 500)
       \/ /\ stmt[r] = NoStmt /\ ~res[r].ok                       \* failed while waiting (40P01, 40001)
          /\ ToRollback(r, "bk_rollback", 500) /\ UNCHANGED dbVars
    /\ UNCHANGED <<rq, lv, nextId>>
```

- **Read each result from `res'[r]`**: `rows` (a set of `<<key, row>>`), `ok`, `code` (SQLSTATE).
  Branch on it exactly as the handler does: a unique violation (`23505`, Prisma `P2002`, Django
  `IntegrityError`) → the handler's error path; zero rows → its not-found path.
- **Every `_finish` step has a branch for a statement that failed while waiting**
  (`stmt[r] = NoStmt /\ ~res[r].ok`: deadlock or serialization failure).
- **`LIMIT 1` queries** return any one matching row: choose with `\E p \in res'[r].rows`.
- **Model the statement, not the ORM call.** A relative update (`SET v = v - $1`) is re-evaluated on
  the newest row version under the lock; a value computed in the app and written back
  (`SET v = $1`) is not. That difference is the lost-update bug.
- **Error handling of the framework**: what an exception inside a transaction does (Prisma rolls
  back and rethrows; Django `atomic()` rolls back), and what status the client then gets.

## Granularity Audit

Walk every step and ask:

| Question | If "yes" → split |
|---|---|
| Does it cover more than one SQL statement? | Yes |
| Does it span an `await` on any I/O (cache, queue, external API, email)? | Yes |
| Does it read a value in one statement and write a value computed from it in another? | Yes (two steps; the gap is the race) |
| Is it a single statement? | No (already correct; waiting statements are start/finish pairs) |

State-space cost is controlled in the MC layer (fewer actors, narrower `Inputs`, hunt configs), never
by merging steps. Merging statements hides exactly the interleavings where web bugs live.

## `StepName`, `Step` and `Next`

```tla
StepName(r) ==                       \* the trace action name of r's next step, from its pc
    CASE pc[r] = "bk_begin"  -> "Begin"
      [] pc[r] = "bk_read"   -> "Book_ReadSeat"
      [] pc[r] = "bk_hold"   -> "Book_Hold_start"
      [] pc[r] = "bk_hold_f" -> "Book_Hold_finish"
      [] ...

Step(r) == Book_Begin(r) \/ Book_ReadSeat(r) \/ Book_Hold_start(r) \/ Book_Hold_finish(r) \/ ...

Next == \/ \E r \in Txns : \E input \in Inputs : Arrive(r, input)
        \/ \E r \in Txns : Step(r) \/ Respond(r)
        \/ DBSilent /\ UNCHANGED appVars
```

`StepName` must agree with the instrumentation spec: trace validation matches each recorded
statement to the step its request is at through it. `DBSilent` is where lock acquisition, deadlock
detection and serialization failures happen; it must be in `Next`.

## Invariants

In `<App>Invariants.tla` (`EXTENDS <App>`), shared by model checking and the reproduction checks.
Read committed state with `Committed(tb, k)` and `CommittedKeys(tb)`:

```tla
\* README "Booking": a seat is never sold beyond its capacity.
NoOverbooking ==
    \A s \in CommittedKeys("Seat") :
        Cardinality({b \in CommittedKeys("Booking") : Committed("Booking", b).seatId = s})
            <= Committed("Seat", s).capacity
```

Each invariant's comment quotes its contract evidence. Three kinds: domain invariants (the app's
promises), code-level invariants (legal status transitions, idempotency records), structural
invariants (sanity checks that hold in every correct state).

## Faults

Concurrency is not a fault. Model as bounded faults only what the brief's fault model names: a
client retry of a request whose response was lost, a crash between two autocommit statements, a
duplicate webhook delivery, a job retry. Each is an action the MC layer bounds with a counter.
