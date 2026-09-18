#!/usr/bin/env python3
"""프롬프트 참고 문서(PROMPTS.md)를 소스에서 생성한다.

프롬프트 원문은 coarse_probe.py / fine_probe.py 의 상수(PROMPT, COMMON_BLOCK, DELTAS)가
**유일한 원본**이다 — 캐시와 prompt_hash 가 거기 걸려 있다. 이 스크립트는 그 상수를
읽어 PROMPTS.md 로 찍기만 한다. **PROMPTS.md 를 손으로 고치지 마라.** 프롬프트를 바꿀 땐
.py 상수를 고치고 `python modules/search/dump_prompts.py` 로 다시 찍는다. 그러면 문서와
코드가 어긋나지 않고, 문서 상단의 해시로 최신 여부가 확인된다.

PROMPTS.md 는 **부품**(공통 블록 + 델타)을, FULL_PROMPTS.md 는 **조립된 완성형**을 찍는다.
둘 다 이 스크립트가 만든다 — FULL_PROMPTS.md 는 2026-09-15 이전까지 수동 관리였고 실제로
한 번 낡았다(헤더 해시가 소스와 어긋남). 사람이 손으로 맞추는 사본은 반드시 표류한다.

두 probe 스크립트는 genai 를 함수 안에서 lazy import 하므로 SDK 없이도 import 된다.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import coarse_probe as coarse  # noqa: E402
import fine_probe as fine  # noqa: E402

OUT = HERE / "PROMPTS.md"
OUT_FULL = HERE / "FULL_PROMPTS.md"


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def fence(text: str) -> str:
    """프롬프트 원문을 코드펜스로 감싼다. 내부에 ``` 가 없다는 전제(실측 없음)."""
    return "```text\n" + text.rstrip("\n") + "\n```"


def build() -> str:
    coarse_prompt = coarse.build_prompt()
    coarse_hash = sha12(coarse_prompt)              # coarse_probe.py 와 동일한 계산(assembled sha256[:12])
    fine_hash = fine.prompt_fingerprint()           # COMMON_BLOCK + DELTAS 지문

    lines: list[str] = []
    w = lines.append

    w("<!-- 이 파일은 dump_prompts.py 가 생성한다. 손으로 고치지 마라. -->")
    w("<!-- 프롬프트를 바꾸려면 coarse_probe.py / fine_probe.py 의 상수를 고치고 -->")
    w("<!-- `python modules/search/dump_prompts.py` 로 다시 찍는다. -->")
    w("")
    w("# 탐침 프롬프트 (Coarse 1 + Fine 4)")
    w("")
    w("**원본은 코드다.** 아래는 그 사본이며 커밋 전 재생성으로 일치를 유지한다.")
    w("")
    w("| 프롬프트 | 원본 상수 | 해시(prompt_hash) |")
    w("|---|---|---|")
    w(f"| Coarse | `coarse_probe.py:PROMPT` (+ EVENT_DEFINITIONS·힌트 치환) | `{coarse_hash}` |")
    w(f"| Fine 공통+델타 | `fine_probe.py:COMMON_BLOCK` + `DELTAS` | `{fine_hash}` ({fine.PROMPT_VERSION}) |")
    w("")
    w("> 이 표의 해시가 jsonl(`probe_runs.jsonl`/`fine_probe_runs.jsonl`)의 `prompt_hash` 와")
    w("> 다르면 문서가 낡은 것이다 — 재생성하라.")
    w("")

    # -- Coarse --------------------------------------------------------------
    w("---")
    w("")
    w("## 1. Coarse — 후보 구간 탐색")
    w("")
    w(f"- 검색 대상: `{', '.join(coarse.TARGET_EVENT_TYPES)}`")
    w("- 역할: 싸게 넓게 훑어 Fine 이 검증할 후보 span 을 뱉는다. Recall 우선.")
    w("- 아래는 `build_prompt()` 가 조립한 **실제 전송 원문**이다(힌트는 비어 있어 `(없음)`).")
    w("")
    w(fence(coarse_prompt))
    w("")

    # -- Fine 공통 -----------------------------------------------------------
    w("---")
    w("")
    w("## 2. Fine — 정밀 검증 (공통 블록 + 델타 4)")
    w("")
    w("Fine 프롬프트 = **공통 블록 1개 + 유형별 델타 4개**. `build_prompt(event_type, ...)` 가")
    w("델타의 4슬롯(정의/필수요건/성립축/primitive예시)을 공통 블록의 `{EVENT_DEFINITION}` ·")
    w("`{REQUIRED_CONDITIONS}` · `{AXIS}` 자리에 끼워 넣는다. 아래 공통 블록의 `{...}` 자리가")
    w("각 유형의 델타로 채워진다.")
    w("")
    w("### 2.0 공통 블록 (4종 공통)")
    w("")
    w(fence(fine.COMMON_BLOCK))
    w("")

    # -- Fine 델타 4종 -------------------------------------------------------
    remap = {v: k for k, v in fine.LEGACY_COARSE_TO_CONTRACT.items() if v != k}
    for i, (etype, d) in enumerate(fine.DELTAS.items(), start=1):
        w(f"### 2.{i} `{etype}`")
        w("")
        note = f"  (Coarse 의 옛 이름 `{remap[etype]}` 에서 매핑)" if etype in remap else ""
        if note:
            w(f"> {note.strip()}")
            w("")
        w("**정의**")
        w("")
        w(fence(d["definition"]))
        w("")
        w("**성립 필수 관찰 (모두 충족해야 성립)**")
        w("")
        w(fence(d["conditions"]))
        w("")
        w("**성립 축**")
        w("")
        w(fence(d["axis"]))
        w("")
        w(f"**primitive 이름 예시:** {d['primitives_hint']}")
        w("")
        if d.get("temporal_hint"):
            w(f"**`temporal_facts[].fact` 이름 예시:** {d['temporal_hint']}")
            w("")

    return "\n".join(lines) + "\n"


def build_full() -> str:
    """조립된 완성형 프롬프트 — Coarse 1 + Fine 4. 실제 전송 원문과 같다."""
    coarse_prompt = coarse.build_prompt()
    lines: list[str] = []
    w = lines.append

    w("<!-- 이 파일은 dump_prompts.py 가 생성한다. 손으로 고치지 마라. -->")
    w("")
    w("# Coarse / Fine 조립 완성형 프롬프트")
    w("")
    w("`PROMPTS.md` 가 부품(공통 블록 + 델타)을 보여 준다면, 이 문서는 **실제로 전송되는**")
    w("조립 결과다. Fine 의 `{HINT_TYPE}`·`{HINT_SUMMARY}` 만 런타임에 후보 값으로 바뀐다.")
    w("")
    w("| 구분 | 원본 | 해시 |")
    w("|---|---|---|")
    w(f"| Coarse | `coarse_probe.py:PROMPT` (+ 조립) | `{sha12(coarse_prompt)}` |")
    w(f"| Fine | `fine_probe.py:COMMON_BLOCK` + `DELTAS` | `{fine.prompt_fingerprint()}` ({fine.PROMPT_VERSION}) |")
    w("")
    w("---")
    w("")
    w("## 1. Coarse")
    w("")
    w(fence(coarse_prompt))
    w("")
    w("---")
    w("")
    w("## 2. Fine")
    w("")
    for i, etype in enumerate(fine.DELTAS, start=1):
        w(f"### 2.{i} `{etype}`")
        w("")
        w(fence(fine.build_prompt(etype, "{{HINT_TYPE}}", "{{HINT_SUMMARY}}")))
        w("")
    return "\n".join(lines) + "\n"


def main() -> None:
    md = build()
    OUT.write_text(md, encoding="utf-8")
    print(f"wrote {OUT}  ({len(md)} chars)")
    full = build_full()
    OUT_FULL.write_text(full, encoding="utf-8")
    print(f"wrote {OUT_FULL}  ({len(full)} chars)")


if __name__ == "__main__":
    main()
