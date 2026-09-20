"""본문 이미지를 '웹 구독'(제미나이 Plus)에서 Playwright로 뽑는다 (수강생 배포판, 선택 기능).

★배포판 기본은 무료 스톡(Unsplash)이다. 이 모듈은 **제미나이 웹에 로그인한 사람만** 선택적으로 쓴다.
  로그인이 없으면 곧바로 스톡으로 넘어간다. (ChatGPT 웹 이미지 경로는 배포판에서 뺐다.)

구조 — naver.py와 같은 '저장 세션 + Playwright'인데, 구글은 자동화 로그인을 잘 막으므로
  기본 크로미움이 아니라 '실제 Chrome + 전용 프로필'(launch_persistent_context, channel=chrome)을 쓴다.
  · login()  = 창 뜸(headless 아님). 에디님이 제미나이에 로그인 → 프로필에 세션 저장(1회).
  · generate(desc, out) = 같은 프로필로 실행 → 프롬프트 → 생성 이미지 다운로드.
    실패(세션 만료·UI 변경·거부) 시 False → image_finder가 무료 Unsplash로 폴백.

⚠️ 무인 브라우저 자동화는 약하다(세션·UI·한도). 반드시 '실패=False→폴백'. 자동실행이 이미지 때문에 죽으면 안 된다.

재로그인/확인:  python3 web_image.py login
단독 테스트:    python3 web_image.py "코딩하는 40대 남성 뒷모습"   (헤드리스)
             python3 web_image.py "..." show               (창 띄워 눈으로 확인)
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE, "session")
PROFILE = os.path.join(SESSION_DIR, "gemini_profile")   # 실제 Chrome 사용자 데이터 디렉토리
GPT_PROFILE = os.path.join(SESSION_DIR, "chatgpt_profile")   # ChatGPT 폴백용(에디님 Plus 구독)
DEBUG_DIR = os.path.join(BASE, "work", "webimg_debug")

GEMINI_URL = "https://gemini.google.com/app"
_INPUT_SEL = ("div.ql-editor[contenteditable='true'], "
              "rich-textarea div[contenteditable='true'], "
              "div[contenteditable='true'][role='textbox']")

CHATGPT_URL = "https://chatgpt.com/"
#: ★2026-08-26 실측으로 `textarea#mobile-composer-prompt`(class `wm-composer-textarea`)가
#   추가로 확인됐다. ChatGPT는 composer DOM을 자주 바꾼다 — 하나만 믿지 않는다.
_GPT_INPUT_SEL = ("div#prompt-textarea[contenteditable='true'], "
                  "div[contenteditable='true'][id='prompt-textarea'], "
                  "textarea#prompt-textarea, "
                  "textarea#mobile-composer-prompt, "
                  "textarea.wm-composer-textarea")


def _ctx(p, headless: bool, profile: str | None = None):
    """실제 Chrome + 전용 프로필. 자동화 티를 줄여 구글/OpenAI 로그인 세션이 유지되게."""
    return p.chromium.launch_persistent_context(
        profile or PROFILE, channel="chrome", headless=headless, locale="ko-KR",
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"])


def login(timeout_sec: int = 300, log=print, service: str = "gemini") -> bool:
    """창을 띄워 에디님이 직접 로그인 → 프로필에 저장(1회). service='gemini'|'chatgpt'.

    ⚠️ 제미나이는 **비로그인 상태에서도 입력창이 보인다** → 입력창만 보고 저장하면 세션이 안 붙는다
       (실측 2026-08-01: 우상단 '로그인' 버튼 + 모델 Flash-Lite = 비로그인).
       그래서 창을 일찍 닫지 않고, 로그인 완료 신호(로그인 버튼 사라짐)를 함께 본다."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    prof = GPT_PROFILE if service == "chatgpt" else PROFILE
    url = CHATGPT_URL if service == "chatgpt" else GEMINI_URL
    sel = _GPT_INPUT_SEL if service == "chatgpt" else _INPUT_SEL
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _ctx(p, headless=False, profile=prof)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded")
        log(f"▶ 뜬 Chrome 창에서 {service}에 로그인하세요(유료 구독 계정).")
        log(f"  로그인이 끝나면 자동 저장됩니다(최대 {timeout_sec}초). 창을 먼저 닫지 마세요.")
        ok = False
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                has_input = bool(pg.query_selector(sel))
                # 로그인 버튼이 남아 있으면 아직 비로그인 → 계속 기다린다
                login_btn = pg.query_selector(
                    'button:has-text("로그인"), a:has-text("로그인"), '
                    'button:has-text("Log in"), a:has-text("Log in")')
                if has_input and not login_btn:
                    ok = True; break
            except Exception:  # noqa: BLE001
                pass
            pg.wait_for_timeout(1500)
        pg.wait_for_timeout(2000)
        ctx.close()   # 프로필에 세션 저장됨
        log("✅ 로그인 세션 저장됨" if ok else "❌ 시간 내 로그인 확인 실패(다시 시도하세요)")
        return ok


