import copy
import json
from datetime import date

import okx_l2_regime_study as study


def _loaded_study():
    return study.load_study_contract()


def test_budget_amendment_is_bound_before_outcomes_and_covers_metadata():
    loaded = _loaded_study()
    amendment = loaded["amendment"]

    assert amendment["outcome_data_accessed"] is False
    assert amendment["factor_return_data_accessed"] is False
    assert amendment["metadata_feasibility"]["original_budget_can_satisfy_admission_coverage"] is False
    assert amendment["amended_download_budget"]["maximum_compressed_l2_bytes"] > 5_706_550_000
    assert len(loaded["contract"]["unseen_regime_dates"]) == 5
    assert len(loaded["contract"]["asset_sample"]) == 5


def test_metadata_freeze_requires_every_frozen_asset_date_and_budget():
    loaded = _loaded_study()
    assets = loaded["contract"]["asset_sample"]

    def fake_discover(inst_ids, target_date: date):
        assert list(inst_ids) == assets
        return {
            "l2": [
                {
                    "module": "4",
                    "inst_family": inst_id[:-5],
                    "inst_id": inst_id,
                    "date_ts": 1,
                    "filename": f"{inst_id}-{target_date}.tar.gz",
                    "size_mb": 10.0,
                    "url": "https://static.okx.com/test",
                }
                for inst_id in assets
            ],
            "trades": [
                {
                    "module": "1",
                    "inst_family": inst_id[:-5],
                    "inst_id": inst_id,
                    "date_ts": 1,
                    "filename": f"{inst_id}-{target_date}.zip",
                    "size_mb": 1.0,
                    "url": "https://static.okx.com/test",
                }
                for inst_id in assets
            ],
        }

    metadata = study.discover_archive_metadata(loaded, discover=fake_discover)

    assert metadata["checks"]["all_25_l2_cells_declared"] is True
    assert metadata["declared_l2_size_mb"] == 250.0
    assert metadata["outcome_data_accessed"] is False


def _cell_payload(loaded, date_text, regime_label, inst_id, quoted_spread):
    impact = {}
    for notional, extra in (("100", 0.1), ("1000", 0.2), ("10000", 0.5)):
        side = {
            "count": 100,
            "median": quoted_spread / 2.0 + extra,
            "p95": quoted_spread + extra,
        }
        impact[notional] = {
            "buy": dict(side),
            "sell": dict(side),
            "buy_fill_fraction": 1.0,
            "sell_fill_fraction": 1.0,
        }
    return {
        "schema_version": 1,
        "audit_type": "okx_l2_regime_asset_date_cell",
        "created_at_utc": "20260718T000000Z",
        "contract_sha256": loaded["contract_sha256"],
        "budget_amendment_sha256": loaded["amendment_sha256"],
        "metadata_sha256": "metadata",
        "cell_evaluator_sha256": study.cell_evaluator_fingerprint()["bundle_sha256"],
        "date": date_text,
        "regime_label": regime_label,
        "inst_id": inst_id,
        "analysis": {
            "sampling": {"coverage_fraction": 1.0},
            "book_integrity": {
                "snapshot_count": 1,
                "monotonic_timestamp_violations": 0,
                "maximum_event_gap_ms": 100,
            },
            "quoted_spread_bps": {"median": quoted_spread},
            "effective_spread_bps": {"quote_notional_weighted_one_way_slippage_bps": quoted_spread / 2.0},
            "market_order_impact_bps": impact,
        },
    }


def _synthetic_cells(tmp_path, loaded):
    cell_dir = tmp_path / "cells"
    cell_dir.mkdir()
    for date_row in loaded["contract"]["unseen_regime_dates"]:
        for rank, inst_id in enumerate(loaded["contract"]["asset_sample"], start=1):
            payload = _cell_payload(
                loaded,
                date_row["date"],
                date_row["label"],
                inst_id,
                float(rank),
            )
            path = study._cell_path(cell_dir, date_row["date"], inst_id)
            path.write_text(json.dumps(payload), encoding="utf-8")
    return cell_dir


def test_aggregate_authorizes_only_when_frozen_rank_and_coverage_gates_pass(tmp_path):
    loaded = _loaded_study()
    cell_dir = _synthetic_cells(tmp_path, loaded)
    metadata = {
        "contract": {"sha256": loaded["contract_sha256"]},
        "dates": {},
    }
    ranks = {inst_id: rank for rank, inst_id in enumerate(loaded["contract"]["asset_sample"], start=1)}

    report = study.aggregate_study(
        loaded,
        metadata,
        cell_dir=cell_dir,
        proxy_loader=lambda inst_id, _date: {
            "full_spread_bps": float(ranks[inst_id]),
            "source_path": "synthetic",
            "source_sha256": "synthetic",
        },
    )

    assert report["complete_cells"] == 25
    assert report["proxy_rank_summary"]["dates_with_positive_spearman"] == 5
    assert report["proxy_rank_summary"]["median_spearman"] == 1.0
    assert all(report["admission_checks"].values())
    assert report["decision"]["microstructure_source_authorized"] is True
    assert report["decision"]["authorized_paths"] == [
        "canonical_bidask",
        "canonical_turnover_volatility",
    ]
    assert len(report["cost_surface"]) == 15
    assert report["cost_surface"][0]["break_even_turnover_formula"]

    reversed_report = study.aggregate_study(
        loaded,
        metadata,
        cell_dir=cell_dir,
        proxy_loader=lambda inst_id, _date: {
            "full_spread_bps": float(6 - ranks[inst_id]),
            "source_path": "synthetic",
            "source_sha256": "synthetic",
        },
    )
    assert reversed_report["proxy_rank_summary"]["median_spearman"] == -1.0
    assert reversed_report["decision"]["microstructure_source_authorized"] is False
    assert reversed_report["decision"]["authorized_paths"] == []


def test_generic_cost_surface_does_not_contain_factor_identity(tmp_path):
    loaded = _loaded_study()
    cell_dir = _synthetic_cells(tmp_path, loaded)
    metadata = {"contract": {"sha256": loaded["contract_sha256"]}, "dates": {}}
    report = study.aggregate_study(
        loaded,
        metadata,
        cell_dir=cell_dir,
        proxy_loader=lambda _inst_id, _date: {
            "full_spread_bps": 1.0,
            "source_path": "synthetic",
            "source_sha256": "synthetic",
        },
    )

    encoded = json.dumps(report["cost_surface"]).lower()
    assert "low_vol" not in encoded
    assert "candidate_id" not in encoded
    assert report["cost_surface_policy"]["same_surface_for_all_factors"] is True


def test_markdown_renders_unfilled_cost_cells_as_na(tmp_path):
    loaded = _loaded_study()
    cell_dir = _synthetic_cells(tmp_path, loaded)
    metadata = {"contract": {"sha256": loaded["contract_sha256"]}, "dates": {}}
    report = study.aggregate_study(
        loaded,
        metadata,
        cell_dir=cell_dir,
        proxy_loader=lambda _inst_id, _date: {
            "full_spread_bps": 1.0,
            "source_path": "synthetic",
            "source_sha256": "synthetic",
        },
    )
    report["cost_surface"][0]["median_one_way_cost_bps"] = None

    rendered = study.render_markdown(report)

    assert "| NA |" in rendered
