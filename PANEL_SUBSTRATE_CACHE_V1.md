# Content-Addressed Panel Substrate Cache v1

## Purpose

Freeze the resolved panel input before factor construction. A formal audit can
now load an explicitly named immutable substrate without calling OKX, Coin
Metrics, or any panel source loader.

This layer preserves data evidence. It is not a factor or baseline cache.

## Request Contract

The automatic request key binds:

- ordered instrument ids, history days, bar size, and explicit cutoff or UTC
  dynamic-day bucket;
- requested spot, open-interest, market-cap, perpetual OHLCV, and sparse real
  funding fields;
- missingness and no-padding policy;
- universe-registry hash;
- loader and substrate-serialization code hashes.

Automatic aliases are valid only while every registered raw source-cache hash
is unchanged. Re-encoding a raw Parquet file without changing the resolved
panel invalidates the alias but reuses the same resolved content object.

## Storage Layout

`data_cache/panel_substrates/v1/` contains:

- `blobs/<prefix>/<sha256>.parquet`: immutable per-asset, per-field blobs;
- `objects/<substrate_id>/manifest.json`: self-hashing immutable object;
- `aliases/<request_key>.json`: replaceable lookup pointer, not evidence.

The substrate id is derived from the resolved panel fingerprint, request
contract, asset metadata, field blobs, and recorded failures. Source filenames
and machine-specific paths do not define content identity.

## Loading Modes

### Automatic

Default behavior validates the source-cache inventory. A matching alias loads
the immutable object; a miss invokes the existing loaders and materializes a
new object.

### Required Cache

`--require-cached-substrate` fails closed on an alias miss and never falls back
to source loaders.

### Explicit Frozen Manifest

`--substrate-manifest <manifest.json>` loads exactly that object, ignores
mutable source caches, verifies every blob hash, and never invokes the panel
loader. Formal frozen status also requires an explicit `--as-of` cutoff.

Loader-code changes are allowed when reading an explicit historical substrate,
but symbols, days, bar, cutoff, field contract, missingness policy, and universe
registry must remain compatible.

## Missingness Guarantees

- Funding remains sparse realized-payment events and is never forward filled.
- Missing spot data remains missing; basis is not padded.
- Missing OI and market cap remain missing.
- Asset-specific indexes, dtypes, Series names, error metadata, listing
  metadata, non-finite scalars, and asset labels survive round-trip.
- A loaded object must reproduce the complete pre-storage panel fingerprint.

## Verified Acceptance

- Unit and integration tests cover exact round-trip, sparse/missing fields,
  blob and object deduplication, source-inventory invalidation, raw-file
  re-encoding, manifest/blob tampering, path confinement, explicit zero-loader
  operation, required-cache hits, and required-cache misses.
- The real eight-asset, 60-day workload used substrate
  `4067c314d34efa8ad3a8ca48b717a43601deadaa3ea004c83a37bddda880f023`.
- Materialize, automatic hit, and explicit frozen runs had the same panel
  fingerprint and byte-equivalent 12-row factor results: 0 pass, 0 watchlist.
- Measured wall times including Python startup were 2.096, 1.955, and 1.870
  seconds respectively. v1 improves evidence integrity more than speed.
- Local Windows and server Linux regressions both pass 194 tests with the
  existing 9 constant-series warnings.
- A server-native 730-day/two-asset materialization and explicit frozen reload
  produced the same fingerprint and failure set while the loader was replaced
  with a call-forbidden sentinel. Server substrate id:
  `fbf6c77292ab3b8ee48021473167c16c8337bc18aef33a3ca4450ac2487d1bcb`.

## Deferred

- persistent factor and baseline feature artifacts;
- garbage collection and storage-retention policy;
- process leases around concurrent materialization;
- automatic stale-run recovery and worker scheduling.