#: 🔴이 둘은 **프로필 폴더가 있는지만** 본다 — 로그인 여부는 모른다.
#   2026-08-26 실측: `gpt_session_alive()`가 True인데 실제로는 로그아웃 상태였다
#   (화면에 «로그인 / 무료로 회원가입»이 떠 있었다). 값싼 선검사로만 쓰고,
#   **진짜 여부는 페이지를 열어 `_logged_out()`으로 확인**한다.
#   ★네이버에서 똑같은 함정이 있었다(08-02: `is_logged_in()`이 파일 존재만 보고 True를 줘
#     만료된 쿠키로 6편을 만든 뒤 업로드에서 0/6 전멸). 그때 `session_alive()`를 새로 만들었는데
#     ChatGPT·제미나이 쪽에는 그 교훈이 반영되지 않은 채 남아 있었다.
def session_alive() -> bool:
    """제미나이 프로필 폴더 존재 여부(로그인 보장 아님)."""
    return os.path.isdir(PROFILE) and bool(os.listdir(PROFILE))


def gpt_session_alive() -> bool:
    """ChatGPT 프로필 폴더 존재 여부(로그인 보장 아님)."""
    return os.path.isdir(GPT_PROFILE) and bool(os.listdir(GPT_PROFILE))


def _logged_out(pg) -> bool:
    """지금 이 페이지가 **로그아웃 상태**인가(입력창을 못 찾았을 때 사유를 가른다)."""
    try:
        t = (pg.inner_text("body") or "")[:1200]
    except Exception:  # noqa: BLE001
        return False
    return ("무료로 회원가입" in t or "로그인해 저장된" in t
            or ("로그인" in t and "새 채팅" in t and "prompt" not in t.lower()))


def _prompt(description_ko: str) -> str:
    return (
        f"블로그 본문에 넣을 사진 한 장을 만들어줘. 장면: {description_ko}. "
        "실제 사진처럼 자연스럽고 밝은 톤, 가로 16:9. "
        "알아볼 수 있는 사람 얼굴·실존 인물·특정 브랜드 로고·워터마크는 넣지 마. "
        "화면·모니터·차트에 구체적 숫자는 적지 마."
    )


