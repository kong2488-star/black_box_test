# Coarse / Fine 단계별 설정 — 구현 참고

작성: 2026-09-10 · 갱신: 2026-09-10 (Fine 탐침 41건 실측 반영)
근거: `gemini-3.8-agentic-review.md`, `probe_report.md`, `fine_probe_report.md`, google-genai 2.12.1/2.22.0 직접 introspection + httpx 요청 본문 확인
관련: `gemini-3.8-apply-targets.md`(ktc4 계약 영향) · 메모 `daesingo-gemini-api`

> `[실측]` 우리 탐침 · `[SDK]` 설치된 SDK를 직접 확인 · `[문서]` 구글 문서 · `[추정]` 산술 · **`[미측정]`** 아무 근거 없음
> **Fine을 돌렸다** (2026-09-10, 41건). §5의 Fine 숫자는 `[실측]`이다.
> 판정의 정답 여부는 정답지가 없어 사람 확인 대상이다.

---

## 1. 결론 — 단계별 배치

| | Coarse (`SEARCH_COARSE`) | Fine (`VISUAL_VERIFY`) |
|---|---|---|
| 하는 일 | **어디를 볼지 찾기** | **찾은 데를 자세히 보기** |
| 입력 | 긴 영상 (분~시간) | 짧은 클립 (수십 초) |
| 구간을 아는가 | 모른다 → 탐색 필요 | **이미 안다** → 탐색 불필요 |
| `processing` | **`agentic` 실험 대상** (SDK ≥ 2.13 필요, §3-1) | **`static` 유지** |
| `resolution` | `low` | `medium`~`high` |
| 모델 | 싼 쪽 (3.7-flash / flash-lite) | 정확한 쪽 (**3.8-flash**) |
| 최적화 목표 | **원가** | **정확도** (특히 시각) |

**한 줄 이유:** agentic이 하는 일이 "긴 타임라인을 훑어 볼 데를 고르는 것"이고 그게 정확히 Coarse다. Fine은 구간을 이미 아니까 탐색할 게 없고, 문서가 「5분 이하 클립·프레임 단위 정밀 작업은 static이 낫다」고 명시한다 `[문서]`. **시각 정확도가 제품의 급소**라 Fine에서 모델이 건너뛰며 보게 하면 안 된다.

`MOTORCYCLE_HELMET_NON_USE`는 더 분명하다 — 한 장면의 객체 속성이라 타임라인 탐색이 무의미하다.

**단계별로 모델을 다르게 쓰는 건 계약이 이미 허용한다.** `AnalysisRun.implementation.{impl_id, model_ref}`가 Run마다 따로다(mock에도 `gemini-candidate-search@c7` vs `gemini-visual-verify@f3`). 계약 개정 불필요.

---

## 2. 호출 형태

```python
from google.genai import interactions as ix

# ---- Coarse: 긴 영상, 모델이 스스로 탐색 ----
ix.VideoContent(
    type="video", uri=file_uri, mime_type="video/mp4",
    resolution="low",
    processing="agentic",              # 또는 {"type": "agentic"}
)

# ---- Coarse: 현행 baseline (비교군) ----
ix.VideoContent(
    type="video", uri=file_uri, mime_type="video/mp4",
    resolution="low",
    processing={"type": "static", "fps": 1.0},
)

# ---- Fine: 짧은 구간, 프레임 정밀 ----
ix.VideoContent(
    type="video", uri=file_uri, mime_type="video/mp4",
    resolution="high",
    processing={"type": "static", "fps": 2.0,
                "start_offset": "37.000s", "end_offset": "57.000s"},  # ★ 문자열
)
```

**업로드 재사용 설계는 안 깨진다.** Fine이 static으로 `start_offset`/`end_offset`을 계속 쓰므로 memo ③의 「1회 업로드 → offset만 바꿔 N회 질의」가 그대로 성립한다. Coarse 1 + Fine K가 하나의 `RemoteCopy`를 공유하는 구조도 유지된다.

---

## 3. ★ SDK 함정 (구현 전에 반드시 읽을 것)

### 3-1. `google-genai < 2.13` 은 `processing` 을 **요청 본문에서 빼버린다** `[실측 정정]`

> **2026-09-10 정정.** 이 절은 처음에 「`extra: allow` 라서 통과한다 ✅」로 적혀 있었다. **틀렸다.**
> `model_dump()` 에는 남지만 **실제 전송 body 에는 없다.** 아래가 실측이다.

**2.12.1** — `VideoContent.model_fields = {data, mime_type, resolution, type, uri}`. `processing` 이 없고 `extra: allow` 다. 그런데 httpx 요청을 가로채 보면:

