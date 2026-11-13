"""``with connect() as connection:`` closes the connection at the end of the
block, so a connection used after its block is a closed one: a 500 in
production.  The scan finds that use in the source before a page does."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from anamna import db
from anamna.config import Settings

SRC = Path(__file__).resolve().parents[2] / "src"


def test_the_block_commits_and_closes(tmp_path):
    settings = Settings(database_path=tmp_path / "closing.sqlite3", source_dir=tmp_path, secret_key="x")
    with db.connect(settings) as connection:
        connection.execute("CREATE TABLE t (x)")
        connection.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with db.connect(settings) as connection:
        assert [tuple(row) for row in connection.execute("SELECT x FROM t")] == [(1,)]


def _used_after_block(tree: ast.AST) -> list[tuple[str, int]]:
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = [node for node in ast.walk(function) if isinstance(node, ast.Name)]
        for block in ast.walk(function):
            if not isinstance(block, ast.With):
                continue
            for item in block.items:
                call, target = item.context_expr, item.optional_vars
                if not (isinstance(call, ast.Call) and isinstance(target, ast.Name)
                        and getattr(call.func, "id", getattr(call.func, "attr", None)) == "connect"):
                    continue
                rebound = min((n.lineno for n in names if n.id == target.id and isinstance(n.ctx, ast.Store)
                               and n.lineno > block.end_lineno), default=float("inf"))
                found += [(function.name, n.lineno) for n in names if n.id == target.id
                          and isinstance(n.ctx, ast.Load) and block.end_lineno < n.lineno < rebound]
    return found


def test_no_connection_is_used_after_its_block():
    late = {str(path.relative_to(SRC)): hits for path in SRC.rglob("*.py")
            if (hits := _used_after_block(ast.parse(path.read_text(encoding="utf-8"))))}
    assert late == {}