def generate(description_ko: str, out_path: str, log=print,
             timeout_sec: int = 220, headless: bool = True) -> bool:
    """저장 세션으로 제미나이에 이미지 1장 생성 → 다운로드. 실패 시 False(→폴백)."""
    if not session_alive():
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return False
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, headless=headless)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(3000)
            box = pg.query_selector(_INPUT_SEL)
            if not box:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "no_input.png"))
                _dbg(log, "입력창 없음(세션 만료 의심)"); ctx.close(); return False
            box.click()
            pg.keyboard.type(_prompt(description_ko), delay=6)
            pg.keyboard.press("Enter")
            img_src = None
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                pg.wait_for_timeout(2500)
                # 생성 이미지: 응답 안 googleusercontent/blob 이미지 중 '큰 것'.
                #  ★'이미지를 만들고 있습니다' 단계의 빈 플레이스홀더를 잡지 않도록 512px 이상만.
                #    (제미나이 생성물은 보통 1024px+; 아바타·아이콘도 이 기준에서 걸러진다)
                srcs = pg.eval_on_selector_all(
                    "img",
                    "els => els.filter(e => e.naturalWidth>=512 && e.naturalHeight>=512)"
                    ".map(e => e.src).filter(s => s && (s.includes('googleusercontent')"
                    " || s.startsWith('blob:') || s.startsWith('data:image')))")
                if srcs:
                    img_src = srcs[-1]; break
            if not img_src:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "no_image.png"))
                _dbg(log, "생성 이미지 못 찾음"); ctx.close(); return False
            # 다운로드: fetch(blob:)은 CORS로 막히는 경우가 많다(제이에서 'Failed to fetch' 실측).
            #  → ① fetch 시도 ② 실패 시 이미지 엘리먼트를 직접 스크린샷(가장 안정적).
            raw = None
            try:
                data = pg.evaluate(
                    """async (src) => { const r=await fetch(src); const b=new Uint8Array(await r.arrayBuffer());
                       let s=''; for(let i=0;i<b.length;i++) s+=String.fromCharCode(b[i]); return btoa(s); }""",
                    img_src)
                import base64
                raw = base64.b64decode(data)
            except Exception as e:  # noqa: BLE001
                log(f"  web_image: fetch 실패 → 엘리먼트 스크린샷으로 대체({str(e)[:40]})")
                try:
                    el = pg.query_selector(f'img[src="{img_src}"]')
                    if el:
                        el.scroll_into_view_if_needed()
                        pg.wait_for_timeout(600)
                        el.screenshot(path=out_path)
                        raw = open(out_path, "rb").read()
                except Exception as e2:  # noqa: BLE001
                    log(f"  web_image: 스크린샷도 실패({str(e2)[:40]})")
            ctx.close()
            if not raw or len(raw) < 3000:
                return False
            if not os.path.exists(out_path) or open(out_path, "rb").read() != raw:
                with open(out_path, "wb") as f:
                    f.write(raw)
            _trim_ui(out_path, log)   # 스크린샷 폴백일 때 붙는 제미나이 UI 버튼·워터마크 제거
            log("  web_image: 제미나이 생성 이미지 저장")
            return True
    except Exception as e:  # noqa: BLE001
        log(f"  web_image 예외 → 폴백: {str(e)[:70]}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 사진을 넣어서 다시 뽑기(image → image) — 2026-08-24 신설
# ─────────────────────────────────────────────────────────────────────────────
#: ★에디님 지시: "직접 AI로 뽑았다는 이미지를 넣으면 좋을 거 같아."
#   글 끝에 «AI로 이렇게 해봤습니다» 문단이 있는데 정작 그 결과물이 글에 없었다.
#   말로만 있고 증거가 없으면 홈판 독자가 스크롤을 멈추지 않는다.
#   기존 generate()는 **글자→그림**이라 '에디님 본인'을 만들 수 없다 → 사진을 올려서 돌린다.
_FILE_SEL = 'input[type="file"]'


def _remix_prompt(description_ko: str, keep_face: bool) -> str:
    if keep_face:
        # ★얼굴을 유지해야 하는 건 **에디님 본인 사진**뿐이다(본인 초상이라 문제없다).
        return (
            f"첨부한 사진 속 인물의 얼굴과 인상착의를 그대로 유지한 채, 장면만 바꿔서 "
            f"사진 한 장을 만들어줘. 장면: {description_ko}. "
            "실제 사진처럼 자연스럽고 밝은 톤, 가로 16:9. "
            "글자·자막·워터마크·브랜드 로고는 넣지 마. 인물은 한 명만."
        )
    # 얼굴을 빼는 쪽 — 실존 인물을 그리지 않는다(초상권·오인 방지)
    return (
        f"첨부한 사진의 **분위기와 색감만** 참고해서 새 이미지를 만들어줘. "
        f"장면: {description_ko}. "
        "★사람 얼굴은 절대 넣지 마. 실존 인물을 그리지 마. 필요하면 뒷모습·손·실루엣만. "
        "사물과 공간 위주로, 실제 사진처럼 자연스럽고 밝은 톤, 가로 16:9. "
        "글자·자막·워터마크·브랜드 로고는 넣지 마."
    )


def remix(src_image: str, description_ko: str, out_path: str, log=print,
          keep_face: bool = True, timeout_sec: int = 420, headless: bool = True) -> bool:
    """사진 1장을 올려 장면을 바꾼 이미지를 받는다. 실패하면 False(호출측이 폴백).

    keep_face=True  : 첨부 인물의 얼굴을 유지(에디님 본인 사진 전용)
    keep_face=False : 얼굴 없이 분위기만 참고(연예 글용 — 실존 인물을 그리지 않는다)

    ★timeout이 420초인 이유: 이미지 입력이 붙으면 생성이 눈에 띄게 느려진다.
      글자→그림 경로에서도 220초는 짧아 «이미지를 만들고 있습니다»에서 잘린 전례가 있다(8/19).
    """
    if not os.path.exists(src_image):
        log(f"  remix: 원본 사진이 없습니다 — {src_image}")
        return False
    if not session_alive():
        log("  remix: 제미나이 세션 없음")
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return False
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, headless=headless)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(3000)
            box = pg.query_selector(_INPUT_SEL)
            if not box:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "remix_no_input.png"))
                log("  remix: 입력창 없음(세션 만료 의심)"); ctx.close(); return False

            # ① 사진 첨부.
            #   ★파일 input은 페이지에 **처음부터 있지 않다**(실측: 초기 0개).
            #     «업로드 및 도구» 버튼(＋)을 눌러야 DOM에 생긴다. 누른 뒤에도 숨어 있지만
            #     Playwright는 숨은 input에 파일을 넣을 수 있다.
            fi = pg.query_selector(_FILE_SEL)
            if not fi:
                for sel in ('button[aria-label*="업로드"]', 'button[aria-label*="Upload"]',
                            'button[aria-label*="파일"]', 'button[aria-label*="추가"]'):
                    b = pg.query_selector(sel)
                    if b:
                        try:
                            b.click()
                            pg.wait_for_timeout(1200)
                        except Exception:  # noqa: BLE001
                            pass
                        break
                fi = pg.query_selector(_FILE_SEL)
            if not fi:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "remix_no_fileinput.png"))
                log("  remix: 파일 첨부 칸을 못 찾음(＋ 버튼 이름이 바뀌었을 수 있음)")
                ctx.close(); return False
            n_before = len(pg.query_selector_all("img"))
            fi.set_input_files(src_image)
            # 🔴Escape를 누르지 않는다 — **첨부가 취소된다**(실측 2026-08-25: 첨부가 사라지고
            #   프롬프트만 입력창에 남은 채 전송도 안 됐다). ＋ 메뉴는 그냥 두면 알아서 닫힌다.
            # 업로드 확인: 미리보기 썸네일이 붙으면 img 개수가 는다.
            #   («작은 이미지가 있는가»로 보면 좌하단 프로필 아바타가 걸려 항상 참이 된다 — 못 쓴다)
            attached, up_deadline = False, time.time() + 90
            while time.time() < up_deadline:
                pg.wait_for_timeout(1500)
                if len(pg.query_selector_all("img")) > n_before:
                    attached = True
                    break
            if not attached:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "remix_not_attached.png"))
                log("  remix: 사진이 첨부되지 않았습니다"); ctx.close(); return False
            pg.wait_for_timeout(2500)        # 업로드 처리 여유
            log(f"  remix: 사진 첨부 완료 → {os.path.basename(src_image)}")

            # ② 지시문 입력 후 전송
            box = pg.query_selector(_INPUT_SEL)
            box.click()
            pg.keyboard.type(_remix_prompt(description_ko, keep_face), delay=6)
            pg.wait_for_timeout(600)
            # 🔴전송 **직전**에 화면의 이미지 목록을 찍어둔다.
            #   실측(1차 시도): 올린 원본 썸네일을 결과물로 착각해 14KB짜리 원본 축소본을 저장했다.
            #   업로드 미리보기는 naturalWidth가 원본 크기(1333×2000)라 512px 필터를 그냥 통과한다.
            #   → 크기로는 못 거른다. **전송 뒤 새로 생긴 src만** 받는다.
            _big = ("els => els.filter(e => e.naturalWidth>=512 && e.naturalHeight>=512)"
                    ".map(e => e.src).filter(s => s && (s.includes('googleusercontent')"
                    " || s.startsWith('blob:') || s.startsWith('data:image')))")
            seen = set(pg.eval_on_selector_all("img", _big))
            # ★Enter만 믿지 않는다 — 첨부가 붙어 있으면 먹지 않는 경우가 있다(실측).
            #   눌러 보고 **입력창이 비었는지 확인**하고, 안 비었으면 전송 버튼을 직접 누른다.
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)
            def _still_typed():
                el = pg.query_selector(_INPUT_SEL)
                return bool(el and (el.inner_text() or "").strip())
            if _still_typed():
                sb = pg.query_selector('button[aria-label*="보내기"], button[aria-label*="Send"]')
                if sb:
                    try:
                        sb.click()
                        pg.wait_for_timeout(2000)
                    except Exception:  # noqa: BLE001
                        pass
            if _still_typed():
                pg.screenshot(path=os.path.join(DEBUG_DIR, "remix_not_sent.png"))
                log("  remix: 전송이 되지 않았습니다"); ctx.close(); return False

            # ③ 결과 수거 — 전송 전에 없던 이미지만 생성물이다
            img_src, deadline = None, time.time() + timeout_sec
            while time.time() < deadline:
                pg.wait_for_timeout(2500)
                fresh = [x for x in pg.eval_on_selector_all("img", _big) if x not in seen]
                if fresh:
                    img_src = fresh[-1]; break
            if not img_src:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "remix_no_image.png"))
                log("  remix: 생성 이미지 못 찾음(디버그 스크린샷 저장)"); ctx.close(); return False

            raw = None
            try:
                data = pg.evaluate(
                    """async (src) => { const r=await fetch(src); const b=new Uint8Array(await r.arrayBuffer());
                       let s=''; for(let i=0;i<b.length;i++) s+=String.fromCharCode(b[i]); return btoa(s); }""",
                    img_src)
                import base64
                raw = base64.b64decode(data)
            except Exception:  # noqa: BLE001
                # blob:은 CORS로 막힌다 — 엘리먼트 스크린샷이 가장 안정적(generate()와 동일)
                try:
                    el = pg.query_selector(f'img[src="{img_src}"]')
                    if el:
                        el.scroll_into_view_if_needed()
                        pg.wait_for_timeout(600)
                        el.screenshot(path=out_path)
                        raw = open(out_path, "rb").read()
                except Exception as e2:  # noqa: BLE001
                    log(f"  remix: 스크린샷도 실패({str(e2)[:40]})")
            ctx.close()
            if not raw or len(raw) < 3000:
                return False
            if not os.path.exists(out_path) or open(out_path, "rb").read() != raw:
                with open(out_path, "wb") as f:
                    f.write(raw)
            _trim_ui(out_path, log)
            log(f"  remix: 저장 → {os.path.basename(out_path)}")
            return True
    except Exception as e:  # noqa: BLE001
        log(f"  remix 예외 → 폴백: {str(e)[:80]}")
        return False


