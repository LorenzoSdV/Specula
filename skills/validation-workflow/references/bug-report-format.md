# Bug Report Format

Template for `spec/bug-report.md`, produced after spec convergence during bug hunting.

For each bug, include the counterexample as request lanes (from `<toolkit>/timeline/timeline.py`): each request's route, its statements in order, what each read, where it waited, and what each COMMIT changed.

## Template

```markdown
# Bug Report — <System Name>

## Summary

- Scenarios tested: N
- Bugs found: N
- Configs run: MC_hunt_<scenario>.cfg, ...

## Bug N: <Title>

- **Scenario**: <scenario name/number>
- **Severity**: Critical / High / Medium
- **Invariant violated**: <name> (for a liveness config, the cfg's `PROPERTY`)
- **Config**: <cfg file>
- **Counterexample**: <N states, output file in spec/output/>

### Trace Summary

<Step-by-step description of the counterexample: which request issues which statement, what it reads, where it waits, what commits — the timeline's request lanes>

### Root Cause

<Why this happens in the implementation, with code references (file:line)>

### Affected Code

- `file:line`: <brief description>

### Recommendation

<Suggested fix>

---

## Not Reproduced

| Scenario | Config | States Explored | Result |
|------------|--------|-----------------|--------|
| ... | ... | ... | No violation / Not testable (reason) |
```

## Guidelines

- **Every bug**: trace summary + root cause + affected code. Without these it's just a TLC output, not a bug report.
- **Not reproduced**: always include. "Not testable" with a reason is valid (e.g., spec doesn't model that mechanism).
- **No bugs found**: still write the report with Summary showing 0 bugs and the full Not Reproduced table.
- **Spec fixes during hunting**: if the spec was adjusted during bug hunting (Case A/B), document them briefly at the end.