```json
// 보낸 것: resolution="high", processing={"type":"static","fps":2.0,
//          "start_offset":33000, "end_offset":41000}
// 실제 body:
{ "mime_type": "video/mp4", "resolution": "high", "type": "video", "uri": "files/..." }
```

**`processing` 이 사라진다. 에러도 경고도 없다.** 결과가 셋이다.

1. **`coarse_probe.py` 의 `fps=1.0` 은 한 번도 전송된 적이 없다.** 실측 91.5 tok/영상초는 서버 기본값(1fps)과 우연히 일치한 것이다.
2. **`processing="agentic"` 을 이 버전으로는 켤 수 없다.** agentic 실험은 SDK 업그레이드가 선행 조건이다.
3. 구간 지정이 무시되므로 짧은 구간을 요청해도 클립 전체가 처리된다 — **실측: 8초 구간을 요청했는데 입력 89,366 tok = 클립 304초 전체.** 후보당 원가가 15배가 된다.

**2.22.0** — `processing` 을 **선언하고 검증한다**. 조용히 버리지 않고 거부한다. 두 형태 모두 body 에 실린다.

```python
processing={"type": "static", "fps": 2.0,
            "start_offset": "33.000s", "end_offset": "41.000s"}   # ← 문자열
processing="agentic"
```

**★ `start_offset`/`end_offset` 은 정수 ms 가 아니라 duration 문자열이다.** 구글 문서는 "In milliseconds" 로 적어 놓았지만 SDK 타입은 `Optional[str]` 이고, 2.22.0 에 정수를 넣으면 pydantic 이 거부한다. `StaticMediaProcessing = {type: Literal['static'], fps: float|None, start_offset: str|None, end_offset: str|None}`.

**결론: `google-genai >= 2.13` 을 요구하고 버전을 기록에 남길 것.** `fine_probe.py` 는 `check_sdk()` 로 낮은 버전을 막고 각 row 에 `sdk_version` 을 적는다.

→ 그래도 **§6의 검증 규칙은 필요하다.** 버전이 맞아도 값이 맞는지는 토큰 수로만 확인된다.

### 3-2. raw dict로 `input`을 넘기면 필드가 사라진다 (기존 함정)

`InteractionsInput = Union[Content, List[Step], List[Content], str]`인데 dict 리스트를 주면 pydantic이 `List[Step]`을 먼저 매칭해 **`UnknownStep`으로 삼키고** `resolution`·`processing`·`text`가 전부 사라진다. 검증은 통과하므로 조용히 잘못된 본문이 나간다. **반드시 `ix.VideoContent(...)`/`ix.TextContent(...)` 객체로.**

### 3-3. 모델 문자열은 SDK가 막지 않는다

현재 venv는 **2.22.0**이다(2026-09-10에 2.12.1에서 올렸다 — §3-1이 이유다). `Interaction.model`의 Literal 목록에 `3.7`·`3.8`이 없지만 union에 `UnrecognizedStr`이 있어 **모델 문자열은 자유롭게 통과한다** `[SDK]`. 구현 시작 시 버전을 한 번 못박고 기록할 것.

---

## 4. `usage`에서 읽어야 하는 것

`Interaction.usage`(`Usage` 타입)의 실제 필드 `[SDK]`. `fine_probe.py`는 전부 읽는다. **`coarse_probe.py`는 아직 2개만 읽는다 — 역이식 대상이다.**

| 필드 | 왜 필요한가 |
|---|---|
| `total_input_tokens` | 현재 읽고 있다 |
| `total_output_tokens` | 현재 읽고 있다 |
| **`total_thought_tokens`** | **★ agentic 탐색 비용이 여기 잡힌다. 이게 없으면 static vs agentic 비교가 불가능하다** |
| `total_tokens` | **`in + out + thought` 다** `[실측]`. 즉 `total ≠ in + out` 이고 `UsageRecord` §8-4 불변조건은 실제로 깨진다 |
| `total_cached_tokens` | 캐시 적용 시 원가 계산에 필요 |
| `input_tokens_by_modality` | **프레임 토큰과 프롬프트 토큰을 분리해준다** — 원가의 89%가 어디인지 확정 가능 |
| `tool_use_tokens_by_modality` | agentic 탐색이 tool use로 잡힐 가능성 |

`total_thought_tokens`가 **SDK에 있고 실제로 값이 온다** — 41/41 호출이 보고했고 합계 32,420 tok이다. `gemini-3.8-apply-targets.md` A-1(UsageRecord 계약에 thought 자리가 없다)이 가설이 아니라 실측이라는 근거다.