def _img_srcs(pg) -> list[str]:
    return pg.eval_on_selector_all(
        "img",
        "els => els.filter(e => e.naturalWidth>=512 && e.naturalHeight>=512)"
        ".map(e => e.src).filter(s => s && (s.includes('googleusercontent')"
        " || s.startsWith('blob:') || s.startsWith('data:image')))")


def _grab_new_image(pg, seen: set, out_path: str, timeout_sec: int, log,
                    base_count: int = -1) -> bool:
    """마지막 프롬프트로 새로 생긴 이미지를 받아 저장.

    ★판정 기준(2026-08-06 수정): 예전엔 'seen에 없는 src'로만 봤는데, 제미나이가 **blob URL을
      재사용**해서 새 이미지인데도 이미 본 것으로 걸러졌다. 그래서 한 장 걸러 한 장씩
      2.5분 타임아웃으로 실패했다(홀수 성공/짝수 실패 패턴).
      이제 **이미지 개수가 늘었는지**를 먼저 보고, 늘었으면 마지막 것을 새 이미지로 쓴다.
    """
    deadline = time.time() + timeout_sec
    img_src = None
    while time.time() < deadline:
        pg.wait_for_timeout(2500)
        srcs = _img_srcs(pg)
        if base_count >= 0 and len(srcs) > base_count:
            img_src = srcs[-1]
            break
        fresh = [s for s in srcs if s not in seen]
        if fresh:
            img_src = fresh[-1]
            break
    if not img_src:
        return False
    seen.add(img_src)
    raw = None
    try:
        data = pg.evaluate(
            """async (src) => { const r=await fetch(src); const b=new Uint8Array(await r.arrayBuffer());
               let s=''; for(let i=0;i<b.length;i++) s+=String.fromCharCode(b[i]); return btoa(s); }""",
            img_src)
        import base64
        raw = base64.b64decode(data)
    except Exception:  # noqa: BLE001
        try:
            el = pg.query_selector(f'img[src="{img_src}"]')
            if el:
                el.scroll_into_view_if_needed()
                pg.wait_for_timeout(500)
                el.screenshot(path=out_path)
                raw = open(out_path, "rb").read()
        except Exception:  # noqa: BLE001
            return False
    if not raw or len(raw) < 3000:
        return False
    if not os.path.exists(out_path) or open(out_path, "rb").read() != raw:
        with open(out_path, "wb") as f:
            f.write(raw)
    _trim_ui(out_path, lambda m: None)
    return True


