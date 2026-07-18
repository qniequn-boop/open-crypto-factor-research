# Factory Source Admission and Scheduler v1

## Purpose

This stage makes the panel factor factory sustainable rather than merely fast.
The scheduler is allowed to do nothing when the research basis is not ready.
It never turns historical evaluation outcomes into permission for more search.

The operating rule is:

> Literature and data admit a source. The source admits exact formulas and a
> lifetime trial budget. The scheduler may then start one small frozen cycle.

## Boundaries

`PANEL_SOURCE_ADMISSION_REGISTRY_V1.json` is the machine-readable research-space
gate. Every hypothesis source must appear exactly once. An open source requires:

- an explicit `allowed_for_generation: true` decision;
- an exact `allowed_panel_formulas` whitelist;
- a positive `max_lifetime_variants` budget;
- human review to change any of those fields.

Backtest, Validation, Holdout, critic, or AI output cannot edit this registry.
The current registry honestly admits zero of nine sources. Closed canonical
work, audit-only methods, prospective-frozen work, deprecated work, and vague
unpreregistered mechanisms cannot silently spawn variants.

## One Invocation

1. Validate the scheduler policy, source registry, literature completeness, and
   immutable scheduler records.
2. Refuse to start when an earlier generation intent is incomplete or a factory
   job is active.
3. Enforce one generation cycle per UTC day and a 24-hour cooldown.
4. Select one admitted source with the lowest historical source-trial count.
5. Give the AI only that source's literature blocks and exact formula catalog.
6. Propose at most five candidates and accept at most three.
7. Count accepted, schema-rejected, guardrail-rejected, and unevaluated
   candidates against the source's lifetime budget. Renaming `family` cannot
   evade this count.
8. Freeze the batch and trial rows before creating one state-machine job.
9. Let the existing formula audit, independent critic, and one-shot evaluator
   produce a terminal job state.

The scheduler never loops inside one invocation and never automatically changes
source admission after seeing a result.

## Durable Evidence

- `logs/panel_factory_scheduler/runs`: immutable idle and blocked receipts.
- `logs/panel_factory_scheduler/intents`: immutable pre-generation claims.
- `logs/panel_factory_scheduler/results`: immutable terminal cycle records.
- `logs/panel_factory_scheduler/batches`: frozen candidate batches.
- `logs/panel_trial_registry.jsonl`: all candidate attempts, including rejects.
- `logs/panel_factory_jobs`: state-machine jobs and process lifecycle evidence.

A generation intent without a matching result blocks replacement generation and
requires review. Record hashes fail closed when edited.

## Current Operating State

The first local production invocation on 2026-07-16 returned
`idle_no_admitted_source`. It made no AI call and left the trial registry at 140
rows before and after. This is the expected healthy state until a new mechanism
has specific literature, available fields, a canonical formula, and a frozen
small budget.

The Linux timer runs once daily at 01:15 UTC with a randomized delay. While no
source is admitted, it only records a health receipt. Human approval remains
required for source admission, formal prospective activation, combo creation,
and any use of capital.

## Runtime Binding And Unattended Drill

Unattended evaluation is now bound by `PANEL_FACTORY_RUNTIME_V1.json` to one
exact content-addressed substrate, manifest hash, cutoff, asset count, and
failure count. The current Linux runtime has 50 of 50 assets, 730 days, zero
source failures, and cutoff `2026-07-15T23:00:00+00:00`. Job contracts inherit
the frozen substrate's `days` and `as_of`; wall-clock drift cannot silently
change the evaluation request.

The evaluator writes reports and trial events to job-local output sinks. Only
after report validation does the state machine atomically and idempotently
commit the exact evaluated rows into canonical trial history. Frozen job inputs
are never reused as mutable outputs.

The final Linux synthetic approved-source drill passed all 15 checks. It
included one schema rejection and an intentionally interrupted formula worker,
which was terminated as a process group and retried once. The real formula
audit, critic, and staged evaluator each completed under the frozen contract.
The synthetic candidate was economically rejected at Stage 2, Holdout was not
accessed, no combo was created, and the production 140-row trial registry was
unchanged. See `FACTORY_UNATTENDED_DRILL_RESULT_20260716.md`.

Local and Linux full regression suites both pass: `270 passed` with the same
nine pre-existing constant-series warnings.

## Architecture Basis

The design deliberately implements only the small subset needed here:

- Qlib Recorder's persistent experiment, recorder, status, metric, and artifact
  hierarchy: https://qlib.readthedocs.io/en/stable/component/recorder.html
- Qlib task persistence for controlled research execution:
  https://qlib.readthedocs.io/en/latest/advanced/task_management.html
- Airflow pool slots and per-workflow active-run limits as the model for the
  single active job and bounded daily cycle:
  https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html
- Airflow heartbeat, orphan, and active-run controls:
  https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html
- RD-Agent's experiment memory, idea pool, timer, and pause/resume engineering
  patterns: https://github.com/microsoft/RD-Agent/blob/main/CHANGELOG.md

These references guide process discipline. They do not provide economic factor
evidence and cannot admit a tradable hypothesis.
