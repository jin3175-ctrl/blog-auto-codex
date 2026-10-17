"""네이버에 글을 넣는 브라우저를 고른다 (2026-10-17 · 3기 2주차부터).

  맥     → **에고라이트(ego lite)** — 사람이 클릭하듯 글쓰기 화면에 넣고 임시저장한다.
  윈도우 → **어사이드(Aside)**   — 원고를 `어사이드용/` 폴더에 보기 좋은 페이지로 만들어 두고,
                                  어사이드에게 프롬프트 한 장으로 임시저장을 시킨다.
  (예전 크롬 방식은 `내정보.txt`의 「브라우저: 크롬」으로만 쓴다.)

왜 크롬이 아닌가: 크롬(Playwright)은 자동화로 잡힐 수 있다. 에고라이트·어사이드는 내 브라우저에
내가 로그인한 그대로 움직인다.

🔴어느 브라우저든 **임시저장까지만** 한다. 발행 버튼은 사람이 누른다.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys

import config

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "ego", "publish.mjs")
SPACE_NAME = "블로그 자동"
ASIDE_DIR = os.path.join(os.path.dirname(config.SOURCE_ROOT), "어사이드용")


def mode() -> str:
    """'ego' | 'aside' | 'chrome' — 환경변수 EDI_BROWSER > 내정보.txt 「브라우저:」 줄 > 컴퓨터 종류."""
    v = (os.environ.get("EDI_BROWSER") or "").strip().lower()
    if not v:
        for d in (HERE, os.path.dirname(HERE)):
            try:
                m = re.search(r"^브라우저\s*[:：]\s*(\S+)",
                              open(os.path.join(d, "내정보.txt"), encoding="utf-8").read(), re.M)
            except OSError:
                continue
            v = (m.group(1) if m else "").lower()
            break
    if v in ("에고", "에고라이트", "ego", "egolite"):
        return "ego"
    if v in ("어사이드", "aside"):
        return "aside"
    if v in ("크롬", "chrome"):
        return "chrome"
    return "ego" if sys.platform == "darwin" else "aside"


def _blog_id() -> str:
    v = getattr(config, "EXPECT_BLOG_ID", "")
    if v:
        return v
    try:
        import myinfo
        return myinfo.blog_id() or ""
    except BaseException:  # noqa: BLE001 — 빈칸이면 myinfo가 SystemExit로 멈춘다
        return ""


# ── 에고라이트 (맥) ─────────────────────────────────────────────

def ego_bin() -> str:
    for c in (shutil.which("ego-browser"), os.path.expanduser("~/.local/bin/ego-browser")):
        if c and os.path.exists(c):
            return c
    return ""


def _ego_run(src: str, timeout: int) -> str:
    b = ego_bin()
    if not b:
        raise RuntimeError("에고라이트가 없습니다 — https://lite.ego.app 에서 설치하고, 앱을 한 번 열어 "
                           "첫 화면(온보딩)을 끝내 주세요.")
    proc = subprocess.run([b, "nodejs"], input=src, text=True, capture_output=True, timeout=timeout)
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def ego_session(log=print) -> tuple:
    """에고라이트에 **내 블로그 계정**으로 네이버 로그인이 돼 있는지 본다. (ok, 안내문)"""
    bid = _blog_id()
    src = ('const t = await taskSpace(%s);\n'
           'const p = t.page("p1");\n'
           'await p.goto("https://blog.naver.com/GoBlogWrite.naver");\n'
           'await p.waitForTimeout(4000);\n'
           'console.log(JSON.stringify({ url: await p.url() }));\n'
           'try { await t.finish({ keep: [] }); } catch (e) {}\n') % json.dumps(SPACE_NAME)
    try:
        out = _ego_run(src, 240)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and '"url"' in line:
            url = json.loads(line).get("url", "")
            if "nidlogin" in url:
                return False, "에고라이트에서 네이버 로그인이 안 돼 있습니다 — 에고라이트를 열고 직접 로그인해 주세요(로그인 상태 유지 켜기)."
            if bid and bid not in url:
                return False, f"에고라이트가 다른 블로그로 열립니다({url[:80]}) — 내 계정으로 로그인해 주세요."
            return True, ""
    if "control" in out:
        return False, "에고라이트 창을 지금 직접 쓰고 계십니다 — 손을 떼고 다시 실행해 주세요."
    return False, "에고라이트 상태를 확인하지 못했습니다: " + out.strip()[-160:]


def _ego_draft(title, blocks, log, category="", align="", ai_mark=True) -> dict:
    os.makedirs(config.WORK_DIR, exist_ok=True)
    tmp = os.path.join(config.WORK_DIR, "ego_payload.json")
    tags = next((b.get("text", "") for b in blocks if b.get("type") == "hashtags"), "")
    payload = {"blogId": _blog_id(), "no": "1", "title": title, "blocks": blocks,
               "category": category, "align": align, "tags": tags, "mode": "draft",
               "schedule": None, "dryPublish": False, "aiMark": bool(ai_mark),
               "spaceName": SPACE_NAME}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)
    src = f"const PAYLOAD_PATH = {json.dumps(tmp)};\n" + open(DRIVER, encoding="utf-8").read()
    log("에고라이트로 글쓰기 화면을 열어 넣습니다(임시저장까지만)…")
    try:
        out = _ego_run(src, 2400)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}
    try:
        with open(os.path.join(config.WORK_DIR, "ego_driver.log"), "w", encoding="utf-8") as f:
            f.write(out)
    except OSError:
        pass
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"ok"' in line:
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("ok"):
                return {"ok": True, "message": f"에고라이트 임시저장 완료 · 사진 {r.get('images', 0)}장",
                        "notes": r.get("notes") or []}
            return {"ok": False, "message": "에고라이트 실패: " + str(r.get("why") or r)[:300]}
    return {"ok": False, "message": "에고라이트 실패: " + out.strip()[-300:]}


# ── 어사이드 (윈도우) ───────────────────────────────────────────

ASIDE_PROMPT = """너는 내 네이버 블로그 글쓰기 도우미야. 발행 버튼은 절대 누르지 마.