def make_many_once(descriptions: list[str], out_paths: list[str], log=print,
                   headless: bool = True, per_image_sec: int = 150) -> list[bool]:
    """제미나이 창 1개로 여러 장 생성(재시도 없음). make_many가 이걸 감싼다."""
    return _gemini_batch(descriptions, out_paths, log, headless, per_image_sec)


def make_many(descriptions: list[str], out_paths: list[str], log=print,
              headless: bool = True, per_image_sec: int = 150) -> list[bool]:
    """★여러 장을 **한 브라우저 세션**에서 연속 생성(2026-08-04).

    장당 브라우저를 새로 띄우면 5분 넘게 걸렸다(실측 5분27초/장 → 6장이면 33분).
    제미나이 대화창을 한 번만 열고 프롬프트를 이어서 넣으면 장당 1~2분으로 준다.
    반환: 각 장의 성공 여부 리스트(실패분은 호출부가 폴백 처리).
    """
    return _gemini_batch(descriptions, out_paths, log, headless, per_image_sec, retry_gpt=True)


#: ★한 편의 '이미지 단계' 전체 상한(초). 2026-08-10 실측 사고 대응 —
#  per_image_sec=150을 줘도 한 장에 17분을 쓰는 경우가 있어(제미나이 응답 지연/한도)
#  04편 한 편이 **182분**을 먹었다(다른 편은 13~16분). 남은 자리는 호출부가 Gemini API/스톡으로 채운다.
BATCH_BUDGET_SEC = 600


