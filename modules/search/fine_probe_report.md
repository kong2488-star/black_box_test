# Fine Probe Report

생성: 2026-09-17T10:28:58+09:00  ·  원본 기록: `fine_probe_runs.jsonl` (60줄)

> `fine_probe_runs.jsonl`에서 파생된 요약이다. `--report-only`로 다시 만들 수 있다.
> **Recall은 측정하지 않았다.** 정답지가 없으므로 놓친 사건은 셀 수 없다.
> 절대 시각 정확도도 여기 없다 — 화면시각 판독은 `readout` 소유다.
> 비용은 파일 상단 단가 상수 기준 **추정치**이고, thought 토큰을 출력 단가로 계산했다(확인 대상).

회차 10개: `bypass_141927`, `bypass_141927_mp4`, `guard_check`, `guard_check2`, `model37_fine`, `model38_fine`, `rep1_fine`, `run1`, `smoke`, `smoke2` — **합산하지 않는다.** 조건이 다르면 비교할 수 없다.

---

# 회차 `bypass_141927`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 2건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 6~6s (평균 5.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 2  ·  tag bypass_141927

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 2
latency (Fine, 호출당)         : 중앙값 9.9s / 최대 9.9s
tokens                         : 입력 3,457 · 출력 1,110 · thought 1,200
cost                           : $0.0113 (추정)
Fine exposure                  : 11초 (Coarse 원본 2400초 기준 0.5%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260620_141927_EVT_1.avi#M0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 1000 | 0분06초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 25 | 0.00482 |
| 20260620_141927_EVT_1.avi#M1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 0 | 0분05초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 25 | 0.00644 |

## 진단

- 성공 2건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 2건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- 구간 지정 확인: video 토큰/요청구간초 중앙값 **25** (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)
    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다. 플래그를 믿지 말고 이 숫자로 확인한다.
- 프롬프트(text) 토큰 중앙값 1,604 · 호출 2건 합계 3,183
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 2건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 2 / 2건, 합계 1,200
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 5,767 vs 입력+출력 4,567 vs 입력+출력+thought 5,767
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×2, `WHITE_DASHED_LINE`×2, `VEHICLE_CROSSES_LINE`×2, `TARGET_VEHICLE`×1
- **temporal fact** — `VEHICLE_STARTED_LATERAL_MOVE`×2, `VEHICLE_CROSSED_LINE`×2, `VEHICLE_SETTLED_IN_ADJACENT_LANE`×2
- **uncertainty kind** — 없음

- `primitive kind`: 값 4종 / 출현 7회 (값당 평균 1.8회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 3종 / 출현 6회 (값당 평균 2.0회) → **코드로 수렴했다** — registry 후보로 쓸 수 있다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `bypass_141927_mp4`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 2건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 6~6s (평균 5.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 2  ·  tag bypass_141927_mp4

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 2
latency (Fine, 호출당)         : 중앙값 12.5s / 최대 12.5s
tokens                         : 입력 8,991 · 출력 854 · thought 2,250
cost                           : $0.0184 (추정)
Fine exposure                  : 11초 (Coarse 원본 2400초 기준 0.5%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 141927_remux.mp4#R0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 0 | 0분05초 | WHITE_SOLID_LINE=PRESENT; VEHICLE_CROSSES_LINE=ABSENT | - | - | - | 528 | 0.00660 |
| 141927_remux.mp4#R1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 0 | 0분05초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 528 | 0.01179 |

## 진단

- 성공 2건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 2건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 2건**
    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.
      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다 — 에러 없이 무시된다.
    - `141927_remux.mp4#R0`: 요청 6초인데 video 2,904 tok (145 tok/클립초 — 클립 20초 전체 분량)
    - `141927_remux.mp4#R1`: 요청 6초인데 video 2,904 tok (145 tok/클립초 — 클립 20초 전체 분량)
    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**
- 프롬프트(text) 토큰 중앙값 1,604 · 호출 2건 합계 3,183
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 2건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 2 / 2건, 합계 2,250
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 12,095 vs 입력+출력 9,845 vs 입력+출력+thought 12,095
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×2, `VEHICLE_CROSSES_LINE`×2, `WHITE_DASHED_LINE`×1, `TARGET_VEHICLE`×1
- **temporal fact** — `VEHICLE_STARTED_LATERAL_MOVE`×1, `VEHICLE_CROSSED_DASHED_LINE`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 4종 / 출현 6회 (값당 평균 1.5회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 2종 / 출현 2회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `guard_check`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 1건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 6~6s (평균 5.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 1  ·  tag guard_check

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : OBSERVED 1
latency (Fine, 호출당)         : 중앙값 9.4s / 최대 9.4s
tokens                         : 입력 1,716 · 출력 526 · thought 553
cost                           : $0.0053 (추정)
Fine exposure                  : 6초 (Coarse 원본 2400초 기준 0.2%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260620_141927_EVT_1.avi#M0 | SOLID_LINE_LANE_CHANGE | **OBSERVED** | 6-11 | 0 | 0분05초 | WHITE_SOLID_LINE=PRESENT; TARGET_VEHICLE=PRESENT; VEHICLE_CROSSES_LINE | - | OBSERVED_WITHOUT_UNCERTAINTY_NOTE | - | 25 | 0.00533 |

### 실패

| 후보 | 오류 | 메시지 |
|---|---|---|
| 20260620_141927_EVT_1.avi#M0 | UnicodeEncodeError | 'cp949' codec can't encode character '\u2014' in position 24: illegal multibyte sequence |

## 진단

- 성공 1건 / 실패 1건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 관찰 신호 (위반이 아니다 — 계약이 허용하는 형태다. 사람이 먼저 볼 대상)
    - `OBSERVED_WITHOUT_UNCERTAINTY_NOTE` 1건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 1건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- 구간 지정 확인: video 토큰/요청구간초 중앙값 **25** (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)
    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다. 플래그를 믿지 말고 이 숫자로 확인한다.
- 프롬프트(text) 토큰 중앙값 1,579 · 호출 1건 합계 1,579
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 1건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 1 / 1건, 합계 553
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 2,795 vs 입력+출력 2,242 vs 입력+출력+thought 2,795
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×1, `TARGET_VEHICLE`×1, `VEHICLE_CROSSES_LINE`×1
- **temporal fact** — `VEHICLE_STARTED_LATERAL_MOVE`×1, `VEHICLE_CROSSED_LINE`×1, `VEHICLE_SETTLED_IN_ADJACENT_LANE`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `guard_check2`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 2건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 6~6s (평균 5.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 2  ·  tag guard_check2

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 2
latency (Fine, 호출당)         : 중앙값 11.5s / 최대 11.5s
tokens                         : 입력 3,457 · 출력 1,183 · thought 1,164
cost                           : $0.0114 (추정)
Fine exposure                  : 11초 (Coarse 원본 2400초 기준 0.5%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260620_141927_EVT_1.avi#M0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 0 | 0분05초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 25 | 0.00559 |
| 20260620_141927_EVT_1.avi#M1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-11 | 0 | 0분05초 | TARGET_VEHICLE=PRESENT; WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRE | - | - | - | 25 | 0.00581 |

## 진단

- 성공 2건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 2건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- 구간 지정 확인: video 토큰/요청구간초 중앙값 **25** (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)
    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다. 플래그를 믿지 말고 이 숫자로 확인한다.
- 프롬프트(text) 토큰 중앙값 1,604 · 호출 2건 합계 3,183
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 2건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 2 / 2건, 합계 1,164
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 5,804 vs 입력+출력 4,640 vs 입력+출력+thought 5,804
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×2, `WHITE_DASHED_LINE`×2, `VEHICLE_CROSSES_LINE`×2, `TARGET_VEHICLE`×1
- **temporal fact** — `VEHICLE_STARTED_LATERAL_MOVE`×2, `VEHICLE_SETTLED_IN_ADJACENT_LANE`×2, `VEHICLE_CROSSED_DASHED_LINE`×1, `VEHICLE_CROSSED_LINE`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 4종 / 출현 7회 (값당 평균 1.8회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 4종 / 출현 6회 (값당 평균 1.5회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `model37_fine`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 2건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 2개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 8~9s (평균 8.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 2  ·  tag model37_fine

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 2
latency (Fine, 호출당)         : 중앙값 12.8s / 최대 12.8s
tokens                         : 입력 12,214 · 출력 875 · thought 1,338
cost                           : $0.0175 (추정)
Fine exposure                  : 17초 (Coarse 원본 2400초 기준 0.7%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260620_141927_EVT_1.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 10-19 | 0 | 20분54초 | WHITE_DASHED_LINE=PRESENT; WHITE_SOLID_LINE=ABSENT; TARGET_VEHICLE=PRE | - | - | - | 528 | 0.00895 |
| 20260620_141956_EVT_1.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 10-18 | 0 | 21분34초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 528 | 0.00850 |

## 진단

- 성공 2건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 2건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 2건**
    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.
      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다 — 에러 없이 무시된다.
    - `20260620_141927_EVT_1.mp4#0`: 요청 9초인데 video 4,752 tok (237 tok/클립초 — 클립 20초 전체 분량)
    - `20260620_141956_EVT_1.mp4#0`: 요청 8초인데 video 4,224 tok (211 tok/클립초 — 클립 20초 전체 분량)
    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**
- 프롬프트(text) 토큰 중앙값 1,625 · 호출 2건 합계 3,238
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 2건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 2 / 2건, 합계 1,338
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 14,427 vs 입력+출력 13,089 vs 입력+출력+thought 14,427
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_DASHED_LINE`×2, `WHITE_SOLID_LINE`×2, `TARGET_VEHICLE`×2
- **temporal fact** — 없음
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 6회 (값당 평균 2.0회) → **코드로 수렴했다** — registry 후보로 쓸 수 있다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `model38_fine`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 2건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 2개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.8-flash  ·  prompt_version fine-p2
        clip_length 8~9s (평균 8.5s)
        resolution high  ·  fps 2.0
        fine_candidate_count 2  ·  tag model38_fine

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 2
latency (Fine, 호출당)         : 중앙값 10.3s / 최대 10.3s
tokens                         : 입력 12,214 · 출력 633 · thought 1,830
cost                           : $0.0184 (추정)
Fine exposure                  : 17초 (Coarse 원본 2400초 기준 0.7%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20260620_141927_EVT_1.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 10-19 | 0 | 20분54초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 528 | 0.01025 |
| 20260620_141956_EVT_1.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 10-18 | 0 | 21분34초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 528 | 0.00815 |

## 진단

- 성공 2건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 2건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 2건**
    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.
      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다 — 에러 없이 무시된다.
    - `20260620_141956_EVT_1.mp4#0`: 요청 8초인데 video 4,224 tok (211 tok/클립초 — 클립 20초 전체 분량)
    - `20260620_141927_EVT_1.mp4#0`: 요청 9초인데 video 4,752 tok (237 tok/클립초 — 클립 20초 전체 분량)
    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**
- 프롬프트(text) 토큰 중앙값 1,625 · 호출 2건 합계 3,238
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 2건
- 클립 길이 출처: ffprobe 2건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 2 / 2건, 합계 1,830
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 14,677 vs 입력+출력 12,847 vs 입력+출력+thought 14,677
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×2, `WHITE_DASHED_LINE`×2, `TARGET_VEHICLE`×1
- **temporal fact** — 없음
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 5회 (값당 평균 1.7회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `rep1_fine`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 1건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p2
        clip_length 9~9s (평균 9.0s)
        resolution high  ·  fps 2.0
        fine_candidate_count 1  ·  tag rep1_fine

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 1
latency (Fine, 호출당)         : 중앙값 12.8s / 최대 12.8s
tokens                         : 입력 6,394 · 출력 523 · thought 1,002
cost                           : $0.0105 (추정)
Fine exposure                  : 9초 (Coarse 원본 2400초 기준 0.4%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 141927_remux.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 9-18 | 0 | 5분09초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 528 | 0.01051 |

## 진단

- 성공 1건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 1건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 1건**
    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.
      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다 — 에러 없이 무시된다.
    - `141927_remux.mp4#0`: 요청 9초인데 video 4,752 tok (237 tok/클립초 — 클립 20초 전체 분량)
    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**
- 프롬프트(text) 토큰 중앙값 1,642 · 호출 1건 합계 1,642
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.21.0 1건
- 클립 길이 출처: ffprobe 1건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 1 / 1건, 합계 1,002
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 7,919 vs 입력+출력 6,917 vs 입력+출력+thought 7,919
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×1, `WHITE_DASHED_LINE`×1, `TARGET_VEHICLE`×1
- **temporal fact** — `VEHICLE_STARTED_LATERAL_MOVE`×1, `VEHICLE_CROSSED_DASHED_LINE`×1, `VEHICLE_SETTLED_IN_ADJACENT_LANE`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `run1`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 40건, SIGNAL 1건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 8개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p1
        clip_length 8~13s (평균 9.9s)
        resolution high  ·  fps 2.0
        fine_candidate_count 41  ·  tag run1

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 40, OBSERVED 1
latency (Fine, 호출당)         : 중앙값 10.9s / 최대 18.4s
tokens                         : 입력 286,211 · 출력 18,709 · thought 32,420
cost                           : $0.4064 (추정)
Fine exposure                  : 406초 (Coarse 원본 2400초 기준 16.9%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| part_01.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 33-41 | 2500 | 0분35초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01009 |
| part_01.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 46-54 | 2500 | 0분48초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00869 |
| part_01.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 62-71 | 0 | 1분02초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00944 |
| part_01.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 75-84 | 2000 | 1분17초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01130 |
| part_01.mp4#4 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 88-96 | 0 | 1분28초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; LANE_CHANGE=PRESEN | - | - | - | 553 | 0.00932 |
| part_01.mp4#5 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 119-127 | 0 | 1분59초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.00887 |
| part_01.mp4#6 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 181-190 | 0 | 3분01초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00931 |
| part_01.mp4#7 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 240-249 | 0 | 4분00초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.00925 |
| part_02.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 9-19 | 4000 | 5분17초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00874 |
| part_02.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 118-129 | 0 | 7분02초 | TARGET_VEHICLE=PRESENT; WHITE_DASHED_LINE=PRESENT; WHITE_SOLID_LINE=AB | - | - | - | 553 | 0.01153 |
| part_02.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 167-177 | 3500 | 7분54초 | TARGET_VEHICLE=PRESENT; WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRE | - | - | - | 553 | 0.01119 |
| part_02.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 176-186 | 2500 | 8분02초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00855 |
| part_02.mp4#4 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 214-225 | 0 | 8분38초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00941 |
| part_03.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 6-15 | 0 | 10분09초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.00912 |
| part_03.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 119-128 | 0 | 12분02초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00934 |
| part_03.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 233-244 | 2000 | 13분58초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01061 |
| part_03.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 266-277 | 0 | 14분29초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.01034 |
| part_04.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 100-111 | 0 | 16분42초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00989 |
| part_04.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 244-256 | 0 | 19분06초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.01027 |
| part_05.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 216-227 | 2000 | 23분39초 | TARGET_VEHICLE=PRESENT; WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRE | - | - | - | 553 | 0.01031 |
| part_05.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 186-198 | 4000 | 23분11초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00896 |
| part_05.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 285-296 | 3500 | 24분49초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01096 |
| part_05.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 203-213 | 0 | 23분24초 | WHITE_DASHED_LINE=PRESENT; WHITE_SOLID_LINE=ABSENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.01072 |
| part_05.mp4#4 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 229-239 | 4500 | 23분54초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00931 |
| part_06.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 52-63 | 2000 | 25분54초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00873 |
| part_06.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 180-191 | 6000 | 28분06초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.01091 |
| part_06.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 277-288 | 4000 | 29분41초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.01006 |
| part_07.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 1-10 | 3000 | 30분08초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00987 |
| part_07.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 37-48 | 0 | 30분41초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00988 |
| part_07.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 112-120 | 0 | 31분55초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00785 |
| part_07.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 118-128 | 0 | 32분02초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.00889 |
| part_07.mp4#4 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 154-164 | 0 | 32분38초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT | - | - | - | 553 | 0.00954 |
| part_07.mp4#5 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 218-228 | 0 | 33분41초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01065 |
| part_07.mp4#6 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 254-262 | 0 | 34분17초 | WHITE_SOLID_LINE=PRESENT; VEHICLE_CROSSES_LINE=ABSENT | - | - | - | 553 | 0.00941 |
| part_08.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 20-29 | 0 | 35분23초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.00995 |
| part_08.mp4#1 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 32-40 | 0 | 35분35초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01144 |
| part_08.mp4#2 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 41-49 | 2500 | 35분46초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00811 |
| part_08.mp4#3 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 55-64 | 2500 | 36분00초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00970 |
| part_08.mp4#4 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 174-184 | 3000 | 38분00초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01004 |
| part_08.mp4#5 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 196-205 | 3000 | 38분22초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 553 | 0.01111 |
| part_08.mp4#6 | SIGNAL | **OBSERVED** | 211-224 | 0 | 38분34초 | YELLOW_SIGNAL=PRESENT; RED_SIGNAL=PRESENT; GREEN_SIGNAL=PRESENT | - | OBSERVED_WITHOUT_UNCERTAINTY_NOTE | - | 553 | 0.01474 |

### 건너뜀

- `SPAN_OUT_OF_CLIP` 4건

**`SPAN_OUT_OF_CLIP` 은 Fine 의 문제가 아니라 Coarse 출력의 결함이다.**
Coarse 가 클립 길이 밖의 시각을 말했다 — Fine 이 볼 영상이 없다.
**이것이 Coarse timestamp 실패의 실측치다.**

| 후보 | Coarse가 말한 span | 실제 클립 길이 |
|---|---|---|
| part_07.mp4#10 | 454–458s | 298.97s |
| part_07.mp4#7 | 345–350s | 298.97s |
| part_07.mp4#8 | 414–422s | 298.97s |
| part_07.mp4#9 | 444–450s | 298.97s |

## 진단

- 성공 41건 / 실패 0건 / 건너뜀 4건
- 불변조건·관례 위반 0건
- 관찰 신호 (위반이 아니다 — 계약이 허용하는 형태다. 사람이 먼저 볼 대상)
    - `OBSERVED_WITHOUT_UNCERTAINTY_NOTE` 1건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 41건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- 구간 지정 확인: video 토큰/요청구간초 중앙값 **553** (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)
    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다. 플래그를 믿지 말고 이 숫자로 확인한다.
- 프롬프트(text) 토큰 중앙값 1,511 · 호출 41건 합계 61,968
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.22.0 41건
- 클립 길이 출처: ffprobe 45건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 41 / 41건, 합계 32,420
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 337,340 vs 입력+출력 304,920 vs 입력+출력+thought 337,340
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×40, `WHITE_DASHED_LINE`×39, `VEHICLE_CROSSES_LINE`×24, `TARGET_VEHICLE`×19, `LANE_CHANGE`×1, `YELLOW_SIGNAL`×1, `RED_SIGNAL`×1, `GREEN_SIGNAL`×1, `STOP_LINE`×1
- **temporal fact** — `우측 차로에서 주행하던 흰색 SUV 차량이 백색 점선을 넘어 좌측 차로로 진입함`×1, `우측에서 진입한 검은색 왜건 차량이 백색 점선을 넘어 차로를 변경함`×1, `좌측 1차로의 흰색 SUV가 백색 점선을 넘어 2차로로 차로를 변경함`×1, `우측 차로의 흰색 SUV가 백색 점선(파선) 구간을 넘어 차로를 변경함`×1, `차량이 차로를 변경하며 넘은 차선은 백색 실선이 아닌 백색 점선(파선) 구간이다.`×1, `차로 구획선이 백색 점선(파선)으로 유지되는 구간에서 차량 이동이 이루어짐`×1, `우측 차로의 흰색 세단이 백색 점선 구간을 넘어 주행 차로로 이동함`×1, `우측 차로에서 진입한 흰색 SUV가 백색 점선(파선) 구간을 넘어 차로를 변경함`×1, `우측 차로를 주행하던 회색 승용차가 백색 점선 구간을 가로질러 2차로로 차로를 변경함`×1, `우측 전방의 흰색 SUV가 주행하는 차로 간 구획선은 백색 점선(파선)으로 확인됨`×1, `검은색 승용차가 점선(파선) 구간을 넘어 차로를 변경함`×1, `좌측 1차로에서 주행하던 청회색 승용차가 백색 점선(파선) 구간을 넘어 2차로로 차로를 변경함`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 9종 / 출현 127회 (값당 평균 14.1회) → **코드로 수렴했다** — registry 후보로 쓸 수 있다
- `temporal fact`: 값 34종 / 출현 34회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `smoke`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 1건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p1
        clip_length 8~8s (평균 8.0s)
        resolution high  ·  fps 2.0
        fine_candidate_count 1  ·  tag smoke

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 1
latency (Fine, 호출당)         : 중앙값 35.3s / 최대 35.3s
tokens                         : 입력 89,366 · 출력 416 · thought 918
cost                           : $0.0720 (추정)
Fine exposure                  : 8초 (Coarse 원본 2400초 기준 0.3%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| part_01.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 33-41 | 35000 | 1분08초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; TARGET_VEHICLE=PRE | - | - | - | 10982 | 0.07203 |

## 진단

- 성공 1건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 0건 / 클립 절대시간으로 보이는 것 1건
    - 클립 절대시간으로 보이는 것이 섞여 있다. `abs_timecode` 환산을 고쳐야 한다.

- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 1건**
    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.
      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다 — 에러 없이 무시된다.
    - `part_01.mp4#0`: 요청 8초인데 video 87,856 tok (289 tok/클립초 — 클립 304초 전체 분량)
    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**
- 프롬프트(text) 토큰 중앙값 1,510 · 호출 1건 합계 1,510
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- 클립 길이 출처: ffprobe 1건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 1 / 1건, 합계 918
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 90,700 vs 입력+출력 89,782 vs 입력+출력+thought 90,700
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×1, `WHITE_DASHED_LINE`×1, `TARGET_VEHICLE`×1
- **temporal fact** — `차량들이 차로를 변경하는 구간의 차선은 백색 실선이 아닌 백색 점선(파선)으로 관찰됨`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 1종 / 출현 1회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

---

# 회차 `smoke2`

## Experiment Note

> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.
> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).

```text
[CASE]
real  (강변북로 주행 원본 40분, 5분 클립 8개)
visual event type: SOLID_LINE_LANE_CHANGE 1건
positive / hard-negative:  정답지 없음 — 사람 확인 대상
  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.
    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.
source duration: 1개 클립에서 뽑은 후보

[INPUT]
user hint: (없음)
ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다

[PIPELINE]
Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)
Fine:   Structured  ·  model gemini-3.7-flash  ·  prompt_version fine-p1
        clip_length 8~8s (평균 8.0s)
        resolution high  ·  fps 2.0
        fine_candidate_count 1  ·  tag smoke2

[RESULT]
Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)
timestamp error                : 사람 확인 대상 — 아래 확인 표
Fine Recall / HN-FPR / Precision: 사람 확인 대상
verification 분포              : NOT_OBSERVED 1
latency (Fine, 호출당)         : 중앙값 15.6s / 최대 15.6s
tokens                         : 입력 5,934 · 출력 420 · thought 372
cost                           : $0.0074 (추정)
Fine exposure                  : 8초 (Coarse 원본 2400초 기준 0.3%)

[FAILURE]
stage: FINE
kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조

[LEARNING]
(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)
```

## 후보별 결과

| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| part_01.mp4#0 | SOLID_LINE_LANE_CHANGE | **NOT_OBSERVED** | 33-41 | 3000 | 0분36초 | WHITE_SOLID_LINE=ABSENT; WHITE_DASHED_LINE=PRESENT; VEHICLE_CROSSES_LI | - | - | - | 553 | 0.00742 |

## 진단

- 성공 1건 / 실패 0건 / 건너뜀 0건
- 불변조건·관례 위반 0건
- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)
- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 1건 / 클립 절대시간으로 보이는 것 0건
    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.
      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)

- 구간 지정 확인: video 토큰/요청구간초 중앙값 **553** (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)
    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다. 플래그를 믿지 말고 이 숫자로 확인한다.
- 프롬프트(text) 토큰 중앙값 1,510 · 호출 1건 합계 1,510
    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다. 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.
- google-genai 버전: 2.22.0 1건
- 클립 길이 출처: ffprobe 1건
    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.
      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다 (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).
      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.
- thought 토큰을 보고한 호출 1 / 1건, 합계 372
    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.
- `total_tokens` 합 6,726 vs 입력+출력 6,354 vs 입력+출력+thought 6,726
    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.

### 모델이 만들어낸 어휘

계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로
열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.

- **primitive kind** — `WHITE_SOLID_LINE`×1, `WHITE_DASHED_LINE`×1, `VEHICLE_CROSSES_LINE`×1
- **temporal fact** — `우측 차로의 흰색 SUV가 백색 점선 구간에서 좌측 차로로 차로를 변경함`×1
- **uncertainty kind** — 없음

- `primitive kind`: 값 3종 / 출현 3회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다
- `temporal fact`: 값 1종 / 출현 1회 (값당 평균 1.0회) → **산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다

산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**
다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.

## 구간 전달 검산 (video 토큰 기준)

- **7건에서 video 토큰이 기대를 벗어났다. 이 행들의 판정은 무효다.**

| 후보 | tag | flag | 구간(s) | video tok | 기대 | 비율 |
|---|---|---|---|---|---|---|
| part_01.mp4#0 | smoke | `VIDEO_TOKENS_HIGH` | 8.0 | 87856 | 4224 | 2080% |
| 20260620_141927_EVT_1.avi#M0 | bypass_141927 | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |
| 20260620_141927_EVT_1.avi#M1 | bypass_141927 | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |
| 20260620_141927_EVT_1.avi#M0 | guard_check | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |
| 20260620_141927_EVT_1.avi#M0 | guard_check | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |
| 20260620_141927_EVT_1.avi#M0 | guard_check2 | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |
| 20260620_141927_EVT_1.avi#M1 | guard_check2 | `VIDEO_TOKENS_LOW` | 5.5 | 137 | 2904 | 5% |

> `VIDEO_TOKENS_LOW` 는 요청한 구간이 실제로 전달되지 않았다는 뜻이다 (실측: AVI + start_offset 에서 기대의 4.7%). `VIDEO_TOKENS_HIGH` 는 구간 지정이 통째로 무시됐다는 뜻이다 (실측: google-genai 2.12.1 에서 기대의 20배, 원가도 그만큼). flag 가 비어 있는 옛 행은 이 검산이 생기기 전에 기록된 것이다.

## 자동으로 세지 않는 것

**`FINE_FALSE_NEGATIVE` 숫자를 여기서 찍지 않는다.**

taxonomy의 정의는 「Coarse는 찾았는데 Fine이 제거」다. 그런데 Coarse 후보의
`observed`에 점선이 11건, 실선이 0건이다. **점선 차로변경을 기각한 것은**
**Fine이 제대로 작동한 것**이고, 그걸 FN으로 세면 지표가 뒤집힌다.
`failure-taxonomy.md`가 아직 초안·Owner 미확정이라 자동 숫자가 틀린 정의를 굳힌다.

`NOT_OBSERVED`는 사람이 두 갈래로 나눠야 한다.

| 갈래 | 뜻 | 무엇의 지표인가 |
|---|---|---|
| (α) 요건 미충족 정당 기각 | 선이 점선이었다 등 | **Coarse precision** |
| (β) 사람이 요건 충족이라 본 기각 | | 진짜 `FINE_FALSE_NEGATIVE` |

## 실행 뒤에 사람이 해야 하는 일

후보마다 표의 「원본 위치」를 원본에서 직접 열어 보고 두 칸을 적는다.
(환산: `clip_ordinal × 300 + start_offset_ms/1000 + evidence_at_ms/1000`)

| 확인 | 뜻 |
|---|---|
| **근거 시점에 진짜 그 장면이 있는가 (초 오차)** | 시간 정확도 — 제품 성립의 급소 |
| **판정이 맞는가 (α/β 갈래 포함)** | 판정 정확도 |

분포만으로도 즉시 읽히는 것이 있다.

- **전부 `OBSERVED`로 나오면 Fine이 hard-negative를 하나도 거르지 못한다는 뜻**이다.
  프롬프트나 모델을 다시 봐야 한다.
- 전부 `UNCERTAIN`이면 해상도·fps·구간 길이가 부족한 것이다. 설정 문제다.
- `UNCERTAIN_WITHOUT_REASON`이나 `NOT_OBSERVED_WITHOUT_PRIMITIVE`가 많으면
  모델이 세 값을 혼동하고 있다. 그러면 판정 통계 자체를 신뢰할 수 없다.
