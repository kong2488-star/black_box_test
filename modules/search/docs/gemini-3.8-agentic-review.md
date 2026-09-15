# Gemini 3.8 Flash · agentic video understanding — 조사 기록

작성: 2026-09-10 · 대상: search Owner · 상태: **조사만. 모델 교체도 mode 변경도 하지 않았다.**

> 표기 규칙([[daesingo-claim-discipline]]): **[실측]** = 우리가 돌려서 나온 수 · **[문서]** = 구글 문서/블로그 주장 · **[추정]** = 우리가 산술로 끌어낸 수.
> 이 문서의 비용은 전부 **입력·출력 토큰만** 센다. 업로드 대역폭, 저장, ffmpeg 분할 비용은 포함하지 않는다.

## 요약

1. **`gemini-3.8-flash`가 나왔다**(2026-09-02). 가격·컨텍스트·API 형태가 3.7과 같아서 **코드 변경은 모델 문자열 한 줄**이다. 단, **토큰을 더 쓴다고 문서가 명시**하므로 단가가 같아도 원가는 오를 수 있다.
2. **agentic video understanding**(2026-09-04)이 더 큰 건이다. `processing: "agentic"` 한 필드로 켜지고 **우리가 쓰는 3.7에서도 된다**. 우리 원가의 **89%가 입력 토큰**이라 정확히 그 지점을 때린다.
3. 둘은 **따로 재야 한다.** 한 번에 바꾸면 어느 쪽이 원가·품질을 움직였는지 못 가른다.

---

## 1. Gemini 3.8 Flash

2026-09-02 출시. 6주 만의 세 번째 Flash 릴리스(3.6 → 3.7 → 3.8). 모델 ID **`gemini-3.8-flash`**, GA.

### 그대로인 것

| 항목 | 3.7 / 3.8 |
|---|---|
| 입력 단가 | $0.75 / 1M (2026-12-31까지) |
| 출력 단가 | $3.75 / 1M (2026-12-31까지) |
| 2027-01-01 이후 | **$1.50 / $7.50 (2배)** — 3.7과 같은 인상 시점 |
| 컨텍스트 | 1,048,576 입력 / 65,536 출력 |
| API | `client.interactions.create()`, `VideoContent`/`TextContent`, `resolution`(소문자), `processing` |

→ `coarse_probe.py`는 **`MODEL` 한 줄**(60행)만 바꾸면 돈다. 단가 상수(73–74행)도 그대로 유효하다.

### 달라진 것

- `thinking_budget` → **`thinking_level`** 문자열 enum: `low` / `medium`(기본) / `high`. **`minimal`은 에러.**
- **`temperature` / `top_p` / `top_k` / `candidate_count` 제거** — generation_config에서 빼야 한다.
- 멀티턴은 서버측 **`previous_interaction_id`**, `FunctionResponse`에 **`call_id` + `name` 필수**.

**우리 탐침은 이 파라미터를 하나도 안 넘긴다.** (569행의 `candidate_count`는 우리 리포트 필드이고 API 파라미터가 아니다. 헷갈리기 쉬우니 주의.)

### ⚠ 이게 핵심 리스크

> "Gemini 3.8 Flash can use more tokens on longer running and complex tasks, **by design**" — 반복 도구 검증 + 잘게 쪼갠 추론 때문. **[문서]**

**단가가 같아도 clip당·source-hour당 원가는 오를 수 있다.** 그래서 3.8 전환 시 [[daesingo-evaluation-metrics]]의 source-hour 원가에 **3.7 실측치를 재사용하면 안 된다.** 얼마나 더 쓰는지는 **우리 워크로드(coarse span 탐색)에서 재봐야 알 수 있다** — 문서는 "long-horizon SWE·agentic" 기준으로 말하고 있고 우리 작업은 그게 아니다.

---

## 2. agentic video understanding

2026-09-04 발표. 고정 fps로 영상 전체를 먹는 대신 **모델이 타임라인을 스스로 탐색**한다("search, scan, inspect target segments").

### 켜는 법

```python
# 기존 (우리가 지금 쓰는 것)
processing={"type": "static", "fps": 1.0}

# agentic
processing="agentic"          # 또는 {"type": "agentic"}
```

한 요청 안에서 클립별로 static / agentic **혼용 가능**.

### 지원·제약

| 항목 | 내용 |
|---|---|
| 지원 모델 | **3.8 / 3.7 / 3.6 Flash, 3.5 Flash-Lite** — **우리가 쓰는 3.7에서도 된다** |
| 구글 주장 **[문서]** | 토큰 최대 **−88%**, 비용 **−66%**, 영상 벤치마크 정확도 **+7%** |
| 과금 | 별도 기능비 없음. **탐색 비용은 thought token으로 과금** |
| 배포 | Hosted API 전용 (self-host·open weight 없음) |

### 단서 — 우리에게 정확히 걸리는 부분

> "**Static processing performs better for clips under five minutes** and frame-by-frame precision work." **[문서]**

우리 `CLIP_SECONDS = 300`은 **정확히 그 경계선**이다. 다만 판단이 갈리는 지점이 둘 있다.

- coarse는 "프레임 단위 정밀"이 아니라 **후보 span 찾기**다 → agentic에 유리할 수 있다.
- 반대로 **timestamp 정확도는 제품 성립의 급소**다(`probe_report.md`). agentic이 타임라인을 건너뛰며 보면 **"말한 시각이 맞는가"가 나빠질 위험**이 있고, 이건 비용 절감으로 상쇄되지 않는다.
- **클립 길이 자체가 변수가 된다.** agentic이 이기려면 5분 클립을 유지할 이유가 약해질 수 있다(더 긴 단위 = 분할·오버랩 비용 감소). 단, 이건 3차 실험이고 지금 열 것은 아니다.

