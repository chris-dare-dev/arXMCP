
## paper-metadata (2026-07-05)
- Two-epic cut for stub-filling work: (1) data-plane slice (source -> store -> backfill CLI, observable without server changes) then (2) surface slice (handler wiring). Keeps e1 INVEST-independent because the CLI makes it demoable alone.
- With only 2 non-wont epics the 60% must-cap forces exactly one must — decide the payoff-vs-enabler question early (store slice won: nothing downstream works without it).
- Tag both slices value (not enabler) when each has an observable output; a backfilled store visible via CLI counts as observable.
