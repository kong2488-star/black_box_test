# Gemini 변경사항 최종 적용안

작성: 2026-09-12  
적용 대상: Coarse / Fine 기반 블랙박스 영상 검색 파이프라인  
범위: 이번 Gemini 3.8 Flash, agentic video understanding, Interactions API·SDK·usage·가격 변경 중 프로젝트에 직접 적용할 내용

> 이 문서는 Gemini의 전체 신기능 소개가 아니다. 현재 프로젝트의 영상 후보 탐색, 정밀 검증,
> 비용 계측, 계약 기록에 직접 영향을 주는 항목만 남긴 최종 적용 문서다.
> 현재 실측 결과는 [Coarse / Fine 영상 탐침 실험 총정리](./coarse-fine-experiment-summary.md)를 기준으로 한다.

---

## 1. 최종 결론

현재 운영 기준은 다음과 같이 유지한다.

| 항목 | 최종 판단 | 이유 |
|---|---|---|
| Fine processing | **static 유지** | 짧은 구간과 프레임 정밀 판정에는 static이 적합하고, 실선/점선·신호 상태를 정확히 봐야 함 |
| Fine 해상도 / fps | **high / 2fps 유지** | 현재 유일하게 설정 전달과 token density가 실측 검증된 정밀 조건 |
| Coarse 모델 | **3.7 Flash 유지 후 실험** | 3.8의 우리 워크로드 토큰 증가폭과 품질이 아직 미측정 |
| Coarse processing | **static baseline과 agentic A/B 실시** | 입력 토큰이 Coarse 비용의 약 89%라 agentic의 절감 가능성이 가장 큼 |
| Gemini 3.8 전환 | **agentic 실험 뒤 별도 A/B** | 모델 변경과 processing 변경을 동시에 하면 효과 원인을 분리할 수 없음 |
| Flash-Lite | **후속 비용 챌린저** | 단가는 유리하지만 후보 품질과 timestamp 정확도가 미측정 |
| Fine agentic | **적용하지 않음** | 이미 볼 구간을 알고 있어 탐색 이점이 없고 정밀 프레임 판정이 더 중요함 |

즉, 이번 변경의 첫 적용은 “모델 ID를 3.8로 교체”하는 것이 아니다. 먼저 **Coarse에서 agentic을 선택 가능하게 만들고, thought token과 timestamp 품질을 포함한 A/B가 가능하도록 계측을 완성하는 것**이다.

---

## 2. 프로젝트에 영향을 주는 변경사항

### 2.1 Gemini 3.8 Flash

프로젝트에 관계있는 변경은 다음과 같다.

- 새 모델 ID: `gemini-3.8-flash`
- 3.7과 같은 Interactions API 호출 구조를 사용한다.
- 현재 탐침은 `--model` 인자를 이미 지원하므로 모델 비교 실행 자체에는 큰 코드 변경이 필요 없다.
- 장시간·복잡 작업에서 더 많은 추론 토큰을 사용할 수 있으므로, 단가가 같더라도 실행 비용이 같다고 가정할 수 없다.
- `thinking_budget` 대신 `thinking_level`을 사용한다.
- `temperature`, `top_p`, `top_k`, `candidate_count` 같은 기존 generation 설정은 3.8에서 제거되거나 허용되지 않는다.

현재 탐침은 제거된 generation 설정을 전달하지 않으므로 즉시 충돌하는 부분은 없다. 다만 제품 구현에 공통 generation config가 있다면 3.8 적용 전에 해당 필드를 제거하거나 모델별 설정으로 분리해야 한다.

#### 우리 프로젝트에서의 의미

3.8은 “한 줄 교체 가능한 모델”이지만 “동일 비용의 드롭인 교체”로 취급하면 안 된다. 다음 값을 같은 입력에서 다시 측정해야 한다.

