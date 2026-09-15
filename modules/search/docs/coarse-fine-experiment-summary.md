# Coarse / Fine 영상 탐침 실험 총정리

작성: 2026-09-12  
대상: Gemini 기반 블랙박스 영상 검색 2단계 파이프라인  
근거: Coarse/Fine 실행 JSONL, 파생 리포트, 사람 검토 기록, 구현·SDK 조사 문서

> 이 문서는 현재 저장소에 흩어진 실험 내용과 결과를 한 번에 읽을 수 있도록 합친 요약이다.
> 수치에는 **실측**, **실측 토큰 기반 추정 비용**, **문서 주장**, **미측정**을 구분해 적었다.
> 이 코드는 제품 구현이 아니라 제품 설계에 필요한 토큰·비용·지연·판정 분포를 얻기 위한 일회용 탐침이다.

---

## 1. 한눈에 보는 결론

Coarse와 Fine의 역할 분리는 유효했다.

- **Coarse**는 긴 영상을 낮은 해상도로 넓게 훑어 후보 구간을 찾았다.
- **Fine**은 Coarse가 넘긴 짧은 구간만 높은 해상도로 다시 보고, 사건의 필수 시각 요건이 실제로 충족되는지 판정했다.
- 40분 주행 영상에서 Coarse는 후보 **45개**를 만들었고, Fine은 그중 유효 구간 **41개**를 검증했다.
- Fine 결과는 `NOT_OBSERVED` **40개**, `OBSERVED` **1개**였다. Coarse가 넓게 잡은 점선 차로 변경을 Fine이 실선 차로 변경이 아니라고 걸러낸 것이 대부분이다.
- Fine의 유일한 `OBSERVED` 신호 사건은 사람이 원본을 확인했을 때도 “황색 신호 상태에서 정지선 통과”라는 시각 사실은 관찰되었다. 다만 사람의 법규 판정은 **위반 아님**이었고, 이는 시각 사건 검증과 법규 판단이 서로 다른 문제임을 확인해 주었다.
- 비용은 예상과 반대로 **Fine이 Coarse보다 약 2.2배 컸다.** 짧은 구간만 보더라도 high resolution, 2fps, 후보별 반복 프롬프트, thought token이 합쳐졌기 때문이다.
- Fine은 전체 원본의 약 **17.3%**만 다시 봤지만, 파이프라인 비용의 약 **69%**를 차지했다.
- Coarse 후보 4개는 실제 클립 길이 밖의 시각을 가리켜 Fine이 실행되지 못했다. 후보 탐색보다도 **timestamp 신뢰성**이 제품 성립의 핵심이라는 점이 실측으로 드러났다.
- Gemini 3.8 전환과 agentic processing은 **조사만 했고 아직 실험하지 않았다.** 현재 결과로 3.8 또는 agentic 채택을 결론 내릴 수 없다.
- Recall, 전체 precision, 4개 사건 유형 전체 성능은 정답지와 충분한 사람 검토가 없어 **측정되지 않았다.**

---

## 2. 실험 목적과 파이프라인

### 2.1 풀려는 문제

긴 블랙박스 영상 전체를 고해상도로 정밀 분석하면 비용이 크다. 반대로 낮은 해상도로만 보면 차선 종류, 신호 상태, 안전모처럼 세부 시각 정보가 필요한 사건을 정확히 판정하기 어렵다.

실험은 이 문제를 두 단계로 나눴다.

```text
긴 원본 영상
  -> Coarse: 싸게 넓게 탐색, recall 우선
  -> 후보 span
  -> Fine: 짧은 구간을 고해상도로 정밀 검증
  -> OBSERVED / NOT_OBSERVED / UNCERTAIN
```

### 2.2 단계별 책임

