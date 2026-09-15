"""
coarse_probe.py — search Coarse 탐침 (throwaway)

이 파일은 제품 코드가 아니다. 계약도 구현도 아니고, 실측 숫자를 얻기 위한
일회용 스크립트다. 결과가 나오면 리포트만 남기고 버려도 된다.

무엇을 재는가
    - 클립 하나가 Gemini 파이프라인을 통과하는가, 각 단계 몇 초 걸리는가
    - 실측 입력 토큰 (메모의 "low = 100 tok/s" 추정과 대조용)
    - Coarse가 내놓는 후보 span의 개수와 내용
    - 같은 입력을 두 번 돌렸을 때 같은 후보가 나오는가 (신호 vs 노이즈)

무엇을 재지 못하는가
    - Recall. 정답지가 없으므로 놓친 사건은 셀 수 없다.
    - 40분 연속 탐색의 시각 drift. 5분 클립 단위 측정이다.
    이 결과를 Recall 주장으로 쓰지 말 것.

사전 준비
    uv venv && uv pip install google-genai

    API 키는 둘 중 하나로 준다. 환경변수가 .env 를 이긴다.
      1) .env 파일 (권장):  GEMINI_API_KEY=...      <- .gitignore 로 막혀 있다
      2) 환경변수        :  $env:GEMINI_API_KEY = "..."
    어느 쪽이든 git 이 추적하는 소스 파일에는 적지 않는다.

    영상 분할 (직접):
    ffmpeg -i <원본> -c copy -f segment -segment_time 300 -reset_timestamps 1 clips/clip_%03d.mp4

실행 (저장소 루트에서)
    python modules/search/coarse_probe.py chunks/ --concurrency 3
    python modules/search/coarse_probe.py --list-models        # 쓸 수 있는 모델 ID 확인
    python modules/search/coarse_probe.py chunks/ --tag run2   # 재현성 2회차
    python modules/search/coarse_probe.py chunks/ --fps 0.5 --tag fps05
    python modules/search/coarse_probe.py --report-only        # API 호출 없이 리포트만 재생성

    클립 일부만 돌릴 때는 순번이 어긋나므로 base 를 직접 준다:
    python modules/search/coarse_probe.py chunks/part_03.mp4 --index-base 1
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
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 설정 — 여기만 만지면 된다
# ---------------------------------------------------------------------------

MODEL = "gemini-3.7-flash"
MEDIA_RESOLUTION = "low"          # low | medium | high | ultra_high (3.x 는 소문자)
FPS = 1.0                         # (0.0, 24.0], SDK 기본 1.0
CLIP_SECONDS = 300                # ffprobe 가 없을 때만 쓰는 폴백. 길이는 클립마다 실측한다(clip_seconds).
CONCURRENCY = 3                   # 무료 티어 rate limit이 실제 상한이다. 낮게 시작할 것

# gemini-3.7-flash 유료 티어 (2026-09 기준, 100만 토큰당 USD).
# 주의: 공식 요금표에 2027-01-01 부터 2배로 오른다고 명시돼 있다 (0.75 -> 1.50, 3.75 -> 7.50).
# 해가 바뀌면 이 상수를 고치지 않는 한 리포트 비용이 절반으로 나온다.
PRICE_IN_PER_1M_USD = 0.75
PRICE_OUT_PER_1M_USD = 3.75

TARGET_EVENT_TYPES = [
    "SIGNAL",
    "CENTER_LINE_CROSSING",
    "LANE_CHANGE",
    "MOTORCYCLE_HELMET_NON_USE",
]

EVENT_DEFINITIONS = """\
- SIGNAL: 교차로의 신호등 상태와 차량의 정지선 통과 시점이 함께 관찰되는 장면.
  신호등 색과 차량의 진행이 시간에 따라 어떻게 변하는지가 근거가 된다.
- CENTER_LINE_CROSSING: 차량이 중앙선(황색 실선/복선)을 넘어 반대 차로 쪽으로
  차체가 걸치거나 진입하는 장면.
- LANE_CHANGE: 차량이 차선을 가로질러 다른 차로로 이동하는 장면.
  차로 경계 대비 차체 위치가 시간에 따라 이동하는 것이 근거가 된다.
- MOTORCYCLE_HELMET_NON_USE: 이륜차 탑승자의 머리 부분에 안전모가 관찰되지 않는 장면.
  시간 순서가 아니라 한 장면의 객체 속성으로 판단한다."""

VEHICLE_HINT = ""
FREE_TEXT_HINT = ""

# 프롬프트는 search Owner가 작성한 원문이다. 스크립트가 문구를 만들거나 고치지 않는다.
PROMPT = """당신은 장시간 블랙박스 영상에서 시각적 사건의 **후보 시간 구간을 찾는 Coarse Search 모델**입니다.

## 목표

주어진 검색 범위 전체를 확인하여 다음 시각적 사건이 발생했을 가능성이 있는 후보 구간을 찾으세요.

검색 대상:
`{TARGET_EVENT_TYPES}`

