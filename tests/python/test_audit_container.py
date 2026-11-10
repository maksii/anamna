"""Static checks on the container, compose and CI files (no Docker needed)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_dockerfile_cmd_disables_access_log():
    cmd_lines = [line for line in _text("Dockerfile").splitlines() if line.startswith("CMD ")]
    assert cmd_lines, "Dockerfile has no CMD line"
    assert '"--no-access-log"' in cmd_lines[-1]


def test_entrypoint_fails_closed_unless_root_is_allowed():
    raw = (ROOT / "docker-entrypoint.sh").read_bytes()
    assert b"\r" not in raw, "docker-entrypoint.sh must use LF line endings"
    text = raw.decode("utf-8")
    assert "ANAMNA_ALLOW_ROOT" in text
    assert "exit 1" in text
    assert "; continuing as root because ANAMNA_ALLOW_ROOT=1" in text
    assert 'could not take ownership of the data directory; continuing as root"' not in text


def test_compose_hardens_the_service():
    text = _text("compose.yaml")
    assert "read_only: true" in text
    assert "cap_drop:" in text
    assert "/app/tmp:uid=10001,gid=10001" in text


def test_ci_actions_are_pinned_to_commit_shas():
    uses_lines = [line for line in _text(".github/workflows/ci.yml").splitlines() if "uses:" in line]
    assert uses_lines, "ci.yml has no uses: lines"
    pattern = re.compile(r"uses: [\w./-]+@[0-9a-f]{40} # v[\d.]+")
    for line in uses_lines:
        assert pattern.search(line), f"action not pinned to a SHA with a version comment: {line.strip()}"