| 구분 | Coarse Search | Fine Verification |
|---|---|---|
| 핵심 질문 | 어디를 다시 봐야 하는가? | 그 구간에 요구한 사건이 실제로 성립하는가? |
| 입력 | 약 5분 단위 긴 클립 | 후보 span에 앞뒤 2초를 더한 8~13초 구간 |
| 최적화 방향 | 놓치지 않기, 낮은 비용 | 시각적 정확도, 근거 구조화 |
| 해상도 / fps | low / 서버 기본값이 1fps와 유사 | high / 2fps |
| 모델 | `gemini-3.7-flash` | `gemini-3.7-flash` |
| 출력 | 후보 event type, span, 대표 시각, 관찰 요약, 점수 | 3값 판정, primitive, 시간 사실, 불확실성, 대상 연결 |
| 처리 방식 | 사실상 static baseline | static offset 처리 |

Fine 판정의 의미는 다음과 같다.

- `OBSERVED`: 사건의 필수 시각 요건을 모두 확인했다.
- `NOT_OBSERVED`: 필요한 대상을 볼 수 있었고, 확인 결과 요건이 성립하지 않았다.
- `UNCERTAIN`: 가림, 흐림, 화면 밖 등의 이유로 필요한 대상을 볼 수 없어 성립 여부를 정할 수 없다.

이 구분은 “확신도”가 아니라 **관찰 가능성**을 기준으로 한다. 특히 “보이지 않음”을 곧바로 “없음”으로 처리하지 않도록 설계했다.

### 2.3 검색 사건 유형

Coarse는 다음 4종을 검색했다.

1. `SIGNAL`
2. `CENTER_LINE_CROSSING`
3. `LANE_CHANGE`
4. `MOTORCYCLE_HELMET_NON_USE`

Fine에서는 Coarse의 일반 `LANE_CHANGE`를 더 엄격한 `SOLID_LINE_LANE_CHANGE`로 매핑했다. 즉 일반적인 점선 차로 변경은 Coarse 후보가 될 수 있지만, Fine에서는 백색 실선을 넘지 않았다면 정상적으로 `NOT_OBSERVED`가 된다. 이번 데이터는 이 hard-negative 기각 능력을 보는 성격이 강하다.

---

## 3. 데이터와 실험 조건

### 3.1 입력 데이터

- 강변북로 주행 원본 약 40분
- `ffmpeg -c copy`로 나눈 8개 클립
- 명목상 5분 단위지만 실제 길이는 키프레임 경계 때문에 정확히 300초가 아니다.
- ffprobe 실측 전체 길이: **2,347.932초(약 39분 8초)**
- 개별 길이: 304.304초 2개, 298.965초 5개, 244.498초 1개
- 별도의 정답 구간(ground truth)은 없다.

### 3.2 Coarse 조건

| 항목 | 값 |
|---|---|
| 실행 tag | `default` |
| 모델 | `gemini-3.7-flash` |
| 해상도 | `low` |
| 기록상 fps | 1.0 |
| 클립 | 8개 |
| 동시성 | 3 |
| 프롬프트 | recall 우선, 4개 사건 유형 후보 탐색 |
| 결과 원장 | `probe_runs.jsonl` 8행 |

중요한 단서가 있다. 당시 사용한 `google-genai 2.12.1`은 `processing` 필드를 실제 요청 본문에서 조용히 제거했다. 따라서 기록에는 `fps=1.0`이 남았지만, 명시한 static/fps 설정이 전송된 실험은 아니다. 다만 입력 토큰 밀도가 서버 기본 1fps와 거의 일치해 **low resolution + 서버 기본 처리의 static baseline**으로는 사용할 수 있다.

### 3.3 Fine 조건

| 항목 | 값 |
|---|---|
| 본 실험 tag | `run1` |
| 모델 | `gemini-3.7-flash` |
| SDK | `google-genai 2.22.0` |
| 처리 | static |
| 해상도 / fps | high / 2.0 |
| 후보 padding | 앞뒤 각 2초 |
| 요청 구간 | 8~13초, 평균 9.89초 |
| 유효 호출 | 41개 |
| 건너뜀 | 4개 (`SPAN_OUT_OF_CLIP`) |
| 프롬프트 | `fine-p1`, 공통 블록 + 사건별 델타 |
| 결과 원장 | `fine_probe_runs.jsonl` |

