from services.live_dashboard.redaction import REDACTED, redact


def test_redact_recursively_replaces_sensitive_mapping_values_without_mutation():
    payload = {
        "api_key": "sk-secret-value",
        "nested": {
            "Authorization": "Bearer top-secret",
            "safe": "visible",
            "items": [{"password": "hunter2"}],
        },
    }

    result = redact(payload)

    assert result == {
        "api_key": REDACTED,
        "nested": {
            "Authorization": REDACTED,
            "safe": "visible",
            "items": [{"password": REDACTED}],
        },
    }
    assert payload["nested"]["Authorization"] == "Bearer top-secret"


def test_redact_scrubs_secrets_embedded_in_strings():
    payload = {
        "url": "https://alice:p%40ss@example.test/run?token=query-secret&view=full",
        "header": "Authorization: Bearer header-secret",
        "inline": "api_key=sk-inline-secret",
        "pem": (
            "before\n-----BEGIN PRIVATE KEY-----\nprivate-material\n"
            "-----END PRIVATE KEY-----\nafter"
        ),
    }

    result = redact(payload)
    rendered = repr(result)

    assert "alice" not in rendered
    assert "query-secret" not in rendered
    assert "header-secret" not in rendered
    assert "sk-inline-secret" not in rendered
    assert "private-material" not in rendered
    assert result["url"].endswith("view=full")
    assert result["pem"] == f"before\n{REDACTED}\nafter"


def test_redact_scrubs_quoted_multiword_inline_secrets():
    payload = {
        "double": 'password="correct horse battery staple"; mode=safe',
        "single": "api_key='alpha beta gamma delta'; mode=safe",
    }

    result = redact(payload)

    assert result == {
        "double": f'password="{REDACTED}"; mode=safe',
        "single": f"api_key='{REDACTED}'; mode=safe",
    }


def test_redact_scrubs_multiline_and_escaped_quote_secrets_completely():
    payload = {
        "double": 'password="line one\\"quoted\\"\nline two"; mode=safe',
        "single": "token='line one\\'quoted\\'\nline two'; mode=safe",
    }

    result = redact(payload)

    assert result == {
        "double": f'password="{REDACTED}"; mode=safe',
        "single": f"token='{REDACTED}'; mode=safe",
    }
    assert "line one" not in repr(result)
    assert "line two" not in repr(result)


def test_redact_scrubs_generic_long_high_entropy_credentials():
    credential = "Q7mZ2xP9vK4nR8tW3cY6uJ1hD5sF0aB7eL2iN9oC"

    result = redact({"log": f"upload session {credential} completed"})

    assert result == {"log": f"upload session {REDACTED} completed"}


def test_redact_recognizes_common_credential_key_names():
    payload = {
        "private_key": "private",
        "aws_access_key_id": "access",
        "client_secret": "client",
        "session_token": "session",
        "proxy-authorization": "Basic abc",
        "set-cookie": "session=abc",
        "x-api-key": "key",
    }

    assert redact(payload) == {key: REDACTED for key in payload}
