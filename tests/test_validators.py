from app.utils.validators import is_safe_url, is_valid_url


class TestIsValidUrl:
    def test_http_and_https_are_valid_shapes(self):
        assert is_valid_url("http://example.com")
        assert is_valid_url("https://example.com/path")

    def test_missing_scheme_is_invalid(self):
        assert not is_valid_url("example.com")

    def test_non_http_scheme_is_invalid(self):
        assert not is_valid_url("ftp://example.com")
        assert not is_valid_url("file:///etc/passwd")

    def test_empty_and_none(self):
        assert not is_valid_url("")
        assert not is_valid_url(None)


class TestIsSafeUrl:
    def test_public_domain_is_safe(self):
        # example.com is the IANA-reserved documentation domain and
        # resolves to a public IP.
        assert is_safe_url("https://example.com/about") is True

    def test_localhost_is_blocked(self):
        assert is_safe_url("http://localhost/") is False
        assert is_safe_url("http://localhost:8080/admin") is False

    def test_loopback_ip_is_blocked(self):
        assert is_safe_url("http://127.0.0.1/") is False

    def test_private_ranges_are_blocked(self):
        assert is_safe_url("http://10.0.0.5/") is False
        assert is_safe_url("http://192.168.1.1/") is False
        assert is_safe_url("http://172.16.0.1/") is False

    def test_link_local_metadata_ip_is_blocked(self):
        # Cloud-metadata endpoint pattern (AWS/GCP/Azure all use link-local).
        assert is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_non_http_scheme_is_unsafe(self):
        assert is_safe_url("file:///etc/passwd") is False

    def test_garbage_input_is_unsafe(self):
        assert is_safe_url("") is False
        assert is_safe_url("not a url at all") is False