Fine은 Coarse가 이미 업로드한 영상의 Files API 참조를 재사용하고 `start_offset` / `end_offset`만 바꿨다. 별도의 ffmpeg 재분할이나 후보별 재업로드 없이 구간 질의가 가능함을 확인했다.

---

## 4. Coarse 실험 결과

### 4.1 실행 결과

| 지표 | 결과 |
|---|---:|
| 성공 / 실패 | 8 / 0 |
| 입력 토큰 | 219,530 |
| 출력 토큰 | 5,350 |
| 후보 수 | 45 |
| 후보가 0개인 클립 | 0 / 8 |
| 후보 점수 평균 | 0.854 |
| 점수 범위 | 0.78~0.92 |
| 호출 지연 | 클립당 23.2~37.5초 |
| 비용 | **$0.1847** (토큰 기반 추정) |

후보 유형 분포는 다음과 같다.

| 유형 | 후보 수 |
|---|---:|
| `LANE_CHANGE` | 44 |
| `SIGNAL` | 1 |
| `CENTER_LINE_CROSSING` | 0 |
| `MOTORCYCLE_HELMET_NON_USE` | 0 |

### 4.2 읽을 수 있는 것

1. 모든 클립에서 후보가 나왔고 총 45개이므로, recall 우선 프롬프트는 적극적으로 후보를 생성했다.
2. 후보가 차로 변경에 극단적으로 편중되었다. 따라서 이번 결과를 4개 사건 유형 전체의 성능으로 일반화할 수 없다.
3. 입력 토큰이 비용의 약 **89%**를 차지했다. Coarse 비용을 줄이려면 출력 형식보다 영상 입력 프레임을 줄이는 쪽이 효과가 크다.
4. 보고서의 91.5 input tok/s는 모든 클립을 300초로 본 명목 2,400초 기준이다. ffprobe 실측 길이로 다시 계산하면 약 **93.5 input tok/s**다. 어느 기준에서도 low 1fps의 약 100 tok/s 예상과 가깝다.

### 4.3 드러난 문제

Coarse가 `part_07.mp4`에 대해 실제 길이 298.97초를 넘는 4개 span을 생성했다.

| 후보 | Coarse span | 실제 클립 길이 |
|---|---:|---:|
| `part_07.mp4#7` | 345~350초 | 298.97초 |
| `part_07.mp4#8` | 414~422초 | 298.97초 |
| `part_07.mp4#9` | 444~450초 | 298.97초 |
| `part_07.mp4#10` | 454~458초 | 298.97초 |

이는 Fine의 실패가 아니라 Fine이 볼 수 없는 구간을 Coarse가 만든 **Coarse timestamp 실패**다. 후보 카드가 실제 장면으로 연결되지 않으면 검색 결과가 무용해지므로, timestamp 정확도는 후보 존재 여부만큼 중요한 품질 축이다.

또한 Coarse의 원본 위치 환산은 과거 `clip_ordinal × 300` 가정을 사용했다. 실제 클립 길이 누적과 비교하면 최대 약 4.47초 차이가 나며, 후보 span 자체가 4~9초이므로 무시하기 어려운 오차다.

---

## 5. Fine 실험 결과

### 5.1 본 실험 `run1`

| 지표 | 결과 |
|---|---:|
| 전체 후보 행 | 45 |
| 실제 검증 | 41 |
| 구간 밖 건너뜀 | 4 |
| 성공 / 실패 | 41 / 0 |
| `NOT_OBSERVED` | 40 |
| `OBSERVED` | 1 |
| `UNCERTAIN` | 0 |
| Fine 처리 구간 합계 | 405.5초 |
| 원본 대비 Fine exposure | **17.3%** (405.5 / 2,347.932) |
| 입력 토큰 | 286,211 |
| 출력 토큰 | 18,709 |
| thought 토큰 | 32,420 |
| 총 토큰 | 337,340 |
| 후보당 평균 비용 | **$0.00991** |
| 전체 비용 | **$0.4064** (토큰 기반 추정) |
| 호출당 지연 중앙값 / 최대 | 10.92초 / 18.4초 |

### 5.2 40개의 `NOT_OBSERVED` 해석

