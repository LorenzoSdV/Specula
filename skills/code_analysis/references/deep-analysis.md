# Common Deep Analysis Methodology

This file contains the **shared** workflow for deep analysis. The web-specific patterns, invariant
families and fault model are in `web-analysis.md`; read it first.

---

## 1. Common Cross-Cutting Patterns

### 1.1 Map Atomicity Boundaries

For each major operation, determine:

- what reads and writes happen as a single atomic unit?
- what can be interleaved by concurrent operations or crash?
- what ordering dependencies exist between steps?

This directly informs how to split (or not split) TLA+ actions. In a web app the boundary is each
SQL statement or other awaited I/O (cache, queue, external API): other requests run between any two
of them, inside a transaction or not. The isolation level decides only what each statement sees and
when it waits or fails. In-process state with no I/O between two `await`s is the rare exception.

### 1.2 Code Path Inconsistency

**What**: Multiple code paths that handle the same concept but differ in important ways.

**How to find**:
1. Identify all places that handle the same logical operation
2. For each, list what checks and state updates are performed
3. Find paths that are missing checks or updates present in others

Typical web forms: the REST handler checks ownership but the GraphQL mutation does not; checkout
locks the row but the admin edit does not; the webhook handler and the redirect handler both mark an
order paid, with different guards.

### 1.3 Developer Signals

**What**: Explicit acknowledgments of known issues in the code.

```bash
grep -rn "TODO\|FIXME\|HACK\|XXX\|BUG\|WARN" <core_files>
```

These are high-value signals:

- a TODO about a known issue confirms the area is problematic
- a FIXME suggests the developer intended to fix something but didn't
- a HACK suggests a workaround that may have side effects

### 1.4 Error Handling Gaps

**What**: Code paths where errors are logged but not handled, or where partial operations leave state inconsistent.

**How to find**:
1. Search for error handling: `if err != nil`
2. Check what happens after the error: is state rolled back? Is the operation retried? Or just logged?
3. Look for partial operations: Step 1 succeeds, Step 2 fails — is Step 1 rolled back?

---

## 2. Verification Checklist

For **every** finding from Phase 3, verify before including it in the report.

### 2.1 Re-Read

Don't rely on memory. Re-read the exact lines. Context matters — the surrounding code may contain compensating logic.

### 2.2 Compensating Mechanisms

Check if there's another check elsewhere that handles this case:

- is there a timeout that eventually triggers the right behavior?
- is there a periodic check that catches inconsistencies?
- is there a recovery path that fixes the state?

### 2.3 Full Execution Path

Trace the control flow from entry point to the suspicious code:

- what conditions must be true for this code to execute?
- can those conditions actually occur?
- what happens after this code — does subsequent logic fix the issue?

### 2.4 Design Intent

Check if it's intentional:

- read code comments around the suspicious area
- search for related PRs/issues discussing this behavior
- check if similar code in other implementations does the same thing

### 2.5 Real-World Impact

Assess whether the issue can be triggered in practice:

- does it require a specific sequence of events?
- does it require failures, races, or unusual timing?
- has anyone reported this issue in production?

---

## 3. Analysis Method

### 3.1 File-by-File Reading

For each core file, read it **in full** using the `Read` tool. Do not skim.

The core files are the handlers, services, models and middleware on the paths in the write matrix (`web-analysis.md`), plus the schema and migrations.

### 3.2 Parallelization

Use multiple Task subagents for coherent components, mechanisms, or source files when available. Include the adjacent code needed to establish each assignment's interfaces and effects. For example:

```text
Subagent A: Analyze core file 1
Subagent B: Analyze core file 2
Subagent C: Analyze core file 3
```

Each subagent should:
1. Read the file completely
2. Apply all analysis patterns
3. Return findings with file:line references

### 3.3 Cross-Referencing

After parallel analysis, cross-reference findings:

- do findings from different files relate to the same mechanism?
- do they form a Scenario?
- do they confirm or contradict each other?
