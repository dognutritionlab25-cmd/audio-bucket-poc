from urllib.parse import parse_qs, urlparse

import pytest

from app import _s3_client, create_app, generate_audio_url


@pytest.fixture
def calls():
    return []


@pytest.fixture
def client(calls):
    def fake_presign():
        calls.append("presigned")
        return "https://bucket.example/test-audio?short-lived-signature=example", 120

    application = create_app(presign_generator=fake_presign)
    application.config.update(TESTING=True)
    return application.test_client()


def test_allow_generates_presigned_url(client, calls):
    response = client.post("/api/audio-url", headers={"X-PoC-Identity": "allow"})

    assert response.status_code == 200
    assert response.get_json() == {
        "url": "https://bucket.example/test-audio?short-lived-signature=example",
        "expires_in": 120,
    }
    assert calls == ["presigned"]


def test_deny_returns_403_without_presigning(client, calls):
    response = client.post("/api/audio-url", headers={"X-PoC-Identity": "deny"})

    assert response.status_code == 403
    assert response.get_json() == {"error": "not authorized"}
    assert calls == []


def test_unauthenticated_returns_401_without_presigning(client, calls):
    response = client.post("/api/audio-url")

    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}
    assert calls == []


def test_credentials_are_not_embedded_in_page(client, monkeypatch):
    secret_values = {
        "ACCESS_KEY_ID": "test-access-key-id",
        "SECRET_ACCESS_KEY": "test-secret-access-key",
        "BUCKET": "private-bucket-name",
    }
    for name, value in secret_values.items():
        monkeypatch.setenv(name, value)

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert secret_values["ACCESS_KEY_ID"] not in body
    assert secret_values["SECRET_ACCESS_KEY"] not in body
    assert secret_values["BUCKET"] not in body


def test_audio_is_not_proxied_by_flask(client):
    response = client.post("/api/audio-url", headers={"X-PoC-Identity": "allow"})

    assert response.mimetype == "application/json"
    assert "url" in response.get_json()
    assert not response.data.startswith(b"ID3")
    assert not response.data.startswith(b"RIFF")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_health_does_not_require_bucket_credentials(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_boto3_presign_uses_railway_environment_without_network(monkeypatch):
    values = {
        "BUCKET": "audio-test-bucket",
        "ACCESS_KEY_ID": "example-access-key",
        "SECRET_ACCESS_KEY": "example-secret-key",
        "REGION": "auto",
        "ENDPOINT": "https://storage.example.test",
        "TEST_AUDIO_KEY": "folder/test audio.wav",
        "PRESIGNED_URL_TTL_SECONDS": "60",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TEST_AUDIO_RESPONSE_CONTENT_TYPE", raising=False)
    _s3_client.cache_clear()

    url, ttl = generate_audio_url()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert ttl == 60
    assert parsed.scheme == "https"
    assert parsed.netloc == "audio-test-bucket.storage.example.test"
    assert parsed.path == "/folder/test%20audio.wav"
    assert "X-Amz-Signature" in query
    assert values["SECRET_ACCESS_KEY"] not in url