사건 정의:
`{EVENT_DEFINITIONS}`

사용자 힌트:
* 차량: `{VEHICLE_HINT}`
* 상황: `{FREE_TEXT_HINT}`

사용자 힌트는 참고 정보이며 정확하지 않을 수 있습니다. 힌트와 완전히 일치하지 않더라도 사건 가능성이 있다면 후보로 반환하세요.

## 판단 원칙

* **Recall을 Precision보다 우선하세요.**
* 사건을 확정할 필요는 없습니다. 불완전하거나 불확실한 증거라도 사건 가능성이 있다면 후보로 유지하세요.
* Fine Verification에서 이후 후보를 정밀하게 검증하므로, Coarse 단계에서 완전한 증거를 요구하지 마세요.
* 시간적 사건은 단일 장면만 보지 말고 차량, 차선, 중앙선, 신호 등의 시간에 따른 위치·상태 변화를 함께 고려하세요.
* 객체 속성 사건은 대상 객체와 관련 속성이 관찰될 가능성이 있는 구간을 찾으세요.
* 야간, 가림, 흐림, 낮은 해상도 등으로 판단이 어렵다는 이유만으로 의심되는 후보를 제거하지 마세요.
* 영상에서 직접 관찰할 수 있는 사실만 사용하세요.
* 교통법규 위반 여부, 운전자의 의도 또는 책임을 판단하지 마세요.
* 동일한 사건에 대한 겹치는 후보 구간은 가능한 경우 하나로 합치고, 서로 다른 사건은 별도의 후보로 유지하세요.
* Candidate 구간은 Fine Verification에서 다시 확인할 수 있는 전후 맥락을 포함하되 불필요하게 길게 잡지 마세요.

## 출력 원칙

각 Candidate의 `span`은 사건이 발생했을 가능성이 있는 시간 범위를 나타냅니다.
`at`은 Candidate를 대표하는 시점이며, 사건을 가장 잘 확인할 수 있다고 판단되는 시점을 선택하세요.
`observed`에는 Candidate를 선택한 이유가 되는 **직접 관찰 가능한 시각적 사실**만 기록하세요.
유형에 따라 다음 축을 우선해 적으세요. 이 값은 다음 단계가 이 후보를 다시 찾는 데 쓰입니다.

* `SIGNAL`: 신호등 점등 색과 그 변화, 차량과 정지선의 상대 위치 변화
* `CENTER_LINE_CROSSING`: 선의 **색**과 **실선/복선 여부**, 차체와 그 선의 상대 위치 변화
* `LANE_CHANGE`: 선의 **색**과 **실선/점선 여부**, 차체의 횡방향 이동
* `MOTORCYCLE_HELMET_NON_USE`: 이륜차와 탑승자의 존재, 탑승자 머리 부분의 가시 여부

야간, 역광, 우천, 가림처럼 관찰을 제한한 조건이 있었다면 그것도 `observed`에 함께 적으세요. 후보를 제거하는 이유가 아니라 다음 단계가 알아야 할 사실입니다.

`score`는 사건 발생 확률이 아니라 Candidate 간 **상대적인 검색 우선순위**를 나타냅니다.
**이 응답 안의 Candidate들에는 서로 다른 `score`를 주세요.** 여러 후보에 같은 값을 쓰면 우선순위 정보가 사라집니다. 확신이 비슷하더라도 다시 볼 순서를 정하고, 그 순서가 드러나도록 값을 벌리세요.

