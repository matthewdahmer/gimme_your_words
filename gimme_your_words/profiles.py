"""
Site profile loader.

Profiles define how to extract article content and detect paywalls for
specific sites. They are matched against network requests made during
page load, so custom domains (e.g. a Medium publication on its own domain)
are detected automatically.

Profiles are loaded from (in order, last write wins):
  1. The built-in profiles.yaml bundled with the package
  2. A user-supplied profiles file (--profiles flag or SCRAPER_PROFILES env var)
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML is required: pip install pyyaml")


# Built-in profiles bundled with the package
_BUILTIN_PROFILES = Path(__file__).parent / "profiles.yaml"


@dataclass
class PaywallConfig:
    selector: Optional[str] = None
    text: List[str] = field(default_factory=list)
    min_length: int = 0


@dataclass
class ContentConfig:
    selector: str = "article"
    fallback: str = "main"


@dataclass
class SiteProfile:
    name: str
    match_domains: List[str]
    content: ContentConfig
    paywall: PaywallConfig
    warmup_url: Optional[str] = None

    def matches_domain(self, domain: str) -> bool:
        """Check if a domain matches any of this profile's patterns."""
        domain = domain.lower().lstrip(".")
        for pattern in self.match_domains:
            if pattern == "*":
                return True
            if fnmatch.fnmatch(domain, pattern.lower()):
                return True
        return False


def load_profiles(extra_path: Optional[str] = None) -> List[SiteProfile]:
    """
    Load site profiles from built-in file and optional user-supplied file.
    User profiles are appended after built-ins so they take priority in matching.
    """
    profiles = _load_yaml(str(_BUILTIN_PROFILES))

    # Also check env var
    env_path = os.environ.get("SCRAPER_PROFILES")
    if env_path and Path(env_path).exists():
        profiles += _load_yaml(env_path)

    if extra_path and Path(extra_path).exists():
        profiles += _load_yaml(extra_path)

    return profiles


def _load_yaml(path: str) -> List[SiteProfile]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    profiles = []
    for p in data.get("profiles", []):
        content_raw = p.get("content", {})
        paywall_raw = p.get("paywall", {})

        profiles.append(SiteProfile(
            name=p["name"],
            match_domains=p.get("match_domains", ["*"]),
            content=ContentConfig(
                selector=content_raw.get("selector", "article"),
                fallback=content_raw.get("fallback", "main"),
            ),
            paywall=PaywallConfig(
                selector=paywall_raw.get("selector"),
                text=paywall_raw.get("text", []),
                min_length=paywall_raw.get("min_length", 0),
            ),
            warmup_url=p.get("warmup_url"),
        ))

    return profiles


def match_profile(requested_domains: List[str], profiles: List[SiteProfile]) -> SiteProfile:
    """
    Given a list of domains seen in network requests, return the best matching
    profile. User-added profiles (appended last) take priority over built-ins
    because we iterate in reverse, stopping at the first non-Generic match.

    Falls back to the Generic profile if nothing else matches.
    """
    generic = next((p for p in profiles if p.name == "Generic"), profiles[-1])

    # Iterate profiles in reverse so user-supplied ones win
    for profile in reversed(profiles):
        if profile.name == "Generic":
            continue
        for domain in requested_domains:
            if profile.matches_domain(domain):
                return profile

    return generic
