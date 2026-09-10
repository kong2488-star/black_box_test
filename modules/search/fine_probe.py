"""
fine_probe.py — search Fine 탐침 (throwaway)

이 파일은 제품 코드가 아니다. 계약도 구현도 아니고, 실측 숫자를 얻기 위한
일회용 스크립트다. 결과가 나오면 리포트만 남기고 버려도 된다.

기준 레포는 `ktc4-chonnam-2` 다. 계약·양식·CI 제약을 여기서 미리 지켜서,
검증 뒤 그 레포로 옮길 때 번역 작업이 되지 않게 한다.

무엇을 재는가
    - Fine 이 도는가, 후보 하나당 몇 초·몇 토큰·얼마인가
    - 45개 후보의 verification 분포 — **Coarse 오탐(hard-negative)을 거르는가**
    - 모델이 말한 근거 시점(evidence_at_ms)이 실제 장면과 맞는가
    - 모델이 만들어내는 primitive kind / fact 어휘 (계약이 Pending 으로 둔 값 공간)
    - 계약 불변조건 위반 건수, 3값 혼동 건수, 경계 유출(번호판·법적판단) 건수

무엇을 재지 못하는가
    - Recall. 정답지가 없으므로 놓친 사건은 셀 수 없다.
    - 절대 시각 정확도. 화면시각 판독은 readout 소유다. 여기서는 클립 상대시간만 본다.
    - CENTER_LINE_CROSSING / MOTORCYCLE_HELMET_NON_USE 의 성능.
      Coarse 후보에 0건이다(원본이 자동차전용도로 주행 영상이라 이륜차가 없다).
      델타 4개 중 2개는 이번에 전혀 시험되지 않는다.

    이 결과를 Recall 주장이나 4종 전체 성능 주장으로 쓰지 말 것.

★ 이 탐침의 성격
    Coarse 후보 45건의 observed 텍스트에 "점선" 11건 · "실선" 0건이다.
    SOLID_LINE_LANE_CHANGE 는 실선을 요구하므로, **정답이 대부분 NOT_OBSERVED**다.
    즉 이건 hard-negative 기각 시험이다. 점선 차로변경 기각은 Fine 이 제대로
    작동한 것이므로 FINE_FALSE_NEGATIVE 로 세면 지표가 뒤집힌다.
    리포트가 그 숫자를 자동으로 찍지 않는 이유다.

사전 준비
    Coarse 탐침이 먼저 돌아 `probe_runs.jsonl` 에 후보가 있어야 한다.
    Fine 은 그 후보를 읽어 같은 업로드 파일에 offset 만 걸어 호출한다 —
    ffmpeg 재분할이 없다. Files API 48h 만료 시에는 자동으로 다시 올린다.

    API 키는 coarse_probe.py 와 같은 방식이다. 환경변수가 .env 를 이긴다.

실행 (저장소 루트에서)
    python modules/search/fine_probe.py                      # 모든 후보
    python modules/search/fine_probe.py --limit 5            # 앞 5건만 (먼저 이걸로 확인)
    python modules/search/fine_probe.py --event SOLID_LINE_LANE_CHANGE
    python modules/search/fine_probe.py --padding 5 --tag pad5
    python modules/search/fine_probe.py --report-only        # API 호출 없이 리포트만
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 설정 — 여기만 만지면 된다
# ---------------------------------------------------------------------------

MODEL = "gemini-3.7-flash"   # Coarse 와 같게 둔다. 변수를 하나만 바꾼다
MEDIA_RESOLUTION = "high"    # 실선/점선·신호색 판별이 화질에 직접 걸린다
FPS = 2.0                    # 짧은 구간이므로 Coarse(1.0)보다 올린다
PADDING_SEC = 2.0            # 후보 span 앞뒤 여유. Fine 입력 = span ± padding
CONCURRENCY = 3              # 무료 티어 rate limit이 실제 상한이다
CLIP_SECONDS = 300           # Coarse 클립 길이. 원본 절대시각 환산용

# experiment-guide.md §7 — 프롬프트 전문을 실험 기록에 복사하지 않고 버전으로 가리킨다
PROMPT_VERSION = "fine-p1"

# gemini-3.7-flash 유료 티어 (2026-09 기준, 100만 토큰당 USD).
# 주의: 3.x Flash 는 2027-01-01 부터 2배로 오른다 (0.75 -> 1.50, 3.75 -> 7.50).
# Flash-Lite 계열에는 이 인상이 없다.
PRICE_IN_PER_1M_USD = 0.75
PRICE_OUT_PER_1M_USD = 3.75

# ---------------------------------------------------------------------------
# 이벤트 유형 — 계약 이름을 쓴다
#
# contract-visual-evidence.md §4-2 의 닫힌 enum 이다.
# Coarse 탐침은 아직 옛 이름 LANE_CHANGE 를 쓰고 있다. 2026-09-05 ADR 이
# LANE_CHANGE -> SOLID_LINE_LANE_CHANGE 로 전량 교체했다.
# Coarse 상수를 고치면 기존 45건과 비교가 끊기므로 여기서 매핑하고,
# 매핑했다는 사실을 각 row 에 남긴다 — 그래야 NOT_OBSERVED 폭증이
# 매핑 탓인지 모델 탓인지 갈린다.
# ---------------------------------------------------------------------------

EVENT_TYPES = [
    "SIGNAL",
    "CENTER_LINE_CROSSING",
    "SOLID_LINE_LANE_CHANGE",
    "MOTORCYCLE_HELMET_NON_USE",
]

COARSE_TO_CONTRACT = {
    "LANE_CHANGE": "SOLID_LINE_LANE_CHANGE",   # 옛 이름
}

# ---------------------------------------------------------------------------
# 프롬프트 — 공통 블록 1개 + 유형별 델타 4개
#
# 프롬프트는 search Owner 가 작성·확정한다. 스크립트가 문구를 만들거나 고치지 않는다.
# 아래는 Owner 검토용 초안이다.
#
# 공통 블록이 temporal_facts 를 "필요할 때 쓰는 배열"로만 정의하는 것은 의도다.
# 공통이 "시간 순서를 반드시 기록하라"고 하면 안전모 델타가 그것을 취소해야 하고,
# 취소 지시는 가장 안 지켜진다. 공통의 과소 규정이 델타의 부정보다 낫다.
# ---------------------------------------------------------------------------

COMMON_BLOCK = """\
당신은 이미 지정된 **짧은 영상 구간 하나를 정밀 확인하는 Fine Verification 모델**입니다.

**탐색하지 않습니다. 구간은 이미 주어졌습니다.** 이 구간에서 아래 한 가지 사건이 성립하는지만 판단하세요.

## 검증 대상

`{EVENT_TYPE}`

{EVENT_DEFINITION}

### 성립에 필요한 관찰 (모두 충족해야 성립입니다)

{REQUIRED_CONDITIONS}

### 이 사건의 성립 축

{AXIS}

## 앞 단계가 넘긴 참고 정보

* 앞 단계의 유형 추정: `{HINT_TYPE}`
* 앞 단계의 관찰 요약: `{HINT_SUMMARY}`

**이것은 참고이며 확정이 아닙니다.** 앞 단계는 놓치지 않는 것을 우선했기 때문에 유형 추정이 틀릴 수 있습니다. 앞 단계의 요약을 근거로 취급하지 말고, 이 구간의 영상에서 직접 관찰한 것만 사용하세요.

## 시간 기준

모든 시간은 **주어진 구간의 시작을 0으로 하는 상대 시간(밀리초)**입니다. 절대 시각, 날짜, 영상에 찍힌 시계는 사용하지 마세요.

## 판단 절차

**① 먼저 세 값 중 하나를 고르세요.** 기준은 확신의 정도가 아니라 **볼 수 있었는지**입니다.

* `OBSERVED` — 위 필수 관찰이 **모두** 확인되었다.
* `NOT_OBSERVED` — 필요한 것을 **볼 수 있었고**, 본 결과 사건이 성립하지 않았다. 즉 **"보았고, 없었다"**.
* `UNCERTAIN` — 필요한 것을 **볼 수 없어서** 성립·불성립을 정할 수 없었다. 즉 **"보지 못했다"**. 가림, 야간, 흐림, 낮은 해상도, 화면 밖, 구간 밖이 이유가 됩니다.

**세 값 중 어느 것도 더 바람직하지 않습니다.** 근거가 가리키는 값을 고르세요. 근거가 불충분하면 `UNCERTAIN` 이 정답입니다. 억지로 `OBSERVED` 나 `NOT_OBSERVED` 를 고르지 마세요.

**② `event_type` 은 `OBSERVED` 일 때만 적으세요.** `NOT_OBSERVED` 와 `UNCERTAIN` 에서는 반드시 `"NONE"` 입니다.

**③ 고른 값에 따라 반드시 남겨야 하는 것이 있습니다.**

* `UNCERTAIN` 이면 **무엇을 볼 수 없었는지**를 `uncertainties` 에 최소 한 항목 적으세요. 비어 있는 `uncertainties` 와 함께 `UNCERTAIN` 을 내는 것은 잘못된 출력입니다.
* `NOT_OBSERVED` 이면 **무엇을 보았고 어느 요건이 어긋났는지**를 `primitives` 에 적으세요. 비어 있는 `primitives` 와 함께 `NOT_OBSERVED` 를 내는 것은 잘못된 출력입니다.
* 어느 값이든, 대상 차량·객체를 식별할 수 있었다면 `target` 을 채우세요. 사건이 성립하지 않은 경우에도 마찬가지입니다.

## 관찰 기록 원칙

* **`primitives`** — 관찰한 시각 요소를 `kind` + `state` 로 적습니다.
  * `state` 는 `PRESENT`(있음) / `ABSENT`(없음) / `UNCERTAIN`(판별 불가) 셋입니다.
  * **없음은 부정형 이름이 아니라 긍정형 이름 + `ABSENT` 로 적으세요.** 예: 안전모를 쓰지 않았다면 `HELMET_ABSENT` 가 아니라 `kind: "HELMET_ON_RIDER"`, `state: "ABSENT"` 입니다.
  * **가려져서 판별할 수 없었던 것은 `ABSENT` 가 아니라 `UNCERTAIN` 입니다.** 보이지 않은 것과 없는 것은 다릅니다.
  * `kind` 이름은 아래 예시에 없어도 됩니다. 관찰한 것을 적절한 이름으로 적으세요.
