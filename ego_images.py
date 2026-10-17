"""에고라이트로 그림 만들기 — 제미나이 → 챗GPT (2026-10-18 · 맥 전용).

사진 순서(에디님 10/18):
  1. 픽사베이·언스플래시 무료 사진 (image_finder)
  2. 제미나이 — 에고라이트에서 직접 들어가 그림 뽑기   ← 여기
  3. 챗GPT  — 에고라이트에서 직접 들어가 그림 뽑기   ← 여기
  4. 그래도 없으면 빨간 [사진N] 자리로 남긴다 (주인이 직접 넣기)

에고라이트에서 제미나이(gemini.google.com)·챗GPT(chatgpt.com)에 **주인이 직접 로그인**해 둬야 한다.
로그인이 안 돼 있으면 조용히 건너뛰고 다음 순서로 간다.
"""
from __future__ import annotations

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
#: 에고라이트 프로필을 따로 쓰고 싶으면 환경변수로(없으면 기본 프로필)
PROFILE = os.environ.get("EDI_EGO_IMAGE_PROFILE", "")


def _prompt(desc: str) -> str:
    return (f"블로그 본문에 넣을 사진 한 장을 만들어줘. 장면: {desc}. "
            "실제 사진처럼 자연스럽고 밝은 톤, 가로 16:9. "
            "알아볼 수 있는 사람 얼굴·실존 인물·브랜드 로고·글자·워터마크는 넣지 마.")


def _run(driver: str, descs: list[str], outs: list[str], log, per_image_sec: int, budget_sec: int,
         name: str) -> list[bool]:
    import shutil
    n = len(descs)
    b = next((c for c in (shutil.which("ego-browser"), os.path.expanduser("~/.local/bin/ego-browser"))
              if c and os.path.exists(c)), "")
    if not n or not b:
        return [False] * n
    work = os.path.join(HERE, "work")
    os.makedirs(work, exist_ok=True)
    tmp = os.path.join(work, f"ego_{name}.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"prompts": [_prompt(d) for d in descs], "outs": [os.path.abspath(o) for o in outs],
                   "perImageMs": per_image_sec * 1000, "budgetMs": budget_sec * 1000,
                   "profileId": PROFILE, "spaceName": f"{name} 그림"}, f, ensure_ascii=False)
    src = f"const PAYLOAD_PATH = {json.dumps(tmp)};\n" + open(os.path.join(HERE, "ego", driver), encoding="utf-8").read()
    try:
        proc = subprocess.run([b, "nodejs"], input=src, text=True, capture_output=True,
                              timeout=budget_sec + per_image_sec + 120)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception as e:  # noqa: BLE001
        log(f"  {name} 실행 실패 → 다음 순서로: {str(e)[:80]}")
        return [False] * n
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"results"' in line:
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            why = r.get("why")
            if why == "logged_out":
                log(f"  {name}: 에고라이트에서 로그인이 안 돼 있습니다 → 건너뜀 (에고라이트에서 직접 로그인해 두면 다음부터 씁니다)")
            elif why == "limit":
                log(f"  {name}: 오늘 그림 한도에 걸림 → 다음 순서로")
            elif why:
                log(f"  {name} 오류: {str(why)[:100]}")
            res = [bool(x) for x in (r.get("results") or [])][:n]
            return res + [False] * (n - len(res))
    log(f"  {name} 결과를 못 읽음 → 다음 순서로")
    return [False] * n


def gemini(descs, outs, log=print) -> list[bool]:
    return _run("gemini.mjs", descs, outs, log, 150, 600, "제미나이")


def chatgpt(descs, outs, log=print) -> list[bool]:
    return _run("chatgpt.mjs", descs, outs, log, 180, 900, "챗GPT")