---

## 3. 비용

### baseline **[실측]** — `probe_report.md`, tag `default`

3.7-flash · `resolution=low` · `fps=1.0` · 5분 클립 8개(원본 40분) · concurrency 3 · 성공 8 / 실패 0

| 항목 | 값 |
|---|---|
| 입력 토큰 | 219,530 |
| 출력 토큰 | 5,350 |
| 평균 입력토큰 / 영상초 | 91.5 (문서 추정 "low ≈ 100 tok/s"와 부합) |
| 클립당 지연 | 23–38초 |
| 후보 총계 | 45개 (후보 0개 클립 0/8) |

토큰은 실측, 비용은 **실측 토큰 × 공식 단가**다.

| | 토큰 | 단가 | 비용 |
|---|---|---|---|
| 입력 | 219,530 | $0.75/1M | **$0.1646 (89.1%)** |
| 출력 | 5,350 | $3.75/1M | $0.0201 (10.9%) |
| 합 (원본 40분) | | | **$0.1847** |

**원가의 89%가 입력 토큰이다.** 프롬프트·스키마·출력을 줄이는 최적화는 남은 11%를 건드리는 일이고, **입력 프레임 토큰을 줄이는 것만이 의미 있는 절감**이다. agentic이 노리는 지점이 정확히 여기다.

### source-hour 환산

40분 → 시간 환산 배율 1.5.

| 시나리오 | 2026 가격 | 2027-01-01 이후 | 근거 |
|---|---|---|---|
| **3.7 static, low, 1fps (현행)** | **$0.277 / 원본시간** | **$0.554 / 원본시간** | [실측] |
| 3.7 agentic | $0.094 / 원본시간 | $0.188 / 원본시간 | [추정] 문서의 −66%를 실측에 적용 |
| 3.8 static | **미지수** | 미지수 | 단가 동일이지만 토큰 증가폭 미측정 |
| 3.8 agentic | 미지수 | 미지수 | — |

**2027년 인상만으로 현행 원가가 $0.554/시간이 된다.** agentic이 주장대로 먹히면 인상 후에도 지금보다 싸다($0.188 < $0.277) — 이 한 줄이 실측할 이유다.

### 두 주장이 서로 맞물리는지 검산 **[추정]**

"토큰 −88%"와 "비용 −66%"는 왜 다른가. 절감분 일부가 **더 비싼 단가로 되돌아오기** 때문으로 보인다.

- 입력 −88%: 219,530 → 26,344 tok = **$0.0198**
- 총비용 −66% 목표: $0.1847 → **$0.0628**
- 남는 예산 $0.0430 ÷ $3.75/1M = **약 11,500 output-price 토큰**
- 현재 출력 5,350 → **thought token 약 6,000개분의 여유**

즉 **입력 토큰을 88% 지우고 그 자리에 입력 단가의 5배인 thought token을 얹는 거래**다. 우리 워크로드에서 탐색이 저 예산보다 더 필요하면 **절감폭은 66%보다 작아지고, 극단적으로는 역전될 수 있다.** → **재는 항목: `usage`의 thought/reasoning 토큰을 반드시 따로 기록해야 한다.** 현재 탐침은 `total_input_tokens` / `total_output_tokens`만 찍는다.

---

## 4. 무엇을 재야 하는가

**변수를 섞지 말 것.** 두 실험은 독립이고, 같이 바꾸면 원인을 못 가린다.

| # | 실험 | 고정 | 변수 | 볼 것 |
|---|---|---|---|---|
| 1 | 모델 교체 | static, low, 1fps, 같은 클립·같은 프롬프트 | `3.7-flash` → `3.8-flash` | 입력/출력/thought 토큰, 후보 개수, **재현성**(같은 입력 2회) |
| 2 | 처리 mode | **3.7 고정**, 같은 클립·같은 프롬프트 | `static` → `agentic` | 토큰 3종, 지연, 후보 개수, **timestamp 오차** |

두 실험 모두 `probe_report.md` 아래의 사람 확인 절차(precision / **시각 오차** / event_type)를 그대로 밟아야 한다. **Recall은 여전히 측정 불가**다(정답지 없음) — 이 결과를 recall 주장으로 쓰지 말 것.

탐침에 필요한 변경(아직 하지 않았다):

- `--processing static|agentic` 플래그
- `usage`의 **thought/reasoning 토큰 별도 기록** ← 이게 없으면 실험 2의 결론이 안 나온다
- `--model`은 이미 있다

## 5. 지금 결정하지 않은 것

- **3.8로 갈지** — 토큰 증가폭을 재기 전에는 결정 근거가 없다. 3.7이 사라진 것도 아니다.
- **agentic을 켤지** — timestamp 정확도가 나빠지면 비용이 싸도 안 된다.
- **클립 길이(300초)를 바꿀지** — 실험 2 결과 뒤에 볼 3차 항목.
- 챌린저는 조사만 하고 열지 않는다([[daesingo-open-items-and-research]]).

## 출처

- [Introducing Gemini 3.8 Flash and 3.8 Flash Cyber](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/)
- [What's new in Gemini 3.8 Flash — Gemini API](https://ai.google.dev/gemini-api/docs/latest-model)
- [Gemini 3.8 Flash 모델 페이지](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Video understanding — Interactions API](https://ai.google.dev/gemini-api/docs/interactions/video-understanding)
- [Google Launches Agentic Video Understanding for Gemini Flash Models](https://www.marktechpost.com/2026/09/04/google-agentic-video-understanding-gemini-flash-models/)
- 사내: `modules/search/probe_report.md`, 메모 `daesingo-gemini-api`