① 지금 열려 있는 「오늘 글」 탭에서 제목과 본문을 읽어.
② 새 탭에서 https://blog.naver.com/{blog_id}?Redirect=Write& 를 열어. (로그인 화면이 나오면 멈추고 나에게 로그인하라고 말해)
③ 제목 칸에 제목을 넣고, 본문은 「오늘 글」 탭의 문단 순서 그대로 넣어.
   - 소제목(■ 표시)은 굵게 한 줄로.
   - [사진N] 이라고 적힌 자리는 글자 그대로 둬. 사진은 내가 넣을게.
   - 맨 끝 # 태그 줄은 본문에 넣지 말고, 태그 입력 칸이 보이면 거기에 넣어.
④ 다 넣었으면 오른쪽 위 「저장」(임시저장)만 눌러. 「발행」은 누르지 마.
⑤ 끝나면 「임시저장 완료」와 글 제목만 알려줘.
"""


def _aside_page(title: str, blocks: list, post_no: str, log) -> dict:
    os.makedirs(ASIDE_DIR, exist_ok=True)
    parts = []
    n_photo = 0
    for b in blocks:
        t = b.get("type")
        txt = b.get("text", "") or ""
        if t in ("blank",):
            continue
        if t == "hashtags":
            parts.append(f'<p class="tags">{html.escape(txt)}</p>')
        elif t == "subhead":
            parts.append(f"<h2>■ {html.escape(txt)}</h2>")
        elif t == "quote":
            parts.append(f"<blockquote>{html.escape(txt).replace(chr(10), '<br>')}</blockquote>")
        elif t in ("image", "photo"):
            n_photo += 1
            img = ""
            if b.get("path") and os.path.exists(b["path"]):
                img = f'<img src="file:///{html.escape(os.path.abspath(b["path"]).replace(os.sep, "/").lstrip("/"))}">'
            parts.append(f'<p class="photo">[사진{n_photo}] 내가 넣기 {html.escape(b.get("label") or "")}</p>{img}')
        elif t == "oglink":
            parts.append(f'<p>{html.escape(b.get("url") or txt)}</p>')
        else:
            parts.append(f"<p>{html.escape(txt).replace(chr(10), '<br>')}</p>")
    safe = re.sub(r'[\\/:*?"<>|]', "", title)[:40].strip() or "오늘글"
    path = os.path.join(ASIDE_DIR, f"{post_no}_{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset='utf-8'><title>오늘 글</title>"
                "<style>body{max-width:720px;margin:32px auto;font:17px/1.8 sans-serif;padding:0 16px}"
                "h1{font-size:26px}h2{font-size:20px;margin-top:28px}"
                "blockquote{border-left:4px solid #999;margin:16px 0;padding:4px 14px;color:#333}"
                "img{max-width:100%;opacity:.6}.photo{color:#c00;font-weight:bold}.tags{color:#06c}</style>"
                f"<h1>{html.escape(title)}</h1>" + "\n".join(parts))
    prompt_path = os.path.join(ASIDE_DIR, "어사이드에_붙여넣을_프롬프트.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(ASIDE_PROMPT.format(blog_id=_blog_id() or "내아이디"))
    log(f"어사이드용 글 페이지를 만들었습니다: {path}")
    log("→ 이 파일을 어사이드 창으로 끌어다 놓고, 「어사이드에_붙여넣을_프롬프트.txt」를 Ask 칸에 붙여넣으세요.")
    return {"ok": True, "message": f"어사이드용 페이지 준비 완료 — {os.path.basename(path)} (임시저장은 어사이드가 합니다)",
            "notes": ["어사이드에서 임시저장"], "aside_page": path}


# ── 공통 창구 ───────────────────────────────────────────────────

def session_ok(log=print) -> tuple:
    m = mode()
    if m == "ego":
        return ego_session(log)
    if m == "aside":
        return True, ""          # 어사이드는 내가 로그인한 창을 그대로 쓴다 — 여기서 볼 수 없다
    import naver
    return (True, "") if naver.session_alive(log) else (False, "네이버 로그인 세션이 없습니다.")


def save_draft(title, blocks, thumb, log, category="", align="", ai_mark=True,
               post_no="01", folder=None) -> dict:
    m = mode()
    if m == "ego":
        return _ego_draft(title, blocks, log, category=category, align=align, ai_mark=ai_mark)
    if m == "aside":
        return _aside_page(title, blocks, post_no, log)
    import naver
    return naver.save_draft(title, blocks, thumb, log, publish=False, category=category)
