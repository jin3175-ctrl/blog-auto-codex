#!/usr/bin/env python3
"""③ 코덱스 피드백을 받아 클로드 코드가 **검색해 보고** 더 좋은 글로 다시 쓴다 (수강생 배포판).

흐름 — 단계끼리 파일로 넘긴다:
    ① run_ai_daily      원고/gen_YYYYMMDD/NN_*_복붙용.txt + _단계/1_생성완료
    ② 코덱스(유료 ChatGPT) 피드백/NN_피드백.md   (codex_feedback.run 이 부른다)
    ③ 이 러너            피드백 받은 편부터 검색·재작성 → 피드백/NN_재작성.md → _단계/3_재작성완료

★글을 고치는 쪽은 클로드 하나다. 코덱스는 읽고 피드백 파일만 쓴다.
★사진 마커 `[사진N]`의 개수·번호를 바꾸지 않는다 — 그 번호로 사진이 들어간다.
★피드백이 없거나 재작성이 규칙을 못 지키면 **원본을 그대로 둔다**(임시저장은 원본으로 진행).
★코덱스(유료 ChatGPT)가 없으면 ②가 비어 있어 전부 «원본 유지»로 닫힌다 — 죽지 않는다.
★모든 글에는 내이야기.md 의 '내 경험 문장'이 한 개 이상 들어가야 한다(story_pick).

사용:
    python3 run_feedback_rewrite.py                  # 오늘
    python3 run_feedback_rewrite.py 2026-09-20 01    # 특정 날짜·편
    python3 run_feedback_rewrite.py --final          # 지금 마감(남은 편 원본 유지로 닫음)
    python3 run_feedback_rewrite.py --dry            # 무엇을 할지만
"""
from __future__ import annotations

import glob
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

TITLE_MIN_LEN = 20          # 홈판 제목 최소 길이(자)
LOG_PATH = os.path.join(config.WORK_DIR, "feedback_rewrite.log")
MARKER_RE = re.compile(r"\[사진\s*(\d+)")