- input / output / thought / total token
- 후보 수와 후보 유형 분포
- Coarse precision과 recall
- timestamp error
- 같은 입력 반복 시 후보 재현성
- 후보당·source-hour당 비용과 지연

이 값이 없으므로 지금은 3.8을 기본 모델로 올리지 않는다.

---

### 2.2 Agentic video understanding

기존 static은 정해진 fps로 영상 전체를 처리한다. agentic은 모델이 긴 타임라인을 탐색하며 볼 구간을 선택한다.

```python
# 기존 static
processing={"type": "static", "fps": 1.0}

# 비교할 agentic
processing="agentic"
```

프로젝트에서 agentic이 맞는 위치는 **Coarse Search뿐**이다.

| 단계 | agentic 적합성 | 판단 |
|---|---|---|
| Coarse | 긴 타임라인에서 후보 위치를 찾음 | 실험 가치가 큼 |
| Fine | 후보 위치를 이미 알고 짧은 구간을 정밀 판정 | static 유지 |
| 안전모 미착용 Fine | 한 장면의 객체 속성 판단 | agentic 불필요 |

agentic은 별도 기능비 대신 탐색 과정이 thought token으로 과금된다. 입력 프레임이 줄어도 thought token이 많이 늘면 비용 절감폭이 줄거나 역전될 수 있다. 따라서 input token만 비교해서는 안 된다.

#### 채택 판단의 우선순위

1. timestamp error가 허용 범위 안에 있는가
2. Coarse recall이 baseline보다 나빠지지 않는가
3. 후보 precision과 event type 판단이 유지되는가
4. thought token까지 포함한 총비용이 줄어드는가
5. 지연과 결과 재현성이 허용 가능한가

비용은 품질 게이트를 통과한 뒤 비교한다. agentic이 싸더라도 후보 시각이 틀리거나 사건을 놓치면 채택하지 않는다.

---

### 2.3 Interactions API와 SDK

이번 실험에서 SDK 호환성은 단순 구현 문제가 아니라 비용과 결과를 바꾸는 핵심 조건이었다.

#### 필수 버전

```text
google-genai >= 2.13.0
현재 검증 버전: 2.22.0
```

2.13 미만에서는 `VideoContent.processing`이 Python 객체에 있어도 실제 요청 body에서 조용히 빠졌다. Fine smoke 실험에서는 8초 구간을 요청했지만 304초 클립 전체가 처리되어 입력 89,366토큰과 $0.072가 발생했다. 2.22.0에서는 같은 8초 요청이 입력 5,934토큰과 $0.00742로 정상 처리되었다.

#### 적용 규칙

```python
from google.genai import interactions as ix

video = ix.VideoContent(
    type="video",
    uri=file_uri,
    mime_type="video/mp4",
    resolution="high",
    processing={
        "type": "static",
        "fps": 2.0,
        "start_offset": "33.000s",
        "end_offset": "41.000s",
    },
)
```

- `input`은 raw dict가 아니라 `ix.VideoContent` / `ix.TextContent` 객체로 전달한다.
- `start_offset` / `end_offset`은 정수 ms가 아니라 duration 문자열로 전달한다.
- 실행 전에 SDK 최소 버전을 검사한다.
- 실행 row에 실제 SDK 버전을 기록한다.
- 설정 플래그만 믿지 않고 token density로 실제 적용 여부를 검사한다.

검증 기준은 다음과 같다.

| 설정 | 예상 video token 밀도 |
|---|---:|
| low / 1fps | 약 100 tok/s |
| high / 1fps | 약 290 tok/s |
| high / 2fps | 약 553 tok/s |

Fine `run1`은 high / 2fps에서 중앙값 553 video tok/s가 나와 설정 전달이 확인되었다. agentic은 static과 다른 token·thought·step 패턴이 나와야 실제 적용된 것으로 판단한다.

---

### 2.4 Usage와 thought token

Fine 실측에서 다음 관계가 확인되었다.