40건은 모두 `SOLID_LINE_LANE_CHANGE` 검증이었다. Fine 출력에서는 40건 모두 `WHITE_SOLID_LINE=ABSENT`였고, 39건에서 `WHITE_DASHED_LINE=PRESENT`가 관찰되었다. 한 건은 실선이 보였지만 차량이 선을 넘지 않았다.

따라서 현재 근거가 가리키는 해석은 “Fine이 40개를 놓쳤다”가 아니라, **Coarse가 일반 차로 변경을 넓게 모았고 Fine이 백색 실선 횡단 요건을 적용해 hard-negative를 제거했다**는 것이다.

다만 40건 전체를 사람이 확인하지 않았으므로 다음 숫자는 아직 만들 수 없다.

- 정당 기각 수
- 실제 Fine false negative 수
- Fine precision / recall / HN-FPR

`NOT_OBSERVED` 분포만 보고 이를 `FINE_FALSE_NEGATIVE=40`으로 세면 성능 지표의 의미가 뒤집힌다.

### 5.3 유일한 `OBSERVED`와 사람 검토

`part_08.mp4#6`의 `SIGNAL` 사건만 `OBSERVED`였다.

- 모델 관찰: 신호 상태와 차량의 정지선 통과 사이의 시간 관계가 관찰됨
- 사람 관찰: 차량이 황색 신호에 정지선을 통과함
- 사람 법규 판정: **위반 사항 아님 (`NO_VIOLATION`)**

여기서 얻은 중요한 경계는 다음과 같다.

```text
시각 사건 OBSERVED != 교통법규 위반
```

Fine의 역할은 영상에서 요구한 시각 관계가 관찰되는지를 구조화하는 것이다. 위반, 과실, 책임 같은 법적 판단은 별도 단계와 별도 근거가 필요하다.

### 5.4 출력 구조 품질

- 불변조건·출력 관례 위반: **0건**
- 경계 유출 heuristic 탐지: **0건**
- 모든 근거 시각은 요청 구간 시작을 0으로 하는 상대 시간으로 해석됨: **41 / 41건**
- thought token 보고: **41 / 41건**
- `total_tokens = input + output + thought`: **337,340 = 286,211 + 18,709 + 32,420**

Fine 프롬프트의 primitive 예시는 효과가 있었다. `primitives[].kind`는 9종이 127회 반복되어 코드형 어휘로 수렴했다. 반면 `temporal_facts[].fact`는 34종이 각각 한 번씩만 나와 산문으로 흩어졌다. 향후 vocabulary registry가 필요하다면 temporal fact에도 코드 예시나 구조화된 축을 제공해야 한다.

---

## 6. Smoke 실험에서 확인한 SDK 문제

Fine은 본 실험 전에 같은 후보 하나로 `smoke`와 `smoke2`를 실행했다. 두 결과의 차이가 SDK 설정 전달 문제를 명확히 보여 준다.

| 항목 | `smoke` | `smoke2` |
|---|---:|---:|
| SDK | 2.13 미만 | 2.22.0 |
| 요청 구간 | 8초 | 8초 |
| 입력 토큰 | 89,366 | 5,934 |
| 비용 | $0.07203 | $0.00742 |
| 지연 | 35.3초 | 15.6초 |
| video tok / 요청초 | 11,171 | 553 |
| 실제 처리 | 304초 클립 전체 | 요청한 8초 |
| 근거 시간 기준 | 클립 절대시간처럼 출력 | 구간 시작 상대시간 |

`google-genai < 2.13`에서는 `processing`이 모델 객체에 남아 있어도 실제 HTTP body에서 제거된다. 에러와 경고가 없어 비용이 조용히 약 10배 커졌다. 이 실험으로 다음 규칙이 확정되었다.

1. `google-genai >= 2.13`을 강제하고 각 실행 row에 SDK 버전을 남긴다.
2. `start_offset` / `end_offset`은 SDK 요청에서 정수 ms가 아니라 `"33.000s"` 같은 duration 문자열로 보낸다.
3. raw dict 대신 `VideoContent` / `TextContent` 객체를 사용한다.
4. 설정 플래그 자체를 믿지 않고 video token / 요청 구간초로 실제 적용 여부를 검증한다.
5. 기준값은 low@1fps 약 100 tok/s, high@1fps 약 290 tok/s, high@2fps 약 553 tok/s다.

