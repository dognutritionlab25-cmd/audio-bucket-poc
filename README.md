# Railway Audio Bucket PoC

Private Railway Bucket의 오디오를 Flask가 proxy하지 않고 브라우저가 직접 재생할 수 있는지 확인하는 최소 Proof of Concept입니다.

흐름:

1. 브라우저가 Flask에 임시 재생 URL을 요청합니다.
2. Flask가 가짜 authentication/authorization을 확인합니다.
3. 허용된 요청에만 짧게 만료되는 S3 presigned GET URL을 생성합니다.
4. 브라우저의 HTML5 `<audio>`가 Railway Bucket에서 파일을 직접 받습니다.

이 저장소는 Production Quiz App, Production DB, 실제 subscriber 또는 Magic Link를 사용하지 않습니다.

## 파일

- `app.py`: 테스트 UI, 가짜 인증/권한 검사, presigned URL 발급
- `requirements.txt`: Flask, boto3, gunicorn, pytest
- `Procfile`: Railway에서 gunicorn으로 실행
- `tests/test_app.py`: allow/deny/미인증/비노출/비proxy 테스트
- `pytest.ini`: PoC 테스트 디렉터리와 import 경로를 고정
- `.gitignore`: 로컬 환경과 secret 파일 제외

## Railway 환경변수

Bucket의 **Credentials → Add to Service → supportive-clarity**로 아래 값을 연결합니다.

| 변수 | 필수 | 의미 |
| --- | --- | --- |
| `S3_BUCKET` | 예 | S3 API에 사용하는 실제 Bucket 이름 |
| `AWS_ACCESS_KEY_ID` | 예 | Railway Bucket access key ID |
| `AWS_SECRET_ACCESS_KEY` | 예 | Railway Bucket secret key |
| `AWS_DEFAULT_REGION` | 예 | Bucket S3 region |
| `AWS_ENDPOINT_URL` | 예 | Railway S3-compatible endpoint |
| `TEST_AUDIO_KEY` | 예 | Bucket에 업로드한 오디오의 정확한 object key |
| `PRESIGNED_URL_TTL_SECONDS` | 아니요 | URL 유효시간. 기본값 `120` |
| `TEST_AUDIO_RESPONSE_CONTENT_TYPE` | 아니요 | 업로드 metadata가 잘못된 경우에만 `audio/mpeg`, `audio/wav` 등으로 덮어쓰기 |

Railway의 **Flask Style**이 생성한 위 변수명을 그대로 사용합니다. `AWS_ACCESS_KEY_ID`와 `AWS_SECRET_ACCESS_KEY`는 GitHub, HTML 또는 JavaScript에 입력하지 마세요.

기본 동작은 object에 저장된 `Content-Type` metadata를 그대로 사용합니다. 브라우저가 형식을 인식하지 못할 때만 `TEST_AUDIO_RESPONSE_CONTENT_TYPE`을 설정하세요. 값은 `audio/*`만 허용됩니다.

## 배포 순서

1. GitHub에서 빈 repository `audio-bucket-poc`을 만듭니다.
2. 이 폴더 안의 파일과 `tests` 폴더를 repository 최상위에 업로드합니다.
3. Railway의 `innovative-learning` Project를 엽니다.
4. `supportive-clarity` Service에서 **Connect Repo**를 눌러 `audio-bucket-poc`을 연결합니다.
5. `audioletter-test` Bucket을 엽니다.
6. **Credentials → Add to Service → supportive-clarity**를 선택합니다.
7. `supportive-clarity` Variables에서 `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `AWS_ENDPOINT_URL`이 연결되었는지 확인합니다. 값 자체를 복사해 GitHub에 넣지 않습니다.
8. `TEST_AUDIO_KEY`에 업로드한 파일의 정확한 object key를 입력합니다. 폴더가 있다면 `folder/file.wav`처럼 전체 key를 사용합니다.
9. `PRESIGNED_URL_TTL_SECONDS=120`을 설정합니다.
10. 필요하면 `TEST_AUDIO_RESPONSE_CONTENT_TYPE`을 `audio/mpeg` 또는 `audio/wav`로 설정합니다. 먼저 설정하지 않고 object metadata 그대로 테스트하는 것을 권장합니다.
11. `supportive-clarity`에 Public Domain이 없다면 **Settings → Networking → Generate Domain**으로 생성합니다.
12. Deploy가 성공하고 `/health`가 `{"status":"ok"}`를 반환하는지 확인합니다.
13. Public Domain의 `/`에 접속합니다.

Railway가 Start Command를 별도로 요구하면 다음을 입력합니다.

```text
gunicorn --bind 0.0.0.0:$PORT app:app
```

## 브라우저 테스트

### 1. Allow 재생

1. **Allow 재생 테스트**를 누릅니다.
2. “임시 재생 URL 발급 성공”이 표시되는지 확인합니다.
3. Player에서 재생합니다.
4. DevTools → Network에서 요청 대상이 Flask domain이 아니라 Railway Bucket endpoint인지 확인합니다.

### 2. Deny 403

**Deny 403 테스트**를 누릅니다. 화면에 `HTTP 403`이 표시되고 audio source가 설정되지 않아야 합니다.

명령행에서는:

```bash
curl -i -X POST "https://YOUR-DOMAIN/api/audio-url" \
  -H "X-PoC-Identity: deny"
