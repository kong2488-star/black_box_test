# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 성격 — 이건 제품 코드가 아니다

`modules/search/` 의 두 스크립트는 **일회용 탐침(throwaway probe)**이다. 계약도 구현도 아니고,
Gemini 영상 파이프라인의 실측 숫자(토큰·원가·지연·판정 분포)를 얻으려는 측정 도구다.
기준이 되는 제품 레포는 **`ktc4-chonnam-2`** 이고, 이 탐침은 검증 뒤 그 레포로 옮길 때
번역 작업이 되지 않도록 그 레포의 계약·양식·CI 제약을 미리 지킨다. 문서에 나오는
`contract-*.md`, `experiment-guide.md`, `AnalysisRun` 등은 전부 그 레포의 것이다.

주석과 리포트는 한국어로 쓰여 있다. 스타일을 맞춰라.

## 명령어

```bash
# 환경
uv venv && uv pip install google-genai       # google-genai >= 2.13 필수 (아래 SDK 함정 참조)

# API 키: .env 파일(GEMINI_API_KEY=...) 또는 환경변수. 환경변수가 .env 를 이긴다.
cp .env.example .env

# 영상 분할 (직접) — 클립은 저장소에 넣지 않는다(.gitignore)
ffmpeg -i <원본> -c copy -f segment -segment_time 300 -reset_timestamps 1 clips/clip_%03d.mp4

# 1단계 Coarse — 긴 클립에서 후보 구간을 찾는다
python modules/search/coarse_probe.py chunks/ --concurrency 3
python modules/search/coarse_probe.py --list-models        # 이 키로 쓸 수 있는 모델 ID
python modules/search/coarse_probe.py chunks/ --tag run2   # 재현성 회차
python modules/search/coarse_probe.py --report-only        # API 호출 없이 리포트만 재생성

# 2단계 Fine — Coarse 후보를 하나씩 정밀 검증한다 (Coarse 가 먼저 돌아 있어야 한다)
python modules/search/fine_probe.py --limit 5              # 먼저 앞 5건으로 확인
python modules/search/fine_probe.py                        # 전체
python modules/search/fine_probe.py --event SOLID_LINE_LANE_CHANGE
python modules/search/fine_probe.py --print-prompt SIGNAL  # 프롬프트 원문 확인(Owner 검토용)
python modules/search/fine_probe.py --report-only

# 프롬프트 참고 문서 재생성 — Coarse 1 + Fine 4 를 PROMPTS.md 로 찍는다.
# 프롬프트(PROMPT/COMMON_BLOCK/DELTAS)를 고쳤으면 이걸 돌려 문서를 맞춘다. 손으로 PROMPTS.md 를 고치지 않는다.
python modules/search/dump_prompts.py
```

테스트 스위트·린터·빌드는 없다. 검증은 실제 API 호출 결과와 리포트로 한다.

## 아키텍처

**2단계 파이프라인.** Coarse(싸게 넓게 탐색) → Fine(비싸게 좁게 검증). `coarse_probe.py` →
`fine_probe.py` 로 데이터가 흐르되, 결합은 파일 하나뿐이다:

- `probe_runs.jsonl` — Coarse 출력. **Fine 의 입력이 곧 이 파일**이다.
  Fine 은 Coarse 가 이미 올린 Files API 참조(`file_uri`)를 재사용해 `start_offset`/`end_offset`
  만 걸어 같은 영상을 다시 부른다 — ffmpeg 재분할도 재업로드도 없다.
- `fine_probe_runs.jsonl` — Fine 출력.

**jsonl 은 append-only, 절대 덮어쓰지 않는다.** 성공·실패·건너뜀이 전부 한 줄씩 사실로 쌓인다.
리포트(`*_report.md`)는 그 jsonl 에서 **파생**되며 `--report-only` 로 언제든 다시 만들 수 있다.
캐시(`build_caches`)가 같은 조건(clip/tag/prompt_hash/model/res/fps/…)으로 이미 성공한 항목을
건너뛰므로 재실행이 안전하다. `--force` 로 무시한다.

**두 스크립트는 구조가 대칭이다** (`load_api_key`/`ensure_uploaded`/`read_usage`/`process_*`/
`write_report`). `read_usage` 는 Fine 에서 Coarse 로 역이식된 것이라 거의 동일하다. 한쪽을
고치면 다른 쪽도 봐야 한다.

**프롬프트는 search Owner 소유다. 스크립트가 문구를 만들거나 고치지 않는다.** Fine 프롬프트는
공통 블록 1개 + 유형별 델타 4개(`DELTAS`) 조립이다. 이벤트 4종: `SIGNAL`,
`CENTER_LINE_CROSSING`, `SOLID_LINE_LANE_CHANGE`(Coarse 의 옛 이름 `LANE_CHANGE` 에서 매핑),
`MOTORCYCLE_HELMET_NON_USE`.