`run1`의 중앙값이 high@2fps 기대값인 **553 video tok/s**와 일치하므로 Fine의 resolution, fps, offset은 실제로 전송된 것으로 확인된다.

---

## 7. 비용 구조

### 7.1 공표된 40분 기준

| 단계 | 40분 비용 | source-hour 환산 | 전체 비용 비중 |
|---|---:|---:|---:|
| Coarse | $0.1847 | $0.277 | 31.3% |
| Fine | $0.4064 | $0.610 | 68.7% |
| 합계 | **$0.5911** | **$0.887** | 100% |

Fine / Coarse 비용 비율은 약 **220%**다. 2027-01-01 이후 3.x Flash 단가가 2배가 된다는 조사 문서의 가격을 적용하면 합계는 **$1.774/source-hour**가 된다.

### 7.2 ffprobe 실측 길이로 보정한 값

기존 보고서는 원본을 명목상 2,400초로 환산했다. 동일 비용을 ffprobe 실측 2,347.932초로 정규화하면 다음과 같다.

| 단계 | 실측 길이 기준 source-hour |
|---|---:|
| Coarse | 약 $0.283 |
| Fine | 약 $0.623 |
| 합계 | 약 **$0.906** |

두 기준의 차이는 약 2.2%이며, 기존 문서와 비교할 때는 공표된 40분 기준을, 새 원가 모델을 만들 때는 ffprobe 실측 길이를 쓰는 것이 적절하다.

### 7.3 Fine이 더 비싼 이유

1. **프레임 밀도:** low 1fps 약 93.5 input tok/s 대비 high 2fps의 video 토큰은 약 553 tok/s다.
2. **후보 수:** 후보당 한 번 호출하므로 Coarse가 많이 잡을수록 Fine 비용이 선형으로 증가한다.
3. **프롬프트 반복:** Fine text prompt는 중앙값 1,511토큰이며 41회 합계 61,968토큰이다. Fine 입력의 약 22%가 반복 프롬프트다.
4. **thought token:** 32,420토큰이 별도로 발생했고 출력 단가 기준으로 비용에 포함되었다.
5. **정확도 우선 설정:** high resolution과 2fps는 실선/점선, 신호, 객체 속성 구분을 위해 선택했다.

따라서 Fine 비용의 가장 큰 제어 레버는 단순 출력 축약이 아니라 **Fine으로 넘기는 후보 수, fps, resolution, 반복 프롬프트 길이**다. 다만 fps나 resolution을 낮추는 것은 직접적인 품질 교환이므로 사람 정답지 기반 A/B 없이 적용하면 안 된다.

### 7.4 비용 수치의 한계

- 비용은 실행 row의 토큰과 문서에 기록된 단가로 계산한 추정치다.
- 업로드 대역폭, 저장, ffmpeg 처리 비용은 포함하지 않는다.
- Coarse 원장은 input/output token만 기록했다. 당시 thought token이 별도로 발생했다면 Coarse 비용이 과소 계산되었을 가능성이 있다.
- Fine은 thought token을 실제로 기록했고 전체 비용에 반영했다.
- 단가가 바뀔 때 실행 row에 가격을 복제하기보다 `pricing_id`로 가격표 버전을 가리켜야 한다.

---

## 8. 이번 실험으로 얻은 것

### 8.1 제품·모델 관점

