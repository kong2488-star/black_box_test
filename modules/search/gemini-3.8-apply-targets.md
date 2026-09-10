# 적용 대상 — `ktc4-chonnam-2` 레포에서 3.8·agentic·실측 원가가 걸리는 지점

작성: 2026-09-10 · 근거: `gemini-3.8-agentic-review.md`, `probe_report.md` · **읽기만 했고 ktc4 레포는 수정하지 않았다.**

> 계약·타모듈 문서는 Owner와 consumer 확인 절차가 있으므로(`contract-usage-record.md` §9-5 선례) 여기서는 **무엇을 어디에 바꿔야 하는지만** 적는다.
> `[실측]` 우리 탐침 · `[문서]` 구글 문서 · `[추정]` 산술.

---

## A. 계약 개정이 필요한 것 — 1건

### A-1. `UsageRecord`에 thought/reasoning 토큰의 자리가 없다 ★

**파일:** `docs/architecture/contracts/contract-usage-record.md` §4(L60–75)·§5·§8-3·§8-4
**Owner:** 김준영(`common/runtime`) · **확인 필요:** 김대원(`eval` — 비용 분모)·서어진(`search`)

현재 스키마는 `token_usage = {input_tokens, output_tokens, total_tokens}` 3필드로 닫혀 있고 불변조건이 이렇게 걸려 있다.

- §8-3 「객체 전체가 null이거나 **세 필드가 모두 존재**한다. 일부만 채우지 않는다」
- §8-4 「`total_tokens`는 `input_tokens + output_tokens`와 **일치**한다」

그런데 **agentic의 타임라인 탐색 비용은 thought token으로 과금**되고 **[문서]**, 3.8은 사고 토큰을 더 쓴다 **[문서]**. 둘 중 하나가 반드시 벌어진다.

| 갈림길 | 결과 |
|---|---|
| provider가 thought를 별도로 보고 | `total ≠ input + output` → **§8-4 불변조건 위반** |
| thought가 `output_tokens`에 접혀 들어감 | 불변조건은 지켜지지만 **탐색비용과 답변비용을 못 가른다** → eval이 static vs agentic을 원장에서 비교할 수 없다 |

두 번째가 더 위험하다. 계약이 조용히 통과하면서 **A/B의 근거가 사라진다.** §9-5(`run_ref` 타입 변경)가 minor를 올린 선례가 있으니 절차는 있다.

**연쇄 대상**

- `docs/architecture/contracts/contract-analysis-run-candidate-event.md` L182–198 — `usage_summary.token_usage`가 같은 3필드다. **Owner 서어진(우리)** → 동시 개정.
- `data/mock/validate_mock_pack.py` L506–509 — `usage_records` 필수키 목록.
- `docs/mock/03_mock_artifact_templates.md` L2625 부근 — UsageRecord 템플릿.

---

## B. 계약 개정이 **필요 없다**고 확인된 것 (같이 적어두는 게 중요하다)

| # | 지점 | 왜 그대로 두면 되는가 |
|---|---|---|
| B-1 | `contract-analysis-run-candidate-event.md` L155 `config_version` | 「**FPS/chunk 등의 전체 설정값을 공용 Contract에 직접 노출하지 않는다**」 → `processing: static\|agentic`은 이 안에 들어간다. **계약 개정 불필요.** 단 L329가 impl 비교를 `impl_id + model_ref + prompt_version + config_version + contract_version`으로 정의하므로, **mode가 `config_version` 값에 드러나야** A/B가 식별된다 |
| B-2 | 같은 문서 L65 `model_ref: "gemini-3.7-flash"` | 3.8 전환은 **값만** 바뀐다 |
| B-3 | `contract-usage-record.md` §5 `pricing_id` | 「가격표가 바뀌면 새 `pricing_id`가 생긴다」 → 2027-01-01 인상도 이 메커니즘이 흡수한다. **문서가 아니라 `common/runtime` config에 항목 추가**가 필요하다(현재 `gemini-2026-08`은 2026-08-27 스냅샷이라 3.8·2027 요율이 없다) |
| B-4 | `contract-analysis-source-derived.md` §4.4 `profile_ref` | profile은 「실행 단계가 아니라 **media 특성**」을 표현한다. **agentic은 media 특성이 아니라 호출 방식이므로 profile 값 공간에 넣지 않는다.** §11-1 Pending 목록에 agentic을 얹지 말 것 |

---

## C. 숫자·근거가 낡은 문서

### C-1. baseline이 Flash-Lite로 적혀 있는데 실측은 3.7-flash로 돌았다

**파일:** `docs/architecture/module-architecture.md` L642, L1702 · **Owner:** PM/Architecture

> 「Gemini Files API + low resolution + 무음 + **Flash-Lite**가 유력 baseline」

실측은 `gemini-3.7-flash`다. source-hour 원가 차이 **[실측 토큰 + 공식 단가]**:

| 모델 | 입력/출력 단가 | source-hour 원가 | 2027-01-01 이후 |
|---|---|---|---|
| `gemini-3.7-flash` / `3.8-flash` | $0.75 / $3.75 | **$0.277** | **$0.554** (2배) |
| `gemini-3.5-flash-lite` | $0.30 / $2.50 | $0.119 | $0.119 (인상 없음) |
| `gemini-3.1-flash-lite` | $0.25 / $1.50 | $0.094 | $0.094 (인상 없음) |

**2027-01-01 인상은 3.7·3.8 Flash에만 적용되고 Flash-Lite에는 없다** **[문서]**. 그래서 격차가 **지금 2.3~2.9배 → 2027년 4.7~5.9배**로 벌어진다. RT11이 「특정 proxy를 고정하지 않음」이라 아키텍처 결정은 아니지만, **§5의 baseline 문장이 실측과 다른 모델을 가리키고 있다.**

덤: **`gemini-3.5-flash-lite`도 agentic을 지원한다** **[문서]**. 가장 싼 선택지와 agentic이 겹치므로 조합 실험 가치가 있다.

### C-2. search Owner memo — 우리 소유 문서

**파일:** `docs/modules/search/research/architecture-input-memo.md` · **Owner:** 서어진(우리)

| 행 | 무엇이 걸리나 |
|---|---|
| L17–19 | 「low 기준 1시간 ≈ 0.36M tok, **Flash-Lite 0.036/시간**」 — **토큰 추정은 맞았다**(실측 91.5 tok/영상초 → 0.329M/시간, 오차 9%). 그런데 **$0.036/시간은 재현되지 않는다**: $0.10/1M 단가를 쓴 값이고 3.x flash-lite 실단가는 $0.30(3.5)·$0.25(3.1)이다. → **모델을 이름으로 못박고 재계산** |
| L27–29 | 「`videoMetadata.startOffset/endOffset`만 바꿔 N회 질의」 — Interactions API에서는 **`processing.start_offset/end_offset`(ms)**이다. 구 API 명칭. 붙어 있는 `[검토] 일부 SDK 버전 미지원 보고`는 **해소됨**(3.7 호출 8/8 성공) |
| L49 | SentrySearch 겹침 청킹(30s/5s overlap/25s step) 차용 제안 — **agentic이 성립하면 청킹 설계 자체가 무의미해진다.** 재검토 대상 |
| L25 | `is_batch` 플래그 논거(「두 숫자가 섞인다」) — 같은 논리가 static/agentic에도 적용된다. 단 B-1대로 `config_version`이 흡수 |

### C-3. eval 원가 구성식에 Coarse 실측 첫 숫자가 들어갈 수 있다

**파일:** `docs/modules/eval/initial-evaluation-plan.md` L24–36 · **Owner:** 김대원(`eval`)

source-video-hour당 원가 구성식(`Coarse + Fine exposure + OCR + …`)의 **Coarse 항에 처음으로 실측값**을 넣을 수 있다: **$0.277/source-hour** (3.7-flash, low, 1fps).

단 같은 문서 §3이 「실측 전 성과수치로 말하지 않는다」이고 이 실측은 **40분 1회·recall 미측정·LANE_CHANGE 편중**이다. **원가 항의 입력값으로만** 쓰고 성능 주장에 쓰지 않는다.

---

## D. mock fixture의 수치 정합성 — 실측이 생겨서 검증 가능해졌다

### D-1. `token_usage`가 영상 길이와 7.7~16.8배 어긋난다

**파일:** `data/mock/common/*.json` (`SEARCH_COARSE`) · 실측 기준 **91.5 tok/영상초**

| fixture | 적힌 input_tok | `processed_duration_sec` | 실제 tok/s | 실측 기준 기대치 | 배수 |
|---|---|---|---|---|---|
| `scenario_happy_001` | 14,200 | 1,200 | 11.8 | 109,800 | **7.7×** |
| `scenario_unknown_abstain_partial_001` | 13,100 | 1,800 | 7.3 | 164,700 | **12.6×** |
| `scenario_plate_reread_001` | 13,050 | 1,800 | 7.2 | 164,700 | **12.6×** |
| `scenario_correction_rerun_001` | 11,200 | 1,500 | 7.5 | 137,250 | **12.3×** |
| `scenario_empty_001` | 9,800 | 1,800 | 5.4 | 164,700 | **16.8×** |
| `scenario_relative_rebase_001` | 3,800 | 60 | 63.3 | 5,490 | 1.4× |

`contract-usage-record.md` §6 정상 예시(128,400 tok / 3,600s = 35.7 tok/s)도 2.6× 낮다.

### D-2. 같은 row의 `cost`가 자기 `token_usage`와 14~35배 어긋난다 ★

`happy_001`: 적힌 토큰(14,200 in + 1,200 out)을 공식 단가로 계산하면 **$0.0152 = 21 KRW**인데 `cost`는 **588 KRW**($0.42)로 적혀 있다.