* **`temporal_facts`** — 시간에 따른 변화나 순서가 근거가 될 때 사용하는 배열입니다. 이 사건의 성립 축이 시간이 아니라면 비워 두어도 됩니다.
* **`uncertainties`** — 판단을 제한한 것을 적습니다. 불확실한 채로 `OBSERVED` 를 내지 마세요. 남은 불확실성은 반드시 여기 남기세요.
* **모든 관찰 항목에 `evidence_at_ms` 를 붙이세요.** 그 관찰의 근거가 보이는 시점(구간 시작 기준 밀리초)입니다. 여러 시점이면 여러 개 적으세요.
* **확신도(`confidence`)는 관찰 단위로만 적고, 전체를 하나의 숫자로 요약하지 마세요.** 정의할 수 없으면 적지 마세요. `0`을 대신 넣지 마세요.

## 하지 말 것

* 법규 위반 여부, 과실, 책임, 신고 대상 여부를 판단하지 마세요. 운전자의 의도를 추정하지 마세요.
* 위반을 표현하는 문구나 처분 종류를 만들지 마세요.
* **번호판 문자를 읽거나 적지 마세요.** 대상은 색·차종·위치 같은 외형으로만 서술하세요.
* 영상에 찍힌 날짜·시각을 읽거나 적지 마세요.
* 절대 시각이나 날짜를 사용하지 마세요.
* 위치, 좌표, 지명, 주소를 추측하지 마세요.
* 영상에서 직접 관찰할 수 없는 것을 적지 마세요.

## 마지막으로

