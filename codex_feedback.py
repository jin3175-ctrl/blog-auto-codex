#!/usr/bin/env python3
"""② 코덱스 피드백 — **클로드(이 저장소)가 코덱스를 직접 부른다** (2026-09-15 에디님 결정).

> "좋아 너가 같이 일하는 방식으로 하자."

코덱스 앱 자동화 대신 ChatGPT 앱에 들어 있는 `codex` 실행 파일을 터미널에서 부른다.
로그인은 앱 계정을 그대로 쓴다(2026-09-15 실측: 헤드리스 실행 종료코드 0, 글 한 편 피드백 24초).

    ① run_ai_daily 끝 → _단계/1_생성완료 → [이 파일] 피드백/NN_피드백.md → ③ run_feedback_rewrite

★피드백 기준은 코덱스 앱에 넣던 것과 **똑같다** — `docs/새벽흐름_프롬프트/코덱스_피드백.md`
  (에디님 피드백 지침 8항목 100점 + 연예 블로그 해석 + 파일 규칙)를 그대로 넘긴다.
  지침을 바꾸려면 **이 프롬프트 파일**을 고친다(코덱스 앱에서 고쳐도 여기엔 반영되지 않는다).
★모델: `gpt-6-astra`(이 맥 models_cache 설명: 가장 높은 모델) · 추론 강도 `medium`
  (앱의 «Light»가 low다. 채점·교정이라 한 단계 올렸다).
★10편을 **한 번에** 부른다. 코덱스는 실행할 때마다 지침·도구 설명을 읽는 고정 비용이 크다
  («한 단어로 답해»도 1.6만 토큰) → 편마다 따로 부르면 그 비용이 열 번 든다.
  못 쓴 편만 한 편씩 다시 부른다.
⚠️제가 부른 코덱스 작업은 **코덱스 앱 목록에 뜨지 않는다**(9/15 확인). 결과는 `피드백/` 폴더에서 본다.
⚠️사용량은 에디님 ChatGPT 요금제에서 나간다. **실측(2026-09-15, Plus, gpt-6-astra/medium): 글 한 편 피드백에
  5시간 한도 80% → 84%(약 4%), 주간 한도는 표시가 안 바뀜.** 새벽 10편이면 5시간 한도 약 30~40%·주간 3~5%
  (한 번에 부르면 고정 비용이 한 번만 들어 조금 준다). 처음엔 low 강도 시험(1%)으로 10~15%라고 어림했는데 틀렸다.
  ✅**10편을 한 번에 부른 실측(2026-09-15 13:32, 5시간 한도가 막 초기화된 뒤)**: 526초 · **80,439 토큰** ·
  5시간 한도 **17%** · 주간 **13 → 16%(+3%)**. 한 편씩(편당 약 2만 토큰) 부를 때보다 절반 넘게 적다.
  → 새벽 흐름은 **주간 한도의 약 20%/주**(Plus).

사용:
    python3 codex_feedback.py                   # 오늘
    python3 codex_feedback.py 2026-09-15        # 특정 날짜
    python3 codex_feedback.py 2026-09-15 05 07  # 특정 편만(이미 있어도 다시)
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config  # noqa: E402

def _find_codex() -> str:
    """코덱스(ChatGPT) 실행 파일을 찾는다 — 맥이면 앱 안, **윈도우면 PATH/npm/앱**에서.
    🔴맥 경로로만 박아두면 윈도우 수강생이 «맥용»이라며 못 쓴다(유료 ChatGPT가 있어도).
       그래서 플랫폼을 여기서 가린다. 못 찾으면 ""를 돌려 조용히 ①로 넘어간다."""
    # 1) 직접 지정 — 내정보.txt(config.CODEX_BIN) 또는 CODEX_BIN 환경변수
    for env in (os.environ.get("CODEX_BIN"), getattr(config, "CODEX_BIN", "")):
        if env and os.path.exists(env):
            return env
    # 2) PATH 에 깔린 codex — `npm i -g @openai/codex` 하면 여기 잡힌다(윈도우는 codex.cmd)
    found = shutil.which("codex")
    if found:
        return found
    # 3) 플랫폼별 앱 번들/설치 위치 후보
    if sys.platform == "darwin":
        cands = ["/Applications/ChatGPT.app/Contents/Resources/codex"]
    elif os.name == "nt":
        la, ad = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
        cands = [
            os.path.join(la, "Programs", "ChatGPT", "resources", "codex.exe"),
            os.path.join(la, "Programs", "ChatGPT", "codex.exe"),
            os.path.join(ad, "npm", "codex.cmd"),
            os.path.join(ad, "npm", "codex.exe"),
        ]
    else:
        cands = []
    for c in cands:
        if c and os.path.exists(c):
            return c
    return ""


CODEX_BIN = _find_codex()
MODEL = "gpt-6-astra"
EFFORT = "medium"
PROMPT_FILE = os.path.join(BASE, "docs", "새벽흐름_프롬프트", "코덱스_피드백.md")
BATCH_TIMEOUT = 1800        # 10편 한 번에
ONE_TIMEOUT = 600           # 못 쓴 편 하나
LOG_PATH = os.path.join(config.WORK_DIR, "codex_feedback.log")
_LIMIT_RE = re.compile(r"usage limit|rate limit|hit your .*limit|try again (at|in)|quota", re.I)
#: 코덱스는 **유료 ChatGPT**가 필요하다 — 로그인/구독 문제일 때 이 문구가 보인다.
_LOGIN_RE = re.compile(r"not logged in|login|sign in|unauthorized|subscription|forbidden|401|403", re.I)

#: 코덱스(유료 ChatGPT)가 없을 때 수강생에게 보여줄 안내.
NO_CODEX_MSG = (
    "\n────────────────────────────────────────\n"
    "ℹ️  코덱스(② 피드백)는 **유료 ChatGPT + codex 실행 파일**이 있어야 돕습니다.\n"
    "    · 없어도 괜찮습니다 — 초안 그대로 사진 넣어 임시저장까지 진행됩니다.\n"
    "    · 🪟 윈도우에서 쓰려면(유료 ChatGPT가 있는 경우):\n"
    "        1) 터미널에 `npm i -g @openai/codex`  (Node가 없으면 먼저 설치)\n"
    "        2) `codex login` → 유료 ChatGPT 계정으로 **본인이 직접** 로그인\n"
    "        3) 새 터미널에서 다시 `python run_ai_daily.py --ai 1`\n"
    "    · 설치가 번거로우면 무료 패키지 ①(blog-auto-starter)를 쓰세요 — 결과는 같습니다.\n"
    "────────────────────────────────────────")


def _log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def _targets(arch_day: str) -> list[str]:
    flag = os.path.join(arch_day, "_단계", "1_생성완료")
    nos = [l.strip() for l in open(flag, encoding="utf-8").read().splitlines()[1:]
           if re.fullmatch(r"\d{2}", l.strip())]
    return nos or sorted({m.group(1) for fn in os.listdir(arch_day)
                          if (m := re.match(r"^(\d{2})_.*\.txt$", fn))})


def _post_file(arch_day: str, no: str) -> str:
    hits = sorted(f for f in glob.glob(os.path.join(arch_day, f"{no}_*.txt")) if os.path.isfile(f))
    return hits[0] if hits else ""


def feedback_ok(path: str) -> bool:
    """피드백 파일이 **클로드가 읽을 수 있는 형식**인가 — 수정 제목 3개 이상 + 고칠 것/확인 칸이 읽힌다."""
    if not os.path.exists(path) or os.path.getsize(path) < 200:
        return False
    try:
        import run_feedback_rewrite as W
        fb = W.parse_feedback(path)
    except Exception:  # noqa: BLE001
        return False
    body = fb.get("raw", "")
    has_fix = bool(fb["고칠부분"] or fb["사실확인"]) or re.search(r"고칠\s*것[\s\S]{0,40}없음", body)
    return len(fb["추천제목"]) >= 3 and bool(has_fix)


def _codex_argv(args: list[str]) -> list[str]:
    """실행 인자를 만든다. 🔴윈도우의 `codex.cmd`/`.bat`은 CreateProcess가 직접 못 여니
       `cmd /c`로 감싼다(안 그러면 «올바른 응용 프로그램이 아닙니다»가 뜬다)."""
    if os.name == "nt" and CODEX_BIN.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", CODEX_BIN, *args]
    return [CODEX_BIN, *args]


def _codex(prompt: str, cwd: str, last_msg: str, timeout: int, log=_log) -> tuple[int, str]:
    cmd = _codex_argv(["exec", "-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"',
           "-s", "workspace-write", "--skip-git-repo-check", "-C", cwd, "-o", last_msg, "-"])
    try:
        r = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        rc = r.returncode
    except subprocess.TimeoutExpired as e:
        out = f"시간 초과({timeout}초) {(e.stdout or '')[-500:] if isinstance(e.stdout, str) else ''}"
        rc = -9
    except FileNotFoundError:
        return 127, f"코덱스 실행 파일 없음: {CODEX_BIN}"
    tok = re.findall(r"tokens used\s*\n?\s*([\d,]+)", out)
    if tok:
        log(f"   코덱스 토큰 {tok[-1]}")
    if _LIMIT_RE.search(out):
        log("   🔴코덱스 사용 한도 안내가 보입니다 — 요금제 한도를 확인하세요")
    try:
        with open(os.path.join(config.WORK_DIR, "codex_feedback.out.log"), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} rc={rc}\n{out[-6000:]}\n")
    except Exception:  # noqa: BLE001
        pass
    return rc, out


def _header(day: str, arch_day: str, nos: list[str], files: list[str], final: bool) -> str:
    lines = "\n".join(f"- {os.path.basename(f)}" for f in files)
    # 🔴지정 편 호출은 `_완료`가 있어도 써야 한다(2026-09-18). 낮에 모자란 편을 채울 때 부르는데,
    #   지침의 «_완료가 있으면 끝»을 따라 코덱스가 **아무것도 안 쓰고** 종료했다(01·07편 0/2).
    finish = ("대상을 전부 쓰면 `피드백/_완료`를 만든다." if final
              else "이번엔 이 편만 쓴다. ★`피드백/_완료`가 이미 있어도 **종료하지 말고 이 편을 쓴다** "
                   "(클로드가 편을 지정해 부른 것이다). `_완료`는 만들지도 지우지도 않는다.")
    return f"""[이번 실행 — 클로드가 직접 불렀다]