def _gemini_batch(descriptions: list[str], out_paths: list[str], log=print,
                  headless: bool = True, per_image_sec: int = 150,
                  retry_gpt: bool = False) -> list[bool]:
    """제미나이 창 1개로 연속 생성. retry_gpt=True면 실패분을 제미나이 재시도→ChatGPT 순으로 보완."""
    n = len(descriptions)
    results = [False] * n
    if not session_alive() or not n:
        return results
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return results
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, headless=headless)
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            pg.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(3000)
            box = pg.query_selector(_INPUT_SEL)
            if not box:
                ctx.close()
                _dbg(log, "입력창 없음(세션 만료 의심)")
                return results
            seen: set = set()
            try:
                pg.set_default_timeout(20000)      # 개별 Playwright 동작이 오래 매달리지 않게
            except Exception:  # noqa: BLE001
                pass
            _t0 = time.time()
            for i, (desc, out) in enumerate(zip(descriptions, out_paths)):
                if time.time() - _t0 > BATCH_BUDGET_SEC:
                    log(f"  웹이미지 예산({BATCH_BUDGET_SEC//60}분) 초과 → 남은 "
                        f"{n - i}장은 폴백(API·스톡)에 넘김")
                    break
                try:
                    before = len(_img_srcs(pg))     # 보내기 전 이미지 개수(새 이미지 판정 기준)
                    box = pg.query_selector(_INPUT_SEL) or box
                    box.click()
                    pg.keyboard.type(_prompt(desc), delay=4)
                    pg.keyboard.press("Enter")
                    results[i] = _grab_new_image(pg, seen, out, per_image_sec, log,
                                                 base_count=before)
                    log(f"  웹이미지 {i+1}/{n} " + ("생성" if results[i] else "실패"))
                except Exception as e:  # noqa: BLE001
                    log(f"  웹이미지 {i+1}/{n} 예외: {str(e)[:40]}")
            ctx.close()
    except Exception as e:  # noqa: BLE001
        log(f"web_image(make_many) 예외 → 폴백: {str(e)[:60]}")
    # ★제미나이가 실패한 자리는 ChatGPT로 재시도(2026-08-04 에디님: "챗지피티 안되면 제미나이에서
    #   진행해야지" — 단일 make엔 있던 폴백이 일괄 경로엔 빠져 있어 이미지가 통째로 비었다).
    # ★제미나이 우선(2026-08-06 에디님: "챗지피티는 이미지 제한이 자꾸 걸리니 왠만하면 제미나이로").
    #   실패분은 먼저 **제미나이에서 한 번 더** 시도하고, 그래도 안 되는 것만 ChatGPT로 넘긴다.
    retry = [i for i, ok in enumerate(results) if not ok] if retry_gpt else []
    if retry:
        log(f"  제미나이 재시도 {len(retry)}장(창 재사용)")
        try:
            again = _gemini_batch([descriptions[i] for i in retry],
                                  [out_paths[i] for i in retry],
                                  lambda m: None, headless, per_image_sec, False)
            for k, i in enumerate(retry):
                if k < len(again) and again[k]:
                    results[i] = True
            log(f"  제미나이 재시도 결과: {sum(1 for i in retry if results[i])}/{len(retry)}장")
        except Exception as e:  # noqa: BLE001
            log(f"  제미나이 재시도 실패: {str(e)[:40]}")

    # ★2026-08-06 에디님 확정: "지금부터 진행하는 모든 것은 제미나이로."
    #   ChatGPT 폴백은 **완전히 제거**했다(한도가 자주 걸려 실패만 키웠다).
    #   제미나이가 못 만든 자리는 호출부(pipeline)가 Gemini API/스톡으로 채운다.
    return results


def make(description_ko: str, out_path: str, log=print, headless: bool = True) -> bool:
    """★권장 진입점: **제미나이로만** 이미지 1장 확보(2026-08-06 에디님 확정).
    실패하면 False → 호출부(pipeline)가 Gemini API/스톡으로 폴백한다.
    ChatGPT는 이미지 생성 한도가 자주 걸려 자동 경로에서 완전히 뺐다."""
    return generate(description_ko, out_path, log=log, headless=headless)