검색 대상 사건의 가능성이 있는 구간을 찾지 못했다면 빈 Candidate 목록을 반환하세요."""

# ---------------------------------------------------------------------------
# 출력 스키마
#
# Interactions API 의 response_format 은 표준 JSON Schema(소문자 type)를 쓴다.
# 구 generate_content 의 대문자 OBJECT/STRING 스타일이 아니다.
# 프롬프트가 요구하는 span / at / observed / score 를 그대로 강제한다.
# 시간 단위 혼동을 막으려고 필드명에 _sec 를 붙였다 (at_sec == 프롬프트의 at).
#
# legal_status 같은 법적 확정 필드는 두지 않는다.
# search 출력이 법적 위반을 표현할 수 없어야 한다는 규칙이 스키마에 박혀 있어야 한다.
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "description": "사건 가능성이 있는 후보 구간. 없으면 빈 배열.",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": TARGET_EVENT_TYPES + ["NONE"],
                        "description": "이 후보가 어느 검색 대상에 해당하는지.",
                    },
                    "span": {
                        "type": "object",
                        "description": "사건이 발생했을 가능성이 있는 시간 범위(초, 클립 시작 기준).",
                        "properties": {
                            "start_sec": {"type": "number"},
                            "end_sec": {"type": "number"},
                        },
                        "required": ["start_sec", "end_sec"],
                    },
                    "at_sec": {
                        "type": "number",
                        "description": "후보를 대표하는 시점(초, 클립 시작 기준). 프롬프트의 at.",
                    },
                    "observed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "직접 관찰 가능한 시각적 사실만.",
                    },
                    "score": {
                        "type": "number",
                        "description": "후보 간 상대적 검색 우선순위. 발생 확률이 아니다.",
                    },
                },
                "required": ["event_type", "span", "at_sec", "observed", "score"],
            },
        }
    },
    "required": ["candidates"],
}

# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
RUNS_PATH = HERE / "probe_runs.jsonl"
REPORT_PATH = HERE / "probe_report.md"

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".ts", ".webm"}
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


def find_env_files() -> list[Path]:
    """.env 를 찾을 위치. 앞에 있는 것이 우선."""
    seen, out = set(), []
    for d in (Path.cwd(), HERE, HERE.parent.parent):
        f = (d / ".env").resolve()
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def parse_env_file(path: Path) -> dict:
    """의존성 없이 .env 를 읽는다. KEY=value, 주석, 따옴표, export 접두어를 처리."""
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
        # 따옴표로 감싼 값은 벗기고, 안 감쌌으면 뒤쪽 인라인 주석을 잘라낸다
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        else:
            val = val.split(" #")[0].strip()
        data[key] = val
    return data


def load_api_key() -> tuple[str | None, str]:
    """API 키와 그 출처를 돌려준다.

    이미 설정된 환경변수가 .env 를 이긴다 (python-dotenv 기본 동작과 같다).
    한 번만 쓰고 싶을 때 셸에서 덮어쓸 수 있어야 하기 때문이다.
    """
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
# 클립 수집
# ---------------------------------------------------------------------------


def clip_index_of(path: Path, fallback: int) -> int:
    """파일명 끝의 숫자를 클립 순번으로 본다. 없으면 정렬 순서를 쓴다."""
    m = re.search(r"(\d+)\s*$", path.stem)
    return int(m.group(1)) if m else fallback


def collect_clips(paths: list[str]) -> list[dict]:
    """경로 여러 개(파일·폴더 섞어서)에서 클립 목록을 만든다.

    source = 클립이 들어 있는 폴더 이름. 여러 영상을 한 번에 돌릴 때
    어느 원본에서 나온 클립인지 구분하는 키가 된다.
    """
    clips: list[dict] = []
    seen: set[Path] = set()

    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            found = sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
            if not found:
                log(f"  ! {p} 안에 영상 파일이 없다")
            for i, f in enumerate(found):
                if f in seen:
                    continue
                seen.add(f)
                clips.append({"path": f, "source": p.name, "clip_index": clip_index_of(f, i)})
        elif p.is_file():
            if p in seen:
                continue
            seen.add(p)
            clips.append({"path": p, "source": p.parent.name, "clip_index": clip_index_of(p, 0)})
        else:
            log(f"  ! 경로를 찾을 수 없다: {p}")

    clips.sort(key=lambda c: (c["source"], c["clip_index"], c["path"].name))
    return clips


def normalize_ordinals(clips: list[dict], index_base) -> int:
    """파일명 번호를 0 기준 순번(clip_ordinal)으로 맞춘다.

    part_01..part_08 처럼 1부터 시작하는 이름을 그대로 쓰면 절대시각이
    통째로 한 클립만큼 밀린다. base 를 빼서 맞춘다.

    index_base=None 이면 수집된 클립의 최소 번호를 base 로 본다.
    클립 일부만 골라 돌릴 때는 --index-base 로 직접 지정할 것.
    """
    base = index_base
    if base is None:
        base = min((c["clip_index"] for c in clips), default=0)
    for c in clips:
        c["clip_ordinal"] = c["clip_index"] - base
    return base


# ---------------------------------------------------------------------------
# 기록 — jsonl 은 append only. 절대 덮어쓰지 않는다.
# ---------------------------------------------------------------------------


def append_run(row: dict) -> None:
    with _write_lock:
        with RUNS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_runs() -> list[dict]:
    if not RUNS_PATH.exists():
        return []
    rows = []
    for line in RUNS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 깨진 줄은 건너뛴다. 원본은 그대로 둔다.
    return rows


def build_caches(rows: list[dict]) -> tuple[dict, set]:
    """이전 실행 기록에서 두 가지를 되살린다.

    uri_cache : 클립 -> 업로드된 파일 참조. 재업로드를 피한다 (48h 만료 전까지).
    done      : 같은 조건으로 이미 성공한 (클립, 조건) 조합. 다시 돌리지 않는다.
    """
    uri_cache: dict[str, dict] = {}
    done: set[tuple] = set()
    for r in rows:
        if r.get("file_uri") and r.get("file_name"):
            uri_cache[r["clip_path"]] = {"uri": r["file_uri"], "name": r["file_name"]}
        if r.get("ok"):
            done.add(run_key(r))
    return uri_cache, done


def run_key(r: dict) -> tuple:
    return (
        r.get("clip_path"),
        r.get("tag"),
        r.get("prompt_hash"),
        r.get("model"),
        r.get("media_resolution"),
        r.get("fps"),
        r.get("schema"),
    )


# ---------------------------------------------------------------------------
# Gemini 호출
# ---------------------------------------------------------------------------


def sdk_known_models(ix) -> set[str]:
    """SDK 의 Interactions 모델 Literal 목록. models.list() 가 3.x 를 안 줄 때의 보조."""
    import typing
    try:
        hints = typing.get_type_hints(ix.CreateModelInteraction)
        out: set[str] = set()
        for arg in typing.get_args(hints["model"]):
            out.update(x for x in typing.get_args(arg) if isinstance(x, str))
        return out
    except Exception:  # noqa: BLE001
        return set()


def client_models(genai, api_key: str) -> list[str]:
    """이 키로 generateContent 가능한 모델 ID 목록. 실패하면 빈 목록."""
    try:
        c = genai.Client(api_key=api_key)
        out = []
        for m in c.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                out.append((m.name or "").replace("models/", ""))
        return sorted(set(filter(None, out)))
    except Exception as e:  # noqa: BLE001
        print(f"  ! 모델 목록 조회 실패 ({type(e).__name__}). 검증을 건너뛴다.", file=sys.stderr)
        return []


def build_prompt() -> str:
    return (
        PROMPT.replace("{TARGET_EVENT_TYPES}", ", ".join(TARGET_EVENT_TYPES))
        .replace("{EVENT_DEFINITIONS}", EVENT_DEFINITIONS)
        .replace("{VEHICLE_HINT}", VEHICLE_HINT or "(없음)")
        .replace("{FREE_TEXT_HINT}", FREE_TEXT_HINT or "(없음)")
    )


PLATE_RE = re.compile(r"\d{2,3}\s*[가-힣]\s*\d{4}")


def mask_sensitive(text: str) -> str:
    """저장 전에 번호판 문자열을 지운다.

    ★ 기록에 남기면 안 되는 값이다 — `product-spec` §7 과
      `contract-usage-record` 가 번호판 문자열 보관을 금지한다.
      프롬프트는 번호판을 묻지 않는데도 모델이 `observed` 에 넣었다
      (45건 중 1건 실측). 프롬프트만으로는 막히지 않으므로 기록 층에서 막는다.
    """
    return PLATE_RE.sub("[번호판]", text)


def mask_candidates(cands):
    """후보의 자유 텍스트(observed)에 마스킹을 적용한다."""
    if not cands:
        return cands
    out = []
    for c in cands:
        c = dict(c)
        if isinstance(c.get("observed"), list):
            c["observed"] = [mask_sensitive(str(x)) for x in c["observed"]]
        out.append(c)
    return out


def read_usage(resp) -> dict:
    """usage 를 전량 읽는다. None 과 0 을 구분한다. (fine_probe.py 와 같은 구현)"""
    u = getattr(resp, "usage", None)
    keys = ("input_tokens", "output_tokens", "thought_tokens",
            "total_tokens", "cached_tokens", "input_tokens_by_modality")
    if u is None:
        return {k: None for k in keys}

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


def probe_duration(path: str) -> float | None:
    """ffprobe 로 실제 클립 길이(초)를 읽는다. 없으면 None."""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        return float(out) if out else None
    except Exception:  # noqa: BLE001
        return None


def clip_starts(rows: list[dict]) -> dict:
    """clip_path -> 원본 기준 시작 초. 실측 길이의 누적이다.

    ★ `clip_ordinal x CLIP_SECONDS` 를 쓰지 않는다.
      `ffmpeg -c copy` 는 키프레임 경계에서 자르므로 세그먼트가 정확히 300초가 아니다.
      실측: 304.30 / 298.97 x4 / 304.30 / 298.97 / 244.50.
      300초 가정으로 환산하면 원본 위치가 **최대 4.47초 어긋난다**(part_07).
      후보 span 이 4~9초인데 환산 오차가 span 길이와 맞먹는다 —
      「말한 시각이 맞는가」를 사람이 확인하는 표가 그 위에 서 있으므로 그냥 둘 수 없다.

      ffprobe 가 없거나 파일이 사라졌으면 그 클립만 가정으로 떨어진다.
    """
    seen: dict[str, int] = {}
    for r in rows:
        p = r.get("clip_path")
        if p and p not in seen:
            seen[p] = r.get("clip_index") or 0

    out: dict[str, dict] = {}
    cursor = 0.0
    for p in sorted(seen, key=lambda k: (seen[k], k)):
        d = probe_duration(p)
        out[p] = {"start_sec": round(cursor, 3),
                  "duration_sec": d if d is not None else float(CLIP_SECONDS),
                  "source": "ffprobe" if d is not None else "assumed"}
        cursor += out[p]["duration_sec"]
    return out


def is_rate_limited(exc: Exception) -> bool:
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "rate limit" in s.lower()


def ensure_uploaded(client, clip: dict, cached: dict | None, mime: str) -> tuple[dict, float, float]:
    """캐시된 참조가 아직 살아 있으면 재사용하고, 아니면 새로 올린다."""
    if cached:
        try:
            f = client.files.get(name=cached["name"])
            if str(getattr(f.state, "name", f.state)) == "ACTIVE":
                return {"uri": f.uri, "name": f.name}, 0.0, 0.0
        except Exception:
            pass  # 만료됐거나 사라졌다. 새로 올린다.

    t0 = time.monotonic()
    f = client.files.upload(file=str(clip["path"]), config={"mime_type": mime})
    upload_sec = time.monotonic() - t0

    t1 = time.monotonic()
    while str(getattr(f.state, "name", f.state)) == "PROCESSING":
        time.sleep(2)
        f = client.files.get(name=f.name)
    active_wait_sec = time.monotonic() - t1

    state = str(getattr(f.state, "name", f.state))
    if state != "ACTIVE":
        raise RuntimeError(f"업로드 파일 상태가 {state} 다 ({clip['path'].name})")

    return {"uri": f.uri, "name": f.name}, upload_sec, active_wait_sec


def process_clip(client, ix, clip: dict, prompt: str, args, prompt_hash: str,
                 cached: dict | None, counter: dict, total: int) -> dict:
    mime = MIME_BY_EXT.get(clip["path"].suffix.lower(), "video/mp4")

    # 길이는 고정 300초로 가정하지 않는다. 클립마다 ffprobe 로 실측한다.
    # ffprobe 가 없거나 못 읽으면 None → tok/영상초·환산은 CLIP_SECONDS 로 떨어진다.
    clip_seconds = probe_duration(str(clip["path"]))

    row = {
        "ts": now_iso(),
        "tag": args.tag,
        "source": clip["source"],
        "clip": clip["path"].name,
        "clip_path": str(clip["path"]),
        "clip_index": clip["clip_index"],
        "clip_ordinal": clip["clip_ordinal"],
        "index_base": args.index_base_used,
        "clip_seconds": clip_seconds,
        "model": args.model,
        "media_resolution": args.media_resolution,
        "fps": args.fps,
        "concurrency": args.concurrency,
        "prompt_hash": prompt_hash,
        "schema": not args.no_schema,
    }

    upload_sec = active_wait_sec = generate_sec = 0.0
    delay = 5.0

    for attempt in range(1, args.max_retries + 2):
        try:
            ref, u_sec, a_sec = ensure_uploaded(client, clip, cached, mime)
            upload_sec += u_sec
            active_wait_sec += a_sec
            row["file_uri"] = ref["uri"]
            row["file_name"] = ref["name"]

            # Gemini 3.x 는 Interactions API 를 쓴다.
            # 구 generate_content + types.Part/VideoMetadata 조합이 아니다.
            #   resolution  : low | medium | high | ultra_high  (구 media_resolution)
            #   processing  : {type: static, fps, start_offset, end_offset}
            #
            # 반드시 타입 객체로 넘길 것. raw dict 로 넘기면
            # InteractionsInput = Union[Content, List[Step], List[Content], str] 에서
            # List[Step] 이 먼저 매칭돼 UnknownStep 으로 삼켜지고 필드가 전부 사라진다.
            video_input = ix.VideoContent(
                type="video",
                uri=ref["uri"],
                mime_type=mime,
                resolution=args.media_resolution,
                processing={"type": "static", "fps": args.fps},
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

            # usage 전량을 기록한다 (fine_probe.py 에서 역이식, 2026-09-10).
            # 이전에는 total_input_tokens / total_output_tokens 두 개만 읽었다.
            #
            # ★ `or 0` 을 쓰지 않는다. None 과 0 은 다르다 —
            #   None 은 "provider 가 안 줬다", 0 은 "안 썼다"다.
            #   `or 0` 으로 뭉개면 원가가 조용히 0 으로 보고된다.
            # ★ total_thought_tokens 를 반드시 읽는다. 실측에서 total_tokens 가
            #   in + out + thought 였다 — thought 를 빼면 원가가 과소 보고된다.
            usage = read_usage(resp)
            row["usage"] = usage
            tok_in = usage["input_tokens"] or 0     # 기존 리포트 호환용
            tok_out = usage["output_tokens"] or 0
            row["interaction_id"] = getattr(resp, "id", None)
            row["status"] = status or None

            text = (getattr(resp, "output_text", None) or "").strip()
            parsed, parse_error = None, None
            if not args.no_schema:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as e:
                    parse_error = str(e)

            candidates = parsed.get("candidates") if isinstance(parsed, dict) else None

            row.update({
                "ok": True,
                "attempt": attempt,
                "upload_sec": round(upload_sec, 2),
                "active_wait_sec": round(active_wait_sec, 2),
                "generate_sec": round(generate_sec, 2),
                "input_tokens": tok_in,
                "output_tokens": tok_out,
                "tokens_per_sec_of_video": (
                    round(tok_in / (clip_seconds or CLIP_SECONDS), 1)
                    if (clip_seconds or CLIP_SECONDS) else None),
                "cost_usd_est": round(
                    tok_in / 1_000_000 * PRICE_IN_PER_1M_USD
                    + tok_out / 1_000_000 * PRICE_OUT_PER_1M_USD, 6),
                "candidate_count": len(candidates) if candidates is not None else None,
                # 모델 출력에 번호판이 섞여 나온다. 저장 전에 마스킹한다.
                "candidates": mask_candidates(candidates),
                "raw_text": None if candidates is not None else mask_sensitive(text),
                "parse_error": parse_error,
            })

            append_run(row)   # 무엇보다 먼저 기록한다

            with _print_lock:
                counter["n"] += 1
                n = counter["n"]
            cc = row["candidate_count"]
            log(f"[{n}/{total}] {clip['source']}/{clip['path'].name} 완료 "
                f"({generate_sec:.1f}s, 후보 {cc if cc is not None else '?'}개, in {tok_in} tok)")
            return row

        except Exception as e:  # noqa: BLE001 — 어떤 실패든 기록하고 넘어간다
            limited = is_rate_limited(e)
            if attempt <= args.max_retries and limited:
                sleep_for = delay + random.uniform(0, 2)
                log(f"  · {clip['path'].name} 429 — {sleep_for:.0f}s 뒤 재시도 ({attempt}/{args.max_retries})")
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
            log(f"[{n}/{total}] {clip['source']}/{clip['path'].name} 실패 — {type(e).__name__}: {str(e)[:160]}")
            return row

    return row  # 도달하지 않는다


# ---------------------------------------------------------------------------
# 리포트 — jsonl 에서 파생. 언제든 다시 만들 수 있다.
# ---------------------------------------------------------------------------


def fmt(v, spec="", dash="-"):
    if v is None:
        return dash
    return format(v, spec) if spec else str(v)


def top_candidate_summary(row: dict, starts: dict | None = None) -> str:
    cands = row.get("candidates")
    if cands is None:
        if row.get("raw_text"):
            return "(스키마 없음 — raw_text 참조)"
        return "-"
    if not cands:
        return "후보 없음"
    top = max(cands, key=lambda c: c.get("score") or 0)
    at = top.get("at_sec")

    # 실측 클립 시작이 있으면 그것을 쓴다. 없으면 300초 가정으로 떨어진다.
    g = (starts or {}).get(row.get("clip_path"))
    if g:
        abs_sec = g["start_sec"] + (at or 0)
        oob = "" if at is None or at <= g["duration_sec"] else " **[클립 길이 초과]**"
        obs_ = "; ".join(top.get("observed") or [])[:90]
        return (f"at {fmt(at, '.0f')}s (원본 {int(abs_sec // 60)}분{int(abs_sec % 60):02d}초){oob} / "
                f"{top.get('event_type')} / score {fmt(top.get('score'), '.2f')} / {obs_}")

    ordinal = row.get("clip_ordinal")
    if ordinal is None:
        ordinal = row.get("clip_index", 0)
    abs_sec = ordinal * (row.get("clip_seconds") or CLIP_SECONDS) + (at or 0)
    obs = "; ".join(top.get("observed") or [])[:90]
    return (f"at {fmt(at, '.0f')}s (원본 ~{int(abs_sec // 60)}분{int(abs_sec % 60):02d}초) / "
            f"{top.get('event_type')} / score {fmt(top.get('score'), '.2f')} / {obs}")


def write_report(rows: list[dict]) -> None:
    # 원본 위치 환산은 실측 클립 길이의 누적을 쓴다 (clip_starts 참조).
    starts = clip_starts(rows)
    lines: list[str] = []
    lines.append("# Coarse Probe Report")
    lines.append("")
    lines.append(f"생성: {now_iso()}  ·  원본 기록: `{RUNS_PATH.name}` ({len(rows)}줄)")
    lines.append("")
    lines.append("> 이 리포트는 `probe_runs.jsonl`에서 파생된 요약이다. 언제든 `--report-only`로 다시 만들 수 있다.")
    lines.append("> **Recall은 측정하지 않았다.** 정답지가 없으므로 놓친 사건은 셀 수 없고,")
    lines.append("> 5분 클립 단위 측정이라 40분 연속 탐색의 시각 drift도 여기 없다.")
    lines.append("> 비용은 파일 상단 단가 상수 기준 **추정치**다.")
    lines.append("")

    by_tag: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_tag[r.get("tag") or "default"][r.get("source") or "-"].append(r)

    g_tok_in = g_tok_out = g_cost = 0
    g_ok = g_fail = g_zero = g_cand = 0
    g_secs = 0.0   # 실측 영상 길이의 누적 (성공 건만). 평균 tok/영상초 분모.

    for tag in sorted(by_tag):
        lines.append(f"## tag: `{tag}`")
        lines.append("")
        for source in sorted(by_tag[tag]):
            rs = sorted(by_tag[tag][source], key=lambda r: (r.get("clip_index", 0), r.get("clip", "")))
            lines.append(f"### {source}")
            lines.append("")
            lines.append("| 클립 | 후보 | 입력tok | 출력tok | tok/영상초 | 지연(s) | 비용($) | 최상위 후보 |")
            lines.append("|---|---|---|---|---|---|---|---|")

            s_in = s_out = s_cost = 0
            for r in rs:
                if not r.get("ok"):
                    err = (r.get("error") or {}).get("type", "실패")
                    lines.append(f"| {r.get('clip')} | **{err}** | - | - | - | "
                                 f"{fmt(r.get('generate_sec'), '.1f')} | - | "
                                 f"{(r.get('error') or {}).get('message', '')[:80]} |")
                    g_fail += 1
                    continue

                s_in += r.get("input_tokens") or 0
                s_out += r.get("output_tokens") or 0
                s_cost += r.get("cost_usd_est") or 0
                g_secs += (r.get("clip_seconds")
                           or (starts.get(r.get("clip_path")) or {}).get("duration_sec")
                           or CLIP_SECONDS)
                g_ok += 1
                cc = r.get("candidate_count")
                if cc == 0:
                    g_zero += 1
                if cc:
                    g_cand += cc

                lines.append(
                    f"| {r.get('clip')} | {fmt(cc)} | {fmt(r.get('input_tokens'))} | "
                    f"{fmt(r.get('output_tokens'))} | {fmt(r.get('tokens_per_sec_of_video'), '.1f')} | "
                    f"{fmt(r.get('generate_sec'), '.1f')} | {fmt(r.get('cost_usd_est'), '.5f')} | "
                    f"{top_candidate_summary(r, starts)} |"
                )

            lines.append(f"| **소계** | | **{s_in}** | **{s_out}** | | | **{s_cost:.5f}** | |")
            lines.append("")
            g_tok_in += s_in
            g_tok_out += s_out
            g_cost += s_cost

    lines.append("## 전체 합계")
    lines.append("")
    lines.append(f"- 성공 {g_ok}건 / 실패 {g_fail}건")
    lines.append(f"- 입력 {g_tok_in:,} tok · 출력 {g_tok_out:,} tok · 추정비용 ${g_cost:.4f}")
    lines.append(f"- 후보 총 {g_cand}개, **후보 0개인 클립 {g_zero} / {g_ok}건**  ← 오탐 경향의 첫 신호")
    if g_ok and g_secs:
        lines.append(f"- 평균 입력토큰/영상초 = {g_tok_in / g_secs:.1f} "
                     f"(실측 영상 {g_secs:.0f}초 기준 · 메모의 low ≈ 100 tok/s 추정과 대조할 것)")
    lines.append("")
    lines.append("## 실행 뒤에 사람이 해야 하는 일")
    lines.append("")
    lines.append("표의 「원본 N분NN초」 지점을 직접 열어 보고 세 가지를 적는다.")
    lines.append("**이 값은 ffprobe 로 읽은 실측 클립 길이의 누적으로 환산한 것이다.**")
    lines.append("`clip_ordinal × 300` 으로 계산하면 최대 4.47초 어긋난다 — "
                 "`ffmpeg -c copy` 가 키프레임 경계에서 자르기 때문이다"
                 "(실측 304.30 / 298.97 / 244.50).")
    lines.append("")
    lines.append("| 확인 | 뜻 |")
    lines.append("|---|---|")
    lines.append("| 그 구간에 실제로 뭔가 있는가 | precision |")
    lines.append("| **말한 시각이 맞는가 (초 오차)** | timestamp 정확도 — 제품 성립의 급소 |")
    lines.append("| event_type이 맞는가 | 유형 판단 |")
    lines.append("")
    lines.append("시각 오차가 크면 precision이 좋아도 제품이 안 된다. "
                 "후보 카드를 눌러 갔는데 거기 아무것도 없으면 카드가 무의미하기 때문이다.")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------


def main() -> int:
    # Windows 콘솔 코드페이지와 무관하게 한글이 깨지지 않게 한다
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="search Coarse 탐침 (throwaway)")
    ap.add_argument("paths", nargs="*", help="클립 폴더 또는 파일 (여러 개 가능)")
    ap.add_argument("--tag", default="default", help="회차·조건 이름. jsonl에 그대로 기록된다")
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    ap.add_argument("--fps", type=float, default=FPS)
    ap.add_argument("--media-resolution", default=MEDIA_RESOLUTION,
                    choices=["low", "medium", "high", "ultra_high"])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-retries", type=int, default=3, help="429일 때만 재시도")
    ap.add_argument("--no-schema", action="store_true", help="structured output 없이 원문 그대로 기록")
    ap.add_argument("--force", action="store_true", help="같은 조건으로 이미 성공한 클립도 다시 돌린다")
    ap.add_argument("--index-base", type=int, default=None,
                    help="파일명 번호의 시작값. 기본은 자동(수집된 최소 번호). "
                         "클립 일부만 골라 돌릴 때는 직접 지정할 것")
    ap.add_argument("--list-models", action="store_true",
                    help="이 키로 쓸 수 있는 모델 ID를 출력하고 끝낸다")
    ap.add_argument("--report-only", action="store_true", help="API 호출 없이 리포트만 재생성")
    args = ap.parse_args()

    if args.report_only:
        rows = load_runs()
        if not rows:
            print(f"기록이 없다: {RUNS_PATH}")
            return 1
        write_report(rows)
        print(f"리포트 재생성: {REPORT_PATH}  ({len(rows)}줄)")
        return 0

    if not args.paths:
        ap.error("클립 폴더나 파일을 하나 이상 지정할 것 (또는 --report-only)")

    api_key, key_source = load_api_key()
    if not api_key:
        print("API 키를 찾지 못했다. 둘 중 하나로 주면 된다:", file=sys.stderr)
        print("", file=sys.stderr)
        print("  1) .env 파일 (권장, .gitignore 로 막혀 있다)", file=sys.stderr)
        print("     GEMINI_API_KEY=...", file=sys.stderr)
        print("     찾는 위치:", file=sys.stderr)
        for f in find_env_files():
            print(f"       {f}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  2) 환경변수 (이쪽이 .env 를 이긴다)", file=sys.stderr)
        print('     $env:GEMINI_API_KEY = "..."', file=sys.stderr)
        print("", file=sys.stderr)
        print("어느 쪽이든 추적되는 소스 파일에는 적지 말 것.", file=sys.stderr)
        return 1
    print(f"API 키: {key_source} — {mask(api_key)}")

    try:
        from google import genai
        from google.genai import interactions as ix
    except ImportError:
        print("google-genai 가 없다:  uv pip install google-genai", file=sys.stderr)
        return 1

    if args.list_models:
        listed = client_models(genai, api_key)
        print("이 키로 조회된 모델 (legacy Models API):")
        print("")
        for m in listed:
            print(f"  {m}")
        print("")
        print("SDK 가 아는 Interactions 모델 (3.x 는 여기에만 있을 수 있다):")
        print("")
        for m in sorted(sdk_known_models(ix)):
            print(f"  {m}")
        return 0

    available = client_models(genai, api_key)
    known = sdk_known_models(ix)
    # models.list() 는 legacy Models API 목록이라 3.x 가 빠질 수 있다.
    # 둘 중 어디에도 없을 때만 막는다.
    if available and args.model not in available and args.model not in known:
        print(f"모델 '{args.model}' 을 이 키로 쓸 수 없다.", file=sys.stderr)
        flash = [m for m in available if "flash" in m]
        print("", file=sys.stderr)
        print("쓸 수 있는 flash 계열:", file=sys.stderr)
        for m in (flash or available):
            print(f"  {m}", file=sys.stderr)
        print("", file=sys.stderr)
        print("--model 로 지정할 것.", file=sys.stderr)
        return 1

    clips = collect_clips(args.paths)
    if not clips:
        print("처리할 클립이 없다.", file=sys.stderr)
        return 1

    args.index_base_used = normalize_ordinals(clips, args.index_base)

    prompt = build_prompt()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]

    prior = load_runs()
    uri_cache, done = build_caches(prior)

    pending = []
    skipped = 0
    for c in clips:
        key = (str(c["path"]), args.tag, prompt_hash, args.model,
               args.media_resolution, args.fps, not args.no_schema)
        if not args.force and key in done:
            skipped += 1
            continue
        pending.append(c)

    by_source = defaultdict(int)
    for c in pending:
        by_source[c["source"]] += 1

    print(f"클립 {len(clips)}개 발견 · 영상 {len(set(c['source'] for c in clips))}개"
          + (f" · 이미 완료 {skipped}개 건너뜀" if skipped else ""))
    for s, n in sorted(by_source.items()):
        print(f"    {s}: {n}개")
    print(f"모델 {args.model} · {args.media_resolution} · fps {args.fps} · "
          f"동시 {args.concurrency} · tag '{args.tag}' · prompt {prompt_hash}")
    print(f"클립 순번 base {args.index_base_used} "
          f"(파일명 번호 - {args.index_base_used} = 0부터 시작하는 순번)")
    print(f"기록: {RUNS_PATH}\n")

    if not pending:
        write_report(load_runs())
        print("새로 돌릴 클립이 없다. 리포트만 갱신했다.")
        return 0

    counter = {"n": 0}
    total = len(pending)
    wall0 = time.monotonic()

    client = genai.Client(api_key=api_key)

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [
            pool.submit(process_clip, client, ix, c, prompt, args, prompt_hash,
                        uri_cache.get(str(c["path"])), counter, total)
            for c in pending
        ]
        for fut in as_completed(futures):
            try:
                fut.result()   # 기록은 워커가 이미 했다. 여기선 예외만 확인한다
            except Exception as e:  # noqa: BLE001
                log(f"  ! 워커 예외: {type(e).__name__}: {e}")

    wall = time.monotonic() - wall0
    rows = load_runs()
    write_report(rows)

    ok = sum(1 for r in rows if r.get("tag") == args.tag and r.get("ok"))
    fail = sum(1 for r in rows if r.get("tag") == args.tag and not r.get("ok"))
    print(f"\n총 벽시계 {wall:.1f}s · tag '{args.tag}' 성공 {ok} / 실패 {fail}")
    print(f"리포트: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
