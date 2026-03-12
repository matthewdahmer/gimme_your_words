"""
Tests for gimme_your_words.profiles
"""

import textwrap
import pytest

from gimme_your_words.profiles import (
    load_profiles,
    match_profile,
    SiteProfile,
    ContentConfig,
    PaywallConfig,
)


class TestLoadProfiles:

    def test_loads_builtin_profiles(self, builtin_profiles):
        assert len(builtin_profiles) > 0

    def test_medium_profile_present(self, builtin_profiles):
        names = [p.name for p in builtin_profiles]
        assert "Medium" in names

    def test_generic_profile_present(self, builtin_profiles):
        names = [p.name for p in builtin_profiles]
        assert "Generic" in names

    def test_generic_is_last(self, builtin_profiles):
        assert builtin_profiles[-1].name == "Generic"

    def test_loads_custom_profiles(self, custom_profiles_yaml, builtin_profiles):
        profiles = load_profiles(custom_profiles_yaml)
        names = [p.name for p in profiles]
        assert "My Blog" in names
        # Built-ins still present
        assert "Medium" in names

    def test_custom_profiles_appended_after_builtins(self, custom_profiles_yaml, builtin_profiles):
        profiles = load_profiles(custom_profiles_yaml)
        builtin_count = len(builtin_profiles)
        # Custom profile appears after builtins (before Generic which may be reordered)
        my_blog_idx = next(i for i, p in enumerate(profiles) if p.name == "My Blog")
        assert my_blog_idx >= builtin_count - 1  # after all builtins except possibly Generic

    def test_missing_extra_profiles_file_ignored(self):
        """A nonexistent extra profiles path should not crash."""
        profiles = load_profiles("/nonexistent/profiles.yaml")
        assert len(profiles) > 0

    def test_custom_profile_fields(self, custom_profiles_yaml):
        profiles = load_profiles(custom_profiles_yaml)
        blog = next(p for p in profiles if p.name == "My Blog")
        assert blog.content.selector == ".post-content"
        assert blog.content.fallback == "article"
        assert blog.match_domains == ["myblog.com"]

    def test_profile_with_paywall_text(self, builtin_profiles):
        medium = next(p for p in builtin_profiles if p.name == "Medium")
        assert "Member-only story" in medium.paywall.text

    def test_profile_warmup_url(self, builtin_profiles):
        medium = next(p for p in builtin_profiles if p.name == "Medium")
        assert medium.warmup_url == "https://medium.com"

    def test_profile_without_warmup_url(self, builtin_profiles):
        generic = next(p for p in builtin_profiles if p.name == "Generic")
        assert generic.warmup_url is None


class TestSiteProfileMatchesDomain:

    def test_exact_match(self, medium_profile):
        assert medium_profile.matches_domain("medium.com")

    def test_wildcard_subdomain(self, medium_profile):
        assert medium_profile.matches_domain("user.medium.com")
        assert medium_profile.matches_domain("publication.medium.com")

    def test_no_match(self, medium_profile):
        assert not medium_profile.matches_domain("notmedium.com")
        assert not medium_profile.matches_domain("evil-medium.com")

    def test_generic_matches_everything(self, generic_profile):
        assert generic_profile.matches_domain("anything.com")
        assert generic_profile.matches_domain("example.org")

    def test_case_insensitive(self, medium_profile):
        assert medium_profile.matches_domain("MEDIUM.COM")
        assert medium_profile.matches_domain("User.Medium.Com")

    def test_leading_dot_stripped(self, medium_profile):
        assert medium_profile.matches_domain(".medium.com")


class TestMatchProfile:

    def test_matches_medium_by_domain(self, builtin_profiles):
        profile = match_profile(["medium.com", "cdn.medium.com"], builtin_profiles)
        assert profile.name == "Medium"

    def test_matches_medium_subdomain(self, builtin_profiles):
        profile = match_profile(["user.medium.com"], builtin_profiles)
        assert profile.name == "Medium"

    def test_falls_back_to_generic(self, builtin_profiles):
        profile = match_profile(["unknown-site.xyz"], builtin_profiles)
        assert profile.name == "Generic"

    def test_empty_domains_returns_generic(self, builtin_profiles):
        profile = match_profile([], builtin_profiles)
        assert profile.name == "Generic"

    def test_custom_profile_wins_over_generic(self, custom_profiles_yaml):
        profiles = load_profiles(custom_profiles_yaml)
        profile = match_profile(["myblog.com"], profiles)
        assert profile.name == "My Blog"

    def test_custom_profile_wins_over_builtin(self, tmp_path):
        """A user-defined profile for medium.com should override the built-in one."""
        yaml_content = textwrap.dedent("""
            profiles:
              - name: Custom Medium Override
                match_domains:
                  - "*.medium.com"
                  - "medium.com"
                content:
                  selector: ".custom-article"
                  fallback: "main"
                paywall:
                  text: []
        """)
        f = tmp_path / "override.yaml"
        f.write_text(yaml_content)
        profiles = load_profiles(str(f))
        profile = match_profile(["medium.com"], profiles)
        assert profile.name == "Custom Medium Override"

    def test_multiple_domains_first_match_wins(self, builtin_profiles):
        """When multiple domains are present, the most specific profile wins."""
        profile = match_profile(
            ["googletagmanager.com", "medium.com", "analytics.google.com"],
            builtin_profiles
        )
        assert profile.name == "Medium"

    def test_substack_matched(self, builtin_profiles):
        profile = match_profile(["example.substack.com"], builtin_profiles)
        assert profile.name == "Substack"
