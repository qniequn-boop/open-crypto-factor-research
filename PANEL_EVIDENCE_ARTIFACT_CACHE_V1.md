# Content-Addressed Panel Evidence Artifact Cache v1

## Purpose

`panel_artifact_cache.py` persists expensive pre-multiplicity path evidence
across processes. It removes repeated baseline and factor-path work without
reusing statistical decisions.

## Cached Boundary

For a fixed panel fingerprint, formula code fingerprint, factor, weighting
mode, split contract, costs, and evaluation parameters, the cache may store:

- RankIC summaries and coverage;
- split economics and IS/Validation selection returns;
- rolling 90-day diagnostics;
- large/liquid, bucket, crash, and related robustness evidence.

The cache never stores or reuses:

- effective trial count;
- DSR, CSCV-PBO, or family FDR decisions;
- pass, watchlist, reject, or gate classifications;
- any permission to access Holdout or enter a combo.

Multiplicity and every classification are recomputed from the frozen trial
registry on each run.

## Storage And Integrity

The store uses immutable Parquet blobs addressed by SHA256, self-hashing JSON
manifests, and replaceable aliases. A load verifies path confinement, manifest
identity, alias identity, and every blob hash. DataFrame and Series index,
dtype, name, and DatetimeIndex frequency metadata survive round-trip.

Duplicate writes reuse an existing content object. Any blob, manifest, alias,
or path mutation fails closed.

## Measured Acceptance

On the same eight-asset, 730-day frozen substrate and candidate batch:

- cold legacy run: 109.875 seconds, 0 hits and 16 misses;
- warm legacy run: 37.908 seconds, 16 hits and 0 misses;
- warm staged run: 37.409 seconds;
- warm legacy was 65.5% faster than cold;
- warm staged was about 63% faster than the prior 101.9-second staged run.

Status, checks, IC, split metrics, rolling evidence, robustness, DSR/PBO,
baseline comparisons, and gate v2/v3 outputs matched. Trial count remained
100 and was recomputed rather than read from cache.

## Non-Claims

- A cache hit is not evidence of alpha.
- The cache does not permit formula changes under an old key.
- A code-fingerprint change intentionally invalidates aliases.
- Storage retention and garbage collection remain operational follow-up work.