```text
total_tokens = input_tokens + output_tokens + thought_tokens
337,340 = 286,211 + 18,709 + 32,420
```

따라서 usage는 최소한 다음 필드를 보존해야 한다.

| 필드 | 용도 |
|---|---|
| `total_input_tokens` | 영상·텍스트 입력 비용 |
| `total_output_tokens` | 최종 응답 비용 |
| `total_thought_tokens` | agentic 탐색·추론 비용 |
| `total_tokens` | provider가 보고한 전체 토큰 |
| `total_cached_tokens` | 캐시 적용 비용 계산 |
| `input_tokens_by_modality` | video와 text 비용 분리 |
| `tool_use_tokens_by_modality` | agentic 도구 탐색이 별도 보고될 때 사용 |

`None`과 `0`은 구분한다. `None`은 provider가 값을 주지 않은 것이고, `0`은 토큰을 쓰지 않은 것이다. `or 0`으로 저장하면 계측 누락이 무료 호출처럼 보인다.

#### 계약 적용

- 제품의 `UsageRecord.token_usage`에 thought/reasoning token 자리를 추가한다.
- `total = input + output` 불변식을 `total = input + output + thought` 또는 provider별 명시 규칙으로 개정한다.
- `AnalysisRun.usage_summary`도 같은 구조로 맞춘다.
- validator는 필드 존재뿐 아니라 합계 관계를 검사한다.
- 비용 계산은 thought token을 빠뜨리지 않는다.

agentic A/B 전에 이 변경이 먼저 필요한 이유는, thought token이 없으면 입력 절감과 탐색 비용을 분리할 수 없고 원장에 비교 근거가 남지 않기 때문이다.

---

### 2.5 가격과 모델 선택

현재 문서 기준 가격은 다음과 같다.

| 모델 | 입력 / 출력 1M token | 현재 Coarse source-hour 추정 | 2027-01-01 이후 |
|---|---:|---:|---:|
| Gemini 3.7 / 3.8 Flash | $0.75 / $3.75 | $0.277 | $0.554 |
| Gemini 3.5 Flash-Lite | $0.30 / $2.50 | $0.119 | $0.119 |
| Gemini 3.1 Flash-Lite | $0.25 / $1.50 | $0.094 | $0.094 |

source-hour 값은 기존 Coarse 토큰 실측에 각 모델 단가를 적용한 비교용 추정이다. 모델별 토큰 사용량과 품질이 동일하다는 뜻은 아니다.

#### 적용 규칙

- 단가 숫자를 실행 row와 여러 문서에 복제하지 않는다.
- 공용 가격 설정이 가격표를 소유한다.
- 각 usage row에는 `pricing_id`만 남긴다.
- 2027 가격 변경은 기존 ID 수정이 아니라 새 `pricing_id`로 추가한다.
- 비용 비교는 input/output/thought token과 해당 실행의 `pricing_id`로 재현 가능해야 한다.

Flash-Lite는 가격상 매력적이고 agentic도 지원하지만, 현재 프로젝트에서는 품질이 미측정이다. 3.7 static/agentic 비교 뒤 별도 모델 A/B로 다룬다.

---

## 3. 현재 코드 기준 적용 상태

현재 `modules/search` 탐침을 확인한 결과다.

### 3.1 이미 반영된 것

| 항목 | 현재 상태 |
|---|---|
| Interactions API 사용 | Coarse/Fine 모두 사용 중 |
| typed `VideoContent` / `TextContent` | 반영됨 |
| Fine SDK 최소 버전 검사 | `MIN_SDK = (2, 13, 0)` 반영됨 |
| Fine duration 문자열 offset | `offset_str()`로 반영됨 |
| Fine static / high / 2fps | 반영 및 실측 검증됨 |
| 전체 usage 읽기 | Coarse/Fine 모두 input/output/thought/total/cached/modality 읽음 |
| `None`과 `0` 구분 | `read_usage()`에 반영됨 |
| ffprobe 누적 시각 환산 | Coarse/Fine 로직에 반영됨 |
| 모델 CLI 선택 | `--model` 지원 |