1. **2단계 구조는 작동한다.** Coarse가 후보를 넓게 모으고 Fine이 엄격한 사건 요건으로 hard-negative를 제거하는 흐름이 실제 출력으로 확인되었다.
2. **Fine은 단순 후처리가 아니라 주 비용 구간이다.** 전체 영상의 17.3%만 보면서도 Coarse의 2.2배 비용을 썼다.
3. **Coarse precision이 Fine 원가를 지배한다.** recall 우선 정책으로 만든 후보 하나마다 high-resolution 호출과 반복 프롬프트 비용이 붙는다.
4. **timestamp는 독립 품질 지표다.** 사건 유형을 맞혀도 시각이 클립 밖이거나 몇 초씩 어긋나면 제품에서 사용할 수 없다.
5. **시각 관찰과 법규 판단을 분리해야 한다.** `OBSERVED`는 위반 판정이 아니다.
6. **일반 차로 변경과 실선 차로 변경의 정의 차이를 지표에 반영해야 한다.** Coarse와 Fine의 event type mapping을 무시하면 정상 기각을 false negative로 잘못 센다.

### 8.2 구현 관점

1. Files API 업로드를 재사용하고 offset만 바꾸는 설계가 성립한다.
2. SDK가 필드를 조용히 버릴 수 있으므로 요청 설정은 token density로 사후 검증해야 한다.
3. ffprobe 실측 누적 길이가 절대 시각 환산의 기준이어야 한다.
4. `None`과 `0`을 구분해 usage를 읽어야 한다. 값을 받지 못한 경우를 0토큰으로 기록하면 원가가 조용히 왜곡된다.
5. `total_tokens`는 실제로 input + output + thought였으므로, input + output만으로 총량을 정의한 계약은 현실과 맞지 않는다.
6. primitive는 예시를 주면 코드형 어휘로 수렴하지만 자유 서술 temporal fact는 그대로 산문화된다.

### 8.3 계약·평가 관점

1. `UsageRecord`에 thought/reasoning token을 기록할 자리가 필요하다.
2. `total_tokens = input_tokens + output_tokens` 불변식은 Fine 실측과 충돌한다. thought를 포함하도록 계약과 validator를 함께 고쳐야 한다.
3. processing mode, fps, resolution은 media profile이 아니라 실행 구성이다. `config_version`으로 A/B를 식별해야 한다.
4. 기존 mock의 token, 처리 시간, 비용 사이에는 실측과 큰 불일치가 있다. mock 숫자가 예산 기본값 같은 제품 결정을 움직였다면 재검토가 필요하다.
5. Recall과 precision을 주장하려면 정답지와 사람 검토가 먼저다. 실행 성공률이나 판정 분포는 성능 지표를 대신하지 못한다.

---

## 9. 아직 얻지 못한 것

다음 항목은 현재 자료만으로 결론 내릴 수 없다.

| 미측정 항목 | 이유 |
|---|---|
| Coarse recall | 정답지가 없어 놓친 사건을 셀 수 없음 |
| Coarse precision | 45개 후보 전체의 사람 검토가 없음 |
| Fine precision / recall / HN-FPR | `NOT_OBSERVED` 40건의 정당 기각/오판 라벨이 없음 |
| 절대 timestamp 오차 분포 | 후보 전체에 대한 사람 기준 시각이 없음 |
| 중앙선 침범 성능 | 후보 0건 |
| 안전모 미착용 성능 | 후보 0건 |
| agentic의 토큰·비용·시각 정확도 | 아직 실제 agentic 실행을 하지 않음 |
| Gemini 3.8의 품질·토큰 증가폭 | 3.8 실행을 하지 않음 |
| Fine fps 1.0의 품질 | 비용 절감치는 추정 가능하지만 시각 품질 미측정 |
| flash-lite 후보 품질 | 가격 비교만 있고 워크로드 실측 없음 |

특히 `NOT_OBSERVED 40 / OBSERVED 1`이라는 분포만으로 정확도를 주장해서는 안 된다. 지금 확정할 수 있는 것은 파이프라인의 동작 형태, 토큰·지연·비용, 출력 구조, 명백한 timestamp 범위 오류뿐이다.

---

## 10. 다음 실험 우선순위

변수는 한 번에 하나씩만 바꿔야 한다.

### 1순위: 사람 정답지 만들기

- 45개 Coarse 후보의 실제 사건 여부, 사건 유형, 대표 시각 오차를 기록한다.
- Fine의 `NOT_OBSERVED` 40건을 정당 기각과 실제 false negative로 나눈다.
- 최소한 timestamp error, Coarse precision, Fine HN-FPR을 계산할 수 있게 한다.

