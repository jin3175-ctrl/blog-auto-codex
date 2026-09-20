#!/usr/bin/env python3
"""홈판 글 하루치 생성 → (코덱스 피드백 → 재작성) → 사진 → 네이버 임시저장 (수강생 배포판).

수강생 흐름 한 번(ONE RUN):
    ① 생성      gen_ai 로 홈판 초안 N편 → 원고/gen_YYYYMMDD/NN_*_복붙용.txt + _단계/1_생성완료
    ② 피드백    코덱스(유료 ChatGPT)가 채점·교정 → 피드백/NN_피드백.md
    ③ 재작성    클로드 코드가 검색해 보고 더 좋은 글로 다시 씀 → _단계/3_재작성완료
    ④ 사진      무료 스톡(Unsplash) 우선으로 [사진N] 자리를 채움
    ⑤ 임시저장  네이버에 **임시저장**(발행 아님) — 최종 발행 버튼은 사람이 누른다

★코덱스(유료 ChatGPT)가 없거나 로그인 문제면 ②③을 건너뛰고 **초안 그대로** 임시저장한다
  (그리고 화면에 «패키지 ①(blog-auto-starter)를 쓰라»고 안내한다). 절대 죽지 않는다.
★네이버 로그인이 없으면 파일은 만들어 두고 «로그인하고 다시 해달라»고 안내하고 멈춘다.

사용:
    python3 run_ai_daily.py --ai 1              # 홈판 1편: 생성→피드백→재작성→사진→임시저장
    python3 run_ai_daily.py --ai 1 --dry        # 미리보기(네이버·클로드 안 건드림)
    python3 run_ai_daily.py --ai 1 --gen-only   # 생성만(품질 확인용)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import myinfo  # noqa: E402

#: 소재뱅크는 수강생 PC에 없다 — 없으면 조용히 건너뛰고 주제는 블로그분석.md·트렌드에서 뽑는다.
BANK = os.path.join(config.BASE_DIR, "docs", "소재뱅크.md")
USED_FILE = os.path.join(config.WORK_DIR, "ai_topics_used.json")


def categorize(text: str) -> str:
    """홈판 글의 카테고리 = 내정보.txt 의 '내 카테고리'. 없으면 기본 칸에 저장된다."""
    return myinfo.category() or ""


def _log(m: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {m}", flush=True)


#: 그날 못 만든 편과 이유
LAST_GEN_FAILURES: list = []


def _alert(title: str, msg: str) -> None:
    """실패를 눈에 보이게 한다(맥이면 알림, 아니면 로그). 개인 메일 연동은 배포판에서 뺐다."""
    try:
        import subprocess
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{msg}" with title "{title}" sound name "Basso"'],
            timeout=10, capture_output=True)
    except Exception:  # noqa: BLE001
        _log(f"[알림] {title} — {msg}")


def _topics() -> list[str]:
    """소재뱅크(있으면)의 '1. 주제' 목록. 수강생 PC엔 보통 없다 → 빈 리스트."""
    out = []
    try:
        with open(BANK, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*\d+\.\s+(.+)$", line.strip())
                if m:
                    out.append(m.group(1).strip())
    except Exception:  # noqa: BLE001
        pass
    return out


def _analysis_topics() -> list[str]:
    """블로그분석.md 의 '최근 글 제목'을 주제 후보로 쓴다(같은 독자가 오는 결로 이어 쓰기)."""
    path = os.path.join(config.BASE_DIR, "블로그분석.md")
    out, grab = [], False
    try:
        for line in open(path, encoding="utf-8"):
            s = line.strip()
            if s.startswith("## 최근 글 제목"):
                grab = True
                continue
            if grab:
                if s.startswith("#"):
                    break
                t = s.lstrip("-* ").strip()
                if t and not t.startswith("(") and len(t) > 4:
                    out.append(t)
    except Exception:  # noqa: BLE001
        pass
    return out


def _used() -> list[str]:
    try:
        with open(USED_FILE, encoding="utf-8") as f:
            return json.load(f).get("used", [])
    except Exception:  # noqa: BLE001
        return []


def _mark_used(topics: list[str]) -> None:
    used = _used()
    used.extend(t for t in topics if t not in used)
    try:
        with open(USED_FILE, "w", encoding="utf-8") as f:
            json.dump({"used": used}, f, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass


def pick_topics(n: int) -> list[str]:
    """아직 안 쓴 주제 n개 (소재뱅크 → 블로그분석.md 순). 소진돼도 이력을 초기화하지 않는다."""
    all_t = _topics() + _analysis_topics()
    if not all_t:
        return []
    used = set(_used())
    fresh = [t for t in all_t if t not in used]
    return fresh[:n]


def check_categories(log=print) -> bool:
    """코드가 쓰려는 카테고리(내 카테고리)가 네이버에 실제로 있는지 대조(베스트 에포트).

    ★없어도 글은 죽지 않는다 — naver 가 못 찾으면 기본 칸에 저장하고 로그만 남긴다.
    """
    import json as _j
    import urllib.request as _u
    want = {c for c in {categorize("")} if c}
    if not want:
        return True
    H = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 Mobile/15E148",
         "Referer": f"https://m.blog.naver.com/{config.EXPECT_BLOG_ID}"}
    try:
        r = _u.urlopen(_u.Request(
            f"https://m.blog.naver.com/api/blogs/{config.EXPECT_BLOG_ID}/category-list",
            headers=H), timeout=20).read().decode("utf-8", "ignore")
        live = {c.get("categoryName") for c in
                ((_j.loads(r).get("result") or {}).get("mylogCategoryList") or [])}
    except Exception as e:  # noqa: BLE001
        log(f"[안내] 카테고리 목록을 못 읽었습니다(대조 생략): {str(e)[:70]}")
        return True
    miss = sorted(w for w in want if w and w not in live)
    for w in sorted(want):
        log(f"   {'OK ' if w in live else '없음'}  «{w}»")
    if miss:
        log("[안내] 네이버에 없는 칸이라 기본 칸에 저장됩니다(네이버 블로그 관리에서 칸을 만들면 됩니다): "
            + ", ".join(f"«{m}»" for m in miss))
    return not miss


def generate_all(out_dir: str, ai_count: int) -> list[tuple[str, str]]:
    """홈판 글 ai_count편 생성. 성공한 (글번호, 카테고리) 목록 반환."""
    import gen_ai

    os.makedirs(out_dir, exist_ok=True)
    made: list[tuple[str, str]] = []

    # 그날의 홈판 공식·트렌드는 1회만 수집해 공유(구조·주제가 매일 달라지도록)
    live_ctx = None
    try:
        live_ctx = gen_ai.collect_live_context(_log)
    except Exception as e:  # noqa: BLE001
        _log(f"[안내] 홈판 트렌드 수집 실패(기본 뼈대로 진행): {str(e)[:80]}")

    # 주제: 트렌드 → 블로그분석.md/소재뱅크 순으로 채운다
    used_hist = _used()
    topics: list[str] = []
    if live_ctx:
        try:
            topics = gen_ai.derive_topics(live_ctx, ai_count, used=used_hist, log=_log)
        except Exception as e:  # noqa: BLE001
            _log(f"[안내] 오늘의 주제 도출 실패(블로그분석/소재뱅크로 진행): {str(e)[:80]}")
    if len(topics) < ai_count:
        for t in pick_topics(ai_count):
            if t not in topics:
                topics.append(t)
            if len(topics) >= ai_count:
                break
    topics = topics[:ai_count]
    if not topics:
        _log("[중단] 쓸 주제를 못 정했습니다. 먼저 클로드 코드에게 "
             "«내 블로그 blog.naver.com/○○○ 분석해줘»로 블로그분석.md 를 만들어 주세요.")
        return made
    _log(f"[주제] {len(topics)}개: " + " · ".join(t[:24] for t in topics))

    done_topics = []
    for i, topic in enumerate(topics):
        no = str(i + 1).zfill(2)
        try:
            _log(f"[생성] 홈판 {no}: {topic[:40]}")
            gen_ai.generate(topic, out_dir, no=no, log=_log, ctx=live_ctx)
            made.append((no, categorize(topic)))
            done_topics.append(topic)
        except Exception as e:  # noqa: BLE001
            _log(f"[생성] 홈판 {no} 실패(건너뜀): {str(e)[:160]}")
            LAST_GEN_FAILURES.append((no, "홈판", str(e)[:200]))
    if done_topics:
        _mark_used(done_topics)
    return made


def _write_stage1(out_dir: str, made: list) -> str:
    """① 생성 완료 신호 → 코덱스 피드백(②)이 이걸 보고 시작한다. 날짜(YYYY-MM-DD)를 반환."""
    import pipeline
    import time as _t
    m = re.search(r"gen_(\d{4})(\d{2})(\d{2})", out_dir or "")
    day = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else _t.strftime("%Y-%m-%d")
    sd = os.path.join(pipeline.DRAFT_ARCHIVE, day, "_단계")
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, "1_생성완료"), "w", encoding="utf-8") as f:
        f.write(_t.strftime("%Y-%m-%d %H:%M:%S") + "\n" + "\n".join(n for n, _ in made) + "\n")
    _log(f"[단계] ① 생성 완료 → {day}/_단계/1_생성완료 ({len(made)}편)")
    return day


def main(ai_count: int = 1, gen_only: bool = False, dry: bool = False) -> int:
    date = config.today_str()
    out_dir = os.path.join(config.SOURCE_ROOT, f"gen_{date}")
    _log(f"=== [{config.BLOG_NAME} / {config.EXPECT_BLOG_ID}] 홈판 {ai_count}편 → {out_dir} ===")

    if dry:
        _log("[dry] 카테고리 대조:")
        check_categories(lambda m: _log("  " + m))
        _log("[dry] 홈판 예정 주제(트렌드는 실제 실행 때 수집):")
        for t in (pick_topics(ai_count) or ["(블로그분석.md·소재뱅크가 비어 실행 때 홈판 트렌드에서 뽑습니다)"]):
            _log(f"   - {t}")
        _log("[dry] 흐름: 생성 → 코덱스 피드백 → 재작성 → 무료 스톡 사진 → 네이버 임시저장")
        _log("[dry] 최종 발행 버튼은 사람이 누릅니다(자동은 임시저장까지).")
        return 0

    # 🔴생성 전에 클로드 로그인 확인 — 만료면 편마다 죽으므로 지금 멈추고 알린다.
    try:
        import claude_cli as _cc
        _cok, _cwhy = _cc.auth_ok()
    except Exception as e:  # noqa: BLE001
        _cok, _cwhy = False, str(e)[:140]
    if not _cok:
        _log(f"[중단] 클로드 로그인 문제 — 생성 전에 감지: {_cwhy}")
        _alert("클로드 로그인 만료 — 오늘 글 생성 못 함", "터미널에서 `claude login` 후 다시 해주세요.")
        return 1

    made = generate_all(out_dir, ai_count)
    _log(f"=== 생성 완료: {len(made)}편 ({', '.join(n for n, _ in made) or '없음'}) ===")
    if not made:
        _log("[중단] 생성된 글이 없습니다.")
        return 1

    day = _write_stage1(out_dir, made)

    if gen_only:
        _log("[생성만] 피드백·재작성·사진·임시저장은 건너뜁니다.")
        return 0

    # ── ②③ 코덱스 피드백 → 재작성 (클로드 코드가 검색해 더 좋은 글로) ──
    try:
        import run_feedback_rewrite
        _log("[단계] ②③ 시작 — 코덱스 피드백 → 검색·재작성")
        run_feedback_rewrite.main([day])
    except Exception as e:  # noqa: BLE001
        _log(f"[안내] ②③ 코덱스 피드백/재작성을 건너뜁니다(초안 그대로 진행): {str(e)[:120]}")
        _log("      → 코덱스(유료 ChatGPT)가 필요합니다. 없으면 패키지 ①(blog-auto-starter)를 쓰세요.")

    # ── ④⑤ 사진(무료 스톡 우선) → 네이버 임시저장 ──
    import naver
    import pipeline
    if not naver.session_alive(_log):
        _log("[중단] 네이버 로그인이 없습니다 — 원고 파일은 만들어 두었습니다.")
        _log("      네이버에 로그인(python3 check_session.py --login)한 뒤 다시 실행하면 임시저장됩니다.")
        _alert("네이버 로그인 필요", "글은 만들어 뒀습니다. 로그인 후 다시 실행하면 임시저장됩니다.")
        return 1

    ok = 0
    for no, cat in made:
        try:
            _log(f"[{no}] 사진 넣고 임시저장 → 카테고리 '{cat or '(기본)'}'")
            res = pipeline.process_post(no, lambda m, n=no: _log(f"   [{n}] {m}"),
                                        publish=False, folder=out_dir, category=cat)
            _log(f"[{no}] 결과: ok={res.get('ok')} · {res.get('message')}")
            if res.get("ok"):
                ok += 1
        except Exception as e:  # noqa: BLE001
            _log(f"[{no}] 오류: {str(e)[:160]}")
    _log(f"=== 완료: {ok}/{len(made)} 임시저장 ===")
    _log("→ 네이버 글쓰기 → 저장 목록에서 검토 후 **직접** 발행하세요(자동은 임시저장까지).")
    return 0


if __name__ == "__main__":
    def _val(flag, default):
        if flag in sys.argv:
            i = sys.argv.index(flag)
            if i + 1 < len(sys.argv):
                try:
                    return int(sys.argv[i + 1])
                except ValueError:
                    pass
        return default

    sys.exit(main(ai_count=_val("--ai", 1),
                  gen_only="--gen-only" in sys.argv,
                  dry="--dry" in sys.argv))
