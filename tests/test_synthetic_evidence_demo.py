import json

from examples import run_synthetic_evidence_demo as demo


def test_demo_exercises_leakage_multiplicity_and_prospective_boundaries():
    report = demo.run_demo()
    by_id = {row["candidate_id"]: row for row in report["cases"]}

    leak = by_id["future_leak_candidate"]
    assert leak["status"] == "historical_reject"
    assert "factor:future_leak_candidate" in leak["leakage_frames"]

    multiple = by_id["multiplicity_candidate"]
    assert multiple["raw_p"] < 0.05
    assert multiple["bh_adjusted_p"] > 0.10
    assert multiple["prospective_entry_allowed"] is False

    prospective = by_id["prospective_candidate"]
    assert prospective["status"] == "prospective_eligible"
    assert prospective["formal_pass_possible"] is False

    assert report["external_market_data_used"] is False
    assert report["decision"] == {
        "formal_factor_pass_count": 0,
        "combo_allowed": False,
        "paper_trading_allowed": False,
        "capital_allowed": False,
        "reason": "historical_evidence_can_reject_or_authorize_observation_but_cannot_authorize_capital",
    }


def test_demo_json_cli_is_machine_readable(capsys):
    assert demo.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["demo"] == "synthetic_evidence_pipeline"
    assert payload["decision"]["capital_allowed"] is False
