# MC Spec Pattern

The MC wrapper (`MC.tla`, `EXTENDS <App>Invariants`) runs a few concurrent requests from a small,
seeded database. Hunt configs narrow it to one Scenario each.

## Structure

```tla
EXTENDS BookingInvariants

CONSTANT Inputs                        \* the requests an actor may send (substituted per cfg)

\* Seed data (db/seed.ts), shrunk to what the Scenarios need.
MCKeys == 1..3
MCInitRows == [tb \in AppTables |-> [k \in MCKeys |->
    CASE tb = "Seat" /\ k = 1 -> [capacity |-> 1, held |-> 0]
      [] OTHER                -> Absent]]
MCSeq == [tb \in AppTables |-> CASE tb = "Seat" -> 2 [] OTHER -> 1]

In(route, token, seat) == [route |-> route, token |-> token, seatId |-> seat]

TwoBuyersInputs == {In("Book", "tok-a", 1), In("Book", "tok-b", 1)}
AllInputs       == TwoBuyersInputs \cup {In("GetSeat", "", 1)}

MCInit == AppInit(MCSeq)
MCNext ==
    \/ \E r \in Txns : \E input \in Inputs : Arrive(r, input)
    \/ \E r \in Txns : Step(r) \/ Respond(r)
    \/ DBSilent /\ UNCHANGED appVars
MCSpec == MCInit /\ [][MCNext]_vars
```

- **Seeded initial rows** come from the app's own seed data (shrunk), so the start state is reachable.
  An unreachable seed produces false positives.
- **`Inputs`**: concrete requests, built from the seeded accounts. Each actor arrives once with one of
  them. The number of actors is `Txns` in the cfg.
- **Faults** (retry after a lost response, crash between autocommit statements, duplicate delivery)
  get a counter each, checked and incremented on the same transition. Never bound handler steps or
  `DBSilent`.

## Configs

```
SPECIFICATION MCSpec
CONSTANTS
    Txns = {"r1", "r2"}
    Tables <- AppTables
    Keys <- MCKeys
    UniqueCols <- AppUniqueCols
    InitRows <- MCInitRows
    RowDomain <- AppRowDomain
    AutoIso = "RC"
    Absent = Absent
    NoTxn = NoTxn
    NoWrite = NoWrite
    Inputs <- TwoBuyersInputs
INVARIANTS
    NoOverbooking
CHECK_DEADLOCK FALSE
```

- **`MC.cfg`** — convergence: `Inputs <- AllInputs`, two or three actors, safety and structural
  invariants enabled, extension (scenario) invariants listed but commented out.
- **`MC_hunt_<scenario>.cfg`** — `Inputs` narrowed to the Scenario's requests; the Scenario's
  invariants enabled together with the other safety and structural invariants. Do not narrow a hunt
  cfg to the target invariant alone. If a known violation keeps stopping the run, rerun with `-C`
  (TLC `-continue`), or disable that one property, and note it.
- `CHECK_DEADLOCK FALSE`: every actor finishing is a terminal state, not a deadlock.
- **Liveness** properties from brief §5 get their own `MC_hunt_<scenario>_live.cfg` (see
  `liveness-pattern.md`).

## Sizing

Start with two actors and one or two rows per entity; add a third actor only when the Scenario needs
it (for example a retry overlapping two originals). Each extra actor multiplies the interleavings.
When BFS cannot finish, the validation workflow follows up with simulation: do not shrink the
Scenario's own requests to make BFS deeper.