**주의:** `coarse_probe.py`는 `getattr(um, "total_input_tokens", None) or 0` 형태로 읽는다. 값이 `None`이면 **조용히 0**이 되어 원가가 0으로 보고된다. 구현 코드에서는 `None`과 `0`을 구분할 것(계약도 「0은 안 썼다, null은 개념이 없다」로 구분한다).

---

## 5. 원가 모델

### 상수

```python
# 2026-12-31까지 유효. 2027-01-01부터 3.x flash만 2배.
PRICING = {                        # (input, output) USD per 1M tokens
    "gemini-3.8-flash":      (0.75, 3.75),   # 2027-01-01 -> (1.50, 7.50)
    "gemini-3.7-flash":      (0.75, 3.75),   # 2027-01-01 -> (1.50, 7.50)
    "gemini-3.5-flash-lite": (0.30, 2.50),   # 인상 없음
    "gemini-3.1-flash-lite": (0.25, 1.50),   # 인상 없음
}
TOK_PER_VIDEO_SEC = {            # 전부 [실측] (video modality 토큰 기준)
    "low@1fps":  91.5,           # Coarse
    "high@2fps": 553.0,          # Fine. 문서의 "high 300"은 1fps 기준이다
}
MIN_SDK = (2, 13, 0)             # 이하에서는 processing 이 전송되지 않는다 (§3-1)
```

**단가를 코드에 박을 때 `pricing_id`를 같이 남길 것.** 계약(`contract-usage-record.md` §5)이 「row에 단가를 복제하면 원천이 둘이 된다」고 금지한다 — 단가표는 `common/runtime` config가 소유하고 기록에는 id만 남긴다. 2027-01-01은 **새 `pricing_id`**로 처리된다(계약이 이미 그 메커니즘을 가지고 있다).

### 단계별 원가

**Coarse — 길어서 비싸다** `[실측]`

| 모델 | source-hour 원가 | 2027 이후 |
|---|---|---|
| 3.7 / 3.8-flash | **$0.277** | **$0.554** |
| 3.5-flash-lite | $0.119 | $0.119 |
| 3.1-flash-lite | $0.094 | $0.094 |

입력 토큰이 **원가의 89%**다. 프롬프트·스키마 최적화는 남은 11%를 건드리는 일이다.

**Fine — 짧지만 싸지 않다** `[실측: 2026-09-10, tag run1, 후보 41건]`

| 항목 | 값 |
|---|---|
| 설정 | 3.7-flash · high · fps 2.0 · padding ±2s · 후보당 1호출 |
| 구간 길이 | 8~13초 (평균 9.8초) |
| 후보 1건 | 입력 6,981 tok · 출력 456 · thought 791 → **$0.0099** |
| 40분 원본 | 입력 286,211 · 출력 18,709 · thought 32,420 → **$0.4064** |
| source-hour | **$0.610** (2027 이후 $1.220) |
| 지연 | 후보당 중앙값 10.9초 / 최대 18.4초 |
| Fine exposure | 406초 / 2,348초 = **17.3%** |
| video 토큰 | **553 tok/구간초** (high 2fps 기대 548과 일치 — 설정이 실제로 전송됐다는 증거) |

### ⚠ Fine이 Coarse보다 비싸다 — 실측 220%

| | source-hour 원가 | 2027 이후 |
|---|---|---|
| Coarse (low, 1fps) | $0.277 | $0.554 |
| **Fine (high, 2fps)** | **$0.610** | **$1.220** |
| 합계 | **$0.887** | **$1.774** |

**Fine / Coarse = 220%.**

> **정정 이력.** 이 절은 두 번 틀렸다. 처음 「155%」는 20초 클립 가정이었고, 다음 「79~133%」는 span을 실측(중앙값 6초)으로 바꿨지만 세 가지를 빠뜨렸다 — **fps 2.0이 video를 553 tok/초로 올린다**(300 가정), **프롬프트가 입력의 22%**(후보당 1,511 tok × 41회 = 61,968), **thought 32,420 tok이 출력 단가로 청구된다**. 추정을 실측으로 갈아 끼울 때 한 변수만 바꾸면 이렇게 된다.

**줄일 수 있는 것 (아직 안 재봤다):**

- `fps 2.0 → 1.0` — video 토큰이 절반(553 → ~290). Fine 원가가 대략 −35%
- 프롬프트 단축 — 입력의 22%다. 후보당 1호출이라 매번 재청구된다
- `resolution high → medium` — 실선/점선 판별이 화질에 직접 걸리므로 품질과 맞바꾼다

