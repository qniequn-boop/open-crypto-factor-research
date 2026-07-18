# Independent Panel Research Critic v1

## Purpose

`panel_research_critic.py` is a deterministic veto role between formula
compilation and historical evaluation. It follows the separation of research,
development, execution, and critic responsibilities used by R&D-Agent, while
keeping market outcomes unavailable to the critic.

## Admission Checks

For every frozen candidate and the batch as a whole, the critic checks:

- schema, candidate id, exact signature, and approximate signature uniqueness;
- historical candidate and family-variant budgets;
- formula direction and deprecation policy;
- formal literature-replication authorization;
- engineering-only sources are not used as alpha evidence;
- formula-audit schema, batch binding, leakage status, and Holdout absence;
- every required candidate formula is exactly `causal_pass`.

The critic reads neither performance outcomes nor Holdout metrics and cannot
promote a factor.

## Evaluator Enforcement

`panel_critic_contract.py` binds an approval to:

- the exact candidate-batch SHA256;
- the exact differential formula-audit SHA256;
- the same batch id and complete candidate-id set;
- complete passing batch and candidate checks;
- a formula report whose required results are all `causal_pass`.

`panel_factor_research.py --candidate-batch` now requires
`--critic-report`. It validates approval before creating a run contract and
again immediately before evaluation. Candidate batches cannot use the old
direct evaluator path. The AI generator's legacy smoke option is routed
through the factory orchestrator.

## Real Rejection Evidence

The prior OI batch `20260713T150601Z` is correctly rejected because:

- its OI source has no formal factor-authorizing replication entry;
- its required formulas are unobservable on the frozen eight-asset panel under
  the 20-asset breadth contract;
- its candidate ids/signatures are already present in historical trial
  evidence.

This is a valid stop decision, not a reason to loosen the critic.

## Non-Claims

- v1 is deterministic policy code, not a second LLM opinion.
- Approximate signatures do not yet prove algebraic equivalence.
- Critic approval only permits historical evaluation.
- Economic pass, prospective activation, combo creation, and capital remain
  separate gates.

