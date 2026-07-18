# Contributing

Open Crypto Factor Research welcomes careful replications, negative results,
data audits, tests, and mechanism-based hypotheses. Contributions are judged by
the clarity of their evidence, not by whether they produce a positive return.

## Before Proposing a Factor

A proposal must state:

1. **Source:** a paper, primary source, or clearly identified market mechanism.
2. **Hypothesis:** a falsifiable statement, not a desired return target.
3. **Mechanism:** why the information could be related to expected returns.
4. **Data:** required fields, timing, availability, missingness, and universe.
5. **Formula family:** the bounded set of allowed constructions and parameters.
6. **Direction:** the expected sign before results are observed.
7. **Portfolio policy:** neutralization, buckets, weighting, rebalance, and
   holding horizon.
8. **Baselines:** simple and economically relevant alternatives the proposal
   must outperform or distinguish itself from.
9. **Costs:** fees, slippage, funding, borrow, impact, and capacity assumptions.
10. **Failure conditions:** evidence that would reject, freeze, or narrow the
    claim.
11. **Trial budget:** the maximum number of paths allowed for the mechanism.

A candidate without a registered source and failure conditions is not eligible
for automated search.

## Preregistration Rules

- Freeze formulas and batch membership before evaluation.
- Do not revise a candidate under the same ID after seeing its result.
- Count generated, manual, failed, duplicate, and syntax-invalid attempts.
- Do not use Holdout details in candidate prompts, rankings, or revision notes.
- Do not invert a failed sign, rename a failed path, or change a horizon on the
  same sample without a new admissible hypothesis and counted trial.
- Do not promote a historical result directly into a combination or strategy.

## Evidence Language

Use the narrowest accurate statement:

- `historical reject` for a failed frozen path;
- `historical clue` for evidence that justifies more observation;
- `prospective eligible` only when the factor and future policy were frozen
  before activation;
- `factor promotion` only after all frozen prospective requirements pass;
- `paper-trading eligible` and `deployment eligible` only after their separate
  downstream audits.

Avoid claims such as "proven alpha," "profitable strategy," or "production
ready" when the evidence establishes only code behavior or historical
association.

## Code Contributions

1. Keep changes focused on one research or software claim.
2. Add tests proportional to the behavioral risk.
3. Preserve sparse funding events and missing basis, returns, and pre-listing
   history rather than filling them silently.
4. Maintain point-in-time boundaries and purge forward targets across sample
   splits.
5. Update `CURRENT_BASELINE.json` only when the intended collected test count
   changes, and explain the change.
6. Install and test from `requirements.txt` using `--require-hashes`.
7. Do not commit credentials, market-data caches, ordinary runtime logs, or
   private server configuration.

## Historical Artifacts

Dated reports, frozen batches, hashes, candidate IDs, and trial records are
provenance. Do not rewrite them to make the current narrative cleaner. Add a
new correction or superseding record and preserve the old result.

Legacy `BTCLab` and `factory` paths may remain where renaming would break a
cited artifact or operational contract.

## Pull Request Checklist

- [ ] The research or software claim is stated explicitly.
- [ ] Source, mechanism, data timing, and failure conditions are documented.
- [ ] Candidate and parameter budgets were fixed before evaluation.
- [ ] Holdout isolation and point-in-time boundaries remain intact.
- [ ] Costs and relevant baselines are reported.
- [ ] Negative and invalid results remain counted.
- [ ] Tests pass in a clean Python 3.11 environment with the locked dependencies.
- [ ] No secret, cache, or private operational record is included.
- [ ] The conclusion does not exceed the evidence stage.

## Research Conduct

Disagreement is welcome when it is specific, reproducible, and respectful.
The preferred contribution is not the most optimistic interpretation. It is
the interpretation that another researcher can inspect and try to falsify.
