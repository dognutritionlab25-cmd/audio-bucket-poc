import os
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, render_template_string, request


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Railway Audio Bucket PoC</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 680px; margin: 40px auto; padding: 0 18px; line-height: 1.55; }
    button { margin: 0 8px 12px 0; padding: 10px 14px; cursor: pointer; }
    audio { display: block; width: 100%; margin-top: 20px; }
    #result { min-height: 1.6em; padding: 10px 0; white-space: pre-wrap; }
    .note { color: #555; font-size: 0.92rem; }
  </style>
</head>
<body>
  <h1>Railway Audio Bucket PoC</h1>
  <p>Flask는 권한 확인과 임시 URL 발급만 담당합니다. 오디오 파일은 Bucket에서 브라우저로 직접 전달됩니다.</p>

  <button type="button" data-identity="allow">Allow 재생 테스트</button>
  <button type="button" data-identity="deny">Deny 403 테스트</button>
  <button type="button" data-identity="">미인증 401 테스트</button>

  <div id="result" role="status" aria-live="polite"></div>
  <audio id="player" controls preload="metadata"></audio>
  <p class="note">Range/seek는 Chrome DevTools의 Network 탭에서 Bucket 요청을 선택해 확인하세요.</p>

  <script>
    const result = document.getElementById("result");
    const player = document.getElementById("player");

    async function runTest(identity) {
      player.pause();
      player.removeAttribute("src");
      player.load();
      result.textContent = "요청 중...";

      const headers = {};
      if (identity) headers["X-PoC-Identity"] = identity;

      try {
        const response = await fetch("/api/audio-url", { method: "POST", headers });
        const data = await response.json();
        if (!response.ok) {
          result.textContent = `HTTP ${response.status}: ${data.error || "request failed"}`;
          return;
        }

        player.src = data.url;
        player.load();
        result.textContent = `임시 재생 URL 발급 성공 (유효시간 ${data.expires_in}초)`;
      } catch (error) {
        result.textContent = "요청 실패: 네트워크 또는 서버 상태를 확인하세요.";
      }
    }

    document.querySelectorAll("button[data-identity]").forEach((button) => {
      button.addEventListener("click", () => runTest(button.dataset.identity));
    });
  </script>
</body>
</html>
"""


REQUIRED_BUCKET_ENV = (
    "S3_BUCKET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "AWS_ENDPOINT_URL",
    "TEST_AUDIO_KEY",
)


def _positive_ttl() -> int:
    raw_value = os.environ.get("PRESIGNED_URL_TTL_SECONDS", "120")
    try:
        ttl = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("PRESIGNED_URL_TTL_SECONDS must be an integer") from exc
    if ttl < 1:
        raise RuntimeError("PRESIGNED_URL_TTL_SECONDS must be greater than zero")
    return ttl


def _settings() -> dict:
    missing = [name for name in REQUIRED_BUCKET_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

    response_content_type = os.environ.get("TEST_AUDIO_RESPONSE_CONTENT_TYPE", "").strip()
    if response_content_type and (
        not response_content_type.lower().startswith("audio/")
        or "\r" in response_content_type
        or "\n" in response_content_type
    ):
        raise RuntimeError("TEST_AUDIO_RESPONSE_CONTENT_TYPE must be a valid audio/* media type")

    return {
        "bucket": os.environ["S3_BUCKET"].strip(),
        "access_key_id": os.environ["AWS_ACCESS_KEY_ID"].strip(),
        "secret_access_key": os.environ["AWS_SECRET_ACCESS_KEY"].strip(),
        "region": os.environ["AWS_DEFAULT_REGION"].strip(),
        "endpoint": os.environ["AWS_ENDPOINT_URL"].strip().rstrip("/"),
        "object_key": os.environ["TEST_AUDIO_KEY"].strip(),
        "ttl": _positive_ttl(),
        "response_content_type": response_content_type,
    }


@lru_cache(maxsize=1)
def _s3_client(endpoint: str, region: str, access_key_id: str, secret_access_key: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def generate_audio_url() -> tuple[str, int]:
    settings = _settings()
    client = _s3_client(
        settings["endpoint"],
        settings["region"],
        settings["access_key_id"],
        settings["secret_access_key"],
    )
    params = {"Bucket": settings["bucket"], "Key": settings["object_key"]}

    # By default S3 returns the object's stored Content-Type metadata.
    # This optional override is useful only if the uploaded object's metadata is wrong.
    if settings["response_content_type"]:
        params["ResponseContentType"] = settings["response_content_type"]

    url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=settings["ttl"],
        HttpMethod="GET",
    )
    return url, settings["ttl"]


def create_app(presign_generator=None):
    flask_app = Flask(__name__)
    flask_app.config["PRESIGN_GENERATOR"] = presign_generator or generate_audio_url

    @flask_app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @flask_app.get("/")
    def index():
        return render_template_string(INDEX_HTML)

    @flask_app.get("/health")
    def health():
        return jsonify(status="ok")

    @flask_app.post("/api/audio-url")
    def audio_url():
        identity = request.headers.get("X-PoC-Identity", "").strip().lower()
        if not identity:
            return jsonify(error="authentication required"), 401
        if identity != "allow":
            return jsonify(error="not authorized"), 403

        try:
            url, ttl = flask_app.config["PRESIGN_GENERATOR"]()
        except RuntimeError as exc:
            flask_app.logger.error("PoC configuration error: %s", exc)
            return jsonify(error="service not configured"), 503
        except (BotoCoreError, ClientError, ValueError):
            # Do not log the generated URL, raw token, or bucket credentials.
            flask_app.logger.error("Presigned URL generation failed")
            return jsonify(error="could not create playback URL"), 502

        return jsonify(url=url, expires_in=ttl)

    return flask_app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
