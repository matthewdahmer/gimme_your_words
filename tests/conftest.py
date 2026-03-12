"""
Shared fixtures for the test suite.
"""

import json
import textwrap
from pathlib import Path

import pytest

from gimme_your_words.profiles import load_profiles, SiteProfile, ContentConfig, PaywallConfig


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Profile fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def builtin_profiles():
    """The profiles loaded from the built-in profiles.yaml."""
    return load_profiles()


@pytest.fixture()
def medium_profile(builtin_profiles):
    return next(p for p in builtin_profiles if p.name == "Medium")


@pytest.fixture()
def generic_profile(builtin_profiles):
    return next(p for p in builtin_profiles if p.name == "Generic")


@pytest.fixture()
def custom_profiles_yaml(tmp_path):
    """A minimal custom profiles YAML file."""
    content = textwrap.dedent("""
        profiles:
          - name: My Blog
            match_domains:
              - "myblog.com"
            content:
              selector: ".post-content"
              fallback: "article"
            paywall:
              text: []
            warmup_url: null
    """)
    p = tmp_path / "custom_profiles.yaml"
    p.write_text(content)
    return str(p)


# ---------------------------------------------------------------------------
# Cookie fixtures
# ---------------------------------------------------------------------------

SAMPLE_COOKIES_JSON = [
    {"name": "sid",  "value": "abc123", "domain": ".medium.com", "path": "/"},
    {"name": "uid",  "value": "xyz789", "domain": ".medium.com", "path": "/"},
    {"name": "_ga",  "value": "GA1.1.1", "domain": ".medium.com", "path": "/"},
]

SAMPLE_COOKIES_NETSCAPE = """\
# Netscape HTTP Cookie File
.medium.com\tTRUE\t/\tTRUE\t0\tsid\tabc123
.medium.com\tTRUE\t/\tTRUE\t0\tuid\txyz789
"""


@pytest.fixture()
def cookies_json_file(tmp_path):
    f = tmp_path / "cookies.json"
    f.write_text(json.dumps(SAMPLE_COOKIES_JSON))
    return str(f)


@pytest.fixture()
def cookies_netscape_file(tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text(SAMPLE_COOKIES_NETSCAPE)
    return str(f)


@pytest.fixture()
def cookies_escaped_file(tmp_path):
    """A JSON file where quotes are backslash-escaped (common copy-paste artifact)."""
    raw = json.dumps(SAMPLE_COOKIES_JSON).replace('"', '\\"')
    f = tmp_path / "cookies_escaped.json"
    f.write_text(raw)
    return str(f)


# ---------------------------------------------------------------------------
# Scraper config fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def base_config(tmp_path):
    from gimme_your_words.scraper import ScrapeConfig
    return ScrapeConfig(
        output_dir=tmp_path / "articles",
        format="markdown",
        delay=0,
        timeout=5000,
        headless=True,
        skip_existing=True,
        force=False,
        max_retries=1,
    )
