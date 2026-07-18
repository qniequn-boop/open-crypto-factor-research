from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def _integer_attribute(root: ET.Element, name: str) -> int:
    return int(float(root.attrib.get(name, "0")))


def _junit_totals(root: ET.Element) -> dict[str, int]:
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError(f"JUnit report contains no test suites: {root.tag}")
    return {
        name: sum(_integer_attribute(suite, name) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: ci_test_summary.py JUNIT_XML CURRENT_BASELINE_JSON")
        return 2

    junit_path = Path(sys.argv[1])
    baseline_path = Path(sys.argv[2])
    if not junit_path.exists():
        print(f"CI test report is missing: {junit_path}")
        return 1

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    root = ET.parse(junit_path).getroot()
    totals = _junit_totals(root)
    tests = totals["tests"]
    failures = totals["failures"]
    errors = totals["errors"]
    skipped = totals["skipped"]
    passed = tests - failures - errors - skipped
    expected = int(baseline["expected_collected_tests"])
    expected_skipped = int(baseline["expected_skipped_tests"])
    expected_python = str(baseline["python_version"])
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"

    baseline_matches = (
        tests == expected
        and skipped == expected_skipped
        and actual_python == expected_python
    )
    suite_passed = failures == 0 and errors == 0
    status = "PASS" if baseline_matches and suite_passed else "FAIL"

    lines = [
        "## Test baseline",
        "",
        f"**Status: {status}**",
        "",
        "| Field | Result |",
        "| --- | ---: |",
        f"| Python | {actual_python} |",
        f"| Collected | {tests} |",
        f"| Expected | {expected} |",
        f"| Passed | {passed} |",
        f"| Failed | {failures} |",
        f"| Errors | {errors} |",
        f"| Skipped | {skipped} |",
        f"| Expected skipped | {expected_skipped} |",
        "",
        "Earlier test counts in the Roadmap are historical milestones. ",
        "This table is the current commit's CI result.",
    ]
    summary = "\n".join(lines) + "\n"
    print(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(summary)

    if actual_python != expected_python:
        print(f"Python baseline mismatch: expected {expected_python}, got {actual_python}")
    if tests != expected:
        print(f"Test-count baseline mismatch: expected {expected}, got {tests}")
    if skipped != expected_skipped:
        print(f"Skipped-test baseline mismatch: expected {expected_skipped}, got {skipped}")
    return 0 if baseline_matches and suite_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