def _log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def _lock():
    try:
        import fcntl
    except Exception:  # noqa: BLE001
        return open(os.path.join(config.WORK_DIR, "feedback_rewrite.lock"), "w")
    f = open(os.path.join(config.WORK_DIR, "feedback_rewrite.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return f


# ─────────────────────────────────────────────────────────────
#  ② 코덱스 피드백 읽기
# ─────────────────────────────────────────────────────────────
def _sections(md: str) -> dict:
    out, cur = {}, None
    for line in (md or "").splitlines():
        m = re.match(r"^\s*##\s+(.+?)\s*$", line) or re.match(r"^\s*\[([^\]]{2,20})\]\s*$", line)
        if m:
            cur = re.sub(r"[\s\[\]]", "", m.group(1))
            out[cur] = []
            continue
        if cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def _items(text: str, head: str) -> list[dict]:
    items, cur = [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s in ("- 없음", "없음"):
            continue
        m = re.match(r"^-\s*(원문|주장)\s*[:：]\s*(.*)$", s)
        if m:
            cur = {head: m.group(2).strip().strip('"“”')}
            items.append(cur)
            continue
        m = re.match(r"^(이유|검색어|고칠\s*방향|고친\s*문장)\s*[:：]\s*(.*)$", s)
        if m and cur is not None:
            cur[re.sub(r"\s", "", m.group(1))] = m.group(2).strip()
    return items


_DEVICE_TAIL = re.compile(
    r"\s*[(（]\s*[^()（）]{0,20}(인용|갭|숫자|수치|반전|특정|질문|의외|궁금|종결|장치|감춤|말줄임|구어|권위|대상"
    r"|격차|손실|회피|타이밍|비교|증거|미래|상상|공감)[^()（）]{0,20}[)）]\s*$")


def strip_device_label(title: str) -> str:
    """추천 제목 끝의 «(궁금증 갭)» 같은 장치 이름 괄호를 뗀다."""
    return _DEVICE_TAIL.sub("", title or "").strip()


def parse_feedback(path: str) -> dict:
    md = open(path, encoding="utf-8").read()
    sec = _sections(md)

    def _pick(*names):
        for n in names:
            for k, v in sec.items():
                if k.startswith(n):
                    return v
        return ""
    titles = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip()
              for l in _pick("수정제목", "추천제목").splitlines() if re.match(r"^\s*\d+[.)]", l)]
    return {
        "raw": md.strip(),
        "원래제목": _pick("원래제목").strip(),
        "추천제목": [strip_device_label(t) for t in titles if strip_device_label(t)],
        "고칠부분": _items(_pick("고칠것", "고칠부분"), "원문"),
        "사실확인": _items(_pick("확인이필요한것", "사실확인필요"), "주장"),
    }


# ─────────────────────────────────────────────────────────────
#  검색 — 피드백이 짚은 곳과 글의 주제로 네이버 뉴스를 다시 찾는다
# ─────────────────────────────────────────────────────────────
def _queries(title: str, fb: dict) -> list[str]:
    words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", title) if not re.fullmatch(r"\d+", w)]
    subj = " ".join(words[:3])
    qs = [subj]
    for x in fb["고칠부분"] + fb["사실확인"]:
        q = x.get("검색어", "")
        if q:
            qs.append(q)
    seen, out = set(), []
    for q in qs:
        q = re.sub(r"[\[\]\"'“”‘’]", " ", q or "").strip()
        q = re.sub(r"\s{2,}", " ", q)
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:5]


def search_context(queries: list[str], log=_log) -> str:
    try:
        import celeb_sources as S
    except Exception:  # noqa: BLE001
        return "(검색 모듈 없음 — 원고의 사실을 새로 단정하지 마라)"
    import time as _t
    seen, arts = set(), []
    for attempt in (1, 2):
        for q in queries:
            try:
                items = S.fetch_news_search(q, 6)
            except Exception as e:  # noqa: BLE001
                log(f"   검색 실패({q}): {str(e)[:50]}")
                items = []
            for a in items:
                k = a.get("url") or a.get("title", "")[:40]
                if k and k not in seen:
                    seen.add(k)
                    arts.append(a)
        if arts or attempt == 2:
            break
        log("   검색이 전부 0건 — 20초 뒤 한 번 더 찾습니다")
        _t.sleep(20)
    for a in [x for x in arts if x.get("url")][:2]:
        try:
            art = S.fetch_article(a["url"])
            a["body"] = (art.get("body") or "")[:1500]
            a["date"] = a.get("date") or art.get("date", "")
        except Exception:  # noqa: BLE001
            pass
    lines = []
    for a in arts[:12]:
        lines.append(f"- [{a.get('date') or '날짜?'}] {a.get('title', '')} — {(a.get('snippet') or '')[:180]}")
        body = a.get("body") or ""
        if body and body.strip() != f"{a.get('title', '')} {a.get('snippet', '')}".strip():
            lines.append(f"  (본문 발췌) {body[:1200]}")
    log(f"   검색 {len(queries)}개 → 기사 {len(arts)}건: {', '.join(queries)[:80]}")
    return "\n".join(lines) or "(검색 결과 없음 — 원고의 사실을 새로 단정하지 마라)"


def _my_story_line() -> str:
    """내이야기.md 에서 경험 한 줄을 뽑는다(없으면 빈 문자열)."""
    try:
        import story_pick
        return story_pick.pick()
    except Exception:  # noqa: BLE001
        return ""


REWRITE_PROMPT = """당신은 네이버 블로그 홈판 글쓴이입니다.
새벽에 쓴 [원고]를 편집자의 [피드백]과 방금 찾은 [검색 결과]를 보고 **더 좋은 글로 다시 씁니다.**

[오늘] {today}

[원고]
{body}

[피드백 — 편집자(코덱스)]
{feedback}

[검색 결과 — 네이버 뉴스, 방금 검색]
{search}

[내 경험 한 줄 — 내이야기.md에서]
{story}

[다시 쓰는 규칙]
1. 제목: [피드백]의 추천 제목과 원래 제목을 견줘 **가장 좋은 것 하나**를 고르거나 더 낫게 새로 짓는다.
   {min_len}자 이상 · 결론을 다 말하지 않는다 · 검색 결과에 없는 숫자·사실 금지 · 대괄호 금지.
   제목 뒤 괄호에 적힌 심리 장치(예: «(정보격차+손실회피)»)는 설명일 뿐이다 — 제목에 넣지 않는다.
2. [피드백]이 짚은 곳은 **검색 결과로 확인**한다.
   - 확인되면 더 정확한 사실·날짜·이름으로 고친다.
   - 확인이 안 되는 주장은 **빼거나** «~라는 반응이 나온다»처럼 낮춘다. 지어내지 않는다.
3. 🔴**내 경험 한 줄을 본문에 자연스럽게 한 문장 이상 녹인다**(위 [내 경험 한 줄]이 있으면 그 취지로).
   억지로 넣지 말되, 검색·요약만 있고 '내 이야기'가 없으면 그 글은 홈판에서 안 눌린다.
4. 그대로 지킬 것:
   - 사진 마커 `[사진N - …]`: **개수와 번호를 원고 그대로** ({markers}개: {marker_nums}). 장면 설명은
     고쳐도 되지만 줄을 없애거나 새로 만들지 않는다. 마커 안에 대괄호를 또 쓰지 않는다.
   - `[표]` 줄, 맨 끝 `@출처`·해시태그 줄.
   - 존댓말 · 말하듯 쓰는 문체 · 1~2문장마다 빈 줄. 인사·자기소개·이모지·마크다운(별표·#머리글) 금지.
   - 분량은 원고보다 줄이지 않는다. 뺀 자리는 검색으로 확인된 사실이나 내 경험으로 채운다.
5. 반영하지 않은 피드백은 [변경]에 이유를 적는다.
6. 🔴수익을 약속하지 않는다("제 경우"와 기간을 붙인다). 병이 낫는다·효과 보장 같은 표현 금지.

[출력 — 아래 두 칸만. 앞뒤 설명 금지]
===원고===
제목: (최종 제목)
(본문 전체 — 원고와 같은 형식)
===변경===
- 제목: 원래 → 최종 (고른 이유 한 줄)
- 반영: …
- 반영 안 함: … (이유)
- 검색으로 확인한 것: …
- 내 경험 반영: …
"""


def _split_output(out: str) -> tuple[str, str]:
    m = re.search(r"===\s*원고\s*===\s*(.*?)\s*===\s*변경\s*===\s*(.*)$", out or "", re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", "")


def _marker_nums(text: str) -> list[int]:
    return sorted(int(n) for n in MARKER_RE.findall(text or ""))


def _title_of(body: str) -> str:
    m = re.search(r"^\s*제목\s*[:：]\s*(.+)$", body or "", re.M)
    return m.group(1).strip() if m else ""


def rewrite_one(no: str, gen_dir: str, arch_day: str, log=_log, dry: bool = False) -> dict:
    """한 편을 다시 쓴다. 성공하면 원고·임시저장 파일을 바꾸고 피드백/NN_재작성.md를 남긴다."""
    import gen_ai as GA
    import gen_common as GC
    from claude_cli import UsageLimitError, run_claude_p_retry

    fb_path = os.path.join(arch_day, "피드백", f"{no}_피드백.md")
    src = sorted(glob.glob(os.path.join(gen_dir, f"{no}_*_복붙용.txt")))
    if not src:
        return {"ok": False, "why": "원고 없음"}
    src = src[0]
    body0 = open(src, encoding="utf-8").read()
    title0 = _title_of(body0)
    fb = parse_feedback(fb_path)
    nums0 = _marker_nums(body0)
    log(f"[{no}] ③ 재작성 시작 — {title0[:40]} · 추천 제목 {len(fb['추천제목'])} · "
        f"고칠 곳 {len(fb['고칠부분'])} · 사실 확인 {len(fb['사실확인'])}")
    if dry:
        return {"ok": True, "why": "dry"}

    queries = _queries(title0, fb)
    search = search_context(queries, log)
    prompt = REWRITE_PROMPT.format(
        today=date.today().isoformat(), body=body0, feedback=fb["raw"], search=search,
        story=_my_story_line() or "(내이야기.md가 비어 있음 — 클로드 코드에게 «내 이야기 5개 질문해줘»)",
        min_len=TITLE_MIN_LEN, markers=len(nums0), marker_nums=", ".join(map(str, nums0)) or "없음")

    def _ok(out: str) -> bool:
        b, _ = _split_output(out)
        return bool(b) and b.lstrip().startswith("제목") and _marker_nums(b) == nums0 \
            and GC.enough_length(b, 1000)

    try:
        out = run_claude_p_retry(prompt, timeout=420, tries=2, ok=_ok, log=log, label=f"[{no}] 재작성")
    except UsageLimitError:
        raise
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"claude 호출 실패: {str(e)[:80]}"}

    body, change = _split_output(out)
    if not body or _marker_nums(body) != nums0:
        return {"ok": False, "why": f"사진 마커가 원고와 달라짐({_marker_nums(body)} ≠ {nums0}) — 원본 유지"}

    warns = []
    title = strip_device_label(GC.strip_brackets(_title_of(body)))
    if not title or GC.looks_meta(title) or len(title) < TITLE_MIN_LEN:
        warns.append(f"새 제목 «{title}»이 규칙에 안 맞아 원래 제목을 썼다")
        title = title0
    body = GC.flatten_marker_brackets(GA._set_title_line(body, title))

    backup = src.replace("_복붙용.txt", "_복붙용.원본.txt")
    if not os.path.exists(backup):
        with open(backup, "w", encoding="utf-8") as f:
            f.write(body0)
    with open(src, "w", encoding="utf-8") as f:
        f.write(body)

    # 임시저장 파일(복붙용)을 새 원고로 다시 만든다(제목이 바뀌면 파일 이름도 바뀐다)
    import pipeline
    r = pipeline.process_post(no, log, publish=False, folder=gen_dir,
                              category="", archive_only=True)
    if not r.get("ok"):
        with open(src, "w", encoding="utf-8") as f:          # 되돌린다
            f.write(body0)
        pipeline.process_post(no, log, publish=False, folder=gen_dir,
                              category="", archive_only=True)
        return {"ok": False, "why": f"복붙용 파일 재생성 실패 — 원본으로 되돌림: {r.get('message', '')[:60]}"}

    note = [f"# {no} 재작성 — {datetime.now():%Y-%m-%d %H:%M}",
            "", "## 제목", f"- 원래: {title0}", f"- 최종: {title}",
            "", "## 변경(클로드)", change or "- (변경 설명 없음)",
            "", "## 검색어", *[f"- {q}" for q in queries]]
    if warns:
        note += ["", "## 확인 필요", *[f"- {w}" for w in warns]]
    with open(os.path.join(arch_day, "피드백", f"{no}_재작성.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(note) + "\n")
    log(f"[{no}] ③ 재작성 완료 — «{title0[:24]}» → «{title[:24]}»" + (f" · 확인 필요 {len(warns)}" if warns else ""))
    return {"ok": True, "title": title, "warns": warns}


def _keep_original(no: str, arch_day: str, why: str, log=_log) -> None:
    os.makedirs(os.path.join(arch_day, "피드백"), exist_ok=True)
    with open(os.path.join(arch_day, "피드백", f"{no}_재작성.md"), "w", encoding="utf-8") as f:
        f.write(f"# {no} 재작성 — {datetime.now():%Y-%m-%d %H:%M}\n\n## 원본 유지\n- {why}\n")
    log(f"[{no}] ③ 원본 유지 — {why}")


def _targets(arch_day: str) -> list[str]:
    flag = os.path.join(arch_day, "_단계", "1_생성완료")
    try:
        nos = [l.strip() for l in open(flag, encoding="utf-8").read().splitlines()[1:]
               if re.fullmatch(r"\d{2}", l.strip())]
    except Exception:  # noqa: BLE001
        nos = []
    return nos or sorted({m.group(1) for fn in os.listdir(arch_day)
                          if (m := re.match(r"^(\d{2})_.*\.txt$", fn))})


def main(argv: list[str]) -> int:
    import pipeline
    dry, final = "--dry" in argv, "--final" in argv
    args = [a for a in argv if not a.startswith("--")]
    day = next((a for a in args if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)), date.today().isoformat())
    only = {a.zfill(2) for a in args if a.isdigit() and len(a) <= 2}
    arch_day = os.path.join(pipeline.DRAFT_ARCHIVE, day)
    gen_dir = os.path.join(config.SOURCE_ROOT, "gen_" + day.replace("-", ""))
    flag1 = os.path.join(arch_day, "_단계", "1_생성완료")
    flag3 = os.path.join(arch_day, "_단계", "3_재작성완료")

    if not os.path.exists(flag1):
        _log(f"[{day}] ① 생성 완료 표시가 아직 없습니다")
        return 0
    if os.path.exists(flag3) and not only:
        return 0
    lk = None if dry else _lock()
    if not dry and lk is None:
        _log("다른 실행이 재작성 중 — 이번엔 빠집니다")
        return 0

    targets = [n for n in _targets(arch_day) if not only or n in only]
    fb_dir = os.path.join(arch_day, "피드백")
    os.makedirs(fb_dir, exist_ok=True)

    # ② 코덱스 피드백 — 클로드 코드가 직접 부른다. 코덱스(유료 ChatGPT)가 없으면 조용히 넘어간다.
    if not dry and not os.path.exists(os.path.join(fb_dir, "_완료")):
        try:
            import codex_feedback
            codex_feedback.run(day, log=_log)
        except Exception as e:  # noqa: BLE001
            _log(f"[안내] ② 코덱스 피드백을 못 받았습니다 — 피드백 없는 편은 원본 유지: {str(e)[:100]}")
            _log("      코덱스는 유료 ChatGPT가 필요합니다. 없으면 패키지 ①(blog-auto-starter)를 쓰세요.")

    def _done(n):
        return os.path.exists(os.path.join(fb_dir, f"{n}_재작성.md"))

    def _fed(n):
        return os.path.exists(os.path.join(fb_dir, f"{n}_피드백.md"))

    tried: set = set()
    stop = False
    while not stop:
        pending = [n for n in targets if _fed(n) and n not in tried and (only or not _done(n))]
        if not pending:
            break
        n = pending[0]
        tried.add(n)
        try:
            r = rewrite_one(n, gen_dir, arch_day, _log, dry=dry)
        except Exception as e:  # noqa: BLE001
            from claude_cli import UsageLimitError
            if isinstance(e, UsageLimitError):
                _log("[중단] 클로드 사용 한도 — 남은 편은 원본 유지로 닫습니다")
                stop = True
                break
            r = {"ok": False, "why": f"예외: {str(e)[:80]}"}
        if not r.get("ok") and not dry:
            _keep_original(n, arch_day, r.get("why", "재작성 실패"))

    if dry or only:
        return 0
    now = datetime.now()
    left = [n for n in targets if not _done(n)]
    # 피드백이 하나도 없으면(코덱스 없음) 즉시 전부 원본 유지로 닫는다 — 초안 그대로 임시저장.
    if left and (final or stop or not any(_fed(n) for n in targets)):
        for n in left:
            _keep_original(n, arch_day, "코덱스 피드백이 없었다(초안 그대로 진행)" if not _fed(n) else "재작성하지 못했다")
        left = []
    if not left:
        os.makedirs(os.path.dirname(flag3), exist_ok=True)
        with open(flag3, "w", encoding="utf-8") as f:
            f.write(f"{now:%Y-%m-%d %H:%M:%S}\n" + "\n".join(targets) + "\n")
        _log(f"[{day}] ③ 재작성 단계 완료 → _단계/3_재작성완료")
    else:
        _log(f"[{day}] ③ 대기 — 피드백 기다리는 편 {', '.join(left)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