오늘 날짜: {day} (YYYYMMDD = {day.replace('-', '')})
작업 폴더(지금 있는 폴더): {arch_day}
시작 조건(`_단계/1_생성완료`)은 클로드가 이미 확인했다.
이번에 피드백할 편: {', '.join(nos)}
대상 파일:
{lines}
각 편마다 `피드백/NN_피드백.md`를 아래 형식 그대로 쓴다. {finish}
글 파일과 다른 폴더는 만들거나 고치지 않는다. 마지막 답은 «완료: 편 번호 목록» 한 줄이면 된다.
━━━━━━━━━━━━━━━━━━━━

"""


def run(day: str | None = None, only: list[str] | None = None, log=_log) -> dict:
    import pipeline
    day = day or date.today().isoformat()
    arch_day = os.path.join(pipeline.DRAFT_ARCHIVE, day)
    if not os.path.exists(os.path.join(arch_day, "_단계", "1_생성완료")):
        log(f"[②] {day} ① 생성 완료 신호가 없어 코덱스를 부르지 않습니다")
        return {"ok": False, "why": "① 신호 없음"}
    fb_dir = os.path.join(arch_day, "피드백")
    os.makedirs(fb_dir, exist_ok=True)
    done_flag = os.path.join(fb_dir, "_완료")
    targets = _targets(arch_day)
    if only:
        targets = [n for n in targets if n in only]
    elif os.path.exists(done_flag):
        return {"ok": True, "why": "이미 완료"}

    def _fb(n):
        return os.path.join(fb_dir, f"{n}_피드백.md")

    pending = [n for n in targets if (only or not feedback_ok(_fb(n))) and _post_file(arch_day, n)]
    if only:
        for n in pending:                      # 다시 쓰게 옛 파일을 치운다
            if os.path.exists(_fb(n)):
                os.replace(_fb(n), _fb(n) + ".old")
    if not pending:
        if not only:
            open(done_flag, "w", encoding="utf-8").write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n" + "\n".join(targets) + "\n")
        return {"ok": True, "why": "쓸 편 없음"}

    # 🔴코덱스 실행 파일이 없으면(유료 ChatGPT 미설치) 지금 안내하고 조용히 끝낸다 — 죽지 않는다.
    if not os.path.exists(CODEX_BIN):
        log("[②] 코덱스 실행 파일이 없습니다(유료 ChatGPT 미설치) — 피드백을 건너뜁니다")
        log(NO_CODEX_MSG)
        return {"ok": False, "why": "코덱스 없음"}

    base = open(PROMPT_FILE, encoding="utf-8").read()
    last_msg = os.path.join(config.WORK_DIR, f"codex_last_{day.replace('-', '')}.txt")
    t0 = time.time()
    log(f"[②] 코덱스 피드백 시작 — {len(pending)}편({', '.join(pending)}) · {MODEL}/{EFFORT}")
    files = [_post_file(arch_day, n) for n in pending]
    rc, _out = _codex(_header(day, arch_day, pending, files, final=not only) + base,
                      arch_day, last_msg, BATCH_TIMEOUT, log)
    if rc != 0 and _LOGIN_RE.search(_out or ""):
        log("[②] 코덱스 로그인/구독 문제로 보입니다 — 피드백을 건너뜁니다")
        log(NO_CODEX_MSG)
    missing = [n for n in pending if not feedback_ok(_fb(n))]
    if missing:
        log(f"   한 번에 부른 뒤 못 쓴 편 {', '.join(missing)} (종료코드 {rc}) — 한 편씩 다시 부릅니다")
        for n in missing:
            _codex(_header(day, arch_day, [n], [_post_file(arch_day, n)], final=False) + base,
                   arch_day, last_msg, ONE_TIMEOUT, log)
        missing = [n for n in pending if not feedback_ok(_fb(n))]
    secs = int(time.time() - t0)
    if not missing and not only:
        with open(done_flag, "w", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} (클로드가 코덱스 호출 · {secs}초)\n" + "\n".join(targets) + "\n")
    scores = []
    for n in pending:
        m = re.search(r"총점\s*\|\s*(\d{1,3})\s*/\s*100", open(_fb(n), encoding="utf-8").read()) if os.path.exists(_fb(n)) else None
        scores.append(f"{n}:{m.group(1) if m else '?'}")
    log(f"[②] 코덱스 피드백 {'완료' if not missing else '일부 실패'} — {len(pending) - len(missing)}/{len(pending)}편 · "
        f"{secs}초 · 총점 {' '.join(scores)}" + (f" · 🔴못 쓴 편 {', '.join(missing)}" if missing else ""))
    return {"ok": not missing, "missing": missing, "secs": secs}


if __name__ == "__main__":
    a = sys.argv[1:]
    d = next((x for x in a if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)), None)
    o = [x.zfill(2) for x in a if x.isdigit() and len(x) <= 2] or None
    sys.exit(0 if run(d, o).get("ok") else 1)