**지지하는 근거를 찾지 못했다면 `NOT_OBSERVED` 가 정상적인 결과입니다.** 억지로 사건을 만들어내지 마세요."""


# 유형별 델타 — 4슬롯: 정의 / 필수 요건 / primitive 예시 / 성립 축
DELTAS = {
    "SIGNAL": {
        "definition": (
            "교차로에서 신호등의 점등 상태와 대상 차량의 정지선 통과가 함께 관찰되는 사건입니다."
        ),
        "conditions": (
            "① 신호등의 점등 상태를 식별할 수 있다\n"
            "② 대상 차량이 정지선을 통과하는 시점을 식별할 수 있다\n"
            "③ 그 둘의 **시간 관계**를 관찰할 수 있다"
        ),
        "primitives_hint": "`RED_SIGNAL`, `GREEN_SIGNAL`, `STOP_LINE`, `TARGET_VEHICLE`",
        "axis": (
            "**시간 순서가 이 사건의 실체입니다.** 신호 상태와 정지선 통과 시점을 "
            "`temporal_facts` 에 각각의 `at_offset_ms` 와 함께 적으세요.\n"
            "두 시점 중 하나라도 밀리초로 짚을 수 없다면 `NOT_OBSERVED` 가 아니라 `UNCERTAIN` 입니다."
        ),
    },
    "CENTER_LINE_CROSSING": {
        "definition": (
            "차량이 중앙선을 넘어 반대 차로 쪽으로 차체가 걸치거나 진입하는 사건입니다."
        ),
        "conditions": (
            "① 차량이 넘은 선을 **중앙선(황색 실선 또는 황색 복선)으로 식별**할 수 있다\n"
            "② 차체가 그 선을 넘거나 걸친다\n"
            "③ 그 진입이 시간에 따라 진행되는 것을 관찰할 수 있다"
        ),
        "primitives_hint": (
            "`YELLOW_CENTER_LINE`, `YELLOW_DOUBLE_LINE`, `TARGET_VEHICLE`, `VEHICLE_BODY_OVER_LINE`"
        ),
        "axis": (
            "성립 축은 시간에 따른 차체 위치 변화입니다. `temporal_facts` 를 사용하세요.\n"
            "선의 색·종류를 판별할 수 없었다면 `UNCERTAIN` 입니다. "
            "판별했고 차량이 넘지 않았다면 `NOT_OBSERVED` 입니다."
        ),
    },
    "SOLID_LINE_LANE_CHANGE": {
        "definition": (
            "차량이 **백색 실선**을 넘어 인접 차로로 이동하는 사건입니다."
        ),
        "conditions": (
            "① 차량이 넘은 선을 **백색 실선으로 식별**할 수 있다\n"
            "② 차체가 그 선을 가로질러 인접 차로로 이동한다"
        ),
        "primitives_hint": (
            "`WHITE_SOLID_LINE`, `WHITE_DASHED_LINE`, `TARGET_VEHICLE`, `VEHICLE_CROSSES_LINE`"
        ),
        "axis": (
            "성립 축은 시간에 따른 차체의 횡단입니다. `temporal_facts` 를 사용하세요.\n\n"
            "**중요 — 배제 조항:** 점선(파선) 구간에서의 차로 변경은 이 사건이 **아닙니다**. "
            "넘은 선이 점선이었다면 `kind: \"WHITE_SOLID_LINE\"`, `state: \"ABSENT\"` 로 기록하고 "
            "`NOT_OBSERVED` 를 반환하세요. 차로 변경 자체가 관찰되었다는 것만으로 성립하지 않습니다.\n"
            "선의 종류를 판별할 수 없었다면 `UNCERTAIN` 입니다."
        ),
    },
    "MOTORCYCLE_HELMET_NON_USE": {
        "definition": (
            "이륜차 탑승자의 머리에 안전모가 관찰되지 않는 사건입니다. "
            "시간 순서가 아니라 한 장면의 객체 속성으로 판단합니다."
        ),
        "conditions": (
            "① 대상이 이륜차 탑승자로 식별된다\n"
            "② 탑승자의 **머리 부분이 실제로 보인다** (가려지거나 흐려서 판별 불가한 상태가 아니다)\n"
            "③ 그 머리에 안전모가 없다"
        ),
        "primitives_hint": "`MOTORCYCLE_RIDER`, `HELMET_ON_RIDER`",
        "axis": (
            "**시간 순서가 필요하지 않습니다.** `temporal_facts` 를 비워 두어도 정상입니다.\n\n"
            "**중요 — 상태 구분:** 머리가 잘 보이고 안전모가 없으면 "
            "`kind: \"HELMET_ON_RIDER\"`, `state: \"ABSENT\"` 입니다.\n"
            "머리가 가려졌거나 흐려서 안전모 유무를 판별할 수 없었다면 "
            "`state: \"UNCERTAIN\"` 이고 전체 판정도 `UNCERTAIN` 입니다.\n"
            "**\"안전모가 보이지 않는다\" 를 곧바로 `ABSENT` 로 적지 마세요.** "
            "보이지 않은 것과 없는 것은 다릅니다."
        ),
    },
}

# ---------------------------------------------------------------------------
# 출력 스키마
#
# Interactions API 의 response_format 은 표준 JSON Schema(소문자 type)를 쓴다.
#
# ★ legal_status 를 두지 않는다.
#   계약은 "키 존재 + 항상 null" 이지만 그 값을 채우는 것은 모델이 아니라
#   직렬화 계층이다. 값이 하나뿐인 필드는 0비트를 전달한다. 그리고 모델 앞에
#   legal_status 라는 토큰을 놓는 것 자체가 법적 추론을 권하는 일이다.
#   없는 필드는 채울 수 없다 — 생략이 null 강제보다 강한 강제다.
#
# ★ evidence_refs 대신 evidence_at_ms 를 쓴다.
#   계약의 evidence_refs 는 recording 이 발급하는 opaque frame ref 이고
#   탐침은 만들 수 없다. 강제하면 모델이 존재하지 않는 식별자를 발명한다 —
#   조작된 식별자는 유효한 것과 구별되지 않아 가장 해로운 환각이다.
#   조작된 숫자는 영상을 열어 반증할 수 있다.
#   계약 필드명을 재사용하지 않는 것도 의도다. 탐침 산출물이 계약 payload 처럼
#   보이면 누군가 그대로 소비한다.
#
# ★ kind / fact / uncertainties[].kind 를 enum 으로 닫지 않는다.
#   ADR 이 새 코드 추가를 별도 ADR 없이 허용하므로 닫으면 계약 위반이다.
#   무엇을 만들어내는지가 관찰 대상이기도 하다.
#
# ★ verification 과 event_type 을 스키마에서 결합하지 않는다.
#   "OBSERVED 면 event_type non-null" 은 oneOf/if-then 으로 표현할 수 있지만
#   이 provider 가 지키는지 미확인이고, 미지원 키워드는 조용히 무시될 수 있다
#   (같은 함정: VideoContent 가 processing 을 선언하지 않고 extra=allow 라
#    필드명 오타가 에러 없이 삼켜진다).
#   더 중요한 이유는 측정이다. 디코더가 맞춰 준 필드는 모델의 판단을 알려주지
#   않는다. 이 불변조건은 실패하게 두고 세어야 한다. 도구가 사후 검증한다.
#
# ★ null 대신 "NONE" 센티널을 쓴다.
#   nullable enum 의 provider 지원이 불확실하다. coarse_probe.py 가 이미
#   같은 선택을 했다(enum + "NONE"). 도구가 기록할 때 계약의 null 로 환산한다.
# ---------------------------------------------------------------------------

_EVIDENCE_AT_MS = {
    "type": "array",
    "items": {"type": "integer"},
    "description": "이 관찰의 근거가 보이는 시점(구간 시작 기준 밀리초).",
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verification": {
            "type": "string",
            "enum": ["OBSERVED", "NOT_OBSERVED", "UNCERTAIN"],
            "description": "관찰 상태. 실행 성공/실패가 아니다.",
        },
        "event_type": {
            "type": "string",
            "enum": EVENT_TYPES + ["NONE"],
            "description": "OBSERVED 일 때만 유형을 적는다. 아니면 NONE.",
        },
        "target": {
            "type": "object",
            "description": "대상 association 관찰. 식별할 수 없었으면 association_status 만 채운다.",
            "properties": {
                "association_status": {
                    "type": "string",
                    "enum": ["MATCHED", "AMBIGUOUS", "NOT_FOUND"],
                },
                "described_as": {
                    "type": "string",
                    "description": "외형만. 색·차종·위치. 번호판 문자를 넣지 않는다.",
                },
                "association_confidence": {"type": "number"},
                "evidence_at_ms": _EVIDENCE_AT_MS,
            },
            "required": ["association_status"],
        },
        "primitives": {
            "type": "array",
            "description": "관찰한 시각 요소. 없음은 긍정 kind + ABSENT 로 적는다.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": "관찰 요소 이름. 예시 목록에 없어도 된다.",
                    },
                    "state": {
                        "type": "string",
                        "enum": ["PRESENT", "ABSENT", "UNCERTAIN"],
                    },
                    "confidence": {"type": "number"},
                    "evidence_at_ms": _EVIDENCE_AT_MS,
                },
                "required": ["kind", "state", "evidence_at_ms"],
            },
        },
        "temporal_facts": {
            "type": "array",
            "description": "시간 변화·순서가 근거일 때 사용. 객체 속성 사건이면 빈 배열이 정상.",
            "items": {
                "type": "object",
                "properties": {
                    "at_offset_ms": {
                        "type": "integer",
                        "description": "구간 시작 기준 밀리초.",
                    },
                    "fact": {"type": "string"},
                    "evidence_at_ms": _EVIDENCE_AT_MS,
                },
                "required": ["fact", "evidence_at_ms"],
            },
        },
        "uncertainties": {
            "type": "array",
            "description": "판단을 제한한 것. UNCERTAIN 이면 최소 한 항목.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "detail": {"type": "string"},
                    "evidence_at_ms": _EVIDENCE_AT_MS,
                },
                "required": ["kind"],
            },
        },
    },
    "required": ["verification", "event_type", "primitives", "temporal_facts", "uncertainties"],
}

# ---------------------------------------------------------------------------
# 경계 유출 스캔
#
# 가설이 아니다. Coarse 는 번호판을 묻지도 않았는데 모델이 observed 에
# 실제 차량 번호를 넣었다 (probe_report.md, 45건 중 1건. 값은 여기 적지 않는다).
# 계약에는 이걸 막는 조항이 없다. 프롬프트가 사실상 유일한 방어선이고,
# 그 방어선이 작동하는지는 출력을 뒤져서만 알 수 있다.
#
# 이 패턴들은 heuristic 이다. 걸리면 사람이 봐야 한다는 신호이고
# 걸리지 않았다고 유출이 없었다는 뜻은 아니다.
# ---------------------------------------------------------------------------

PLATE_RE = re.compile(r"\d{2,3}\s*[가-힣]\s*\d{4}")


def mask_sensitive(text: str) -> str:
    """저장 전에 번호판 문자열을 지운다.

    ★ 기록에 남기면 안 되는 값이다 — `product-spec` §7 과
      `contract-usage-record` 가 번호판 문자열 보관을 금지한다.
      모델은 묻지 않아도 이 값을 출력한다(Coarse 45건 중 1건 실측).

    ★ 순서가 중요하다. 유출 스캔은 **원문에서** 돌려야 프롬프트 방어선이
      작동하는지 측정된다. 마스킹은 스캔 **뒤에** 한다.
      스캔 결과에도 원문 발췌를 넣지 않는다 — 패턴 이름과 마스킹된 발췌만 남긴다.
    """
    return PLATE_RE.sub("[번호판]", text)


def mask_deep(obj):
    """중첩 구조 안의 모든 문자열에 마스킹을 적용한다."""
    if isinstance(obj, str):
        return mask_sensitive(obj)
    if isinstance(obj, list):
        return [mask_deep(x) for x in obj]
    if isinstance(obj, dict):
        return {k: mask_deep(v) for k, v in obj.items()}
    return obj


LEAK_PATTERNS = {
    "plate": PLATE_RE,
    "legal": re.compile(r"위반|불법|과실|처벌|벌점|범칙|입건|단속"),
    "clock": re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}:\d{2}|오전|오후"),
    "place": re.compile(r"위도|경도|GPS|좌표|[가-힣]{2,}(?:대로|로|길)\s*\d"),
}

# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
COARSE_RUNS_PATH = HERE / "probe_runs.jsonl"
RUNS_PATH = HERE / "fine_probe_runs.jsonl"
REPORT_PATH = HERE / "fine_probe_report.md"

MIME_BY_EXT = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".ts": "video/mp2t",
    ".webm": "video/webm",
}

_write_lock = threading.Lock()
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# API 키 — coarse_probe.py 와 같은 규칙. 환경변수가 .env 를 이긴다.
# ---------------------------------------------------------------------------


def find_env_files() -> list[Path]:
    seen, out = set(), []
    for d in (Path.cwd(), HERE, HERE.parent.parent):
        f = (d / ".env").resolve()
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def parse_env_file(path: Path) -> dict:
    data: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return data
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not key:
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            val = val.split(" #")[0].strip()
        data[key] = val
    return data


def load_api_key() -> tuple[str | None, str]:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(name)
        if v:
            return v.strip(), f"환경변수 {name}"
    for f in find_env_files():
        if not f.is_file():
            continue
        data = parse_env_file(f)
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if data.get(name):
                return data[name].strip(), f"{f} 의 {name}"
    return None, ""


def mask(key: str) -> str:
    return f"{key[:4]}...{key[-4:]} ({len(key)}자)" if len(key) > 12 else "(짧음)"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# 후보 수집 — Coarse 기록에서 읽는다
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 깨진 줄은 건너뛴다. 원본은 그대로 둔다.
    return rows


def collect_candidates(coarse_rows: list[dict], coarse_tag: str | None,
                       geo: dict) -> list[dict]:
    """Coarse 기록에서 Fine 이 검증할 후보 목록을 만든다.

    후보 1건당 1호출이므로 여기서 나온 항목 수가 곧 호출 수다.
    같은 클립의 후보들은 하나의 업로드를 공유한다.

    ★ 클립 길이를 벗어난 후보에 `out_of_clip` 을 붙인다. 조용히 잘라내지 않는다.
      실측에서 part_07(298.97초)의 후보 4건이 345/414/444/453초를 말했다 —
      물리적으로 불가능한 시각이고 Fine 의 문제가 아니라 Coarse 출력의 결함이다.
      1초짜리 구간으로 뭉개서 호출하면 호출만 낭비하고 판정 분포를 오염시킨다.
      이건 **Coarse timestamp 실패의 실측치**이므로 세어서 리포트에 낸다.
    """
    out: list[dict] = []
    for r in coarse_rows:
        if not r.get("ok"):
            continue
        if coarse_tag and r.get("tag") != coarse_tag:
            continue
        cands = r.get("candidates")
        if not cands:
            continue
        for i, c in enumerate(cands):
            span = c.get("span") or {}
            start = span.get("start_sec")
            end = span.get("end_sec")
            if start is None or end is None:
                continue
            raw_type = c.get("event_type") or "NONE"
            mapped = COARSE_TO_CONTRACT.get(raw_type, raw_type)
            g = geo.get(r.get("clip_path")) or {
                "duration_sec": float(CLIP_SECONDS), "start_sec": 0.0, "source": "assumed"}
            out.append({
                "candidate_key": f"{r.get('clip')}#{i}",
                "clip": r.get("clip"),
                "clip_path": r.get("clip_path"),
                "clip_index": r.get("clip_index"),
                "clip_ordinal": r.get("clip_ordinal"),
                "clip_duration_sec": g["duration_sec"],
                "clip_start_sec": g["start_sec"],
                "duration_source": g["source"],
                "out_of_clip": float(start) >= g["duration_sec"],
                "coarse_tag": r.get("tag"),
                "coarse_file_uri": r.get("file_uri"),
                "coarse_file_name": r.get("file_name"),
                "span_start_sec": float(start),
                "span_end_sec": float(end),
                "coarse_at_sec": c.get("at_sec"),
                "coarse_score": c.get("score"),
                "hint_type_raw": raw_type,
                "hint_type": mapped,
                "hint_type_remapped": mapped != raw_type,
                # Coarse 의 observed 를 그대로 옮기면 거기 섞인 번호판까지 따라온다.
                # 실측으로 확인된 경로다 — 마스킹해서 넘긴다.
                "hint_summary": mask_sensitive("; ".join(c.get("observed") or [])),
            })
    out.sort(key=lambda c: (c.get("clip_index") or 0, c["candidate_key"]))
    return out


def probe_duration(path: str) -> float | None:
    """ffprobe 로 실제 길이(초)를 읽는다. ffprobe 가 없거나 실패하면 None."""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        return float(out) if out else None
    except Exception:  # noqa: BLE001 — 없으면 가정으로 떨어진다
        return None


def clip_geometry(coarse_rows: list[dict]) -> dict:
    """clip_path -> {duration_sec, start_sec, source}

    ★ CLIP_SECONDS 를 가정하지 않는다.
      ffmpeg -c copy 로 자르면 키프레임 경계 때문에 세그먼트가 정확히 300초가 아니다.
      실측: 304.30 / 298.97 x4 / 304.30 / 298.97 / 244.50 (마지막이 짧다).
      가정 300초로 누적하면 마지막 클립에서 원본 위치가 약 3.4초 어긋난다.
      **시각 정확도가 제품의 급소이므로 이 3.4초를 가정으로 흘리지 않는다.**

      ffprobe 가 없으면 CLIP_SECONDS 로 떨어지고 source 를 "assumed" 로 남긴다.
      리포트가 그 사실을 표시한다.
    """
    seen: dict[str, int] = {}
    for r in coarse_rows:
        p = r.get("clip_path")
        if p and p not in seen:
            seen[p] = r.get("clip_index") or 0

    geo: dict[str, dict] = {}
    cursor = 0.0
    for p in sorted(seen, key=lambda k: (seen[k], k)):
        d = probe_duration(p)
        geo[p] = {
            "duration_sec": d if d is not None else float(CLIP_SECONDS),
            "start_sec": round(cursor, 3),
            "source": "ffprobe" if d is not None else "assumed",
        }
        cursor += geo[p]["duration_sec"]
    return geo


def fine_window(cand: dict, padding: float, clip_len: float) -> tuple[int, int, bool]:
    """Fine 입력 구간(ms)과 clamp 여부. 후보 span 앞뒤로 padding 을 붙인다.

    span 이 클립을 부분적으로만 넘으면 잘라서 쓰고 clamp 사실을 남긴다.
    span 이 통째로 클립 밖이면 여기서 다루지 않는다 — collect_candidates 가 걸러낸다.
    """
    start = max(0.0, cand["span_start_sec"] - padding)
    end = min(clip_len, cand["span_end_sec"] + padding)
    clamped = (cand["span_end_sec"] + padding) > clip_len or (cand["span_start_sec"] - padding) < 0
    if end <= start:
        end = min(clip_len, start + 1.0)
    return int(round(start * 1000)), int(round(end * 1000)), clamped


# ---------------------------------------------------------------------------
# 기록 — jsonl 은 append only. 절대 덮어쓰지 않는다.
# ---------------------------------------------------------------------------


def append_run(row: dict) -> None:
    with _write_lock:
        with RUNS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_key(r: dict) -> tuple:
    return (
        r.get("candidate_key"),
        r.get("tag"),
        r.get("prompt_hash"),
        r.get("model"),
        r.get("media_resolution"),
        r.get("fps"),
        r.get("padding_sec"),
    )


def build_caches(rows: list[dict]) -> tuple[dict, set]:
    """이전 기록에서 업로드 참조와 완료 목록을 되살린다."""
    uri_cache: dict[str, dict] = {}
    done: set[tuple] = set()
    for r in rows:
        if r.get("file_uri") and r.get("file_name") and r.get("clip_path"):
            uri_cache[r["clip_path"]] = {"uri": r["file_uri"], "name": r["file_name"]}
        if r.get("ok"):
            done.add(run_key(r))
    return uri_cache, done


def seed_uri_cache_from_coarse(coarse_rows: list[dict]) -> dict:
    """Coarse 가 이미 올린 파일을 재사용한다. ffmpeg 재분할도 재업로드도 없다."""
    cache: dict[str, dict] = {}
    for r in coarse_rows:
        if r.get("file_uri") and r.get("file_name") and r.get("clip_path"):
            cache[r["clip_path"]] = {"uri": r["file_uri"], "name": r["file_name"]}
    return cache


# ---------------------------------------------------------------------------
# 프롬프트 조립
# ---------------------------------------------------------------------------


def build_prompt(event_type: str, hint_type: str, hint_summary: str) -> str:
    delta = DELTAS[event_type]
    return (
        COMMON_BLOCK
        .replace("{EVENT_TYPE}", event_type)
        .replace("{EVENT_DEFINITION}", delta["definition"])
        .replace("{REQUIRED_CONDITIONS}", delta["conditions"])
        .replace("{AXIS}", delta["axis"] + "\n\n관찰 요소 이름 예시: " + delta["primitives_hint"])
        .replace("{HINT_TYPE}", hint_type or "(없음)")
        .replace("{HINT_SUMMARY}", hint_summary or "(없음)")
    )


def prompt_fingerprint() -> str:
    """공통 블록 + 델타 4개 전체의 해시. 문구가 바뀌면 값이 바뀐다."""
    blob = COMMON_BLOCK + json.dumps(DELTAS, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 사후 검증 — 스키마로 막지 않고 세는 것들
# ---------------------------------------------------------------------------


def check_invariants(parsed: dict, expected_event: str) -> tuple[list[str], list[str]]:
    """계약 불변조건과 탐침 관례를 검사한다. 고치지 않고 이름만 남긴다.

    두 목록을 나눠서 돌려준다.

    violations — **정의상 잘못된 출력.** 계약 불변조건 위반이거나, 탐침 관례가
                 「잘못된 출력」이라고 프롬프트에 명시한 것이다. 0건이 정상이다.
    watch      — **잘못은 아니지만 세어 볼 것.** 계약이 허용하는 형태이므로
                 위반으로 세면 안 된다. 섞으면 「위반 N건」이 항상 0이 아니게 되고
                 계기로 쓸 수 없다.
    """
    out: list[str] = []
    watch: list[str] = []
    v = parsed.get("verification")
    et = parsed.get("event_type")
    prims = parsed.get("primitives") or []
    uncs = parsed.get("uncertainties") or []

    # 계약 — contract-visual-evidence.md §11 Verification
    if v == "OBSERVED":
        if not et or et == "NONE":
            out.append("OBSERVED_WITHOUT_EVENT_TYPE")
        elif et != expected_event:
            # 호출 1건이 가설 1개를 검증하므로 도구는 기대 유형을 안다.
            # 계약 불변조건보다 강한 검사이고, 이름은 taxonomy 후보에서 가져왔다.
            out.append("EVENT_CLASS_FAIL")
    elif v in ("NOT_OBSERVED", "UNCERTAIN"):
        if et and et != "NONE":
            out.append("NON_OBSERVED_WITH_EVENT_TYPE")
    else:
        out.append("BAD_VERIFICATION_VALUE")

    # 탐침 관례 — 계약이 요구하는 것은 아니다. 3값 혼동을 세기 위한 것이다.
    # 이게 없으면 NOT_OBSERVED 와 UNCERTAIN 의 구분이 검증 불가능해지고
    # FINE_FALSE_NEGATIVE · OVERCONFIDENT 통계가 근거 없이 선다.
    if v == "UNCERTAIN" and not uncs:
        out.append("UNCERTAIN_WITHOUT_REASON")
    if v == "NOT_OBSERVED" and not prims:
        out.append("NOT_OBSERVED_WITHOUT_PRIMITIVE")
    if v == "NOT_OBSERVED" and prims and not any(
            p.get("state") == "ABSENT" for p in prims):
        out.append("NOT_OBSERVED_WITHOUT_ABSENT_STATE")

    # 계약 §9 Confidence
    for p in prims:
        c = p.get("confidence")
        if c is not None and not (0.0 <= float(c) <= 1.0):
            out.append("CONFIDENCE_OUT_OF_RANGE")
            break
    if "confidence" in parsed:
        out.append("TOP_LEVEL_CONFIDENCE")

    # ── watch — 계약이 허용하는 형태다. 위반이 아니다. ──────────────
    # `OVERCONFIDENT` 후보 정의는 「불확실하지만 확정값 반환 = uncertainty 미기록」이다.
    # 그런데 정말로 불확실할 것이 없는 OBSERVED 는 정당하고 계약도 빈 배열을 허용한다.
    # 사람이 판정을 확인할 때 먼저 볼 대상이라는 뜻일 뿐이다.
    if v == "OBSERVED" and not uncs:
        watch.append("OBSERVED_WITHOUT_UNCERTAINTY_NOTE")
    # 관찰이 전혀 없는데 판정을 내렸다 — 근거 없는 판정일 수 있다.
    if not prims and not (parsed.get("temporal_facts") or []):
        watch.append("NO_OBSERVATION_AT_ALL")
    # 근거 시점이 하나도 없으면 시간 정확도를 확인할 방법이 없다.
    if not all_evidence_ms(parsed):
        watch.append("NO_EVIDENCE_MS")

    return out, watch


def free_texts(parsed: dict) -> list[str]:
    """유출 스캔 대상 — 모델이 자유롭게 쓴 문자열 전부."""
    out: list[str] = []
    tgt = parsed.get("target") or {}
    if isinstance(tgt, dict) and tgt.get("described_as"):
        out.append(str(tgt["described_as"]))
    for p in parsed.get("primitives") or []:
        if p.get("kind"):
            out.append(str(p["kind"]))
    for t in parsed.get("temporal_facts") or []:
        if t.get("fact"):
            out.append(str(t["fact"]))
    for u in parsed.get("uncertainties") or []:
        for k in ("kind", "detail"):
            if u.get(k):
                out.append(str(u[k]))
    return out


def scan_leaks(parsed: dict) -> dict:
    """경계 유출 스캔. 걸린 패턴 이름 -> **마스킹된** 발췌(짧게).

    ★ 원문에서 스캔하되 발췌는 마스킹해서 남긴다. 유출을 세는 것이 목적이고,
      유출된 값을 보관하는 것이 목적이 아니다 — 값을 남기면 이 파일이 곧
      유출 자체가 된다.
    """
    hits: dict[str, list[str]] = {}
    for text in free_texts(parsed):
        for name, pat in LEAK_PATTERNS.items():
            if pat.search(text):
                hits.setdefault(name, [])
                if len(hits[name]) < 3:
                    hits[name].append(mask_sensitive(text)[:80])
    return hits


def collect_vocab(parsed: dict) -> dict:
    """모델이 만들어낸 어휘. 계약이 Pending 으로 둔 값 공간을 채울 자료다."""
    return {
        "primitive_kinds": [p.get("kind") for p in (parsed.get("primitives") or []) if p.get("kind")],
        "facts": [t.get("fact") for t in (parsed.get("temporal_facts") or []) if t.get("fact")],
        "uncertainty_kinds": [u.get("kind") for u in (parsed.get("uncertainties") or []) if u.get("kind")],
    }


def modality_tokens(usage: dict | None, name: str) -> int | None:
    """`input_tokens_by_modality` 에서 한 modality 의 토큰 수를 꺼낸다.

    ★ 배열 순서에 의존하지 않는다. 실측에서 호출마다 video/text 순서가 바뀌었다.
    """
    for m in ((usage or {}).get("input_tokens_by_modality") or []):
        if str(m.get("modality", "")).lower().endswith(name):
            t = m.get("tokens")
            return int(t) if isinstance(t, (int, float)) else None
    return None


def all_evidence_ms(parsed: dict) -> list[int]:
    out: list[int] = []
    tgt = parsed.get("target") or {}
    if isinstance(tgt, dict):
        out += [int(x) for x in (tgt.get("evidence_at_ms") or []) if isinstance(x, (int, float))]
    for group in ("primitives", "temporal_facts", "uncertainties"):
        for item in parsed.get(group) or []:
            out += [int(x) for x in (item.get("evidence_at_ms") or []) if isinstance(x, (int, float))]
    for t in parsed.get("temporal_facts") or []:
        if isinstance(t.get("at_offset_ms"), (int, float)):
            out.append(int(t["at_offset_ms"]))
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Gemini 호출
# ---------------------------------------------------------------------------


MIN_SDK = (2, 13, 0)   # VideoContent 가 processing 을 선언하기 시작한 경계


def check_sdk(genai) -> str:
    """SDK 버전을 확인한다. 낮으면 구간 지정이 조용히 무시되므로 막는다."""
    ver = getattr(genai, "__version__", "0")
    try:
        parts = tuple(int(x) for x in ver.split(".")[:3])
    except ValueError:
        return ver
    if parts < MIN_SDK:
        raise SystemExit(
            f"google-genai {ver} 은 쓸 수 없다. {'.'.join(map(str, MIN_SDK))} 이상이 필요하다.\n"
            "  이 버전의 VideoContent 는 processing 을 선언하지 않아서\n"
            "  start_offset/end_offset/fps 가 **요청 본문에서 조용히 빠진다.**\n"
            "  구간을 8초로 지정해도 클립 전체가 처리되고 원가가 30배가 된다.\n"
            "  uv pip install -U google-genai"
        )
    return ver


def offset_str(ms: int) -> str:
    """SDK 는 offset 을 정수 ms 가 아니라 duration 문자열로 받는다."""
    return f"{ms / 1000:.3f}s"


def is_rate_limited(exc: Exception) -> bool:
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "rate limit" in s.lower()


def ensure_uploaded(client, clip_path: str, cached: dict | None, mime: str) -> tuple[dict, float, float]:
    """캐시된 참조가 아직 살아 있으면 재사용하고, 아니면 새로 올린다."""
    if cached:
        try:
            f = client.files.get(name=cached["name"])
            if str(getattr(f.state, "name", f.state)) == "ACTIVE":
                return {"uri": f.uri, "name": f.name}, 0.0, 0.0
        except Exception:
            pass  # 만료됐거나 사라졌다. 새로 올린다.

    p = Path(clip_path)
    if not p.is_file():
        raise RuntimeError(f"클립 파일이 없다: {clip_path} (48h 만료 뒤 재업로드가 필요하다)")

    t0 = time.monotonic()
    f = client.files.upload(file=str(p), config={"mime_type": mime})
    upload_sec = time.monotonic() - t0

    t1 = time.monotonic()
    while str(getattr(f.state, "name", f.state)) == "PROCESSING":
        time.sleep(2)
        f = client.files.get(name=f.name)
    active_wait_sec = time.monotonic() - t1

    state = str(getattr(f.state, "name", f.state))
    if state != "ACTIVE":
        raise RuntimeError(f"업로드 파일 상태가 {state} 다 ({p.name})")

    return {"uri": f.uri, "name": f.name}, upload_sec, active_wait_sec


def read_usage(resp) -> dict:
    """usage 를 읽는다.

    ★ `or 0` 을 쓰지 않는다. None 과 0 은 다르다 —
      None 은 "provider 가 안 줬다", 0 은 "안 썼다"다.
      `or 0` 으로 뭉개면 원가가 조용히 0 으로 보고된다.

    ★ total_thought_tokens 를 반드시 읽는다. SDK 2.12.1 의 Usage 에 이미 있다.
      agentic 탐색 비용과 3.8 의 추론 비용이 여기 잡히고,
      ktc4 의 UsageRecord 계약에는 이 자리가 아직 없다.
    """
    u = getattr(resp, "usage", None)
    if u is None:
        return {k: None for k in (
            "input_tokens", "output_tokens", "thought_tokens",
            "total_tokens", "cached_tokens", "input_tokens_by_modality")}

    def g(name):
        v = getattr(u, name, None)
        return int(v) if isinstance(v, (int, float)) else None

    modality = None
    raw_mod = getattr(u, "input_tokens_by_modality", None)
    if raw_mod:
        modality = []
        for m in raw_mod:
            try:
                modality.append({
                    "modality": str(getattr(m, "modality", None)),
                    "tokens": getattr(m, "tokens", None) or getattr(m, "token_count", None),
                })
            except Exception:  # noqa: BLE001
                pass

    return {
        "input_tokens": g("total_input_tokens"),
        "output_tokens": g("total_output_tokens"),
        "thought_tokens": g("total_thought_tokens"),
        "total_tokens": g("total_tokens"),
        "cached_tokens": g("total_cached_tokens"),
        "input_tokens_by_modality": modality,
    }


def cost_usd(usage: dict) -> float | None:
    """thought 토큰은 출력 단가로 본다. 확인 대상이며 리포트에 그렇게 적는다."""
    ti = usage.get("input_tokens")
    to = usage.get("output_tokens")
    if ti is None or to is None:
        return None
    th = usage.get("thought_tokens") or 0
    return round(
        ti / 1_000_000 * PRICE_IN_PER_1M_USD
        + (to + th) / 1_000_000 * PRICE_OUT_PER_1M_USD, 6)


def process_candidate(client, ix, cand: dict, args, prompt_hash: str,
                      cached: dict | None, counter: dict, total: int) -> dict:
    event_type = cand["hint_type"]

    skip_reason = None
    if event_type not in DELTAS:
        # 계약 enum 에 없는 유형은 검증할 델타가 없다.
        skip_reason = "NO_DELTA_FOR_EVENT_TYPE"
    elif cand.get("out_of_clip"):
        # Coarse 가 클립 길이 밖의 시각을 말했다. Fine 이 볼 영상이 없다.
        skip_reason = "SPAN_OUT_OF_CLIP"

    if skip_reason:
        row = dict(cand)
        row.update({
            "ts": now_iso(), "tag": args.tag, "ok": False, "skipped": skip_reason,
        })
        append_run(row)
        with _print_lock:
            counter["n"] += 1
            n = counter["n"]
        log(f"[{n}/{total}] {cand['candidate_key']} 건너뜀 — {skip_reason}"
            + (f" (span {cand['span_start_sec']:.0f}–{cand['span_end_sec']:.0f}s "
               f"> 클립 {cand.get('clip_duration_sec', 0):.0f}s)"
               if skip_reason == "SPAN_OUT_OF_CLIP" else ""))
        return row

    start_ms, end_ms, clamped = fine_window(cand, args.padding, cand["clip_duration_sec"])
    clip_len_ms = end_ms - start_ms
    mime = MIME_BY_EXT.get(Path(cand["clip_path"]).suffix.lower(), "video/mp4")
    prompt = build_prompt(event_type, cand["hint_type_raw"], cand["hint_summary"])

    row = dict(cand)
    row.update({
        "ts": now_iso(),
        "tag": args.tag,
        "model": args.model,
        "media_resolution": args.media_resolution,
        "fps": args.fps,
        "padding_sec": args.padding,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        # 구간 지정이 실제로 전송됐는지는 SDK 버전이 좌우한다. 기록에 남긴다.
        "sdk_version": getattr(args, "sdk_version", None),
        "verified_event_type": event_type,
        "start_offset_ms": start_ms,
        "end_offset_ms": end_ms,
        "fine_clip_ms": clip_len_ms,
        "span_clamped": clamped,
        "concurrency": args.concurrency,
    })

    upload_sec = active_wait_sec = generate_sec = 0.0
    delay = 5.0

    for attempt in range(1, args.max_retries + 2):
        try:
            ref, u_sec, a_sec = ensure_uploaded(client, cand["clip_path"], cached, mime)
            upload_sec += u_sec
            active_wait_sec += a_sec
            row["file_uri"] = ref["uri"]
            row["file_name"] = ref["name"]

            # Fine 은 static 이다. 구간을 이미 아니까 모델이 타임라인을 탐색할 필요가 없다.
            #
            # ★ google-genai >= 2.13 필요. 2.12.1 에서는 VideoContent 가 processing 을
            #   선언하지 않고, model_dump 에는 남지만 **요청 본문에서는 빠진다.**
            #   즉 조용히 무시된다 — offset·fps 가 안 먹고 클립 전체가 기본값으로 처리된다.
            #   (실측: 8초 구간을 요청했는데 입력 89,366 tok = 클립 304초 전체.)
            #   2.22.0 은 선언·검증하므로 틀린 값을 넣으면 에러를 낸다.
            #
            # ★ start_offset/end_offset 은 **정수 ms 가 아니라 문자열**이다 ("33.000s").
            #   문서가 "In milliseconds" 로 적어 놓았지만 SDK 타입은 Optional[str] 이고
            #   정수를 넣으면 2.22.0 이 거부한다.
            video_input = ix.VideoContent(
                type="video",
                uri=ref["uri"],
                mime_type=mime,
                resolution=args.media_resolution,
                processing={
                    "type": "static",
                    "fps": args.fps,
                    "start_offset": offset_str(start_ms),
                    "end_offset": offset_str(end_ms),
                },
            )

            create_kwargs = {
                "model": args.model,
                "input": [video_input, ix.TextContent(type="text", text=prompt)],
            }
            if not args.no_schema:
                create_kwargs["response_format"] = ix.TextResponseFormat(
                    type="text",
                    mime_type="application/json",
                    schema=RESPONSE_SCHEMA,
                )

            t2 = time.monotonic()
            resp = client.interactions.create(**create_kwargs)
            generate_sec = time.monotonic() - t2

            status = str(getattr(resp, "status", "") or "")
            if status and status != "completed":
                errs = getattr(resp, "errors", None) or []
                raise RuntimeError(f"interaction status={status} errors={errs}")

            usage = read_usage(resp)
            row["interaction_id"] = getattr(resp, "id", None)
            row["status"] = status or None

            text = (getattr(resp, "output_text", None) or "").strip()
            parsed, parse_error = None, None
            if not args.no_schema:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as e:
                    parse_error = str(e)
            if not isinstance(parsed, dict):
                parsed = None

            tok_in = usage.get("input_tokens")
            row.update({
                "ok": True,
                "attempt": attempt,
                "upload_sec": round(upload_sec, 2),
                "active_wait_sec": round(active_wait_sec, 2),
                "generate_sec": round(generate_sec, 2),
                "usage": usage,
                "tokens_per_sec_of_video": (
                    round(tok_in / (clip_len_ms / 1000), 1)
                    if tok_in is not None and clip_len_ms else None),
                "cost_usd_est": cost_usd(usage),
                # ★ 성공해도 raw 를 남긴다. coarse 는 파싱 실패 시에만 남겼다.
                #   강제 변환(coercion) 진단에 원문 구조가 필요하다.
                #   단 **마스킹해서** 남긴다 — 원문 그대로면 기록이 곧 유출이 된다.
                "raw_text": mask_sensitive(text),
                "parse_error": parse_error,
            })

            if parsed is not None:
                verification = parsed.get("verification")
                et = parsed.get("event_type")
                violations, watch = check_invariants(parsed, event_type)
                # ★ 스캔은 원문(parsed)에서, 저장은 마스킹본(safe)에서.
                #   순서를 바꾸면 방어선 측정이 사라진다.
                leaks = scan_leaks(parsed)
                safe = mask_deep(parsed)
                row.update({
                    "verification": verification,
                    # 계약은 null 이다. 탐침은 "NONE" 센티널을 쓰고 여기서 환산한다.
                    "visual_event_type": None if et in (None, "NONE") else et,
                    "target": safe.get("target"),
                    "primitives": safe.get("primitives"),
                    "temporal_facts": safe.get("temporal_facts"),
                    "uncertainties": safe.get("uncertainties"),
                    "evidence_at_ms_all": all_evidence_ms(parsed),
                    "invariant_violations": violations,
                    "watch_flags": watch,
                    "leaks": leaks,
                    "vocab": collect_vocab(safe),
                })

            append_run(row)   # 무엇보다 먼저 기록한다

            with _print_lock:
                counter["n"] += 1
                n = counter["n"]
            viol = row.get("invariant_violations") or []
            leak = row.get("leaks") or {}
            log(f"[{n}/{total}] {cand['candidate_key']} {event_type} "
                f"-> {row.get('verification') or '?'} "
                f"({generate_sec:.1f}s, in {tok_in if tok_in is not None else '?'} tok"
                + (f", 위반 {','.join(viol)}" if viol else "")
                + (f", 유출 {','.join(leak)}" if leak else "")
                + ")")
            return row

        except Exception as e:  # noqa: BLE001 — 어떤 실패든 기록하고 넘어간다
            limited = is_rate_limited(e)
            if attempt <= args.max_retries and limited:
                sleep_for = delay + random.uniform(0, 2)
                log(f"  · {cand['candidate_key']} 429 — {sleep_for:.0f}s 뒤 재시도 "
                    f"({attempt}/{args.max_retries})")
                time.sleep(sleep_for)
                delay *= 2
                cached = None
                continue

            row.update({
                "ok": False,
                "attempt": attempt,
                "upload_sec": round(upload_sec, 2),
                "active_wait_sec": round(active_wait_sec, 2),
                "generate_sec": round(generate_sec, 2),
                "rate_limited": limited,
                "error": {"type": type(e).__name__, "message": str(e)[:2000]},
            })

            append_run(row)   # 실패도 사실이다. 먼저 기록한다

            with _print_lock:
                counter["n"] += 1
                n = counter["n"]
            log(f"[{n}/{total}] {cand['candidate_key']} 실패 — "
                f"{type(e).__name__}: {str(e)[:160]}")
            return row

    return row  # 도달하지 않는다


# ---------------------------------------------------------------------------
# 리포트
#
# 양식은 ktc4 의 docs/modules/eval/experiment-guide.md 가 소유한다.
# 새 형식을 만들지 않는다 — "다른 모듈의 규칙을 자기 문서에 복제하지 않는다".
# ---------------------------------------------------------------------------


def fmt(v, spec="", dash="-"):
    if v is None:
        return dash
    return format(v, spec) if spec else str(v)


def abs_timecode(row: dict, ms: int | None) -> str:
    """구간 시작 기준 ms 를 원본 절대 위치로 환산한다.

    ★ `clip_ordinal x 300` 을 쓰지 않는다. 실제 클립 길이의 누적(`clip_start_sec`)을 쓴다.
      coarse_probe.py 의 리포트는 300초 가정으로 환산하는데, 실측 길이가
      304.30 / 298.97 / ... / 244.50 이라 마지막 클립에서 약 3.4초 어긋난다.

    모델이 말한 0이 Fine 입력 시작인지 클립 시작인지는 **확인되지 않았다.**
    provider 가 start_offset 을 적용한 뒤 시간을 0부터 세는지 미확인이다.
    여기서는 "0 = Fine 입력 시작"으로 환산한다. ms 값이 0 근처가 아니라
    start_offset 근처에 몰려 있으면 반대 해석이라는 신호이고 리포트가 그걸 센다.
    """
    if ms is None:
        return "-"
    base = row.get("clip_start_sec")
    if base is None:
        ordinal = row.get("clip_ordinal")
        if ordinal is None:
            ordinal = row.get("clip_index") or 0
        base = ordinal * CLIP_SECONDS
    sec = base + row.get("start_offset_ms", 0) / 1000 + ms / 1000
    return f"{int(sec // 60)}분{int(sec % 60):02d}초"


def primitive_digest(row: dict) -> str:
    prims = row.get("primitives") or []
    if not prims:
        return "-"
    return "; ".join(
        f"{p.get('kind')}={p.get('state')}" for p in prims[:3]
    )[:70]


def write_report(all_rows: list[dict]) -> None:
    """tag 별로 갈라서 쓴다.

    ★ tag 를 섞지 않는다. experiment-guide §2 가 「한 실험에서는 핵심 변수 하나를
      중심으로 비교하고, 동시에 여러 항목을 바꿨다면 무엇을 변경했는지 명확하게
      기록한다」고 요구한다. tag 가 곧 조건 집합이므로 합산하면 실험 기록이 아니다.
      (실제로 SDK 2.12.1 의 깨진 회차가 섞여 원가가 20% 부풀었다.)
    """
    L: list[str] = []
    L.append("# Fine Probe Report")
    L.append("")
    L.append(f"생성: {now_iso()}  ·  원본 기록: `{RUNS_PATH.name}` ({len(all_rows)}줄)")
    L.append("")
    L.append("> `fine_probe_runs.jsonl`에서 파생된 요약이다. `--report-only`로 다시 만들 수 있다.")
    L.append("> **Recall은 측정하지 않았다.** 정답지가 없으므로 놓친 사건은 셀 수 없다.")
    L.append("> 절대 시각 정확도도 여기 없다 — 화면시각 판독은 `readout` 소유다.")
    L.append("> 비용은 파일 상단 단가 상수 기준 **추정치**이고, thought 토큰을 출력 단가로 계산했다(확인 대상).")
    L.append("")

    tags = sorted({r.get("tag") or "default" for r in all_rows})
    if len(tags) > 1:
        L.append(f"회차 {len(tags)}개: " + ", ".join(f"`{t}`" for t in tags)
                 + " — **합산하지 않는다.** 조건이 다르면 비교할 수 없다.")
        L.append("")

    for tag in tags:
        rows = [r for r in all_rows if (r.get("tag") or "default") == tag]
        _write_tag_section(L, tag, rows, len(tags) > 1)

    _write_shared_tail(L)
    REPORT_PATH.write_text("\n".join(L), encoding="utf-8")


def _write_tag_section(L: list[str], tag: str, rows: list[dict], multi: bool) -> None:
    ok_rows = [r for r in rows if r.get("ok")]
    fail_rows = [r for r in rows if not r.get("ok") and not r.get("skipped")]
    skip_rows = [r for r in rows if r.get("skipped")]

    if multi:
        L.append(f"---")
        L.append("")
        L.append(f"# 회차 `{tag}`")
        L.append("")

    # ── experiment-guide.md Experiment Note Template ──────────────────
    by_event = Counter(r.get("verified_event_type") for r in ok_rows)
    verifs = Counter(r.get("verification") for r in ok_rows)
    tags = sorted({r.get("tag") for r in rows if r.get("tag")})
    models = sorted({r.get("model") for r in ok_rows if r.get("model")})
    pvers = sorted({r.get("prompt_version") for r in ok_rows if r.get("prompt_version")})
    clip_ms = [r.get("fine_clip_ms") for r in ok_rows if r.get("fine_clip_ms")]

    t_in = sum(r["usage"]["input_tokens"] for r in ok_rows
               if (r.get("usage") or {}).get("input_tokens") is not None)
    t_out = sum(r["usage"]["output_tokens"] for r in ok_rows
                if (r.get("usage") or {}).get("output_tokens") is not None)
    t_thought = sum((r.get("usage") or {}).get("thought_tokens") or 0 for r in ok_rows)
    t_cost = sum(r["cost_usd_est"] for r in ok_rows if r.get("cost_usd_est") is not None)
    lat = [r.get("generate_sec") for r in ok_rows if r.get("generate_sec") is not None]
    exposure_ms = sum(clip_ms)

    L.append("## Experiment Note")
    L.append("")
    L.append("> 양식은 `ktc4-chonnam-2/docs/modules/eval/experiment-guide.md`가 소유한다.")
    L.append("> 프롬프트 전문은 여기 복사하지 않고 `prompt_version`으로 가리킨다(§7).")
    L.append("")
    L.append("```text")
    L.append("[CASE]")
    L.append("real  (강변북로 주행 원본 40분, 5분 클립 8개)")
    L.append("visual event type: " + (", ".join(f"{k} {v}건" for k, v in by_event.most_common()) or "-"))
    L.append("positive / hard-negative:  정답지 없음 — 사람 확인 대상")
    L.append("  ★ Coarse observed 텍스트에 점선 11건 / 실선 0건이다.")
    L.append("    SOLID_LINE_LANE_CHANGE는 실선을 요구하므로 대부분 hard-negative로 보인다.")
    L.append(f"source duration: {len(set(r.get('clip') for r in ok_rows))}개 클립에서 뽑은 후보")
    L.append("")
    L.append("[INPUT]")
    L.append("user hint: (없음)")
    L.append("ground-truth interval: 없음 — Coarse 후보 span ± padding 을 입력으로 썼다")
    L.append("")
    L.append("[PIPELINE]")
    L.append("Coarse: gemini-3.7-flash / low / fps 1.0 / 5분 클립  (probe_report.md)")
    L.append(f"Fine:   Structured  ·  model {', '.join(models) or '-'}"
             f"  ·  prompt_version {', '.join(pvers) or '-'}")
    if clip_ms:
        L.append(f"        clip_length {min(clip_ms)/1000:.0f}~{max(clip_ms)/1000:.0f}s"
                 f" (평균 {sum(clip_ms)/len(clip_ms)/1000:.1f}s)")
    res = sorted({r.get("media_resolution") for r in ok_rows if r.get("media_resolution")})
    fpss = sorted({r.get("fps") for r in ok_rows if r.get("fps")})
    L.append(f"        resolution {', '.join(res) or '-'}  ·  fps {', '.join(map(str, fpss)) or '-'}")
    L.append(f"        fine_candidate_count {len(ok_rows)}  ·  tag {tag}")
    L.append("")
    L.append("[RESULT]")
    L.append("Recall@K / Final Recall@3      : 측정 불가 (정답지 없음)")
    L.append("timestamp error                : 사람 확인 대상 — 아래 확인 표")
    L.append("Fine Recall / HN-FPR / Precision: 사람 확인 대상")
    L.append("verification 분포              : "
             + (", ".join(f"{k} {v}" for k, v in verifs.most_common()) or "-"))
    if lat:
        L.append(f"latency (Fine, 호출당)         : 중앙값 {sorted(lat)[len(lat)//2]:.1f}s"
                 f" / 최대 {max(lat):.1f}s")
    L.append(f"tokens                         : 입력 {t_in:,} · 출력 {t_out:,} · thought {t_thought:,}")
    L.append(f"cost                           : ${t_cost:.4f} (추정)")
    L.append(f"Fine exposure                  : {exposure_ms/1000:.0f}초 "
             f"(Coarse 원본 2400초 기준 {exposure_ms/1000/2400*100:.1f}%)")
    L.append("")
    L.append("[FAILURE]")
    L.append("stage: FINE")
    L.append("kind : 자동 분류하지 않는다 — 아래 「자동으로 세지 않는 것」 참조")
    L.append("")
    L.append("[LEARNING]")
    L.append("(실행 뒤 사람이 채운다 — 다음 실험에서 바꿀 한 가지)")
    L.append("```")
    L.append("")

    # ── 후보별 표 ────────────────────────────────────────────────────
    L.append("## 후보별 결과")
    L.append("")
    L.append("| 후보 | 검증 유형 | 판정 | 구간(s) | 근거 시점 | 원본 위치 | primitives | 위반 | 신호 | 유출 | tok/s | 비용($) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(ok_rows, key=lambda x: (x.get("clip_index") or 0, x.get("candidate_key") or "")):
        ev = r.get("evidence_at_ms_all") or []
        first = ev[0] if ev else None
        viol = r.get("invariant_violations") or []
        watch = r.get("watch_flags") or []
        leak = r.get("leaks") or {}
        L.append(
            f"| {r.get('candidate_key')} | {r.get('verified_event_type')} | "
            f"**{r.get('verification') or '?'}** | "
            f"{r.get('start_offset_ms', 0)/1000:.0f}-{r.get('end_offset_ms', 0)/1000:.0f} | "
            f"{fmt(first)} | {abs_timecode(r, first)} | {primitive_digest(r)} | "
            f"{','.join(viol) if viol else '-'} | {','.join(watch) if watch else '-'} | "
            f"{','.join(leak) if leak else '-'} | "
            f"{fmt(r.get('tokens_per_sec_of_video'), '.0f')} | "
            f"{fmt(r.get('cost_usd_est'), '.5f')} |"
        )
    L.append("")

    if fail_rows:
        L.append("### 실패")
        L.append("")
        L.append("| 후보 | 오류 | 메시지 |")
        L.append("|---|---|---|")
        for r in fail_rows:
            e = r.get("error") or {}
            L.append(f"| {r.get('candidate_key')} | {e.get('type', '?')} | "
                     f"{str(e.get('message', ''))[:100]} |")
        L.append("")
    if skip_rows:
        reasons = Counter(r.get("skipped") for r in skip_rows)
        L.append("### 건너뜀")
        L.append("")
        for k, v in reasons.most_common():
            L.append(f"- `{k}` {v}건")
        oob = [r for r in skip_rows if r.get("skipped") == "SPAN_OUT_OF_CLIP"]
        if oob:
            L.append("")
            L.append("**`SPAN_OUT_OF_CLIP` 은 Fine 의 문제가 아니라 Coarse 출력의 결함이다.**")
            L.append("Coarse 가 클립 길이 밖의 시각을 말했다 — Fine 이 볼 영상이 없다.")
            L.append("**이것이 Coarse timestamp 실패의 실측치다.**")
            L.append("")
            L.append("| 후보 | Coarse가 말한 span | 실제 클립 길이 |")
            L.append("|---|---|---|")
            for r in oob:
                L.append(f"| {r.get('candidate_key')} | "
                         f"{r.get('span_start_sec', 0):.0f}–{r.get('span_end_sec', 0):.0f}s | "
                         f"{r.get('clip_duration_sec', 0):.2f}s |")
        L.append("")

    clamped_rows = [r for r in ok_rows if r.get("span_clamped")]
    if clamped_rows:
        L.append(f"구간을 클립 경계로 잘라 쓴 후보 {len(clamped_rows)}건 "
                 f"(`span_clamped`) — Fine 이 본 구간이 후보 span 보다 짧다.")
        L.append("")

    # ── 진단 ─────────────────────────────────────────────────────────
    L.append("## 진단")
    L.append("")
    L.append(f"- 성공 {len(ok_rows)}건 / 실패 {len(fail_rows)}건 / 건너뜀 {len(skip_rows)}건")

    viol_count = Counter()
    for r in ok_rows:
        for v in r.get("invariant_violations") or []:
            viol_count[v] += 1
    if viol_count:
        L.append("- **불변조건·관례 위반 (정의상 잘못된 출력. 0건이 정상이다)**")
        for k, v in viol_count.most_common():
            L.append(f"    - `{k}` {v}건")
    else:
        L.append("- 불변조건·관례 위반 0건")

    watch_count = Counter()
    for r in ok_rows:
        for v in r.get("watch_flags") or []:
            watch_count[v] += 1
    if watch_count:
        L.append("- 관찰 신호 (위반이 아니다 — 계약이 허용하는 형태다. 사람이 먼저 볼 대상)")
        for k, v in watch_count.most_common():
            L.append(f"    - `{k}` {v}건")

    leak_count = Counter()
    for r in ok_rows:
        for k in (r.get("leaks") or {}):
            leak_count[k] += 1
    if leak_count:
        L.append("- **경계 유출 (사람이 봐야 한다)**")
        for k, v in leak_count.most_common():
            L.append(f"    - `{k}` {v}건")
        L.append("    - Coarse에서도 번호판이 1건 새어 나왔다. 계약에 이를 막는 조항이 없으므로")
        L.append("      프롬프트가 유일한 방어선이고, 이 숫자가 그 방어선의 실측이다.")
    else:
        L.append("- 경계 유출 스캔 0건 (패턴은 heuristic이다 — 0건이 유출 없음을 뜻하지 않는다)")

    # 시간 기준 해석 진단
    near_zero = near_offset = 0
    for r in ok_rows:
        ev = r.get("evidence_at_ms_all") or []
        span = r.get("fine_clip_ms") or 0
        if not ev or not span:
            continue
        if max(ev) <= span * 1.2:
            near_zero += 1
        elif abs(min(ev) - (r.get("start_offset_ms") or 0)) < span:
            near_offset += 1
    L.append(f"- 근거 시점의 기준: 구간 시작(0) 해석에 맞는 것 {near_zero}건 / "
             f"클립 절대시간으로 보이는 것 {near_offset}건")
    if near_zero and not near_offset:
        L.append("    - **모델은 요청 구간의 시작을 0으로 쓴다.** 전량이 구간 안에 들어온다.")
        L.append("      `abs_timecode` 환산이 맞다. (계약의 `at_offset_ms` 정의와도 같다.)")
    elif near_offset:
        L.append("    - 클립 절대시간으로 보이는 것이 섞여 있다. "
                 "`abs_timecode` 환산을 고쳐야 한다.")

    # ★ 구간 지정이 실제로 먹었는지 — 플래그를 믿지 말고 토큰 수로 확인한다.
    #   요청 구간이 8초인데 입력 토큰이 클립 전체 분량이면 offset 이 무시된 것이다.
    bad_window = []
    vid_rates = []
    for r in ok_rows:
        vid = modality_tokens(r.get("usage"), "video")
        if vid is None:
            vid = (r.get("usage") or {}).get("input_tokens")
        win = (r.get("fine_clip_ms") or 0) / 1000
        dur = r.get("clip_duration_sec") or 0
        if vid is None or not win:
            continue
        vid_rates.append(vid / win)
        # 요청 구간이 클립보다 훨씬 짧은데 video 토큰이 클립 전체 분량이면
        # offset 이 무시된 것이다. low(100 tok/s)로 본 전체 클립보다도 많다.
        if dur and dur > win * 2 and vid > dur * 80:
            bad_window.append((r.get("candidate_key"), vid, win, dur))
    L.append("")
    if bad_window:
        L.append(f"- **★ 구간 지정이 먹지 않은 것으로 보이는 호출 {len(bad_window)}건**")
        L.append("    - video 입력 토큰이 요청 구간이 아니라 **클립 전체** 분량이다.")
        L.append("      `google-genai < 2.13` 은 `processing` 을 요청 본문에서 빼버린다"
                 " — 에러 없이 무시된다.")
        for k, vid, win, dur in bad_window[:5]:
            L.append(f"    - `{k}`: 요청 {win:.0f}초인데 video {vid:,} tok "
                     f"({vid/dur:.0f} tok/클립초 — 클립 {dur:.0f}초 전체 분량)")
        L.append("    - **이 행들의 원가·토큰 수치를 Fine 실측으로 쓰지 말 것.**")
    elif vid_rates:
        med = sorted(vid_rates)[len(vid_rates) // 2]
        L.append(f"- 구간 지정 확인: video 토큰/요청구간초 중앙값 **{med:.0f}**"
                 f" (high 2fps 기대 ~550, high 1fps ~290, low 1fps ~100)")
        L.append("    - 기대치와 맞으면 `resolution`·`fps`·`offset` 이 실제로 전송된 것이다."
                 " 플래그를 믿지 말고 이 숫자로 확인한다.")
    txt_tokens = [modality_tokens(r.get("usage"), "text") for r in ok_rows]
    txt_tokens = [t for t in txt_tokens if t]
    if txt_tokens:
        med_t = sorted(txt_tokens)[len(txt_tokens) // 2]
        L.append(f"- 프롬프트(text) 토큰 중앙값 {med_t:,} · 호출 {len(txt_tokens)}건 합계 "
                 f"{sum(txt_tokens):,}")
        L.append("    - 후보당 1호출이므로 프롬프트가 매번 다시 청구된다."
                 " 후보 수가 많으면 프롬프트 길이가 원가 항목이 된다.")
    sdks = Counter(r.get("sdk_version") for r in ok_rows if r.get("sdk_version"))
    if sdks:
        L.append("- google-genai 버전: "
                 + ", ".join(f"{k} {v}건" for k, v in sdks.most_common()))

    dsrc = Counter(r.get("duration_source") for r in rows if r.get("duration_source"))
    if dsrc:
        L.append("- 클립 길이 출처: "
                 + ", ".join(f"{k} {v}건" for k, v in dsrc.most_common()))
        L.append("    - `assumed` 가 있으면 원본 위치 환산에 오차가 있다.")
        L.append("      실측 길이는 304.30 / 298.97 / 244.50 처럼 300초가 아니다"
                 " (`ffmpeg -c copy` 는 키프레임 경계에서 자른다).")
        L.append("      **`coarse_probe.py` 의 리포트는 300초 가정으로 환산하므로"
                 " 마지막 클립에서 약 3.4초 어긋난다** — 별건으로 고칠 것.")

    thought_seen = [r for r in ok_rows if (r.get("usage") or {}).get("thought_tokens") is not None]
    L.append(f"- thought 토큰을 보고한 호출 {len(thought_seen)} / {len(ok_rows)}건, 합계 {t_thought:,}")
    L.append("    - `UsageRecord` 계약에는 이 자리가 없다. 값이 실제로 온다는 근거다.")
    if t_in and t_out is not None:
        tot_reported = sum((r.get("usage") or {}).get("total_tokens") or 0 for r in ok_rows)
        L.append(f"- `total_tokens` 합 {tot_reported:,} vs 입력+출력 {t_in + t_out:,} "
                 f"vs 입력+출력+thought {t_in + t_out + t_thought:,}")
        L.append("    - 어느 쪽과 맞는지가 계약 §8-4(`total = in + out`)의 성립 여부를 정한다.")

    vocab_p, vocab_f, vocab_u = Counter(), Counter(), Counter()
    for r in ok_rows:
        v = r.get("vocab") or {}
        vocab_p.update(v.get("primitive_kinds") or [])
        vocab_f.update(v.get("facts") or [])
        vocab_u.update(v.get("uncertainty_kinds") or [])
    L.append("")
    L.append("### 모델이 만들어낸 어휘")
    L.append("")
    L.append("계약이 `primitives[].kind` · `fact` · `uncertainties[].kind`의 값 목록을 Pending으로")
    L.append("열어 두었다. 확정은 `modules/search/decisions/`의 별건이고, 이 표가 그 자료다.")
    L.append("")
    for title, c in (("primitive kind", vocab_p), ("temporal fact", vocab_f),
                     ("uncertainty kind", vocab_u)):
        L.append(f"- **{title}** — " + (
            ", ".join(f"`{k}`×{v}" for k, v in c.most_common(12)) or "없음"))
    L.append("")
    # 코드로 수렴했는가 vs 산문으로 나왔는가 — registry 를 만들 수 있는지가 갈린다
    for title, c in (("primitive kind", vocab_p), ("temporal fact", vocab_f),
                     ("uncertainty kind", vocab_u)):
        total = sum(c.values())
        if not total:
            continue
        reuse = total / len(c)
        verdict = ("**코드로 수렴했다** — registry 후보로 쓸 수 있다" if reuse >= 2
                   else "**산문으로 나왔다** — 재사용되는 값이 없어 registry 자료가 되지 않는다")
        L.append(f"- `{title}`: 값 {len(c)}종 / 출현 {total}회 "
                 f"(값당 평균 {reuse:.1f}회) → {verdict}")
    L.append("")
    L.append("산문으로 나온 항목은 **프롬프트가 그 항목의 예시를 주지 않았기 때문일 수 있다.**")
    L.append("다음 회차에서 해당 델타에 코드 예시를 넣고 다시 보는 것이 한 가지 변경이다.")
    L.append("")


def _write_shared_tail(L: list[str]) -> None:
    # ── 자동으로 세지 않는 것 ────────────────────────────────────────
    L.append("## 자동으로 세지 않는 것")
    L.append("")
    L.append("**`FINE_FALSE_NEGATIVE` 숫자를 여기서 찍지 않는다.**")
    L.append("")
    L.append("taxonomy의 정의는 「Coarse는 찾았는데 Fine이 제거」다. 그런데 Coarse 후보의")
    L.append("`observed`에 점선이 11건, 실선이 0건이다. **점선 차로변경을 기각한 것은**")
    L.append("**Fine이 제대로 작동한 것**이고, 그걸 FN으로 세면 지표가 뒤집힌다.")
    L.append("`failure-taxonomy.md`가 아직 초안·Owner 미확정이라 자동 숫자가 틀린 정의를 굳힌다.")
    L.append("")
    L.append("`NOT_OBSERVED`는 사람이 두 갈래로 나눠야 한다.")
    L.append("")
    L.append("| 갈래 | 뜻 | 무엇의 지표인가 |")
    L.append("|---|---|---|")
    L.append("| (α) 요건 미충족 정당 기각 | 선이 점선이었다 등 | **Coarse precision** |")
    L.append("| (β) 사람이 요건 충족이라 본 기각 | | 진짜 `FINE_FALSE_NEGATIVE` |")
    L.append("")

    # ── 사람이 하는 일 ──────────────────────────────────────────────
    L.append("## 실행 뒤에 사람이 해야 하는 일")
    L.append("")
    L.append("후보마다 표의 「원본 위치」를 원본에서 직접 열어 보고 두 칸을 적는다.")
    L.append("(환산: `clip_ordinal × 300 + start_offset_ms/1000 + evidence_at_ms/1000`)")
    L.append("")
    L.append("| 확인 | 뜻 |")
    L.append("|---|---|")
    L.append("| **근거 시점에 진짜 그 장면이 있는가 (초 오차)** | 시간 정확도 — 제품 성립의 급소 |")
    L.append("| **판정이 맞는가 (α/β 갈래 포함)** | 판정 정확도 |")
    L.append("")
    L.append("분포만으로도 즉시 읽히는 것이 있다.")
    L.append("")
    L.append("- **전부 `OBSERVED`로 나오면 Fine이 hard-negative를 하나도 거르지 못한다는 뜻**이다.")
    L.append("  프롬프트나 모델을 다시 봐야 한다.")
    L.append("- 전부 `UNCERTAIN`이면 해상도·fps·구간 길이가 부족한 것이다. 설정 문제다.")
    L.append("- `UNCERTAIN_WITHOUT_REASON`이나 `NOT_OBSERVED_WITHOUT_PRIMITIVE`가 많으면")
    L.append("  모델이 세 값을 혼동하고 있다. 그러면 판정 통계 자체를 신뢰할 수 없다.")
    L.append("")


# ---------------------------------------------------------------------------


def main() -> int:
    # Windows 콘솔 코드페이지와 무관하게 한글이 깨지지 않게 한다
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="search Fine 탐침 (throwaway)")
    ap.add_argument("--tag", default="default", help="회차·조건 이름. jsonl에 그대로 기록된다")
    ap.add_argument("--coarse-tag", default=None,
                    help="Coarse 기록에서 이 tag의 후보만 쓴다. 기본은 전부")
    ap.add_argument("--event", action="append", choices=EVENT_TYPES,
                    help="이 유형만 검증한다 (여러 번 지정 가능)")
    ap.add_argument("--limit", type=int, default=None,
                    help="앞에서 N건만. 처음 확인할 때 쓸 것")
    ap.add_argument("--padding", type=float, default=PADDING_SEC,
                    help="후보 span 앞뒤 여유(초)")
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    ap.add_argument("--fps", type=float, default=FPS)
    ap.add_argument("--media-resolution", default=MEDIA_RESOLUTION,
                    choices=["low", "medium", "high", "ultra_high"])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-retries", type=int, default=3, help="429일 때만 재시도")
    ap.add_argument("--no-schema", action="store_true", help="structured output 없이 원문 그대로")
    ap.add_argument("--force", action="store_true", help="같은 조건으로 이미 성공한 후보도 다시")
    ap.add_argument("--print-prompt", choices=EVENT_TYPES,
                    help="해당 유형의 프롬프트를 출력하고 끝낸다 (Owner 검토용)")
    ap.add_argument("--report-only", action="store_true", help="API 호출 없이 리포트만 재생성")
    args = ap.parse_args()

    if args.print_prompt:
        print(build_prompt(args.print_prompt, "(예시 힌트)", "(예시 관찰 요약)"))
        return 0

    if args.report_only:
        rows = load_jsonl(RUNS_PATH)
        if not rows:
            print(f"기록이 없다: {RUNS_PATH}")
            return 1
        write_report(rows)
        print(f"리포트 재생성: {REPORT_PATH}  ({len(rows)}줄)")
        return 0

    coarse_rows = load_jsonl(COARSE_RUNS_PATH)
    if not coarse_rows:
        print(f"Coarse 기록이 없다: {COARSE_RUNS_PATH}", file=sys.stderr)
        print("먼저 coarse_probe.py 를 돌려 후보를 만들 것.", file=sys.stderr)
        return 1

    geo = clip_geometry(coarse_rows)
    assumed = [p for p, g in geo.items() if g["source"] == "assumed"]
    if assumed:
        print(f"  ! ffprobe 로 길이를 읽지 못한 클립 {len(assumed)}개 — "
              f"{CLIP_SECONDS}초 가정으로 떨어진다. 원본 위치 환산에 오차가 생긴다.")

    cands = collect_candidates(coarse_rows, args.coarse_tag, geo)
    if args.event:
        cands = [c for c in cands if c["hint_type"] in set(args.event)]
    if not cands:
        print("검증할 후보가 없다.", file=sys.stderr)
        return 1

    api_key, key_source = load_api_key()
    if not api_key:
        print("API 키를 찾지 못했다. 둘 중 하나로 주면 된다:", file=sys.stderr)
        print("  1) .env 파일 (권장, .gitignore 로 막혀 있다):  GEMINI_API_KEY=...", file=sys.stderr)
        for f in find_env_files():
            print(f"       {f}", file=sys.stderr)
        print('  2) 환경변수 (이쪽이 .env 를 이긴다):  $env:GEMINI_API_KEY = "..."', file=sys.stderr)
        return 1
    print(f"API 키: {key_source} — {mask(api_key)}")

    try:
        from google import genai
        from google.genai import interactions as ix
    except ImportError:
        print("google-genai 가 없다:  uv pip install google-genai", file=sys.stderr)
        return 1

    args.sdk_version = check_sdk(genai)
    prompt_hash = prompt_fingerprint()

    prior = load_jsonl(RUNS_PATH)
    uri_cache = seed_uri_cache_from_coarse(coarse_rows)
    prior_cache, done = build_caches(prior)
    uri_cache.update(prior_cache)   # 더 최신 기록이 이긴다

    pending = []
    skipped = 0
    for c in cands:
        key = (c["candidate_key"], args.tag, prompt_hash, args.model,
               args.media_resolution, args.fps, args.padding)
        if not args.force and key in done:
            skipped += 1
            continue
        pending.append(c)

    if args.limit is not None:
        pending = pending[:args.limit]

    by_event = defaultdict(int)
    for c in pending:
        by_event[c["hint_type"]] += 1
    remapped = sum(1 for c in pending if c["hint_type_remapped"])
    oob = [c for c in pending if c.get("out_of_clip")]

    print(f"후보 {len(cands)}건 발견"
          + (f" · 이미 완료 {skipped}건 건너뜀" if skipped else "")
          + (f" · 이번 실행 {len(pending)}건" if len(pending) != len(cands) else ""))
    for e, n in sorted(by_event.items()):
        print(f"    {e}: {n}건")
    if remapped:
        print(f"    (그중 {remapped}건은 Coarse의 옛 이름을 계약 이름으로 매핑한 것이다)")
    if oob:
        print(f"  ! 클립 길이를 벗어난 후보 {len(oob)}건 — 호출하지 않고 기록만 한다")
        for c in oob:
            print(f"      {c['candidate_key']}: span {c['span_start_sec']:.0f}–"
                  f"{c['span_end_sec']:.0f}s > 클립 {c['clip_duration_sec']:.0f}s")
    print(f"모델 {args.model} · {args.media_resolution} · fps {args.fps} · "
          f"padding ±{args.padding}s · 동시 {args.concurrency}")
    print(f"prompt {PROMPT_VERSION} ({prompt_hash}) · tag '{args.tag}' "
          f"· google-genai {args.sdk_version}")
    print(f"기록: {RUNS_PATH}\n")

    if not pending:
        write_report(load_jsonl(RUNS_PATH))
        print("새로 돌릴 후보가 없다. 리포트만 갱신했다.")
        return 0

    counter = {"n": 0}
    total = len(pending)
    wall0 = time.monotonic()
    client = genai.Client(api_key=api_key)

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [
            pool.submit(process_candidate, client, ix, c, args, prompt_hash,
                        uri_cache.get(c["clip_path"]), counter, total)
            for c in pending
        ]
        for fut in as_completed(futures):
            try:
                fut.result()   # 기록은 워커가 이미 했다. 여기선 예외만 확인한다
            except Exception as e:  # noqa: BLE001
                log(f"  ! 워커 예외: {type(e).__name__}: {e}")

    wall = time.monotonic() - wall0
    rows = load_jsonl(RUNS_PATH)
    write_report(rows)

    mine = [r for r in rows if r.get("tag") == args.tag]
    ok = sum(1 for r in mine if r.get("ok"))
    skip = sum(1 for r in mine if r.get("skipped"))
    fail = sum(1 for r in mine if not r.get("ok") and not r.get("skipped"))
    verifs = Counter(r.get("verification") for r in mine if r.get("ok"))
    print(f"\n총 벽시계 {wall:.1f}s · tag '{args.tag}' "
          f"성공 {ok} / 실패 {fail} / 건너뜀 {skip}")
    if verifs:
        print("판정 분포: " + ", ".join(f"{k} {v}" for k, v in verifs.most_common()))
    print(f"리포트: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
