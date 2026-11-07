"""Static URLs must carry a version, or a deploy ships new markup on old CSS.

Cloudflare caches `/static/*` by URL for four hours in front of the deployed
server and the deploy does not purge it.  An unversioned `<link>` therefore
serves the previous release's stylesheet to the current release's templates —
which surfaces as a control that renders unstyled, not as an obviously stale
file.  That is exactly how `.ai-fab` shipped invisible.
"""

from __future__ import annotations

import re

from anamna.web.app import WEB_DIR, asset


def test_asset_url_carries_the_files_mtime() -> None:
    stamp = int((WEB_DIR / "static" / "app.css").stat().st_mtime)
    assert asset("app.css") == f"/static/app.css?v={stamp}"


def test_missing_file_still_yields_a_usable_url() -> None:
    assert asset("not-here.css") == "/static/not-here.css"


def test_no_template_hardcodes_a_static_url() -> None:
    """A new `<script src="/static/...">` would silently reintroduce the bug."""
    offenders = []
    for template in sorted((WEB_DIR / "templates").rglob("*.html")):
        for number, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""(?:href|src)=["']/static/""", line):
                offenders.append(f"{template.name}:{number}: {line.strip()}")
    assert not offenders, "use {{ asset('file.css') }} instead:\n" + "\n".join(offenders)