### 3.2 아직 반영할 것

| 우선순위 | 대상 | 필요한 변경 |
|---:|---|---|
| P0 | `coarse_probe.py` | `--processing static|agentic` 추가 |
| P0 | `coarse_probe.py` | Fine과 같은 SDK 최소 버전 검사 및 `sdk_version` 기록 |
| P0 | Coarse 실행 row | `processing`, 실제 fps, resolution, model, SDK를 비교 키에 포함 |
| P0 | Coarse 비용 계산 | thought token을 포함하도록 수정 |
| P0 | Coarse 리포트 | thought/total/modality token과 실제 처리 길이를 출력 |
| P0 | 캐시 키 | processing mode가 다른 실행이 같은 결과로 취급되지 않도록 분리 |
| P1 | token density | 고정 300초가 아니라 ffprobe 실측 길이를 분모로 사용 |
| P1 | 제품 계약 | `UsageRecord`와 summary에 thought token 추가 |
| P1 | 가격 설정 | `pricing_id` 기반 3.7/3.8/Flash-Lite/2027 가격표 추가 |
| P2 | 평가 데이터 | 사람 ground truth와 timestamp error 기록 추가 |

현재 Coarse 코드는 full usage를 읽지만 `cost_usd_est`는 여전히 input/output만 계산하고, 리포트도 legacy input/output 필드를 중심으로 출력한다. 새 agentic 실험 전에 이 간극을 닫아야 한다.

---

## 4. 제품 계약에 넣을 위치

| 변경값 | 제품 계약 위치 | 판단 |
|---|---|---|
| 모델 ID | `AnalysisRun.implementation.model_ref` | 값 변경, 계약 구조 변경 불필요 |
| static / agentic, fps, resolution | `implementation.config_version` | 실행 설정으로 기록 |
| 프롬프트 버전 | `implementation.prompt_version` | 본문 대신 버전 참조 |
| thought token | `UsageRecord.token_usage` | 계약 구조 개정 필요 |
| 실제 처리 길이 | `UsageRecord.processed_duration_sec` | 전체 source 길이와 분리 |
| 가격표 | `UsageRecord.pricing_context.pricing_id` | 단가 값 직접 복제 금지 |
| 호출 지연 | `UsageRecord.latency_ms` | source-hour latency 계산에 사용 |

다음 위치에는 넣지 않는다.

- `profile_ref`: static/agentic은 media 특성이 아니라 호출 방식이다.
- `Observation.source.kind`: 모델 이름이나 `gemini_3_8`을 관찰 출처 종류로 만들지 않는다.
- 이벤트 schema: 모델 버전과 processing mode는 사건 의미가 아니다.

---

## 5. 적용 순서

### Phase 0. 비교 가능한 계측 만들기

1. Coarse에 SDK 검사와 `--processing`을 추가한다.
2. execution row와 cache key에 processing mode를 포함한다.
3. Coarse 비용과 리포트에 thought token을 반영한다.
4. token density의 분모를 실제 처리 길이로 바꾼다.
5. 제품 `UsageRecord`와 validator를 thought-aware 구조로 개정한다.
6. 사람 검토표에 실제 사건 여부와 timestamp error를 기록한다.

이 단계가 끝나기 전에는 agentic 또는 3.8 결과를 비용·품질 비교 자료로 채택하지 않는다.

### Phase 1. 3.7 static baseline 재실행

동일 데이터로 계측이 완성된 baseline을 다시 만든다.

```text
model: gemini-3.7-flash
processing: static
resolution: low
fps: 1.0
prompt: 현재 Coarse prompt 고정
clips: 동일 8개
```

