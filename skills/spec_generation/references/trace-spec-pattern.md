# Trace Spec Pattern (WebTrace)

The tracing stack records, at the app's boundaries: every HTTP request and response, every SQL
statement with its result rows, error code and row count, and the rows each `COMMIT` committed
(logical decoding). The trace builder turns one recording window into an NDJSON trace:

- line 1, the header: committed rows when the window starts (`tables`), the next value of each id
  sequence (`seq`), the actors (`actors`), and the largest key (`maxkey`);
- one event per model action, each with `actor`, `action`, `kind`, an interval `[lo, hi]` in which it
  took effect, and its outcome fields (`args`, `rows`, `has_rows`, `limit1`, `count`, `err`,
  `writes`, `status`, `resp`).

Events of one actor are in program order. Events of different actors are ordered only when their
intervals do not overlap. `WebTrace.tla` encodes that partial order (`Ready`, `Consume`, `done`), so
the trace spec only says how one event matches one step.

## Files

- `Trace<App>.tla`: `EXTENDS <App>, WebTrace`. The matching logic below.
- `Trace.tla`: `EXTENDS Trace<App>` (Specula's expected name).
- `Trace.cfg.tmpl`: the config template, with `@TRACE@` (trace path) and `@CUT@` (number of events to
  match) filled in by the toolkit's checker.

## Template

```tla
EXTENDS Booking, WebTrace

\* WebDB constants from the trace header (substituted in the cfg).
TraceActors == {Header.actors[i] : i \in 1..Len(Header.actors)}
TraceKeys == 1..Header.maxkey
Strip(rec) == [c \in DOMAIN rec \ {"k"} |-> rec[c]]
TraceInitRows ==
    [tb \in AppTables |-> [k \in TraceKeys |->
        LET rows == Header.tables[tb] IN
        IF \E i \in 1..Len(rows) : rows[i].k = k
        THEN Strip(rows[CHOOSE i \in 1..Len(rows) : rows[i].k = k]) ELSE Absent]]

Arg(e, f, d) == IF f \in DOMAIN e.args THEN e.args[f] ELSE d
RouteOf(action) == CASE action = "Book_Begin" -> "Book" [] action = "GetSeat_Begin" -> "GetSeat"
InputOf(e) == [route |-> RouteOf(e.action), token |-> Arg(e, "authorization", ""),
               seatId |-> Arg(e, "seatId", 0)]

ModelRows(S) == {[c \in {"k"} \cup DOMAIN p[2] |-> IF c = "k" THEN p[1] ELSE p[2][c]] : p \in S}
ObsRows(e) == {e.rows[i] : i \in 1..Len(e.rows)}

\* A statement's result equals the recorded one: rows, error code, affected-row count.
ResultOK(r, e) ==
    IF e.err # "" THEN ~res'[r].ok /\ res'[r].code = e.err
    ELSE /\ res'[r].ok
         /\ IF e.limit1
            THEN /\ ObsRows(e) \subseteq ModelRows(res'[r].rows)
                 /\ Cardinality(ObsRows(e)) = IF res'[r].rows = {} THEN 0 ELSE 1
            ELSE e.has_rows => ObsRows(e) = ModelRows(res'[r].rows)
         /\ e.kind = "write" => e.count = Cardinality(res'[r].rows)

\* COMMIT: exactly the rows logical decoding recorded, with the same values.
CommittedP(tb, k) == ver'[tb][k][Len(ver'[tb][k])][2]
CommitOK(r, e) ==
    /\ res'[r].ok
    /\ {<<w.table, w.k>> : w \in {e.writes[i] : i \in 1..Len(e.writes)}}
         = {p \in AppTables \X TraceKeys : Produces(wr[r][p[1]][p[2]])}
    /\ \A i \in 1..Len(e.writes) :
           LET w == e.writes[i] IN CommittedP(w.table, w.k) = IF w.present THEN Strip(w.row) ELSE Absent

StatementOK(r, e) ==
    CASE e.kind = "commit"               -> CommitOK(r, e)
      [] e.kind \in {"begin", "rollback"} -> res'[r].ok
      [] e.phase = "start"               -> TRUE
      [] OTHER                           -> ResultOK(r, e)

MatchEvent(j) ==
    LET e == Ev(j)  r == e.actor IN
    \/ e.kind = "request" /\ Arrive(r, InputOf(e))
    \/ e.kind = "response" /\ pc[r] = "respond" /\ rs[r].status = e.status /\ Respond(r)
    \/ /\ e.kind \notin {"request", "response"}
       /\ StepName(r) = e.action
       /\ Step(r)
       /\ StatementOK(r, e)

Init == AppInit([tb \in AppTables |-> Header.seq[tb]]) /\ TraceInit
TraceNext ==
    \/ \E j \in Ready : MatchEvent(j) /\ Consume(j)
    \/ DBSilent /\ UNCHANGED <<appVars, done>>
TraceSpec == Init /\ [][TraceNext]_<<vars, done>>
```

```
SPECIFICATION TraceSpec
CONSTANTS
    Txns <- TraceActors
    Tables <- AppTables
    Keys <- TraceKeys
    UniqueCols <- AppUniqueCols
    InitRows <- TraceInitRows
    RowDomain <- AppRowDomain
    AutoIso = "RC"
    Absent = Absent
    NoTxn = NoTxn
    NoWrite = NoWrite
    TracePath = "@TRACE@"
    Cut @CUT@
INVARIANT TraceNotDone
CHECK_DEADLOCK FALSE
```

## Rules

- **Existential, not `TraceMatched`.** `INVARIANT TraceNotDone` is violated exactly when some
  behavior matched `Cut` events; the checker reads that as ACCEPTED. Never add
  `PROPERTIES TraceMatched`: it asks that *all* behaviors consume the trace, which concurrent traces
  never satisfy.
- **Check outcomes, not just the action sequence.** Every statement's rows, error code and row count,
  every COMMIT's committed rows, every response's status (and the key response fields the mapping
  records). A trace spec that only checks action names validates nothing about state.
- **No extra silent actions.** The only unrecorded steps are WebDB's `DBSilent` (lock grants,
  deadlock and serialization failures). Anything else the app does shows up as a recorded event; if
  an event has no matching step, the model is missing it.
- `InputOf` decodes exactly the arguments the mapping file records for each route: path groups, body
  fields, headers (a header `idempotency-key` arrives as `idempotency_key`; a `bearer` header as
  the token alone).
- Absent values arrive as `-1` (int) and `""` (text): use the same defaults in the model's input record.