**이게 제품 결정을 움직였다.** `docs/mock/05_mock_deep_review_report.md` L1130의 4차 라운드 갱신 노트가 이 588 KRW를 근거로 `AnalysisScope.budget.max_cost_krw` 기본값을 **300 → 1000**으로 올렸다(`docs/modules/case/decisions/budget-krw-normalization.md`).

실측 단가로 다시 계산하면 **[추정, 1 USD = 1400 KRW mock 환율]**:

| fixture | 적힌 cost | 실측 기준 cost |
|---|---|---|
| `happy_001` (20분) | 588 KRW | **122 KRW** |
| `unknown_abstain_partial` (30분) | 546 KRW | 178 KRW |
| `plate_reread` (30분) | 532 KRW | 178 KRW |
| `correction_rerun` (25분) | 462 KRW | 149 KRW |
| `empty_001` (30분) | 434 KRW | 175 KRW |
| `relative_rebase` (1분) | 84 KRW | 8 KRW |

1시간 coarse도 **388 KRW**라 **원래 기본값 300도 거의 들어온다.** → **예산 기본값을 실측으로 다시 볼 근거가 생겼다.** Owner 유소연(`case`)·김준영.

> 이건 「mock을 실측에 맞춰라」가 아니다. mock의 목적이 계약 통과라면 숫자가 비현실적이어도 된다. **다만 mock 숫자가 제품 기본값을 움직인 지점(예산 300→1000)은 다시 봐야 한다.**

### D-3. 「gemini-3.7-flash는 실재하지 않는 모델명이다」 — 사실이 아니다

**파일:** `docs/mock/05_mock_deep_review_report.md` L1161 (P3-2 항목)

실재하고, 우리가 호출해서 8/8 성공했다(`probe_report.md`). 정정 대상. 같은 값이 `contract-analysis-run-candidate-event.md` L65와 `docs/mock/03_mock_artifact_templates.md` L196·L311에도 있는데 **그쪽은 고칠 게 없다**(진짜 모델명이니까).

### D-4. CI 가드 공백 — D-1·D-2가 통과한 이유

`data/mock/validate_mock_pack.py` L506–509는 `usage_records`의 **키 존재만** 본다. 없는 검사:

- `total_tokens == input_tokens + output_tokens` (**계약 §8-4 불변조건인데 검사 코드가 없다**)
- `input_tokens / processed_duration_sec`이 상식 범위인가
- `cost`가 `token_usage × pricing_id 단가`와 정합인가 (`scripts/check_contract_fixtures.py`는 v9에서 **합계**만 본다)

**첫 항목은 계약이 이미 요구하는 것이라 논의 없이 추가할 수 있다.** 두 번째는 단가·tok/s 범위를 config로 빼면 되고, 있으면 이 계열 결함이 재발하지 않는다. 문서 결정이 아니라 스크립트라 즉시 가능.

---

## E. 챌린저 정책과의 관계

**파일:** `docs/modules/search/decisions/challenger-policy.md` · **Owner:** 서어진(우리)

- `COST` 행의 챌린저는 「Local SLM / CV / self-host / fine-tuning」이다. **agentic·flash-lite는 표에 없고, 챌린저도 아니다** — 같은 provider 안의 설정·모델 변경이라 개방 절차(주간 회의 안건)를 타지 않는다. 「열지 않는 것」에도 걸리지 않는다. 절차 오해를 막으려면 한 줄 적어두는 값어치가 있다.
- 「**baseline 실측이 나오기 전의 챌린저 전부** 열지 않는다」 — 실측이 나왔으므로 전제가 부분 해소됐다. 다만 **precision 미검증·recall 미측정**이라 `failure-taxonomy`가 카테고리를 지목하는 단계는 아니다. **챌린저는 여전히 열 때가 아니다.**

---

## 적용하면 안 되는 것

| 하지 말 것 | 근거 |
|---|---|
| `profile_ref` 값 공간에 `agentic` 추가 | profile은 media 특성이다 (`contract-analysis-source-derived.md` §4.4) |
| 문서에 단가를 값으로 복제 | 「row에 단가를 복제하면 원천이 둘이 된다」 (`contract-usage-record.md` §5) |
| `Observation.source.kind`에 모델명 | `contract-observation.md` L177이 `search.gemini_3_7_coarse ❌`로 금지 |
| 3.8 전환을 agentic과 같이 켜기 | 원인을 못 가른다 (`gemini-3.8-agentic-review.md` §4) |

## 우선순위

1. **A-1** — 계약 개정. 이게 없으면 agentic A/B 결과를 원장에 기록할 수 없다. 절차가 가장 길다(consumer 확인).
2. **D-4 첫 항목** — 계약이 이미 요구하는 검사. 즉시 가능.
3. **C-2** — 우리 소유 문서. 우리가 바로 고칠 수 있다.
4. **D-2 / C-1 / C-3** — 타모듈 Owner 확인 대상. 실측 숫자를 근거로 안건화.
5. **D-3 / E** — 표기 정정. 급하지 않다.
