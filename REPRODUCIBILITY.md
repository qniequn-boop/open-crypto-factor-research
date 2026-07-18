# Reproducibility

## Reproducibility Target

Every public commit should make its software baseline independently testable
and its empirical claim boundaries explicit. Code reproducibility and data
reproducibility are reported separately because the repository intentionally
does not distribute market-data caches.

## Supported Environment

- Python 3.11
- Dependency ranges in `requirements.in`
- Exact direct and transitive versions with hashes in `requirements.txt`
- Ubuntu GitHub-hosted runner for the independent CI baseline

The exact machine-readable expectation is stored in
[`CURRENT_BASELINE.json`](./CURRENT_BASELINE.json). The latest successful
`main` workflow is the source of truth for the current commit.

## Clean Validation

```bash
git clone https://github.com/qniequn-boop/open-crypto-factor-research.git
cd open-crypto-factor-research
python -m venv .venv
python -m pip install --require-hashes -r requirements.txt
python -m pytest -q --junitxml=test-results.xml
python .github/scripts/ci_test_summary.py test-results.xml CURRENT_BASELINE.json
```

The final command verifies the collected, passed, failed, errored, and skipped
counts against the declared baseline. A lower collected count fails the build
even if every collected test passed.

## Data-Free Research Logic Demo

```bash
python examples/run_synthetic_evidence_demo.py
python examples/run_synthetic_evidence_demo.py --json
```

This deterministic example needs no external market data. It exercises the
production point-in-time leakage audit, family multiple-testing adjustment,
and historical discovery classifier. It proves that these declared software
boundaries execute; it does not reproduce an empirical factor return.

## Continuous Integration

The workflow in [`.github/workflows/ci.yml`](./.github/workflows/ci.yml):

1. uses exact commit pins for official GitHub Actions;
2. creates a fresh Python 3.11 environment;
3. installs only the hash-locked dependency graph;
4. runs the full test suite and emits JUnit results;
5. compares those results with `CURRENT_BASELINE.json`.

Dependabot may propose dependency and workflow updates weekly. Updates are not
merged automatically and must pass the full baseline.

## Test Count Semantics

The current baseline is 296 collected tests with zero expected skips. Counts
such as 274, 278, 284, 286, and 288 in dated research reports document earlier
development states. They remain visible for provenance but do not describe the
current commit.

## Data Boundary

Not committed:

- exchange credentials or private API material;
- cloud credentials, IP addresses, or server configuration values;
- bulk market-data caches and downloaded L2 archives;
- ordinary runtime logs and unpublished operational records.

Some integration and empirical workflows therefore require public market data
to be acquired separately. A software test pass proves the declared code
behavior under its fixtures; it does not prove that an external data source is
complete, immutable, or still available.

## Empirical Artifact Integrity

Research batches and reports use identifiers, timestamps, SHA-256 hashes,
input fingerprints, and frozen policy references where the stage requires
them. Content-addressed panel artifacts can bypass live source loading and fail
closed when their identity does not match the declared run.

Dated audit records should not be edited to match a later narrative. A
correction should be a new record that identifies the superseded artifact and
explains why it changed.

## Known Reproduction Limits

- The current-live OKX instruments endpoint is not a complete archive of
  historical delistings.
- Public exchange endpoints and archive formats may change after a research
  artifact is frozen.
- Current contract metadata cannot automatically reconstruct every historical
  contract specification.
- Visible order-book reconstruction does not reproduce hidden liquidity,
  latency, rejection, or queue position.
- A researcher who obtains a different data snapshot may reproduce the method
  without reproducing the exact empirical number.

## Reporting a Reproduction

Please report:

- commit SHA;
- operating system and Python version;
- dependency installation method;
- exact command;
- collected, passed, failed, errored, and skipped counts;
- whether external data was used and its acquisition timestamp;
- input artifact hashes where available;
- the smallest reproducible discrepancy.

Successful and unsuccessful reproductions are both useful when their data and
environment boundaries are explicit.
