# Instrumentation Spec Format

The instrumentation spec says how each model action is recognized in a recording of the real app.
The tracing stack captures everything at the app's boundaries (HTTP, SQL, committed rows), so this is
an identification table, not a list of code patches. The harness phase turns it into the mapping file
(`harness/mapping.toml`) that the trace builder reads.

## Document Structure

### Section 1: Modeled tables

For each table: its key column and the modeled columns with their types (`int`, `text`, `bool`).
These must match the row records in the model.

### Section 2: Routes

One entry per route in scope:

| Action | Method and path | Inputs | Response fields |
|---|---|---|---|
| `Book` | `POST /seats/:seatId/book` | path `seatId` (int); header `authorization` (bearer) | `id` (int) |

The trace has `<Action>_Begin` and `<Action>_End` events for it.

### Section 3: Statements

One entry per step that is a SQL statement, in handler order:

| Action | Kind | Table | Statement shape | Code | Notes |
|---|---|---|---|---|---|
| `Book_ReadSeat` | select | Seat | `SELECT ... FROM "Seat" WHERE "id" = $1` | `routes/book.ts:L41` | `LIMIT 1` |
| `Book_Hold` | write | Seat | `UPDATE "Seat" SET "held" = "held" + $1 WHERE ...` | `routes/book.ts:L47` | relative update |
| `Book_Insert` | insert | Booking | `INSERT INTO "Booking" ...` | `routes/book.ts:L49` | unique `(seatId)` |

- **Kind**: `select`, `write` (UPDATE, DELETE, SELECT ... FOR UPDATE: these can wait on locks),
  `insert`, `begin`, `commit`, `rollback`. Steps of kind `write` and `insert` appear in traces as
  `<Action>_start` and `<Action>_finish`.
- **Statement shape**: the SQL text the app really sends (record one request of each kind through
  the stack and read `pgproxy.ndjson`), enough to write a regular expression that matches only this
  statement. When two routes send the same statement shape, say which route each step belongs to.
- Note `LIMIT 1` (the result is any one matching row) and results without the key column (only the
  row count can be checked).

### Section 4: Special considerations

In-process state that never reaches the database (an in-memory cache, an in-process lock) is the
only thing boundary tracing cannot see. List it here, with the smallest code `emit()` that would
record it, or explain why the model abstracts it away.
