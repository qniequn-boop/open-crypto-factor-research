import re
from pathlib import Path


def test_python_sources_do_not_embed_long_lived_api_tokens():
    project_root = Path(__file__).resolve().parents[1]
    token_pattern = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
    offenders = []
    for path in project_root.rglob("*.py"):
        if any(part in {"venv", ".venv", "data_cache", "logs"} for part in path.parts):
            continue
        if token_pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(project_root)))
    assert offenders == []