**후보 개수가 여전히 Fine 원가를 지배한다.** 41건 × $0.0099다. Coarse 프롬프트가 의도적으로 「Recall을 Precision보다 우선」하라고 지시하므로 **설계상 Fine에 청구서를 넘기는 구조**다. eval 원가 구성식에 `Fine exposure`가 따로 있는 이유가 여기다. 어디서 자를지는 **제품 판단**(사용자가 후보 카드 몇 개를 보게 할 것인가)이지 최적화 문제가 아니다.

단 이건 버그가 아니다. Coarse 프롬프트가 의도적으로 「Recall을 Precision보다 우선」하라고 지시하고 있으므로 **설계상 Fine에 청구서를 넘기는 구조**다. eval 원가 구성식에 `Fine exposure`가 따로 있는 이유가 여기다. 어디서 자를지는 **제품 판단**(사용자가 후보 카드 몇 개를 보게 할 것인가)이지 최적화 문제가 아니다.

---

## 6. 검증 규칙 — agentic이 실제로 켜졌는지 확인하는 법

§3-1 때문에 **플래그를 믿을 수 없다.** 같은 클립을 두 모드로 돌려 usage를 비교한다.

| 신호 | static | agentic (켜졌다면) |
|---|---|---|
| `total_input_tokens` | ≈ 91.5 × 영상초 | **크게 낮다** (문서 주장 최대 −88%) |
| `total_thought_tokens` | 작거나 0 | **뚜렷하게 존재** |
| `steps`에 `ThoughtStep` | 거의 없음 | 여러 개 |

**입력 토큰이 `91.5 × 영상초` 그대로면 agentic이 안 켜진 것이다.** 이걸 자동 검사로 만들어두면 오타 한 글자에 실험 하루를 날리지 않는다.

---

## 7. 계약 필드 매핑 (구현 시 어디에 넣는가)

| 구현 값 | 들어갈 자리 | 비고 |
|---|---|---|
| 모델 문자열 | `AnalysisRun.implementation.model_ref` | 값만 바뀐다. 계약 개정 없음 |
| `processing` 모드, `fps`, `resolution`, 클립 길이 | **`implementation.config_version`** | 계약 L155가 「FPS/chunk 등 설정값을 공용 Contract에 직접 노출하지 않는다」 → **개정 불필요.** 단 mode가 `config_version` 값에 **드러나야** A/B가 식별된다(L329) |
| 프롬프트 버전 | `implementation.prompt_version` | 본문은 넣지 않는다 |
| `total_input_tokens` / `total_output_tokens` | `UsageRecord.token_usage` | 3필드로 닫혀 있다 |
| **`total_thought_tokens`** | **자리가 없다** | **계약 개정 필요.** `gemini-3.8-apply-targets.md` A-1 |
| 실제 처리한 영상 길이 | `UsageRecord.processed_duration_sec` | `AnalysisSource.duration_sec`(준비된 전체 길이)와 **다른 값**이다 |
| 단가표 식별자 | `UsageRecord.pricing_context.pricing_id` | 단가 값 자체는 넣지 않는다 |
| 왕복 시간 | `UsageRecord.latency_ms` | eval의 `latency_per_source_video_hour`가 이 값 없이는 안 나온다 |

**`agentic`을 `AnalysisSource.profile_ref`에 넣지 말 것.** profile은 「실행 단계가 아니라 media 특성」을 표현한다(`contract-analysis-source-derived.md` §4.4). agentic은 media 특성이 아니라 호출 방식이다.

---

## 8. 무엇이 닫혔고 무엇이 남았는가

### 2026-09-10 Fine 탐침으로 닫힌 것

1. ~~**Fine을 한 번도 돌리지 않았다.**~~ → **돌렸다.** 41건, §5가 실측이다. `fine_probe_report.md` tag `run1`.
2. ~~**`total_tokens`가 thought를 포함하는가**~~ → **포함한다.** 실측 337,340 = 입력 304,920 + thought 32,420. 즉 **`total ≠ in + out`** 이고 `UsageRecord` 계약 §8-4 불변조건은 **실제로 깨진다.** `gemini-3.8-apply-targets.md` A-1이 가설이 아니라는 증거다.
3. **모델이 말하는 시간의 기준** → **요청 구간의 시작이 0이다.** 41/41이 구간 안에 들어왔다. 계약의 `at_offset_ms` 정의와 같다.
4. **`processing` 전송 여부** → §3-1. `google-genai >= 2.13` 필요, offset은 문자열.

### 남은 것 (`[미측정]`)