기존 baseline은 SDK 2.12.1에서 processing이 전송되지 않았고 thought token도 원장에 없으므로, agentic과 공정하게 비교하려면 현재 SDK로 새 baseline이 필요하다.

### Phase 2. 3.7 agentic A/B

Phase 1과 비교해 바꾸는 값은 `processing` 하나뿐이다.

```text
model: gemini-3.7-flash 고정
processing: static -> agentic
resolution, prompt, clips: 동일
```

각 조건은 같은 입력을 최소 2회 실행해 재현성도 확인한다. 다음 표를 한 실험 단위로 기록한다.

| 품질 | 비용·성능 | 적용 확인 |
|---|---|---|
| recall, precision | input/output/thought/total token | SDK version |
| timestamp error | source-hour cost | processing mode |
| event type 정확도 | latency | modality별 token |
| 후보 수·중복 수 | 반복 실행 일치도 | ThoughtStep / tool-use 신호 |

#### agentic 채택 조건

아래 조건을 모두 만족할 때만 Coarse 기본값 후보로 올린다.

- 정답지 기준 recall이 static보다 의미 있게 나빠지지 않는다.
- timestamp error가 제품 허용 범위를 넘지 않는다.
- 구간 밖 span이 증가하지 않는다.
- thought를 포함한 source-hour 비용이 static보다 감소한다.
- 후보 수 감소가 실제 누락이 아니라 precision 개선으로 설명된다.
- 동일 입력 반복 시 결과 변동이 운영 가능한 수준이다.

현재는 정답지와 제품 허용 오차 기준이 없으므로 채택 판정 전에 두 기준을 먼저 확정해야 한다.

### Phase 3. 3.8 모델 A/B

processing mode를 Phase 2에서 선택한 값으로 고정하고 모델만 바꾼다.

```text
processing: 고정
model: gemini-3.7-flash -> gemini-3.8-flash
나머지 조건: 동일
```

3.8은 단가가 같다는 이유가 아니라, 품질·재현성 개선이 추가 thought token과 지연을 정당화할 때 채택한다.

### Phase 4. 비용 챌린저

3.5 Flash-Lite와 Fine fps 1.0을 각각 독립적으로 실험한다.

- Coarse: 3.7/3.8 대비 Flash-Lite 후보 품질과 timestamp 비교
- Fine: high 2fps 대비 high 1fps의 실선/점선·신호 판정 비교
- 후보 gate: Fine으로 넘기는 후보 상한 또는 우선순위 정책 비교
- 프롬프트: 의미를 유지한 축약본의 반복 text token 절감 확인

모델, processing, fps, resolution, 프롬프트를 한 번에 두 개 이상 바꾸지 않는다.

---

## 6. 적용하지 않을 변경

이번 Gemini 변경과 관련되어 보여도 현재 프로젝트에는 다음을 적용하지 않는다.

| 하지 않을 것 | 이유 |
|---|---|
| Fine에 agentic 사용 | 짧은 지정 구간을 프레임 단위로 봐야 하며 탐색 이점이 없음 |
| Coarse를 high resolution으로 상향 | 입력 원가가 크게 늘고 후보 탐색 단계의 목적과 맞지 않음 |
| 3.8과 agentic을 동시에 활성화 | 품질·비용 변화의 원인을 분리할 수 없음 |
| 3.8 단가에 3.7 토큰량을 그대로 적용해 최종 비용 주장 | 모델별 토큰 사용량이 미측정 |
| agentic의 공식 최대 절감률을 우리 예상 절감률로 사용 | 우리 영상·프롬프트·후보 탐색에서 검증되지 않음 |
| `profile_ref`에 agentic 추가 | media 특성이 아닌 실행 설정 |
| usage 누락을 0으로 저장 | 무료 호출로 오해되어 비용이 왜곡됨 |
| Fine `NOT_OBSERVED`를 자동으로 false negative 처리 | 대부분이 점선 차로 변경의 정당 기각일 가능성이 큼 |
| 시각 `OBSERVED`를 법규 위반으로 변환 | 사람 검토에서 두 판단이 다름을 확인함 |

