# Liveness Pattern

How to check a Liveness property from modeling brief §5. Safety invariants remain the main target. Each liveness property gets its own hunt cfg, and all liveness cfgs together should take no more than about 30% of the bug-hunting time (see `validation-workflow/guide.md`).

## Choose a checkable property

Check a property whose progress follows from the system's own mechanisms eventually running: an expiry job releasing unpaid holds, a queue worker processing a delivered job, a provider retrying a webhook as its documentation says, a request's handler running to its response. Typical shapes:

```tla
HoldsExpire     == \A k \in Keys : HeldUnpaid(k) ~> (Paid(k) \/ Released(k))
RequestAnswered == \A r \in Txns : pc[r] # "idle" ~> pc[r] = "done"
```

Never assume user behavior (a user eventually pays, eventually retries). Do not check properties that only hold with favorable timing, such as "eventually the retry succeeds" when every attempt can hit the same conflict. The model allows those behaviors, so the property fails without telling you anything about the implementation.

## Add fairness: `LiveSpec`

Without fairness, liveness properties fail by stuttering. Decide the fairness when you write `LiveSpec`, before any liveness run, from what the implementation's scheduling guarantees.

The default is weak fairness per actor on all of its non-fault steps: a request that has started keeps running its handler (the server and the database keep scheduling it), and the database's own silent steps (lock grants, deadlock detection) eventually happen. Cite the code or configuration for any job or retry mechanism you add fairness to (the cron schedule, the queue's worker, the provider's documented retry policy).

```tla
\* every started request runs its handler; the database grants locks and detects deadlocks
Fairness == /\ \A r \in Txns : WF_vars(Step(r) \/ Respond(r))
            /\ WF_vars(DBSilent /\ UNCHANGED appVars)
\* jobs/expire.ts:L12, cron "*/5 * * * *": the expiry job runs while holds are pending
            /\ WF_vars(ExpireJob)

LiveSpec == MCSpec /\ Fairness
```

- Quantify over actors. `WF_vars(\E r \in Txns : Step(r))` only guarantees that some request takes a step; `\A r \in Txns : WF_vars(Step(r))` guarantees it for each request.
- Fairness on a single action, and any `SF`, are stronger claims. Use them only when the code guarantees that specific action (for example, a dedicated timer that always fires, or a lock that hands off in FIFO order so a waiter is not starved), cite it, and keep them few.
- Never put fairness on fault actions.
- Fairness is a claim about the implementation that trace validation cannot check. Never add or strengthen fairness to make a property hold. After a liveness counterexample, change fairness only with a code citation showing that the implementation guarantees the action runs, and log the change as `[fix-fairness]` in `changelog.md`.

## Bounds: faults stop, progress does not

- Keep the counters on fault actions (crash, lost response, duplicate delivery). Once they run out, faults stop, and the property asks whether the system makes progress after that.
- Bound the workload (actors, `Inputs`) as usual.
- Do not let actions the property depends on run out. If progress needs a timer, retry, or heartbeat that the MC spec bounds, remove its bound in the liveness model when the state space stays finite without it. Otherwise make the property conditional, for example `Pending(r) ~> (Done(r) \/ retries = MaxRetry)`, and note in the bug report that behaviors which use up the bound are not checked.
- Make the liveness model much smaller than the safety model. TLC explores far fewer states per minute when it checks a liveness property, and BFS has to finish within the run's time budget. Use the fewest actors and rows the mechanism needs; this is often one actor fewer than in the safety cfgs. Shrink constants unrelated to the property first.

## The `_live` cfg

Name it `MC_hunt_<scenario>_live.cfg`, after the Scenario the property targets.

```
SPECIFICATION LiveSpec
CONSTANTS
    Txns = {"r1", "r2"}
    MaxRetryLimit = 1
    ...
PROPERTY HoldsExpire
```

- One `PROPERTY` per cfg. TLC does not report which temporal property failed.
- No `SYMMETRY`, `VIEW`, or `CONSTRAINT`. Each one can hide liveness violations or report ones that do not exist (see `tla-checking-workflow/references/tlc-gotchas.md`).
- Operator overrides (`<-`) work as in the other cfgs. Other invariants are optional; the safety cfgs already check them.

Run `_live` cfgs with BFS and with deadlock checking off; `tla-checking-workflow/guide.md` covers running them and reading their counterexamples.

## Check the result

- **Violation**: classify it with the "Liveness Counterexamples" section of `tla-checking-workflow/guide.md`. Before calling it Case C, raise by one the bound closest to where the behavior gets stuck (rounds, retries, workload) and rerun. A real progress failure stays; one caused by the bound disappears or moves to the new bound.
- **No violation**: this counts only if BFS finished and the property's premise is reachable. To check the premise, define an invariant saying it never holds and run the same cfg with that `INVARIANT` instead of the `PROPERTY`; TLC must report the invariant violated. If the premise is never true, the property holds vacuously and the run says nothing.

## Example

A hold that an unpaid checkout places on a seat must eventually be released by the expiry job
(`HoldsExpire`). `LiveSpec` gives every request weak fairness and the expiry job weak fairness, citing
its cron schedule. A violation in which the job runs but skips holds whose request is still between
two statements, so the hold stays forever once that request crashes, is Case C when the crash is in
the brief's fault model and raising the crash bound keeps the violation. Without crashes, BFS
finishes without a violation and the premise check (`NoHeldUnpaid` violated) shows the pass is not
vacuous.
