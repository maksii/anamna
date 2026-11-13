"""Exercise real release artifacts using synthetic private-data sentinels."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tarfile
import zipfile

import pytest


REPO = Path(__file__).resolve().parents[2]
PRIVATE_SENTINEL = b"PRIVATE-PACKAGING-SENTINEL-DO-NOT-SHIP"


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("release-artifacts")
    checkout = root / "checkout"
    checkout.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy2(REPO / name, checkout / name)
    for name in ("src", "migrations"):
        shutil.copytree(REPO / name, checkout / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (checkout / "data").mkdir()
    shutil.copy2(REPO / "data/reference_library.json", checkout / "data/reference_library.json")
    shutil.copy2(REPO / "data/icd10.json", checkout / "data/icd10.json")
    # There is deliberately no .gitignore here: the package allowlist must stand
    # on its own, including when a source archive is built outside git.
    for name in (".env", "data/anamna.sqlite3", "sources/report.pdf", "work/private.json", ".tool-cache/state.json"):
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PRIVATE_SENTINEL)
    run([sys.executable, "-m", "hatchling", "build", "-t", "sdist"], cwd=checkout)
    sdist = next((checkout / "dist").glob("*.tar.gz"))
    extracted = root / "extracted"
    with tarfile.open(sdist) as archive:
        archive.extractall(extracted, filter="data")
    rebuilt = next(extracted.iterdir())
    run([sys.executable, "-m", "hatchling", "build", "-t", "wheel"], cwd=rebuilt)
    wheel = next((rebuilt / "dist").glob("*.whl"))
    return root, sdist, wheel


def test_release_artifacts_exclude_private_state_and_include_runtime_resources(artifacts):
    _, sdist, wheel = artifacts
    with tarfile.open(sdist) as archive:
        names = [member.name.split("/", 1)[1] for member in archive.getmembers() if member.isfile()]
        assert "data/reference_library.json" in names
        assert "data/icd10.json" in names
        for member in archive.getmembers():
            if member.isfile():
                assert PRIVATE_SENTINEL not in archive.extractfile(member).read()
        assert all(name.startswith(("src/anamna/", "migrations/")) or name in {
            "data/reference_library.json", "data/icd10.json", "README.md", "pyproject.toml", "uv.lock", "PKG-INFO", ".gitignore"
        } for name in names)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        expected = {f"anamna/resources/migrations/{path.name}" for path in (REPO / "migrations").glob("*.sql")}
        assert expected <= set(names)
        assert "anamna/resources/reference_library.json" in names
        assert "anamna/resources/icd10.json" in names
        assert "anamna/web/templates/login.html" in names
        assert "anamna/web/static/app.css" in names
        for name in names:
            assert PRIVATE_SENTINEL not in archive.read(name)


def test_installed_wheel_bootstraps_database_guidance_and_web_without_checkout(artifacts):
    root, _, wheel = artifacts
    uv = shutil.which("uv")
    assert uv, "uv is required for the offline wheel-install smoke test"
    environment = root / "installed"
    # Reuse installed runtime dependencies, but install the application wheel in
    # its own environment ahead of any editable checkout on sys.path. A nested
    # venv's system-site-packages refers to the base Python, not our test venv.
    env = {key: value for key, value in os.environ.items() if not key.startswith("ANAMNA_") and key != "PYTHONPATH"}
    env["UV_CACHE_DIR"] = str(root / "uv-cache")
    run([uv, "venv", "--python", sys.executable, "--system-site-packages", str(environment)], cwd=root, env=env)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([uv, "pip", "install", "--python", str(python), "--offline", "--no-deps", str(wheel)], cwd=root, env=env)
    installed_site = environment / ("Lib/site-packages" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
    (installed_site / "test-runtime-dependencies.pth").write_text("\n".join(site.getsitepackages()) + "\n", encoding="utf-8")
    state = root / "private-state"
    state.mkdir()
    script = """
from pathlib import Path
import sys
from fastapi.testclient import TestClient
import anamna
from anamna.config import get_settings
from anamna.db import connect, migrate, MIGRATIONS_DIR
from anamna.reference import LIBRARY_PATH, seed_reference_library

assert Path(anamna.__file__).is_relative_to(Path(sys.prefix)), anamna.__file__
settings = get_settings()
assert settings.database_path == Path.cwd() / 'data/anamna.sqlite3'
assert settings.source_dir == Path.cwd() / 'sources'
assert LIBRARY_PATH.is_relative_to(Path(sys.prefix))
assert MIGRATIONS_DIR.is_relative_to(Path(sys.prefix))
migrate(settings)
with connect(settings) as connection:
    assert connection.execute('SELECT count(*) FROM schema_migrations').fetchone()[0] == len(list(MIGRATIONS_DIR.glob('*.sql')))
    seed_reference_library(connection)
    assert connection.execute('SELECT count(*) FROM reference_sets').fetchone()[0] > 0
    assert connection.execute('SELECT count(*) FROM curated_reference_rules').fetchone()[0] > 0
    assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
from anamna.web.app import app
with TestClient(app) as client:
    response = client.get('/login')
    assert response.status_code == 200, response.status_code
    assert '<form' in response.text
    assert client.get('/static/app.css').status_code == 200
print('Installed wheel: migrations, guidance, login and assets passed')
"""
    assert "Installed wheel:" in run([str(python), "-c", script], cwd=state, env=env)
