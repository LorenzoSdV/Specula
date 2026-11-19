# Spec Fidelity Checklist

Use this checklist before classifying a counterexample as Case C (real bug). The most common false-positive shape in formal verification is a counterexample whose preconditions look implausible in the real system — usually because the spec under-models a guard or suppression mechanism the implementation has.

## When to use

Run this checklist when, after reading the counterexample, you find yourself thinking *"this couldn't actually happen because…"*. That instinct is a flag: either the spec is missing a mechanism, or the bug is so subtle the implementation seems immune to it. The checklist helps you tell which.

## Procedure

### Step 1. Extract the preconditions

Read the counterexample (as request lanes, from the timeline tool) and write down the set of conditions the violating state requires. Be specific — "request r2 read the seat *after* r1's UPDATE started but *before* r1 committed" is a precondition; "the requests raced" is not.

### Step 2. For each precondition, ask "what stops this in the real system?"

For every precondition, search the implementation for any guard, gate, check, or reactive update that prevents that condition. Look for:

| Mechanism category | What it looks like in a web app |
|---|---|
| **Database constraints** | UNIQUE, CHECK, foreign keys, exclusion constraints, triggers (read the migrations, not just the ORM schema) |
| **Locks the code or ORM takes** | `SELECT ... FOR UPDATE`, `select_for_update()`, advisory locks, a conditional `UPDATE ... WHERE stock >= $1` whose row count is checked |
| **Isolation overrides** | `$transaction(..., { isolationLevel })`, `SET TRANSACTION`, framework settings such as Django `ATOMIC_REQUESTS` |
| **ORM-implicit transactions** | nested writes, `upsert`, `get_or_create`, `update_or_create`: what they really send |
| **Middleware** | authentication, rate limiting, idempotency middleware, request deduplication |
| **Infrastructure** | queue concurrency of 1, cron on a single replica, a Redis lock, provider-side idempotency keys |
| **Row-level security** | policies that filter what a statement sees or may change |

Not guards: anything that runs only in the browser (a disabled button, client validation, a
debounce). A direct API call bypasses them.

The implementation's choice to put a guard somewhere is itself information. If the developers wrote `if !x { return }` at the top of a function, they believed `x` could happen — and the spec should let it happen too, while modeling the guard.

### Step 3. Compare to the spec

For each guard you found in the implementation, check whether the spec models it:

- **Spec models the guard with the same precondition** → guard is faithful, move on. (A trace-validated model has already been checked against recordings, but only on the interleavings the traces contain.)
- **Spec models the guard with a weaker precondition** → spec lets behavior through that the impl blocks. This is **Case B**.
- **Spec doesn't model the guard at all** → spec explores states the impl can't reach. This is **Case B**.
- **Impl has no guard for this precondition** → the precondition really can occur. The counterexample is Case C-eligible. Continue verification.

### Step 4. Re-run with the spec fix

If you found Case B, fix the spec (add the guard, tighten the precondition, model the reactive update) and re-run TLC. If the violation persists, repeat from Step 1 — there may be a second under-modeled mechanism. If the violation disappears, the original counterexample was a fidelity gap, not a bug.

## What to write down

When you classify a counterexample as Case B via this procedure, record in `changelog.md`:

- The precondition that looked implausible
- The implementation guard you found, with `file:line`
- The spec change made to model it

This trail matters for two reasons. First, it documents that you didn't dismiss the counterexample arbitrarily. Second, if the same precondition shows up in a later counterexample, you'll know whether you're seeing the same gap or a new one.

## Heuristic: if you can name the bug class, double-check fidelity

Bug classes that have a known fidelity trap:

- **Lost update / oversell** — is the write really computed in the app (`SET v = $1`), or is it a relative update (`SET v = v - $1`) re-evaluated under the row lock? Is there a conditional `WHERE` whose row count the code checks?
- **Duplicate records** — is there a UNIQUE index the ORM schema does not show (added in a raw migration)?
- **Read-then-write races** — does the code lock the row (`FOR UPDATE`) or run at REPEATABLE READ / SERIALIZABLE for that transaction?
- **Duplicate webhook effects** — does the handler record the provider's event id under a unique constraint before acting?

A spec that models the action but not the *condition under which the action is allowed* will report violations that aren't in the real system.

## See also

- `tla-checking-workflow/guide.md` Step 3 — this checklist is the detailed version of "Cross-Reference with Implementation".