---

## 7. 완료 기준

이번 변경의 프로젝트 적용은 다음 상태가 되었을 때 완료로 본다.

### 구현 완료

- Coarse가 CLI/config로 static과 agentic을 선택할 수 있다.
- SDK 2.13 미만 실행이 Coarse/Fine 모두 차단된다.
- 실행 row에 model, processing, resolution, fps, SDK, prompt/config version이 남는다.
- cache key가 서로 다른 실험 조건을 혼합하지 않는다.
- input/output/thought/total/cached/modality token이 보존된다.
- 비용 계산과 보고서가 thought token을 포함한다.
- 실제 처리 길이와 timestamp 환산이 ffprobe 실측을 사용한다.

### 실험 완료

- 현재 SDK로 3.7 static baseline을 재실행했다.
- 동일 입력으로 3.7 agentic을 실행했다.
- 각 조건을 반복 실행해 재현성을 확인했다.
- 사람 ground truth로 recall, precision, timestamp error를 계산했다.
- 구간 밖 span과 후보 중복을 비교했다.
- source-hour 비용이 thought token을 포함해 재현 가능하다.

### 의사결정 완료

- 품질 게이트를 통과한 조건끼리만 비용을 비교했다.
- 선택한 기본값을 `model_ref`, `config_version`, `prompt_version`, `pricing_id`로 식별할 수 있다.
- Gemini 3.8 채택 여부는 agentic 결정과 분리해 기록했다.
- 채택하지 않은 대안도 실패 이유와 실측 근거를 남겼다.

---

## 8. 최종 권고 설정

### 지금 유지할 baseline

```yaml
coarse:
  model: gemini-3.7-flash
  processing: static
  resolution: low
  fps: 1.0

fine:
  model: gemini-3.7-flash
  processing: static
  resolution: high
  fps: 2.0
  padding_sec: 2.0
```

### 바로 열 실험

```yaml
coarse_experiment:
  fixed:
    model: gemini-3.7-flash
    resolution: low
    prompt: current
    clips: same_ground_truth_set
  variable:
    processing:
      - static
      - agentic
```

### 다음 단계

```yaml
model_experiment:
  fixed:
    processing: selected_from_coarse_experiment
    resolution: low
    prompt: current
    clips: same_ground_truth_set
  variable:
    model:
      - gemini-3.7-flash
      - gemini-3.8-flash
      - gemini-3.5-flash-lite
```

최종적으로 이번 Gemini 변경은 **Fine의 처리 방식을 바꾸는 변경이 아니라, Coarse에 선택적 agentic 탐색을 도입하고 모델·처리 방식별 비용과 품질을 정확히 기록할 수 있게 만드는 변경**으로 적용한다.

---

## 9. 근거

### 프로젝트 문서

- [Coarse / Fine 영상 탐침 실험 총정리](./coarse-fine-experiment-summary.md)
- [Gemini 3.8 Flash / agentic 조사 기록](./gemini-3.8-agentic-review.md)
- [Coarse / Fine 단계별 설정과 구현 참고](./coarse-fine-implementation-notes.md)
- [제품 저장소 적용 대상 조사](./gemini-3.8-apply-targets.md)
- [Coarse Probe Report](./probe_report.md)
- [Fine Probe Report](./fine_probe_report.md)
- [Fine Probe 사람 검토 기록](./fine_probe_human_reviews.md)

### 공식 참고

- [Gemini 최신 모델 문서](https://ai.google.dev/gemini-api/docs/latest-model)
- [Gemini 3.8 Flash 모델 문서](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Interactions API Video Understanding](https://ai.google.dev/gemini-api/docs/interactions/video-understanding)
- [Gemini 3.8 Flash 발표](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)