def _trim_ui(path: str, log=print) -> None:
    """엘리먼트 스크린샷으로 받은 이미지에서 겹쳐 그려진 제미나이 UI를 잘라낸다.
    UI 위치(실측 2026-08-01): 우상단 공유/복사/다운로드 버튼(가장 큼) · 우하단 반짝이 워터마크.

    🔴2026-08-24 재측정 — **우하단 반짝이(✦)가 계속 남아 있었다.** 하단 5% 크롭으로는 못 지운다.
      확대해서 좌표를 재보니 워터마크는 폭의 오른쪽 **11% 안쪽**, 높이의 아래 17% 지점에 있다.
      세로를 17% 깎는 것보다 **가로 오른쪽을 11%까지 깎는 편이 손실이 적다**(16:9라 가로가 넉넉).
      → 오른쪽 11%. 이 값은 generate()가 만드는 본문 이미지에도 같이 적용된다
        (그동안 본문 이미지에도 이 워터마크가 그대로 실려 나갔다).
    실패해도 원본 유지(무해)."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return   # Pillow 없으면 그냥 원본 사용
    try:
        im = Image.open(path)
        w, h = im.size
        left, right = int(w * 0.05), int(w * 0.11)
        top, bottom = int(h * 0.12), int(h * 0.06)
        if w - left - right < 200 or h - top - bottom < 200:
            return
        im.crop((left, top, w - right, h - bottom)).save(path)
        log(f"  web_image: UI 크롭 → {w-left-right}x{h-top-bottom}")
    except Exception as e:  # noqa: BLE001
        log(f"  web_image: 크롭 생략({str(e)[:40]})")


def _dbg(log, msg: str) -> None:
    log(f"  web_image: {msg} → 폴백 (스크린샷: work/webimg_debug/)")


if __name__ == "__main__":
    arg1 = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg1 == "login":
        login()                          # 제미나이 로그인(1회, 선택)
    else:                                # 제미나이 웹으로만 생성 테스트(실패 시 스톡 폴백)
        desc = arg1 or "노트북 앞에서 메모하는 사람, 밝은 책상"
        show = len(sys.argv) > 2 and sys.argv[2] == "show"
        print("생성:", make(desc, "/tmp/_webimg_test.png", headless=not show))


# ─────────────────────────────────────────────────────────────────────────────
# ChatGPT에 **실제로 물어보고 답변 화면을 캡처** — 2026-08-26 신설
# ─────────────────────────────────────────────────────────────────────────────
#: ★에디님: "문장은 챗지피티에서 나온 답변을 캡쳐한 것처럼 보여야지. 그래야 문맥이 맞지."
#   맞는 요구다. 다만 **그리지 않고 진짜로 찍는다** — ChatGPT UI를 흉내내 그리면
#   그 제품이 실제로 한 답인 것처럼 오인되고, 하지도 않은 말을 붙이는 셈이 된다.
#   에디님 계정이 이미 붙어 있으니(`gpt_session_alive`) 정말로 물어보고 그 화면을 찍으면 된다.
#   진짜 캡처라 문맥도 맞고 거짓도 아니다.
_GPT_ANSWER_SEL = '[data-message-author-role="assistant"]'


def ask_gpt_capture(question: str, out_path: str, log=print,
                    timeout_sec: int = 240, headless: bool = False) -> bool:
    """ChatGPT에 질문을 넣고 **답변 말풍선을 그대로 스크린샷**한다. 실패 시 False.

    ★headless=False가 기본이다 — ChatGPT는 Cloudflare 봇검증 때문에 headless로는 막힌다
      (이 파일 상단 `generate_gpt` 주석 참고. 실측으로 확인된 제약이다).
    """
    if not gpt_session_alive():
        log("  gpt캡처: ChatGPT 세션 없음")
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        return False
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        with sync_playwright() as p:
            ctx = _ctx(p, headless=headless, profile="chatgpt")
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            # 🔴**새 채팅으로 시작한다**(2026-08-26 실측).
            #   저장 프로필이라 이전 대화방을 그대로 이어받는데, 앞서 던진
            #   «이 사진 속 방…» 질문이 남아 있어서 답이 «사진이 지금 메시지에는 안 보여서…»로
            #   시작했다. 사진 얘기를 꺼낸 적이 없는 질문인데도 그랬다.
            #   한 편마다 **맥락이 비어 있어야** 글에 맞는 답이 나온다.
            pg.goto(CHATGPT_URL + "?temporary-chat=true",
                    wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(4500)
            for sel in ('a[data-testid="create-new-chat-button"]',
                        'button[aria-label*="새 채팅"]', 'a[href="/"]'):
                nb = pg.query_selector(sel)
                if nb:
                    try:
                        nb.click(); pg.wait_for_timeout(2500)
                    except Exception:  # noqa: BLE001
                        pass
                    break
            box = pg.query_selector(_GPT_INPUT_SEL)
            if not box:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "gptcap_no_input.png"))
                if _logged_out(pg):
                    log("  gpt캡처: 🔴ChatGPT **로그인이 풀렸습니다**. "
                        "터미널에서 `python3 web_image.py login-gpt` 실행 후 직접 로그인하세요.")
                else:
                    log("  gpt캡처: 입력창을 못 찾음(화면 구성이 바뀐 듯 — "
                        "work/webimg_debug/gptcap_no_input.png 확인)")
                ctx.close(); return False
            n_before = len(pg.query_selector_all(_GPT_ANSWER_SEL))
            box.click()
            pg.keyboard.type(question, delay=8)
            pg.wait_for_timeout(600)
            # 🔴Enter만 믿지 않는다 — 질문만 입력된 채 전송이 안 되는 걸 실측했다(2026-08-26).
            #   눌러 보고 **입력창이 비었는지** 확인하고, 안 비었으면 전송 버튼을 직접 누른다.
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2000)

            def _typed():
                el0 = pg.query_selector(_GPT_INPUT_SEL)
                if not el0:
                    return False
                try:
                    v = el0.input_value()
                except Exception:  # noqa: BLE001
                    v = el0.inner_text() or ""
                return bool((v or "").strip())

            if _typed():
                for sel in ('button[data-testid="send-button"]',
                            'button[aria-label*="보내기"]', 'button[aria-label*="Send"]',
                            'button[aria-label*="전송"]'):
                    b2 = pg.query_selector(sel)
                    if b2:
                        try:
                            b2.click(); pg.wait_for_timeout(2000)
                        except Exception:  # noqa: BLE001
                            pass
                        break
            if _typed():
                pg.screenshot(path=os.path.join(DEBUG_DIR, "gptcap_not_sent.png"))
                log("  gpt캡처: 질문 전송이 되지 않았습니다"); ctx.close(); return False

            # 답변이 **다 나올 때까지** 기다린다. 글자 수가 3회 연속 그대로면 끝난 것으로 본다.
            el, last, stable, deadline = None, -1, 0, time.time() + timeout_sec
            while time.time() < deadline:
                pg.wait_for_timeout(2000)
                els = pg.query_selector_all(_GPT_ANSWER_SEL)
                if len(els) <= n_before:
                    continue
                el = els[-1]
                try:
                    cur = len(el.inner_text() or "")
                except Exception:  # noqa: BLE001
                    continue
                if cur and cur == last:
                    stable += 1
                    if stable >= 3:
                        break
                else:
                    stable = 0
                last = cur
            if el is None or last < 10:
                pg.screenshot(path=os.path.join(DEBUG_DIR, "gptcap_no_answer.png"))
                log("  gpt캡처: 답변을 못 받음"); ctx.close(); return False
            # 🔴엘리먼트 스크린샷은 «화면이 멈출 때까지» 기다리다 30초에 걸린다(2026-08-26 실측).
            #   ChatGPT는 커서 깜빡임·미세 애니메이션이 계속 돌아 **영영 안 멈춘다**.
            #   → 위치만 재서 **페이지를 그 영역만 잘라 찍는다**(안정 대기가 없다).
            try:
                el.scroll_into_view_if_needed(timeout=8000)
                pg.wait_for_timeout(1200)
                box = el.bounding_box()
                if not box or box["width"] < 80 or box["height"] < 40:
                    log("  gpt캡처: 답변 영역 크기를 못 잼"); ctx.close(); return False
                pad = 14
                # ★하단 입력바가 답변 위에 떠 있어 캡처에 겹쳐 들어간다(실측: 마지막 줄이 가렸다).
                #   입력바 윗선까지만 자른다.
                limit = None
                cb = pg.query_selector(_GPT_INPUT_SEL)
                if cb:
                    cbox = cb.bounding_box()
                    if cbox:
                        limit = cbox["y"] - 24
                top = max(0, box["y"] - pad)
                bottom = box["y"] + box["height"] + pad
                if limit and limit > top + 120:
                    bottom = min(bottom, limit)
                clip = {"x": max(0, box["x"] - pad), "y": top,
                        "width": box["width"] + pad * 2,
                        # 답이 너무 길면 위쪽만 — 블로그에 넣기 좋은 높이로 자른다
                        "height": min(bottom - top, 1600)}
                pg.screenshot(path=out_path, clip=clip, animations="disabled",
                              caret="hide", timeout=25000)
            except Exception as e:  # noqa: BLE001
                log(f"  gpt캡처: 스크린샷 실패({str(e)[:60]})"); ctx.close(); return False
            ctx.close()
            ok = os.path.exists(out_path) and os.path.getsize(out_path) > 4000
            log(f"  gpt캡처: {'저장' if ok else '파일이 너무 작음'} ({last}자 답변)")
            return ok
    except Exception as e:  # noqa: BLE001
        log(f"  gpt캡처 예외 → 폴백: {str(e)[:70]}")
        return False


