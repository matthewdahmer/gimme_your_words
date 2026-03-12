"""
Cookie loading utilities.

Supports two formats:
  - JSON array (exported from Cookie-Editor / EditThisCookie browser extension)
  - Netscape format (.txt exported from "Get cookies.txt LOCALLY" extension)

To fix a file with escaped quotes (backslash-quote), run:
    sed 's/\\\\"/"/g' cookies.json > cookies_fixed.json
"""

import json
import re
from pathlib import Path
from typing import List, Dict


def load_cookies(path: str) -> List[Dict]:
    """
    Load cookies from a file and return a list of dicts compatible with
    Playwright's browser_context.add_cookies().
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Cookie file not found: {p}")

    raw = p.read_text(encoding="utf-8-sig").strip()  # utf-8-sig strips BOM

    # Fix literal backslash-escaped quotes (common copy-paste artifact)
    if '\\"' in raw:
        raw = raw.replace('\\"', '"')

    if raw.startswith("[") or raw.startswith("{"):
        return _parse_json(raw)
    else:
        return _parse_netscape(raw)


def _parse_json(raw: str) -> List[Dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON cookie file: {e}") from e

    if isinstance(data, dict):
        data = [data]

    cookies = []
    for c in data:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".medium.com"),
            "path": c.get("path", "/"),
        }
        # Playwright requires sameSite to be one of Strict/Lax/None if provided
        if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
            cookie["sameSite"] = c["sameSite"]
        if "expires" in c and isinstance(c["expires"], (int, float)) and c["expires"] > 0:
            cookie["expires"] = int(c["expires"])
        cookies.append(cookie)

    return cookies


def _parse_netscape(raw: str) -> List[Dict]:
    """Parse Netscape/Mozilla cookie format."""
    cookies = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        cookies.append({
            "domain": parts[0],
            "path": parts[2],
            "name": parts[5],
            "value": parts[6],
        })
    return cookies
