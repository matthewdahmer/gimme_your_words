"""
Tests for gimme_your_words.cookies
"""

import json
import pytest

from gimme_your_words.cookies import load_cookies


class TestLoadCookiesJson:

    def test_loads_json_array(self, cookies_json_file):
        cookies = load_cookies(cookies_json_file)
        assert len(cookies) == 3
        assert cookies[0]["name"] == "sid"
        assert cookies[0]["value"] == "abc123"

    def test_preserves_domain(self, cookies_json_file):
        cookies = load_cookies(cookies_json_file)
        assert all(c["domain"] == ".medium.com" for c in cookies)

    def test_defaults_domain_when_missing(self, tmp_path):
        data = [{"name": "tok", "value": "val123"}]
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps(data))
        cookies = load_cookies(str(f))
        assert cookies[0]["domain"] == ".medium.com"

    def test_strips_escaped_quotes(self, cookies_escaped_file):
        """Files with backslash-escaped quotes (common copy-paste artifact) are fixed."""
        cookies = load_cookies(cookies_escaped_file)
        assert len(cookies) == 3
        assert cookies[0]["name"] == "sid"

    def test_single_dict_wrapped_in_list(self, tmp_path):
        data = {"name": "sid", "value": "abc", "domain": ".medium.com", "path": "/"}
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps(data))
        cookies = load_cookies(str(f))
        assert len(cookies) == 1
        assert cookies[0]["name"] == "sid"

    def test_strips_bom(self, tmp_path):
        data = json.dumps([{"name": "sid", "value": "x", "domain": ".medium.com", "path": "/"}])
        f = tmp_path / "cookies.json"
        f.write_bytes(b"\xef\xbb\xbf" + data.encode("utf-8"))  # UTF-8 BOM
        cookies = load_cookies(str(f))
        assert len(cookies) == 1

    def test_raises_on_invalid_json(self, tmp_path):
        f = tmp_path / "cookies.json"
        f.write_text("[{broken json")
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            load_cookies(str(f))

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_cookies("/nonexistent/path/cookies.json")

    def test_cookie_value_with_equals_sign(self, tmp_path):
        """Values containing '=' (e.g. base64) should be preserved."""
        data = [{"name": "sid", "value": "abc=def==", "domain": ".medium.com", "path": "/"}]
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps(data))
        cookies = load_cookies(str(f))
        assert cookies[0]["value"] == "abc=def=="


class TestLoadCookiesNetscape:

    def test_loads_netscape_format(self, cookies_netscape_file):
        cookies = load_cookies(cookies_netscape_file)
        assert len(cookies) == 2
        names = {c["name"] for c in cookies}
        assert names == {"sid", "uid"}

    def test_skips_comment_lines(self, cookies_netscape_file):
        cookies = load_cookies(cookies_netscape_file)
        assert all(c["name"] != "#" for c in cookies)

    def test_skips_malformed_lines(self, tmp_path):
        f = tmp_path / "cookies.txt"
        f.write_text("only two\tfields\n.medium.com\tTRUE\t/\tTRUE\t0\tsid\tgoodvalue\n")
        cookies = load_cookies(str(f))
        assert len(cookies) == 1
        assert cookies[0]["name"] == "sid"