```

### 3. 미인증 401

**미인증 401 테스트**를 누릅니다. 화면에 `HTTP 401`이 표시되어야 합니다.

```bash
curl -i -X POST "https://YOUR-DOMAIN/api/audio-url"
```

### 4. Range/seek

Allow 요청 후 DevTools → Network에서 Bucket 요청을 선택합니다.

확인할 항목:

- Request Headers의 `Range: bytes=...`
- HTTP `206 Partial Content` 여부
- Response Headers의 `Content-Range`
- Response Headers의 `Accept-Ranges`
- Player에서 앞뒤로 이동했을 때 정상 재생되는지

DevTools에서 임시 URL을 복사한 뒤 다음처럼 별도 확인할 수도 있습니다.

```bash
curl -sS -D - -o /dev/null \
  -H "Range: bytes=0-1023" \
  "PRESIGNED_URL"
```

기대 결과는 일반적으로 `206 Partial Content`와 `Content-Range: bytes 0-1023/...`입니다. Railway의 실제 결과를 기록하세요.

### 5. URL expiration

1. Allow 요청으로 URL을 하나 발급합니다.
2. DevTools에서 presigned URL을 복사합니다.
3. 즉시 요청해 성공하는지 확인합니다.
4. `PRESIGNED_URL_TTL_SECONDS`보다 충분히 오래 기다립니다.
5. 브라우저 cache 영향을 피하기 위해 새 시크릿 창 또는 `curl`로 **동일한 URL**을 다시 요청합니다.
6. 만료된 URL이 거부되는지 확인합니다.
7. 재생 도중 URL이 만료된 뒤 pause/resume 및 seek가 어떻게 동작하는지도 기록합니다.

### 6. 모바일

- Android Chrome: 재생, 일시정지, seek
- iPhone/iPad Safari: 재생, 일시정지, seek
- 모바일 네트워크와 Wi-Fi에서 각각 확인 권장

## 테스트 결과 체크리스트

- [ ] `/health` 성공
- [ ] Allow 요청이 presigned URL을 반환
- [ ] 오디오가 Bucket에서 직접 재생됨
- [ ] Flask 응답이 오디오 bytes를 전달하지 않음
- [ ] Deny 요청이 403
- [ ] 미인증 요청이 401
- [ ] Bucket request가 200 또는 206으로 성공
- [ ] Range request 확인
- [ ] `Content-Range` 확인
- [ ] `Accept-Ranges` 확인
- [ ] 앞/뒤 seek 성공
- [ ] URL 만료 후 동일 URL 재사용 실패
- [ ] 만료 시점 전후 pause/resume 동작 기록
- [ ] Android Chrome 재생/seek 성공
- [ ] iOS Safari 재생/seek 성공
- [ ] GitHub와 브라우저 HTML에 secret key가 없음

## 로컬 자동 테스트

실제 Bucket에 연결하지 않고 authorization과 응답 구조를 확인합니다.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

자동 테스트는 실제 Railway 재생, Range, URL expiration 또는 모바일 브라우저 동작을 검증하지 않습니다.

## 보안상 알아둘 점

- `X-PoC-Identity`는 PoC 전용 가짜 인증입니다. Production 인증으로 사용하면 안 됩니다.
- presigned URL은 만료 전까지 그 URL을 가진 사람이 사용할 수 있습니다.
- 브라우저 개발자도구에서 presigned URL을 보는 것은 정상입니다.
- secret access key는 browser에 전달되지 않습니다.
- 이 앱은 `get_object` presign만 수행하며 Bucket 객체를 다운로드하지 않습니다.

## 공식 문서

- Railway Storage Buckets: https://docs.railway.com/storage-buckets
- Railway Uploading & Serving Files: https://docs.railway.com/storage-buckets/uploading-serving
- boto3 `generate_presigned_url`: https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_url.html
