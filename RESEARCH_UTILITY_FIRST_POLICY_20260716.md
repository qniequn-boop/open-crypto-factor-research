# Research Utility-First Policy - 2026-07-16

2026-07-17 amendment: the named Track A R0 blockers are closed. Track B
economic discovery is now the primary workstream under
`ECONOMIC_RESEARCH_AGENDA_20260717.md`. Track C is maintenance-only unless an
issue blocks valid economic evidence or prospective collection.

## Objective

The factory exists to discover economically useful factors and eventually
produce positive net trading utility. Engineering correctness is a means of
making that evidence believable and executable; zero defects are not the
product.

The priority order is:

1. believable positive net economic evidence;
2. protection against false alpha and unsafe capital decisions;
3. reliable, reproducible research throughput;
4. unattended automation and operational convenience.

Historical evidence grants research permission, not capital permission.

## Risk Classes

### R0 - Stop The Research Decision

An R0 defect can reverse a research conclusion or make a losing strategy look
profitable. It must be removed or explicitly bypassed before a result is used:

- future or Holdout information entering IS/Validation targets, selection, or
  AI feedback;
- trials being omitted from multiplicity accounting;
- stale evidence being reused under a different universe or candidate;
- costs, funding, held returns, or missing observations being economically
  misaccounted;
- a tested formula differing from the frozen formula being classified.

An implementation fix is not always required before a pilot. A narrow,
observable bypass is acceptable, such as disabling the cache until its key is
complete. The bypass must be frozen in the run contract.

### R1 - Guarded Research Is Allowed

An R1 defect weakens provenance or job reliability but does not directly alter
the economics when a human supervises one bounded run. Examples include
cryptographic critic authorization, process-group cleanup, stale-lock recovery,
complete dependency attestation, and concurrent report isolation.

R1 defects block unattended automation. They do not block a supervised pilot
when the run uses one worker, unique output paths, an allowlisted formula, the
canonical registry, and preserved inputs and outputs.

### R2 - Nonblocking Engineering Debt

Schedulers, dashboards, notification acknowledgement, cache garbage
collection, ergonomic reporting, and throughput optimization are valuable but
do not block supervised research or prospective shadow observation.

## Evidence Ladder

1. **Positive control:** prove that a planted causal effect can pass and null
   controls fail. This validates the evaluator, not alpha.
2. **Historical clue:** a preregistered mechanism is positive on Validation
   after costs and beats its baselines. This authorizes prospective observation,
   not trading.
3. **Frozen historical candidate:** the clue survives rolling, liquidity,
   crash, multiplicity, and audit-only Holdout checks without formula changes.
4. **Prospective shadow:** future signals are recorded with no orders and no
   retuning. Early degradation is useful evidence, not a failed project.
5. **Paper strategy:** only a combination of prospectively supported factors is
   translated into executable orders, fills, costs, and risk limits.
6. **Tiny live allocation:** only after paper economics and operations pass.

The factory should seek the earliest rung honestly available. It must not
pretend that a lower rung is a higher one.

## Current Balanced Work Order

### Track A - Credibility Blockers

Before the next candidate batch:

1. purge forward returns at the Validation/Holdout boundary;
2. remove every Holdout-dependent AI-feedback ordering and selection path;
3. make canonical trial accounting fail closed;
4. disable the evidence cache for the pilot unless universe identity is fixed;
5. verify the selected formula family with an allowlist and direct causal code
   review.

### Track B - Economic Discovery

The first bounded cycle is complete:

1. perpetual basis/funding was reframed as the literature-supported two-leg
   mechanism;
2. 12 preregistered paths across a primary and one cost-mitigation batch were
   evaluated;
3. all 12 were net historical rejects because two-leg costs dominated gross
   convergence and funding receipts;
4. Holdout remained sealed and the family is now frozen;
5. the next bounded cycle must use an independent mechanism or materially new
   data, with a `historical_clue` still routed directly to prospective shadow.

### Track C - Factory Hardening

In parallel, but not on the critical path of the supervised pilot:

- trusted critic authorization;
- process ownership and stale-lock recovery;
- complete code and registry provenance;
- per-job output isolation;
- scheduling, alerting, quotas, and cache lifecycle.

Track C becomes binding before unattended daily candidate generation.

## Operating Metrics

Do not use a single completion percentage as the main objective. Report these
separately each cycle:

- time from frozen hypothesis to classified result;
- valid candidates evaluated per bounded batch;
- fraction rejected for software-invalid evidence;
- fraction positive on Validation after costs;
- fraction beating preregistered baselines;
- number and age of prospective shadow tracks;
- prospective net effect and degradation versus historical expectation;
- job success rate and manual interventions;
- open R0, R1, and R2 defects.

## Research Budget

- One family receives a fixed candidate budget before results are seen.
- A failed family is paused rather than expanded into unlimited variants.
- Holdout is consumed once for audit and never used to choose the next formula.
- Prospective shadow capacity is intentionally cheap: several honest clues may
  be observed concurrently without pretending they are approved strategies.
- Capital risk remains zero until prospective and paper evidence exist.

## Literature Basis

- Arnott, Harvey, and Markowitz, *A Backtesting Protocol in the Era of Machine
  Learning*: application choice and data limitations precede model complexity.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3275654
- Wiecki et al., *All that Glitters Is Not Gold*: in 888 algorithms, common
  backtest metrics weakly predicted out-of-sample performance and more
  backtesting was associated with a larger in/out-of-sample gap.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2745220
- Bailey and Lopez de Prado, *The Deflated Sharpe Ratio*: trial count and
  non-normal returns must enter performance claims.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Novy-Marx and Velikov, *A Taxonomy of Anomalies and Their Trading Costs*:
  turnover and cost mitigation materially determine whether an anomaly has net
  economic value.
  https://doi.org/10.1093/rfs/hhv063
- Google SRE, *Embracing Risk*: 100% reliability is usually the wrong target;
  explicit error budgets balance reliability with useful delivery.
  https://sre.google/sre-book/embracing-risk/

## Decision

The red-team findings and 48/100 audit score remain valid descriptions of the
current implementation. They are not a requirement to reach 100/100 before
research resumes. The next supervised pilot is authorized after Track A closes;
R1 and R2 work continues alongside economic discovery.