1. **agentic의 실제 토큰 구성** — thought token이 얼마나 붙는지. 문서의 「토큰 −88% / 비용 −66%」 차이를 검산하면 **입력 절감분의 일부가 출력 단가(입력의 5배)로 되돌아오는 거래**다. 우리 워크로드에서 탐색이 그 예산을 넘으면 절감폭이 줄거나 역전된다. **SDK 업그레이드가 선행 조건이었고 이제 해소됐다**(2.22.0).
2. **agentic의 timestamp 정확도** — 비용이 싸도 시각이 틀리면 제품이 안 된다. Coarse에서 agentic을 채택할지의 **결정 기준은 원가가 아니라 이쪽**이다.
3. **3.8의 토큰 증가폭** — 우리 워크로드에서. 문서는 long-horizon SWE 기준으로 말하고 우리 작업은 그게 아니다.
4. **flash-lite의 후보 품질** — 원가는 2.3~2.9배 싸지만(2027년 4.7~5.9배) 품질 미측정. `gemini-3.5-flash-lite`도 agentic을 지원하므로 **가장 싼 선택지와 agentic이 겹친다** `[문서]`.
5. **Fine 판정의 정답 여부** — 41건 중 40건이 `NOT_OBSERVED`다. 점선 차로변경 기각이라면 맞는 것이고 그건 **Coarse precision의 측정치**다. 사람이 원본을 열어 확인해야 갈린다.
6. **`fps 1.0`으로 낮췄을 때의 품질** — 원가는 −35%로 계산되지만 실선/점선 판별이 유지되는지 미측정.

**실험은 변수를 섞지 말 것.** 모델 교체와 mode 변경을 같이 바꾸면 원인을 못 가른다.

### Fine 탐침이 덤으로 찾은 것 (별건)

- **Coarse 후보 4건이 클립 길이 밖의 시각을 말했다.** `part_07`(298.97초)에서 345·414·444·453초. 그 클립 후보 11건 중 4건이다. **Coarse timestamp 실패의 실측치**이고 Fine이 볼 영상이 없으므로 `SPAN_OUT_OF_CLIP`으로 건너뛴다.
- **클립 길이가 300초가 아니다.** 실측 304.30 / 298.97×5 / 304.30 / 244.50. `ffmpeg -c copy`는 키프레임 경계에서 자른다. **`coarse_probe.py`의 원본 위치 환산(`clip_ordinal × 300`)이 최대 4.47초 어긋난다**(part_07). span이 4~9초인데 환산 오차가 span 길이와 맞먹는다. `fine_probe.py`는 ffprobe로 실측 누적을 쓴다.
- **`temporal_facts[].fact`가 코드가 아니라 산문으로 나왔다.** 34종 / 34회, 재사용 0. 반대로 `primitives[].kind`는 9종 / 127회로 **코드로 수렴했다**(`WHITE_SOLID_LINE`×40 등). 차이는 프롬프트가 primitive 예시만 줬다는 것이다 — 계약이 Pending으로 둔 vocabulary registry를 채우려면 `fact` 쪽에도 코드 예시가 필요하다.

---

## 9. 하지 말 것

| | 근거 |
|---|---|
| Fine에 `agentic` 쓰기 | 구간을 이미 아는데 탐색 토큰만 낸다. 문서도 5분 이하·프레임 정밀은 static |
| Fine을 `low`로 아끼기 | 후보 1건 $0.0064다. 아껴서 얻는 게 없고 시각 정확도를 잃는다 |
| Coarse를 `high`로 올리기 | 원가가 3배 된다. 원가의 89%가 입력 토큰인 쪽이다 |
| 3.8 전환과 agentic을 같이 켜기 | 원인 분리 불가 |
| `profile_ref`에 mode 넣기 | profile은 media 특성 |
| `Observation.source.kind`에 모델명 | `contract-observation.md` L177이 `search.gemini_3_7_coarse ❌`로 금지 |
| 문서·row에 단가 값 복제 | `contract-usage-record.md` §5 |

## 10. 착수 순서

1. **Fine 탐침** — 후보 하나를 실제로 검증해 본다. §5 Fine 숫자를 실측으로 바꾼다. 이게 없으면 「Fine이 Coarse보다 비싸다」도 산수일 뿐이다.
2. **`usage` 필드 확장** — `total_thought_tokens` 외 4개를 기록에 추가(§4). 2·3번의 전제다.
3. **Coarse static vs agentic** — 3.7 고정. §6 검증 규칙을 먼저 넣는다.
4. **모델 비교** — mode 고정 후 3.7 / 3.8 / 3.5-flash-lite.
