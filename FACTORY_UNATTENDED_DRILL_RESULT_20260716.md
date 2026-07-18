# Factory Unattended Drill Result - 2026-07-16

## Conclusion

The sustainable factory's synthetic approved-source path completed unattended
on Linux. This is an engineering pass, not alpha evidence. The evaluated
synthetic momentum candidate was rejected at Stage 2, Holdout was not accessed,
and no combo was created.

The signed machine-readable result is:

- `logs/panel_factory_unattended_drill_20260716_summary.json`
- summary SHA256:
  `01567c8ede496641264a1f6fa3f372b829e48f5e7689464ec898ca2b3be50bf1`

## What The Drill Exercised

1. A synthetic source was admitted inside an isolated drill registry; no real
   economic source was opened.
2. Two proposals were submitted. One valid candidate was frozen and one
   unknown-source candidate was recorded as a schema rejection.
3. The first formula-audit worker was intentionally interrupted. Its child
   process group was terminated and the stage retried exactly once.
4. The real differential formula audit and independent critic ran against the
   frozen candidate and immutable panel substrate.
5. The real staged evaluator ran once. Its job-local trial event was validated
   and committed to the isolated canonical registry only after the evaluation
   report passed artifact checks.
6. The job reached `completed` with no active-process marker and no combo.

All 15 drill checks passed. The isolated registry contains exactly one
`generated`, one `schema_rejected`, and one `evaluated` event. The production
140-row trial registry had the same SHA256 before and after the drill:
`c6428bc9900ebe7d6dddf8fce16bc0a96438afcaca1389ae47537ebbc1c59658`.

## Fail-Closed Finding Before The Pass

The first drill attempt correctly stopped in `manual_review`. The server's
previous runtime binding exposed only a stale two-asset substrate and its
cutoff did not match the evaluator's requested cutoff. The system reported
`frozen_panel_substrate_request_mismatch` instead of silently evaluating a
different dataset.

That failure led to four production hardening changes:

- `panel_substrate_materialize.py` now creates an offline, content-addressed
  substrate from already cached source files and verifies a round trip.
- `PANEL_FACTORY_RUNTIME_V1.json` binds unattended work to one exact substrate,
  manifest hash, cutoff, asset count, and failure count.
- Job contracts inherit the frozen substrate's `days` and explicit `as_of`, so
  evaluator requests cannot drift with wall-clock time.
- Evaluation writes job-local reports and trial events. Canonical trial history
  is updated by an atomic, idempotent two-stage commit only after report
  validation.

The deployed runtime substrate contains 50 of 50 assets, 730 days, zero source
failures, and cutoff `2026-07-15T23:00:00+00:00`. Its substrate ID is
`46e45efdf2579cd3817210dbb06dc5613aed9811aeb9146f7fc0b4e8c6a53d53`.

## Runtime And Verification

The final drill started at 16:24:37 UTC and finished at 16:32:29 UTC. The real
formula audit completed in about 66 seconds, including one injected failed
attempt. Evaluation took about 6 minutes 38 seconds. Total wall time was about
7 minutes 52 seconds.

Formula audit now builds only the requested candidate and its exact underlying
formula while retaining all core input, cutoff, future-perturbation, and planted
leak checks. This removed unrelated formula work without weakening the causal
audit contract.

Local and Linux full regression suites both pass: `270 passed`, with the same
nine pre-existing constant-series warnings.

## Meaning And Next Boundary

The factory can now idle safely, start one bounded cycle, reject malformed
proposals, recover from a killed worker, run the real audit stack once, and
commit evidence without corrupting production history. It has not yet proved
that an admitted economic mechanism can produce useful factors repeatedly.

The next construction boundary is operational observability and governance:
notification routing, daily health and throughput summaries, and append-only
human approval evidence for source-admission changes. After that, one genuinely
independent literature mechanism may be admitted under a small frozen budget.