**이 탐침은 hard-negative 기각 시험이다.** 원본이 자동차전용도로 주행 영상이라 실선·이륜차가
거의 없어 정답이 대부분 `NOT_OBSERVED` 다. 점선 차로변경 기각은 Fine 이 제대로 작동한 것이므로
`FINE_FALSE_NEGATIVE` 로 세면 지표가 뒤집힌다 — 그래서 리포트가 그 숫자를 자동으로 찍지 않는다.

## 반드시 지킬 불변식 (어기면 조용히 틀린 숫자가 나온다)

- **번호판 마스킹.** 모델은 묻지 않아도 `observed`/자유텍스트에 번호판을 넣는다(실측). 저장 직전에
  `mask_sensitive()`(정규식 `\d{2,3}\s*[가-힣]\s*\d{4}`)가 지운다. Fine 의 유출 스캔은 **원문에서**
  돌고 마스킹은 **그 뒤**에 한다 — 순서를 바꾸면 프롬프트 방어선 측정이 사라진다. 새 탐침을 만들면
  같은 마스킹을 통과시키고, 커밋 전 확인: `grep -rnE "[0-9]{2,3} ?[가-힣] ?[0-9]{4}" modules/`

- **usage 는 `or 0` 으로 뭉개지 않는다.** `None`(provider 가 안 줌)과 `0`(안 씀)은 다르다.
  `or 0` 이면 원가가 조용히 0 으로 보고된다. `total_thought_tokens` 를 반드시 읽는다 —
  실측상 `total_tokens = input + output + thought` 라 thought 를 빼면 원가가 과소 보고된다.

- **원본 절대시각은 ffprobe 실측 길이의 누적으로 환산한다.** `ffmpeg -c copy` 는 키프레임 경계에서
  자르므로 세그먼트가 정확히 300초가 아니다(실측 304.30 / 298.97 / 244.50). `clip_ordinal × 300`
  가정은 최대 4.47초 어긋나는데 후보 span 이 4~9초라 오차가 span 길이와 맞먹는다. 시각 정확도가
  제품의 급소다. (Fine 은 실측 누적을 쓰고, Coarse 리포트는 아직 300초 가정이다 — 알려진 별건.)

- **스키마로 막지 않고 세는 것들.** `check_invariants` 가 계약 위반(0건이 정상)과 관찰용 watch 를
  나눠 센다. verification↔event_type 결합을 스키마에 넣지 않는 것은 의도다 — 디코더가 맞춰 준 필드는
  모델의 판단을 알려주지 않으므로 실패하게 두고 세야 한다. 스키마에 `legal_status` 같은 법적 필드를
  두지 않고, `NONE` 센티널을 null 대신 쓴다(provider 의 nullable enum 지원이 불확실).

## SDK 함정 (구현 전에 반드시)

- **`google-genai >= 2.13` 필수.** 이하 버전은 `processing`(fps·offset·resolution)을 요청 본문에서
  **조용히 빼버린다** — 에러 없이. 8초 구간을 요청해도 클립 전체가 처리돼 원가가 15배 된다.
  `fine_probe.py:check_sdk()` 가 낮은 버전을 막고 각 row 에 `sdk_version` 을 남긴다.
- **`start_offset`/`end_offset` 은 정수 ms 가 아니라 duration 문자열**(`"37.000s"`)이다. 구글 문서는
  "In milliseconds" 로 적었지만 SDK 타입은 `Optional[str]` 이다.
- **`input` 은 반드시 `ix.VideoContent(...)`/`ix.TextContent(...)` 객체로.** raw dict 를 넘기면
  pydantic 이 `List[Step]` 으로 먼저 매칭해 `UnknownStep` 으로 삼키고 필드가 전부 사라진다(검증은 통과).
- **플래그를 믿지 말고 토큰 수로 확인한다.** 구간·fps 가 실제 전송됐는지는 `video 토큰/구간초` 로만
  검증된다(low@1fps≈100, high@1fps≈290, high@2fps≈553). 리포트가 이 값을 찍는다.

## 이 탐침이 재지 못하는 것 (리포트도 이렇게 명시한다)

Recall(정답지 없음), 절대 시각 정확도(readout 모듈 소유), `CENTER_LINE_CROSSING`/
`MOTORCYCLE_HELMET_NON_USE` 성능(후보 0건). 이 결과를 Recall 주장이나 4종 전체 성능 주장으로 쓰지 말 것.
비용은 파일 상단 단가 상수 기준 **추정치**이며, 3.x flash 는 2027-01-01 부터 단가가 2배가 된다
(상수를 안 고치면 리포트 비용이 절반으로 나온다).
