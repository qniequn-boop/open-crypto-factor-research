"""Differential point-in-time audit for panel formulas and eligibility.

The audit follows the same black-box principle as Freqtrade lookahead-analysis:
recompute with future data removed or perturbed, then compare historical
outputs.  Forward-return labels are intentionally excluded from the audited
feature set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import config
import panel_factor_research
import panel_substrate_cache


AUDIT_SCHEMA_VERSION = "panel_formula_differential_audit_v1"
DEFAULT_CUTOFF_FRACTIONS = (0.55, 0.70, 0.85)
LOG_DIR = Path(config.LOG_DIR)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _panel_index(panel: dict[str, dict[str, Any]]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex([])
    for item in panel.values():
        ohlcv = item.get("ohlcv")
        if ohlcv is not None:
            index = index.union(pd.DatetimeIndex(ohlcv.index))
    return index.sort_values()


def _copy_and_perturb_future(
    panel: dict[str, dict[str, Any]],
    cutoff: pd.Timestamp,
) -> dict[str, dict[str, Any]]:
    perturbed: dict[str, dict[str, Any]] = {}
    for asset_number, (inst_id, item) in enumerate(panel.items(), start=1):
        clean = dict(item)
        for field in panel_substrate_cache.PANEL_FIELDS:
            value = item.get(field)
            if value is None:
                clean[field] = None
                continue
            changed = value.copy(deep=True)
            future_mask = changed.index > cutoff
            if not future_mask.any():
                clean[field] = changed
                continue
            if isinstance(changed, pd.Series):
                if pd.api.types.is_numeric_dtype(changed.dtype):
                    changed = changed.astype(float)
                    positions = np.arange(int(future_mask.sum()), dtype=float)
                    changed.loc[future_mask] = (
                        changed.loc[future_mask].astype(float).fillna(0.0).to_numpy()
                        * (7.0 + asset_number)
                        + (positions + 1.0) * 0.001 * asset_number
                    )
            else:
                numeric_columns = list(changed.select_dtypes(include=[np.number]).columns)
                for column_number, column in enumerate(numeric_columns, start=1):
                    changed[column] = changed[column].astype(float)
                    positions = np.arange(int(future_mask.sum()), dtype=float)
                    changed.loc[future_mask, column] = (
                        changed.loc[future_mask, column].astype(float).fillna(0.0).to_numpy()
                        * (7.0 + asset_number + column_number)
                        + (positions + 1.0) * 0.001 * (asset_number + column_number)
                    )
            clean[field] = changed
        perturbed[inst_id] = clean
    return perturbed


def _audited_frames(matrices: dict[str, Any]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for name in (
        "eligibility",
        "close",
        "spot_close",
        "basis",
        "returns",
        "funding_signal",
        "funding_cost",
        "open_interest",
        "market_cap",
        "listing_age",
        "vol_quote",
    ):
        value = matrices.get(name)
        if isinstance(value, pd.DataFrame):
            frames[f"core:{name}"] = value
    for name, value in sorted((matrices.get("formula_library") or {}).items()):
        if isinstance(value, pd.DataFrame):
            frames[f"formula:{name}"] = value
    for name, value in sorted((matrices.get("factors") or {}).items()):
        if isinstance(value, pd.DataFrame):
            frames[f"factor:{name}"] = value
    return frames


def _first_mismatch(
    mask: pd.DataFrame,
) -> dict[str, str] | None:
    positions = np.argwhere(mask.to_numpy(dtype=bool))
    if not len(positions):
        return None
    row_number, column_number = positions[0]
    return {
        "timestamp": str(mask.index[int(row_number)]),
        "asset": str(mask.columns[int(column_number)]),
    }


def _compare_prefix(
    expected: pd.DataFrame,
    observed: pd.DataFrame,
    cutoff: pd.Timestamp,
    *,
    atol: float,
    rtol: float,
) -> dict[str, Any]:
    left = expected.loc[expected.index <= cutoff]
    right = observed.loc[observed.index <= cutoff]
    index_match = left.index.equals(right.index)
    columns_match = left.columns.equals(right.columns)
    all_index = left.index.union(right.index)
    all_columns = left.columns.union(right.columns)
    left = left.reindex(index=all_index, columns=all_columns)
    right = right.reindex(index=all_index, columns=all_columns)

    left_missing = left.isna()
    right_missing = right.isna()
    missing_mismatch = left_missing.ne(right_missing)
    comparable = ~(left_missing | right_missing)
    observable_cells = int((~left_missing).sum().sum())

    if all(pd.api.types.is_bool_dtype(dtype) for dtype in left.dtypes) and all(
        pd.api.types.is_bool_dtype(dtype) for dtype in right.dtypes
    ):
        value_mismatch = left.ne(right) & comparable
        max_abs_difference = 0.0
    else:
        left_numeric = left.apply(pd.to_numeric, errors="coerce")
        right_numeric = right.apply(pd.to_numeric, errors="coerce")
        left_values = left_numeric.to_numpy(dtype=float)
        right_values = right_numeric.to_numpy(dtype=float)
        finite_pair = np.isfinite(left_values) & np.isfinite(right_values)
        close = np.zeros(left_values.shape, dtype=bool)
        close[finite_pair] = np.isclose(
            left_values[finite_pair],
            right_values[finite_pair],
            atol=atol,
            rtol=rtol,
        )
        same_nonfinite = (~np.isfinite(left_values)) & (~np.isfinite(right_values)) & (
            np.signbit(left_values) == np.signbit(right_values)
        )
        value_mismatch = pd.DataFrame(
            comparable.to_numpy(dtype=bool) & ~(close | same_nonfinite),
            index=all_index,
            columns=all_columns,
        )
        finite_differences = np.abs(left_values[finite_pair] - right_values[finite_pair])
        max_abs_difference = float(finite_differences.max()) if finite_differences.size else 0.0

    mismatch = missing_mismatch | value_mismatch
    mismatch_count = int(mismatch.sum().sum())
    if not index_match or not columns_match:
        mismatch_count += 1
    return {
        "index_match": index_match,
        "columns_match": columns_match,
        "expected_rows": int(len(expected.loc[expected.index <= cutoff])),
        "observed_rows": int(len(observed.loc[observed.index <= cutoff])),
        "column_count": int(len(all_columns)),
        "observable_cells": observable_cells,
        "missingness_mismatch_count": int(missing_mismatch.sum().sum()),
        "value_mismatch_count": int(value_mismatch.sum().sum()),
        "mismatch_count": mismatch_count,
        "max_abs_difference": max_abs_difference,
        "first_mismatch": _first_mismatch(mismatch),
        "passed": mismatch_count == 0,
    }


def _build(
    builder: Callable[..., dict[str, Any]],
    panel: dict[str, dict[str, Any]],
    candidate_definitions: list[dict[str, Any]],
    requested_factor_names: set[str],
    *,
    filter_default_formula_library: bool,
) -> dict[str, Any]:
    matrices = builder(
        panel,
        candidate_definitions=candidate_definitions,
        requested_factor_names=requested_factor_names,
    )
    if filter_default_formula_library:
        required_formulas = {
            str(candidate["panel_formula"])
            for candidate in candidate_definitions
            if candidate.get("panel_formula")
        }
        required_formulas.update(
            name for name in requested_factor_names if name in panel_factor_research.FACTOR_DEFINITIONS
        )
        matrices["formula_library"] = {
            name: value
            for name, value in (matrices.get("formula_library") or {}).items()
            if name in required_formulas
        }
    return matrices


def run_differential_audit(
    panel: dict[str, dict[str, Any]],
    *,
    candidate_definitions: list[dict[str, Any]] | None = None,
    cutoff_fractions: tuple[float, ...] = DEFAULT_CUTOFF_FRACTIONS,
    required_factor_names: set[str] | None = None,
    matrix_builder: Callable[..., dict[str, Any]] | None = None,
    atol: float = 1e-12,
    rtol: float = 1e-10,
) -> dict[str, Any]:
    candidate_definitions = list(candidate_definitions or [])
    builder = matrix_builder or panel_factor_research._build_matrices
    required = set(required_factor_names or {str(row["candidate_id"]) for row in candidate_definitions})
    filter_default_formula_library = matrix_builder is None
    fractions = tuple(float(value) for value in cutoff_fractions)
    if not fractions or any(not 0.0 < value < 1.0 for value in fractions):
        raise ValueError("cutoff_fractions_must_be_between_zero_and_one")
    timeline = _panel_index(panel)
    if len(timeline) < 10:
        raise ValueError("insufficient_panel_timeline_for_differential_audit")
    cutoff_indexes = sorted({min(max(int(len(timeline) * value), 1), len(timeline) - 2) for value in fractions})
    cutoffs = [timeline[index] for index in cutoff_indexes]

    full_matrices = _build(
        builder,
        panel,
        candidate_definitions,
        required,
        filter_default_formula_library=filter_default_formula_library,
    )
    full_frames = _audited_frames(full_matrices)
    comparisons: list[dict[str, Any]] = []
    for cutoff in cutoffs:
        variants = {
            "future_truncated": panel_factor_research._truncate_panel_as_of(panel, cutoff),
            "future_perturbed": _copy_and_perturb_future(panel, cutoff),
        }
        for variant_name, variant_panel in variants.items():
            variant_frames = _audited_frames(
                _build(
                    builder,
                    variant_panel,
                    candidate_definitions,
                    required,
                    filter_default_formula_library=filter_default_formula_library,
                )
            )
            frame_names = sorted(set(full_frames) | set(variant_frames))
            for frame_name in frame_names:
                if frame_name not in full_frames or frame_name not in variant_frames:
                    comparison = {
                        "passed": False,
                        "mismatch_count": 1,
                        "observable_cells": 0,
                        "reason": "audited_frame_missing_from_variant",
                    }
                else:
                    comparison = _compare_prefix(
                        full_frames[frame_name],
                        variant_frames[frame_name],
                        cutoff,
                        atol=atol,
                        rtol=rtol,
                    )
                comparisons.append(
                    {
                        "cutoff": cutoff.isoformat(),
                        "variant": variant_name,
                        "frame": frame_name,
                        **comparison,
                    }
                )

    frame_summary: dict[str, dict[str, Any]] = {}
    for frame_name in sorted(full_frames):
        rows = [row for row in comparisons if row["frame"] == frame_name]
        mismatch_count = sum(int(row.get("mismatch_count") or 0) for row in rows)
        observable_cells = sum(int(row.get("observable_cells") or 0) for row in rows)
        if mismatch_count:
            status = "leakage_detected"
        elif observable_cells == 0:
            status = "inconclusive_no_observations"
        else:
            status = "causal_pass"
        frame_summary[frame_name] = {
            "status": status,
            "comparison_count": len(rows),
            "observable_cells": observable_cells,
            "mismatch_count": mismatch_count,
            "max_abs_difference": max((float(row.get("max_abs_difference") or 0.0) for row in rows), default=0.0),
        }

    required_results = {
        name: frame_summary.get(f"factor:{name}", {"status": "missing_from_audit"})["status"]
        for name in sorted(required)
    }
    leakage_frames = sorted(
        frame_name for frame_name, row in frame_summary.items() if row["status"] == "leakage_detected"
    )
    inconclusive_frames = sorted(
        frame_name for frame_name, row in frame_summary.items() if row["status"] == "inconclusive_no_observations"
    )
    required_failures = sorted(name for name, status in required_results.items() if status != "causal_pass")
    return {
        "created_at_utc": _stamp(),
        "schema_version": AUDIT_SCHEMA_VERSION,
        "method": "full_vs_future_truncated_and_future_perturbed_prefix_comparison",
        "cutoff_fractions": list(fractions),
        "cutoffs": [cutoff.isoformat() for cutoff in cutoffs],
        "tolerance": {"atol": float(atol), "rtol": float(rtol)},
        "forward_return_label_audited": False,
        "forward_return_label_exclusion_reason": "future_return_is_a_supervised_target_not_a_tradable_feature",
        "candidate_ids": [str(row["candidate_id"]) for row in candidate_definitions],
        "required_factor_names": sorted(required),
        "required_factor_results": required_results,
        "required_factor_failures": required_failures,
        "leakage_frames": leakage_frames,
        "inconclusive_frames": inconclusive_frames,
        "leakage_free": not leakage_frames,
        "required_factors_fully_verified": not required_failures,
        "passed": not leakage_frames and not required_failures,
        "frame_summary": frame_summary,
        "comparisons": comparisons,
        "references": [
            {
                "name": "Freqtrade lookahead-analysis",
                "url": "https://docs.freqtrade.io/en/stable/lookahead-analysis/",
                "adopted_principle": "black-box sliced reruns and indicator comparison",
            },
            {
                "name": "Qlib point-in-time database",
                "url": "https://qlib.readthedocs.io/en/stable/advanced/PIT.html",
                "adopted_principle": "historical outputs may use only information observable by that timestamp",
            },
        ],
    }


def _load_substrate(manifest_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    if manifest_path.name != "manifest.json" or manifest_path.parent.parent.name != "objects":
        raise ValueError("panel_substrate_manifest_path_layout_invalid")
    store = panel_substrate_cache.PanelSubstrateStore(manifest_path.parents[2])
    panel, failures, manifest = store.load(
        manifest_path,
        panel_fingerprint_fn=panel_factor_research._panel_input_fingerprint,
    )
    if failures:
        raise ValueError(f"panel_substrate_contains_load_failures:{failures}")
    return panel, manifest


def _write_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = report_dir / f"panel_formula_audit_{report['created_at_utc']}.json"
    path.write_text(payload, encoding="utf-8")
    (report_dir / "panel_formula_audit_latest.json").write_text(payload, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--substrate-manifest", required=True)
    parser.add_argument("--candidate-batch")
    parser.add_argument(
        "--hypothesis-registry",
        default=str(Path(__file__).with_name("LITERATURE_HYPOTHESIS_REGISTRY.md")),
    )
    parser.add_argument("--cutoff-fractions", default=",".join(str(value) for value in DEFAULT_CUTOFF_FRACTIONS))
    parser.add_argument("--report-dir", default=str(LOG_DIR))
    args = parser.parse_args(argv)

    panel, manifest = _load_substrate(Path(args.substrate_manifest))
    candidates, rejections, batch_id = panel_factor_research._load_candidate_definitions(
        args.candidate_batch,
        args.hypothesis_registry,
    )
    if rejections:
        raise ValueError(f"candidate_batch_contains_rejections:{rejections}")
    fractions = tuple(float(value.strip()) for value in args.cutoff_fractions.split(",") if value.strip())
    report = run_differential_audit(
        panel,
        candidate_definitions=candidates,
        cutoff_fractions=fractions,
    )
    report["candidate_batch_id"] = batch_id
    report["panel_substrate"] = {
        "substrate_id": manifest["substrate_id"],
        "manifest_path": manifest["manifest_path"],
        "manifest_sha256": manifest["manifest_sha256"],
        "panel_fingerprint": manifest["panel_fingerprint"],
    }
    report["code_sha256"] = _file_sha256(Path(__file__))
    path = _write_report(report, Path(args.report_dir))
    print(f"WROTE {path}")
    print(
        f"LEAKAGE_FREE {report['leakage_free']} REQUIRED_VERIFIED "
        f"{report['required_factors_fully_verified']} PASSED {report['passed']}"
    )
    if report["leakage_frames"]:
        print("LEAKAGE_FRAMES", ",".join(report["leakage_frames"]))
    if report["required_factor_failures"]:
        print("REQUIRED_FACTOR_FAILURES", ",".join(report["required_factor_failures"]))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