비용 최적화보다 먼저 필요한 단계다. 품질 기준이 없으면 fps, 모델, processing mode를 비교해도 싼 오답인지 알 수 없다.

### 2순위: usage 계약과 기록 보강

- input/output/thought/total/cached token과 modality별 token을 모두 남긴다.
- `total = input + output + thought` 관계를 validator에서 검사한다.
- 실제 처리 구간, 지연, SDK 버전, `pricing_id`를 기록한다.
- Coarse에도 Fine 수준의 usage 수집을 역이식한다.

### 3순위: Coarse static vs agentic A/B

- 모델은 `gemini-3.7-flash`로 고정한다.
- 같은 클립, 같은 프롬프트, 같은 해상도에서 processing만 바꾼다.
- input/output/thought token, 지연, 후보 수, precision, recall, timestamp error를 비교한다.
- 입력 토큰이 static의 약 93.5 tok/s와 거의 같다면 agentic이 실제 적용되지 않은 것으로 본다.

agentic은 긴 타임라인에서 볼 곳을 고르는 Coarse의 역할과 맞지만, 시각 오차가 나빠진다면 비용 절감만으로 채택할 수 없다. Fine은 이미 구간을 알고 있고 프레임 정밀도가 필요하므로 static 유지가 타당하다.

### 4순위: 모델 A/B

- processing을 고정한 뒤 3.7 / 3.8 / 3.5 Flash-Lite를 비교한다.
- 3.8 전환과 agentic 전환을 한 번에 하지 않는다.
- 같은 입력을 2회 이상 반복해 후보 재현성도 본다.

### 5순위: Fine 비용 최적화

- fps 2.0 -> 1.0
- 반복 프롬프트 축약 또는 캐시 가능성
- Fine 후보 진입 조건 또는 후보 상한
- high -> medium resolution

이 순서의 각 실험은 실선/점선 판별, 신호 시간 관계, timestamp error가 유지되는지를 사람 정답지로 확인해야 한다.

---

## 11. 최종 판단

현재 실험은 “Coarse/Fine 방식이 정확하다”를 증명한 성능 평가가 아니다. 대신 다음을 실측으로 확정한 **파이프라인 계측 실험**이다.

1. Coarse -> Fine 데이터 흐름과 업로드 재사용이 실제로 동작한다.
2. Coarse는 45개 후보를 만들었고 Fine은 유효한 41개를 구조적으로 판정했다.
3. Fine은 일반 차로 변경 후보를 실선 차로 변경 요건으로 걸러내는 hard-negative 필터로 동작했다.
4. Fine 비용은 예상보다 커서 전체 원가의 중심이 되었다.
5. thought token, SDK 필드 누락, 실측 클립 길이, timestamp 범위 검사가 원가와 품질을 크게 왜곡할 수 있다.
6. 법규 판단과 시각 관찰은 반드시 분리해야 한다.
7. 다음 의사결정의 선행 조건은 사람 정답지와 timestamp 오차 측정이다.

따라서 현 시점의 권고안은 **Fine은 static/high로 유지하고, Coarse의 품질 기준을 먼저 만든 뒤 3.7 static 대 agentic을 단일 변수로 비교하는 것**이다. Gemini 3.8 전환, Flash-Lite 전환, Fine fps 축소는 그 다음 실험으로 분리한다.

---

## 12. 근거 문서

- [Coarse Probe Report](../probe_report.md)
- [Fine Probe Report](../fine_probe_report.md)
- [Fine Probe 사람 검토 기록](./fine_probe_human_reviews.md)
- [Coarse / Fine 단계별 설정과 구현 참고](./coarse-fine-implementation-notes.md)
- [Gemini 3.8 Flash / agentic 조사 기록](./gemini-3.8-agentic-review.md)
- [제품 저장소 적용 대상 조사](./gemini-3.8-apply-targets.md)
- [실제 전송 프롬프트](../PROMPTS.md)
- 원본 실행 기록: `probe_runs.jsonl`, `fine_probe_runs.jsonl`

