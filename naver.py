"""네이버 로그인(세션 저장) 및 스마트에디터 ONE 임시저장 자동화."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
MYBLOG_URL = "https://blog.naver.com/MyBlog.naver"

Logger = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# 로그인 / 세션
# ---------------------------------------------------------------------------

# ── 브라우저 구동 방식 (2026-08-03, 에디님: "사람이 한 것처럼 해야 봇으로 안 잡힌다") ──
# 우선순위: ① 이미 떠 있는 실제 크롬에 CDP로 붙기 → ② 실제 Chrome + 전용 프로필 → ③ 내장 크로미움+쿠키
#  ①②는 '진짜 크롬'이라 자동화 티가 적고, 프로필에 로그인이 남아 세션 만료도 드물다.
CDP_URL = os.environ.get("NAVER_CDP_URL", "http://localhost:9222")
#: 실제 크롬 전용 프로필. 🔴블로그(=네이버 계정)마다 달라야 하므로 config에서 받는다
#  (2026-09-08 두 블로그 분리). 옛 경로를 폴백으로 남겨 둔다.
CHROME_PROFILE = getattr(config, "CHROME_PROFILE", None) or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "session", "naver_profile")

_HUMANIZE = ["--disable-blink-features=AutomationControlled"]


def ensure_cdp_chrome(log: Logger = _noop, wait_sec: int = 12) -> bool:
    """9222 포트에 '로그인된 전용 프로필' 크롬이 떠 있게 한다(2026-08-03 에디님 B안).

    이미 떠 있으면 그대로 두고 True. 없으면 전용 프로필로 띄운다.
    → 이후 open_browser가 CDP로 붙어 '사람이 쓰는 크롬'처럼 동작한다.
    에디님이 쓰는 기본 크롬 창은 건드리지 않는다(별도 프로필이라 독립).
    """
    import socket
    import subprocess

    def _up() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", 9222), timeout=1):
                return True
        except OSError:
            return False

    if _up():
        return True
    exe = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(exe):
        log("크롬 실행파일을 찾지 못함 — CDP 생략")
        return False
    try:
        subprocess.Popen(
            [exe, "--remote-debugging-port=9222",
             f"--user-data-dir={CHROME_PROFILE}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-blink-features=AutomationControlled"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        log(f"CDP 크롬 실행 실패: {str(e)[:60]}")
        return False
    for _ in range(wait_sec * 2):
        if _up():
            log("CDP 크롬 기동 완료(전용 프로필)")
            return True
        time.sleep(0.5)
    log("CDP 크롬 기동 확인 실패")
    return False


def _set_reserve_time(frame, page, hh: int, mm: int, log: Logger) -> bool:
    """발행 레이어에서 '예약'을 켜고 시:분을 지정(분은 10분 단위만 가능).

    ★제이 경제 블로그(~/경제이슈 블로그 자동화/naver.py)의 검증된 구현을 그대로 이식(2026-08-06).
      추정 셀렉터로 짰다가 에디님이 "예약은 제이에서 이미 하고 있다"고 알려주셔서 교체했다.
    """
    try:
        ok = frame.evaluate(
            "() => { const r=document.getElementById('radio_time2');"
            " if(!r) return false; r.click(); return true; }")
        if not ok:
            return False
        page.wait_for_timeout(900)
        # 🔴클래스 뒤의 `__J_heO` 같은 꼬리는 네이버가 화면을 배포할 때마다 바뀌는 해시다.
        #   2026-09-10 사고: `hour_option__J_heO` → `hour_option__Vk2eR`로 바뀌어 예약이 둘 다 실패,
        #   strpia 그날 발행 0편(글은 임시저장에 멈췄다). → **앞부분만** 보고 찾는다.
        frame.select_option('select[class^="hour_option__"]', f"{hh:02d}")
        page.wait_for_timeout(300)
        frame.select_option('select[class^="minute_option__"]', f"{mm - mm % 10:02d}")
        page.wait_for_timeout(300)
        log(f"  예약 시간 설정: {hh:02d}:{mm - mm % 10:02d}")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  예약 시간 설정 실패: {str(e)[:90]}")
        return False


def _ctx_logged_in(ctx) -> bool:
    """이 컨텍스트에 네이버 로그인 쿠키가 있나. ★없는 브라우저를 쓰면 업로드가 통째로 실패한다
    (2026-08-04 사고: 로그인 없는 새 프로필을 써서 0/5 전멸)."""
    try:
        return _has_auth_cookie(ctx)
    except Exception:  # noqa: BLE001
        return False


def open_browser(p, log: Logger = _noop, headless: bool = False, require_login: bool = True):
    """(context, closer) 반환. 사람이 쓰는 크롬에 가깝게 열되, **로그인된 것만** 쓴다.

    ★2026-08-04 교훈: CDP/전용 프로필을 1순위로 두자 오히려 불안정해졌다.
      CDP 크롬이 전용 프로필을 잠가 ②를 막고, 크롬을 종료하면 프로필 로그인이 날아갔다.
      **저장 쿠키(storage_state)가 가장 오래 간다**(7/12 로그인이 3주 유지됨).
      그래서 저장 쿠키가 살아 있으면 그걸 먼저 쓴다. EDI_PREFER_CHROME=1이면 옛 순서(CDP 우선).

    require_login=False는 로그인 창을 띄울 때(login_and_save)만 쓴다.
    """
    # ★2026-08-04 에디님 확정: "그냥 플레이라이트로만 진행해줘".
    #   실제 Chrome 프로필·CDP 경로는 프로필 잠금/손상("프로필을 여는 동안 문제가 발생했습니다")과
    #   로그인 소실을 반복해서 **기본으로 쓰지 않는다**. 저장 쿠키 + 내장 브라우저가 가장 안정적이다.
    #   (굳이 실제 크롬을 쓰려면 EDI_PREFER_CHROME=1)
    if not os.environ.get("EDI_PREFER_CHROME"):
        br = p.chromium.launch(headless=headless, slow_mo=30, args=_HUMANIZE)
        ctx = br.new_context(
            storage_state=config.SESSION_FILE if is_logged_in() else None,
            permissions=["clipboard-read", "clipboard-write"],
            locale="ko-KR", viewport={"width": 1440, "height": 900})
        log("브라우저: Playwright 내장 + 저장 쿠키")
        return ctx, br.close

    # ⓪ 저장 쿠키가 유효하면 그것부터 — 가장 안정적이고 프로필 잠금 문제도 없다.
    if require_login and not os.environ.get("EDI_PREFER_CHROME") and is_logged_in():
        try:
            br = p.chromium.launch(headless=headless, slow_mo=30, args=_HUMANIZE)
            ctx = br.new_context(storage_state=config.SESSION_FILE,
                                 permissions=["clipboard-read", "clipboard-write"],
                                 locale="ko-KR", viewport={"width": 1440, "height": 900})
            if _ctx_logged_in(ctx):
                log("브라우저: 저장 쿠키(안정 경로)")
                return ctx, br.close
            br.close()
            log("저장 쿠키가 만료 → 크롬 프로필 경로로")
        except Exception as e:  # noqa: BLE001
            log(f"저장 쿠키 열기 실패({str(e)[:40]})")
    # ① 실행 중인 크롬(원격 디버깅 포트)에 붙기 — 가장 '사람 같은' 방식.
    #    없으면 '로그인된 전용 프로필'로 직접 띄운 뒤 붙는다(에디님 B안, 2026-08-03).
    # ⚠️ EDI_NO_CDP=1 이면 CDP를 아예 건너뛴다. CDP 크롬이 전용 프로필을 '잠가서'
    #    ②경로(전용 프로필 직접 실행)까지 막고 만료된 쿠키로 폴백해 실패한 적이 있다(2026-08-04).
    if os.environ.get("EDI_NO_CDP"):
        log("CDP 생략(EDI_NO_CDP)")
        raise_cdp = True
    else:
        raise_cdp = False
        if require_login:
            ensure_cdp_chrome(log)
    try:
        if raise_cdp:
            raise RuntimeError("cdp disabled")
        br = p.chromium.connect_over_cdp(CDP_URL, timeout=3000)
        ctx = br.contexts[0] if br.contexts else br.new_context()
        if not require_login or _ctx_logged_in(ctx):
            try:
                ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            except Exception:  # noqa: BLE001
                pass
            log("브라우저: 실행 중인 크롬에 연결(CDP)")
            return ctx, (lambda: None)      # 사용자 크롬이므로 닫지 않는다
        log("CDP 크롬에 네이버 로그인이 없어 건너뜀")
    except Exception:  # noqa: BLE001
        pass
    # ② 실제 Chrome 실행파일 + 전용 프로필(로그인 지속) — 로그인돼 있을 때만
    try:
        ctx = p.chromium.launch_persistent_context(
            CHROME_PROFILE, channel="chrome", headless=headless, locale="ko-KR",
            viewport={"width": 1440, "height": 900}, args=_HUMANIZE,
            permissions=["clipboard-read", "clipboard-write"])
        if not require_login or _ctx_logged_in(ctx):
            log("브라우저: 실제 Chrome + 전용 프로필")
            return ctx, ctx.close
        ctx.close()
        log("크롬 전용 프로필에 네이버 로그인이 없어 건너뜀")
    except Exception as e:  # noqa: BLE001
        log(f"크롬 프로필 실행 실패({str(e)[:40]}) → 내장 브라우저로 폴백")
    # ③ 폴백: 내장 크로미움 + 저장 쿠키
    br = p.chromium.launch(headless=headless, slow_mo=30, args=_HUMANIZE)
    ctx = br.new_context(storage_state=config.SESSION_FILE,
                         permissions=["clipboard-read", "clipboard-write"],
                         locale="ko-KR", viewport={"width": 1440, "height": 900})
    log("브라우저: 내장 크로미움 + 저장 쿠키(폴백)")
    return ctx, br.close


def is_logged_in() -> bool:
    """세션 파일 존재만 확인(빠름). 실제 유효성은 session_alive()를 쓸 것."""
    return os.path.exists(config.SESSION_FILE)


# 마지막 session_alive()가 «연결 문제»로 실패했는가 — 만료와 구분해 알리려고 둔다.
LAST_CHECK_NET_ERROR = False


def session_alive(log=lambda m: None) -> bool:
    """쿠키가 '실제로 살아있는지' 네이버에 물어본다(약 10초).

    is_logged_in()은 파일 존재만 보므로 만료된 쿠키도 True다. 그 상태로 6편을
    생성한 뒤 발행에서 전부 죽었다(2026-08-02 실제 발생: 0/6, 게다가 원인 메시지가
    '에디터 셀렉터 조정 필요'로 잘못 떠서 진단도 헷갈렸다). 무인 실행은 '만들기 전에' 이걸로 확인한다.
    (제이 경제 블로그 naver.session_alive와 같은 방식 — 거기선 2026-07-15에 같은 사고)
    """
    if not is_logged_in():
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = b.new_context(storage_state=config.SESSION_FILE)
            pg = ctx.new_page()
            # ★로그인이 '반드시' 필요한 페이지로 검사해야 한다(2026-08-06 사고).
            #   전엔 section.blog.naver.com/BlogHome을 봤는데 이건 비로그인도 열려서
            #   만료된 세션에도 True가 나왔고, 그 상태로 5편을 만들어 업로드에서 0/5 전멸했다.
            pg.goto("https://blog.naver.com/GoBlogWrite.naver",
                    wait_until="domcontentloaded", timeout=25000)
            pg.wait_for_timeout(1500)
            url = pg.url or ""
            b.close()
        ok = "nidlogin" not in url and "nid.naver.com" not in url
        log("네이버 세션 유효" if ok else "네이버 세션 만료 — 재로그인 필요")
        return ok
    except Exception as e:  # noqa: BLE001
        # 🔴**인터넷이 끊긴 것을 «세션 만료»라고 부르지 않는다**(2026-09-15 09:13·09:30).
        #   맥 연결이 끊겨 `ERR_INTERNET_DISCONNECTED`가 났는데 «만료로 간주» → 러너가
        #   «재로그인 후 다시 실행하세요» 알림·메일까지 보냈다. 로그인은 멀쩡했다(연결 복구 후 바로 «유효»).
        #   만료로 믿고 재로그인하면 시간만 쓰고, 정작 할 일(연결 확인·재실행)은 안 한다.
        global LAST_CHECK_NET_ERROR
        msg = str(e)
        LAST_CHECK_NET_ERROR = bool(re.search(
            r"ERR_INTERNET_DISCONNECTED|ERR_NAME_NOT_RESOLVED|ERR_NETWORK|ERR_CONNECTION|"
            r"ERR_ADDRESS_UNREACHABLE|ERR_TIMED_OUT|Timeout .*exceeded", msg))
        if LAST_CHECK_NET_ERROR:
            log(f"세션 확인 불가 — 인터넷 연결 문제({msg[:60]}). 로그인 만료가 아닙니다")
        else:
            log(f"세션 확인 실패({msg[:60]}) — 만료로 간주")
        return False


def load_meta() -> dict:
    if os.path.exists(config.BLOG_META_FILE):
        with open(config.BLOG_META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_meta(meta: dict) -> None:
    with open(config.BLOG_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _has_auth_cookie(context) -> bool:
    for c in context.cookies():
        if c.get("name") in ("NID_AUT", "NID_SES") and "naver.com" in c.get("domain", ""):
            return True
    return False


def _extract_blog_id(page, log: Logger) -> str | None:
    """로그인 상태에서 내 블로그 아이디 추출."""
    try:
        page.goto(MYBLOG_URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        url = page.url
        m = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)", url)
        if m and m.group(1) not in ("MyBlog.naver", "PostList.naver"):
            log(f"blogId 감지: {m.group(1)}")
            return m.group(1)
    except Exception as e:  # noqa: BLE001
        log(f"blogId 추출 실패: {e}")
    return None


def login_and_save(log: Logger = _noop, timeout_sec: int = 300) -> dict:
    """헤드리스 아닌 창을 띄워 사용자가 직접 로그인하게 하고, 세션을 저장한다.

    반환: {"ok":bool, "blog_id":str|None, "message":str}
    """
    log("로그인 창을 띄웁니다. 열린 창에서 네이버에 직접 로그인하세요.")
    with sync_playwright() as p:
        # ★업로드가 쓰는 브라우저(실제 Chrome + 전용 프로필)에 그대로 로그인해야
        #   그 프로필에 세션이 남아 다음부터 자동으로 들어간다(2026-08-03).
        context, _close = open_browser(p, log, headless=False, require_login=False)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            log(f"로그인 페이지 로딩 오류: {e}")

        # ★'로그인 상태 유지'를 코드가 켠다(2026-08-12). 사장님이 체크를 잊으면 쿠키가
        #   **세션쿠키**로 저장돼 며칠 만에 죽는다 — 반복 재로그인의 진짜 원인이었다.
        #   화면을 다시 그리면 꺼지기도 하고, '로그인'을 누르는 순간에 꺼져 있으면 의미가 없으므로
        #   **기다리는 내내 매번 다시 켠다**(체험단 도구에서 검증된 방식).
        def _ensure_keep():
            try:
                return page.evaluate(
                    """() => {
                        const k = document.querySelector('#keep') || document.querySelector('input[name=nvlong]');
                        if (!k) return null;
                        if (!k.checked) {
                            (document.querySelector('label[for=keep], .keep_check') || k).click();
                            if (!k.checked) { k.checked = true; k.dispatchEvent(new Event('change', {bubbles:true})); }
                        }
                        return k.checked;
                    }"""
                )
            except Exception:  # noqa: BLE001
                return None

        page.wait_for_timeout(800)
        log(f"'로그인 상태 유지' 자동 체크 → {_ensure_keep()} (로그인 누를 때까지 계속 켜 둡니다)")
        deadline = time.time() + timeout_sec
        logged = False
        while time.time() < deadline:
            _ensure_keep()
            if _has_auth_cookie(context) and "nidlogin" not in page.url:
                logged = True
                break
            time.sleep(1.5)

        if not logged:
            _close()
            log("시간 내 로그인이 완료되지 않았습니다.")
            return {"ok": False, "blog_id": None, "message": "로그인 시간 초과"}

        log("로그인 감지됨. 세션을 저장합니다.")
        blog_id = _extract_blog_id(page, log)
        # 🔴 계정 확인(2026-08-12): 다른 네이버 계정으로 로그인하면 **저장하지 않는다**.
        #    한 번 잘못 저장되면 새벽 배치가 엉뚱한 블로그에 8편을 올린다(config.EXPECT_BLOG_ID 주석 참고).
        _expect = getattr(config, "EXPECT_BLOG_ID", "")
        if _expect and blog_id and blog_id != _expect:
            _close()
            msg = (f"다른 계정으로 로그인했습니다(blogId: {blog_id}). "
                   f"이 자동화는 '{_expect}' 전용입니다 — 세션을 저장하지 않았습니다. "
                   f"네이버에서 로그아웃하고 에디 계정으로 다시 로그인하세요.")
            log("[중단] " + msg)
            return {"ok": False, "blog_id": blog_id, "message": msg}
        # ★관리자 통계(admin.blog.naver.com) 쿠키까지 확보한다(2026-08-03).
        #   조회수는 통계 페이지에만 있는데, blog.naver.com 쿠키만으로는 admin이 로그인 페이지로 튕긴다.
        #   로그인 상태에서 통계 페이지를 한 번 방문하면 그 도메인 쿠키가 세션에 담긴다.
        try:
            page.goto(f"https://admin.blog.naver.com/{blog_id or ''}/stat/today",
                      wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3500)
            log("통계(관리) 페이지 접근 " + ("성공" if "nidlogin" not in page.url else "실패 — 조회수 수집 제한"))
        except Exception as e:  # noqa: BLE001
            log(f"통계 페이지 방문 생략({str(e)[:50]})")
        context.storage_state(path=config.SESSION_FILE)
        _save_meta({"blog_id": blog_id})
        _close()
        return {
            "ok": True,
            "blog_id": blog_id,
            "message": "로그인 세션을 저장했습니다." + (f" (blogId: {blog_id})" if blog_id else ""),
        }


# ---------------------------------------------------------------------------
# 스마트에디터 ONE — 임시저장
# ---------------------------------------------------------------------------

WRITE_URL_TMPL = "https://blog.naver.com/{blog_id}?Redirect=Write&"

# 후보 셀렉터들 (네이버가 클래스명을 자주 바꾸므로 여러 개 시도)
SEL_TITLE = [
    ".se-section-documentTitle .se-text-paragraph",
    ".se-documentTitle .se-text-paragraph",
    'span[data-placeholder="제목"]',
]
SEL_BODY = [
    ".se-section-text .se-text-paragraph",
    ".se-component-content .se-text-paragraph",
    ".se-content",
]
SEL_IMAGE_BTN = [
    'button.se-image-toolbar-button',
    'button[data-name="image"]',
    'button[data-log="toolbar.image"]',
    'button:has-text("사진")',
]
# 상단 툴바의 '보이는' 인용구 버튼(클릭 시 기본 66 박스 인용 삽입)
SEL_QUOTE_BTN = [
    'button[data-name="quotation"].se-document-toolbar-icon-select-button',
    'button.se-document-toolbar-icon-select-button[data-name="quotation"]',
    'button[data-name="quotation"]',
]
# 인용 블록 탈출용: 캔버스 하단 빈 영역 클릭 대상
SEL_CANVAS = [".se-content", ".se-container-content", ".se-viewer"]

# 강조(굵게+색상) 관련
SEL_BOLD_BTN = "button.se-bold-toolbar-button"
SEL_FONTCOLOR_BTN = "button.se-font-color-toolbar-button, [class*='se-font-color-toolbar']"
EMPH_RED = "rgb(255, 0, 16)"        # 팔레트 빨강(강점 키워드)
EMPH_BLACK = "rgb(0, 0, 0)"         # 기본 검정(리셋용)
EMPH_YELLOW_BG = "rgb(255, 245, 147)"  # 중요 문장 노랑 배경 하이라이트
SEL_BGCOLOR_BTN = "button.se-background-color-toolbar-button, [class*='se-background-color-toolbar']"
SEL_SAVE_BTN = [
    'button.save_btn__bzc5B',
    'button[data-click-area="tpb.save"]',
    'button:has-text("저장")',
]
SEL_CANCEL_POPUP = [
    'button.se-popup-button-cancel',
    '.se-popup-button-cancel',
    'button:has-text("취소")',
]


def _first_visible(frame, selectors, timeout=4000):
    for sel in selectors:
        try:
            loc = frame.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:  # noqa: BLE001
            continue
    return None


def _get_editor_frame(page, log: Logger):
    """mainFrame(iframe) 안에서 에디터를 찾는다. 없으면 page 자체 반환."""
    try:
        page.wait_for_selector("iframe#mainFrame", timeout=15000)
        frame = page.frame(name="mainFrame")
        if frame:
            return frame
    except Exception:  # noqa: BLE001
        pass
    log("mainFrame iframe을 찾지 못해 최상위 문서에서 진행합니다.")
    return page


def _dismiss_popups(frame, page, log: Logger):
    """이어쓰기/도움말 팝업 닫기."""
    for target in (frame, page):
        btn = None
        for sel in SEL_CANCEL_POPUP:
            try:
                loc = target.locator(sel).first
                if loc.is_visible(timeout=1500):
                    btn = loc
                    break
            except Exception:  # noqa: BLE001
                continue
        if btn:
            try:
                btn.click()
                log("이전 작성 글 팝업을 닫았습니다(새 글 작성).")
                page.wait_for_timeout(500)
            except Exception:  # noqa: BLE001
                pass
    # 진입 단계에서는 DOM을 건드리지 않고 ESC로만 시도(에디터 영역 보존)
    try:
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass


def _close_help_panel(frame, page, log: Logger):
    """저장 버튼을 가리는 '도움말' 패널을 닫는다(버튼 클릭 → ESC → JS 강제 숨김)."""
    close_selectors = [
        "button.se-help-panel-close-button",
        ".se-help-panel-close-button",
        ".se-help-panel button[class*='close']",
        "button[class*='help'][class*='close']",
    ]
    for sel in close_selectors:
        try:
            loc = frame.locator(sel).first
            if loc.is_visible(timeout=800):
                loc.click()
                page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass
    # 그래도 남아 있으면 '도움말 패널만' 콕 집어 숨긴다(에디터 본문/제목은 건드리지 않음).
    try:
        frame.evaluate(
            """() => {
                const kill = (el) => { if (el) { el.style.display='none'; el.style.pointerEvents='none'; } };
                document.querySelectorAll('.se-help-panel').forEach(kill);
                // 도움말 제목의 '가장 가까운 container 조상'만 숨김(상위 에디터까지 올라가지 않음)
                document.querySelectorAll('.se-help-title').forEach(h => {
                    kill(h.closest('[class*=\\"container\\"]'));
                });
            }"""
        )
    except Exception:  # noqa: BLE001
        pass


def _type_caption(frame, page, text: str, log: Logger, label: str) -> bool:
    """방금 넣은 이미지의 **캡션 칸**(사진 설명)에 글을 넣는다 (2026-09-13 에디님 지시).

    에디님: "출처를 이미지 밑 문단이 아니라 이미지에 적어야 되는데. 이미지 클릭하면 밑에 쓸 수 있게 나오거든."
    ★캡션 칸(`div.se-caption`)은 **이미지를 클릭하기 전엔 크기가 0**이라 바로 클릭할 수 없다(실측).
      순서: 이미지 클릭 → 캡션 열림(886×23) → 캡션 클릭 → 타이핑.
    ★타이핑 뒤 **본문 끝으로 돌아와야** 다음 문장이 캡션에 이어 붙지 않는다(실측으로 확인한 복귀 경로).
    """
    try:
        frame.locator(".se-component.se-image img").last.click(timeout=5000)
        page.wait_for_timeout(600)
        frame.locator("div.se-caption").last.click(timeout=4000)
        page.wait_for_timeout(250)
        page.keyboard.type(text, delay=18)
        page.wait_for_timeout(350)
    except Exception as e:  # noqa: BLE001
        log(f"[{label}] 캡션 입력 실패(사진은 그대로): {str(e)[:70]}")
        return False
    try:                     # 본문 끝으로 복귀
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        frame.locator(".se-component.se-text .se-text-paragraph").last.click(timeout=4000)
        page.wait_for_timeout(150)
        page.keyboard.press("Meta+ArrowDown")
    except Exception:  # noqa: BLE001
        pass
    return True


def _insert_image(frame, page, path: str, log: Logger, label: str, caption: str = "") -> bool:
    btn = _first_visible(frame, SEL_IMAGE_BTN, timeout=3000)
    if not btn:
        log(f"[{label}] 사진 버튼을 찾지 못함 → 건너뜀")
        return False
    try:
        with page.expect_file_chooser(timeout=8000) as fc_info:
            btn.click()
        fc_info.value.set_files(path)
        # 업로드 반영 대기
        page.wait_for_timeout(2500)
        log(f"[{label}] 이미지 삽입")
        if caption:
            if _type_caption(frame, page, caption, log, label):
                log(f"[{label}] 캡션: {caption[:30]}")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"[{label}] 이미지 삽입 실패: {e}")
        return False


def _mark_all_ai(frame, page, log: Logger) -> bool:
    """삽입된 이미지가 모두 AI 생성물이므로 각 이미지의 'AI 활용 설정' 토글을 켠다.

    2026-07-24 실측: '전체활용' 같은 일괄 버튼은 없고, 이미지마다
    `button.se-set-ai-mark-button-toggle`(기본 OFF)이 있다. 이미지를 선택하면 그 토글이
    보이므로, 모든 이미지를 순회하며 OFF인 것만 켠다(이미 ON이면 두어 끄지 않게 함).
    베스트 에포트 — 실패해도 임시저장은 정상 진행.
    """
    imgs = frame.locator(".se-component.se-image")
    try:
        n = imgs.count()
    except Exception:  # noqa: BLE001
        n = 0
    if not n:
        return False

    # ── 빠른 길: 이미지 하나 선택 → 상단 툴바의 '전체AI활용' 한 번(2026-07-24 에디님 제보) ──
    try:
        first = imgs.first
        first.scroll_into_view_if_needed(timeout=2000)
        first.click(timeout=3000)
        page.wait_for_timeout(500)
        did_all = frame.evaluate(
            """() => {
                const norm = s => (s||'').replace(/\\s+/g,'');
                const vis = e => e && e.offsetParent !== null;
                const el = Array.from(document.querySelectorAll('button,a,span,div[role=button]'))
                    .find(e => vis(e) && ['전체AI활용','전체 AI활용'].includes(norm(e.textContent)));
                if(el){ (el.closest('button')||el).click(); return true; }
                return false;
            }""")
        if did_all:
            page.wait_for_timeout(500)
            frame.evaluate(
                """() => {
                    const norm = s => (s||'').replace(/\\s+/g,'');
                    const b = Array.from(document.querySelectorAll('button')).find(x =>
                        ['확인','적용','설정','표시'].includes(norm(x.textContent)) && x.offsetParent);
                    if(b) b.click();
                }""")
            log(f"AI 활용 표기: '전체AI활용'로 {n}개 일괄 처리.")
            page.wait_for_timeout(300)
            return True
    except Exception as e:  # noqa: BLE001
        log(f"전체AI활용 빠른 처리 실패 → 개별 토글로 진행: {str(e)[:80]}")

    # ── 폴백: 이미지마다 토글 ON(이미 켜진 건 건너뜀 → 위 전체처리와 겹쳐도 안전) ──
    on_cnt = 0
    for i in range(n):
        try:
            comp = imgs.nth(i)
            comp.scroll_into_view_if_needed(timeout=2000)
            comp.click(timeout=3000)          # 이미지 선택 → 토글 노출
            page.wait_for_timeout(300)
            # 현재 선택된 이미지에서 보이는 AI 표기 토글을 찾아 OFF면 켠다
            state = frame.evaluate(
                """() => {
                    const vis = e => e && e.offsetParent !== null;
                    const t = Array.from(document.querySelectorAll('.se-set-ai-mark-button-toggle'))
                                   .find(vis);
                    if(!t) return 'notfound';
                    const cont = t.closest('.se-set-ai-mark-button') || t;
                    const on = /is-selected|is-on|se-is-active|is-checked/.test(cont.className)
                        || t.getAttribute('aria-pressed') === 'true'
                        || t.getAttribute('aria-checked') === 'true';
                    if(on) return 'already-on';
                    (t.closest('button') || t).click();
                    return 'turned-on';
                }""")
            page.wait_for_timeout(250)
            # ★상태 재확인(2026-08-02): 'already-on' 오판정이면 실제로는 꺼진 채 로그만 ON으로 남는다
            #   (에디님: "AI 활용이 왜 하나도 안 되어 있어?"). 켜졌는지 다시 읽고, 아니면 한 번 더 누른다.
            verify = frame.evaluate(
                """() => {
                    const vis = e => e && e.offsetParent !== null;
                    const t = Array.from(document.querySelectorAll('.se-set-ai-mark-button-toggle'))
                                   .find(vis);
                    if(!t) return 'notfound';
                    const cont = t.closest('.se-set-ai-mark-button') || t;
                    const on = /is-selected|is-on|se-is-active|is-checked/.test(cont.className)
                        || t.getAttribute('aria-pressed') === 'true'
                        || t.getAttribute('aria-checked') === 'true'
                        || (t.querySelector('input[type=checkbox]') || {}).checked === true;
                    if(on) return 'on';
                    (t.closest('button') || t).click();   // 아직 꺼져 있으면 한 번 더
                    return 'retried';
                }""")
            if state == "turned-on" or verify in ("on", "retried"):
                on_cnt += 1
            page.wait_for_timeout(200)
            # 첫 토글 시 확인/안내 팝업이 뜨면 확인
            frame.evaluate(
                """() => {
                    const norm = s => (s||'').replace(/\\s+/g,'');
                    const b = Array.from(document.querySelectorAll('button')).find(x =>
                        ['확인','적용','설정','표시'].includes(norm(x.textContent)) && x.offsetParent);
                    if(b) b.click();
                }""")
            page.wait_for_timeout(150)
        except Exception as e:  # noqa: BLE001
            log(f"[이미지{i+1}] AI 표기 토글 실패(건너뜀): {str(e)[:80]}")
    if on_cnt:
        log(f"AI 활용 표기: 이미지 {on_cnt}/{n}개 토글 ON.")
        return True
    log("AI 활용 토글을 찾지 못함 — 이미지에서 직접 표기 필요.")
    return False


def _exit_block_via_bottom_click(frame, page) -> bool:
    """방금 삽입된 마지막 컴포넌트(인용/카드) 아래 빈 캔버스를 클릭해 '새 본문 단락'으로
    caret 이동(컴포넌트 탈출). 말풍선 인용은 아래 꼬리가 있어 '바로 아래'는 꼬리에 맞으므로,
    컴포넌트를 화면 '가운데'로 스크롤해 아래 여백을 확보한 뒤 충분히 아래(꼬리 밑)를 클릭한다."""
    try:
        last = frame.locator(".se-component").last
        last.evaluate("el => el.scrollIntoView({block:'center'})")
        page.wait_for_timeout(200)
        box = last.bounding_box()
        vp = page.viewport_size or {"height": 800}
        if box:
            # 꼬리(약 20~30px)까지 확실히 지나도록 아래로 충분히, 뷰포트 안으로 클램프
            y = min(box["y"] + box["height"] + 30, vp["height"] - 10)
            page.mouse.click(box["x"] + box["width"] / 2, y)
            page.wait_for_timeout(300)
            return True
    except Exception:  # noqa: BLE001
        pass
    # 폴백: 캔버스 하단
    for sel in SEL_CANVAS:
        try:
            box = frame.locator(sel).last.bounding_box()
            if box and box["height"] > 40:
                vp = page.viewport_size or {"height": 800}
                y = min(box["y"] + box["height"] - 8, vp["height"] - 10)
                page.mouse.click(box["x"] + box["width"] / 2, y)
                page.wait_for_timeout(300)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _reset_formatting(frame, page, log: Logger) -> None:
    """에디터에 남아 있는 서식 토글(굵게/기울임/밑줄/취소선)이 켜져 있으면 끈다.
    (이전 드래프트 잔재로 취소선 등이 켜진 채 시작되는 경우가 있음.)"""
    for name in ("bold", "italic", "underline", "strikethrough"):
        try:
            btn = frame.locator(f"button.se-{name}-toolbar-button").first
            cls = btn.get_attribute("class") or ""
            if "se-is-selected" in cls:
                btn.click()
                page.wait_for_timeout(120)
                log(f"서식 초기화: {name} 해제")
        except Exception:  # noqa: BLE001
            pass


def _toggle_bold(frame, page) -> None:
    try:
        frame.locator(SEL_BOLD_BTN).first.click(timeout=2000)
        page.wait_for_timeout(120)
    except Exception:  # noqa: BLE001
        pass


def _set_font_color(frame, page, rgb: str) -> None:
    """색상 버튼 열고 지정 rgb 스와치 클릭."""
    try:
        frame.locator(SEL_FONTCOLOR_BTN).first.click(timeout=2000)
        page.wait_for_timeout(300)
        clicked = frame.evaluate(
            """(rgb) => {
                const btns=[...document.querySelectorAll('button.se-color-palette, .se-color-palette button, button[class*=color-palette]')];
                const t=btns.find(b => ((b.getAttribute('style')||'').replace(/\\s+/g,'')).includes(rgb.replace(/\\s+/g,'')));
                if(t){ t.click(); return true; } return false;
            }""", rgb)
        page.wait_for_timeout(200)
        if not clicked:
            # 팔레트 닫기(못 찾으면 ESC)
            page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass


def _set_bg_color(frame, page, rgb: str) -> None:
    try:
        frame.locator(SEL_BGCOLOR_BTN).first.click(timeout=2000)
        page.wait_for_timeout(300)
        clicked = frame.evaluate(
            """(rgb) => { const bs=[...document.querySelectorAll('button.se-color-palette, .se-color-palette button, button[class*=color-palette]')];
                const t=bs.find(b=>((b.getAttribute('style')||'').replace(/\\s+/g,'')).includes(rgb.replace(/\\s+/g,'')));
                if(t){t.click();return true;} return false; }""", rgb)
        page.wait_for_timeout(200)
        if not clicked:
            page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass


def _clear_bg_color(frame, page) -> None:
    try:
        frame.locator(SEL_BGCOLOR_BTN).first.click(timeout=2000)
        page.wait_for_timeout(300)
        clicked = frame.evaluate(
            """() => { const b=[...document.querySelectorAll('button')].find(x=>(x.textContent||'').trim()==='색상 없음' && (x.offsetParent||x.getClientRects().length));
                if(b){b.click();return true;} return false; }""")
        page.wait_for_timeout(200)
        if not clicked:
            page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass


def _type_rich(frame, page, text: str, spans: list, log: Logger) -> None:
    """text를 타이핑하되 spans의 서식을 적용.
    spans: [(start, end, {"bold":True, "color":rgb, "bg":rgb}), ...] (겹침 허용)
      - 강점 키워드: bold+color(빨강)
      - 중요 문장: bg(노랑) + 그 안 키워드 bold
    상태를 추적해 필요한 순간에만 서식 토글(팔레트 클릭 최소화)."""
    if not spans:
        page.keyboard.type(text, delay=18)
        return
    n = len(text)

    def attrs_at(i):
        bold = False
        color = EMPH_BLACK
        bg = None
        for s, e, a in spans:
            if s <= i < e:
                if a.get("bold"):
                    bold = True
                if a.get("color"):
                    color = a["color"]
                if a.get("bg"):
                    bg = a["bg"]
        return bold, color, bg

    pts = {0, n}
    for s, e, _a in spans:
        pts.add(max(0, min(s, n)))
        pts.add(max(0, min(e, n)))
    pts = sorted(pts)

    cur_bold, cur_color, cur_bg = False, EMPH_BLACK, None
    for j in range(len(pts) - 1):
        a, b_ = pts[j], pts[j + 1]
        seg = text[a:b_]
        if not seg:
            continue
        w_bold, w_color, w_bg = attrs_at(a)
        if w_bg != cur_bg:
            if w_bg:
                _set_bg_color(frame, page, w_bg)
            else:
                _clear_bg_color(frame, page)
            cur_bg = w_bg
        if w_color != cur_color:
            _set_font_color(frame, page, w_color)
            cur_color = w_color
        if w_bold != cur_bold:
            _toggle_bold(frame, page)
            cur_bold = w_bold
        page.keyboard.type(seg, delay=18)
    # 리셋
    if cur_bold:
        _toggle_bold(frame, page)
    if cur_bg:
        _clear_bg_color(frame, page)
    if cur_color != EMPH_BLACK:
        _set_font_color(frame, page, EMPH_BLACK)


def _insert_quote(frame, page, text: str, log: Logger, style: str = "default") -> bool:
    """인용구 컴포넌트를 삽입하고 text(굵게)를 넣은 뒤, 스타일을 적용하고 하단클릭으로 탈출.

    - 인용 블록이 뒤 문단을 삼키지 않도록 '삽입→타이핑→(스타일)→하단클릭' 순서.
    - 인용구 안 글자는 모두 굵게.
    - style: default(66박스) / quotation_line / quotation_bubble / quotation_underline
             / quotation_postit / quotation_corner
    """
    btn = None
    for sel in SEL_QUOTE_BTN:
        try:
            loc = frame.locator(sel).first
            if loc.is_visible(timeout=1500):
                btn = loc
                break
        except Exception:  # noqa: BLE001
            continue
    if not btn:
        return False
    try:
        btn.click()
        page.wait_for_timeout(600)
        # 인용구 안 글자는 모두 굵게
        _toggle_bold(frame, page)
        # 여러 줄이면 줄 사이를 Shift+Enter(줄바꿈)로 넣는다 — 그냥 Enter는 인용구 밖(출처 칸)으로
        #   빠질 수 있다(2026-09-19, Tom 방식 제목 인용구 두 줄). 한 줄이면 종전과 같다.
        for _i, _ln in enumerate((text or "").split("\n")):
            if _i:
                page.keyboard.press("Shift+Enter")
            page.keyboard.type(_ln, delay=18)
        _toggle_bold(frame, page)
        page.wait_for_timeout(200)
        # 스타일 변경(기본이 아니면 플로팅 툴바에서 선택)
        if style and style != "default":
            try:
                sbtn = frame.locator(f"button.se-quotation-{style}-toolbar-button").first
                if sbtn.is_visible(timeout=1500):
                    sbtn.click()
                    page.wait_for_timeout(400)
            except Exception:  # noqa: BLE001
                pass
        if not _exit_block_via_bottom_click(frame, page):
            page.keyboard.press("ArrowDown")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"인용구 삽입 실패: {str(e)[:120]}")
        return False


def _enter_tags(frame, page, tags: list, log: Logger) -> None:
    """발행 팝업의 태그 입력칸(#tag-input)에 태그들을 넣는다(각각 Enter)."""
    if not tags:
        return
    try:
        inp = frame.locator("input#tag-input, input.tag_input__rvUB5").first
        inp.click()
        page.wait_for_timeout(200)
        for tg in tags[:30]:
            inp.type(tg, delay=10)
            page.keyboard.press("Enter")
            page.wait_for_timeout(180)
        log(f"태그 {len(tags[:30])}개를 태그편집에 입력")
    except Exception as e:  # noqa: BLE001
        log(f"태그 입력 실패: {str(e)[:100]}")


def _select_category(frame, page, category: str, log: Logger) -> bool:
    """발행 팝업 안의 '카테고리' 셀렉트에서 지정 카테고리를 고른다.

    ★ 베스트 에포트: 실패해도 예외를 던지지 않는다(카테고리만 기본값으로 남고 임시저장은 정상 진행).
    스마트에디터 ONE은 클래스명에 해시가 붙어 자주 바뀌므로 후보 셀렉터 + 텍스트 매칭으로 방어한다.
    """
    name = (category or "").strip()
    if not name:
        return False
    try:
        # 1) 카테고리 드롭다운 열기 (발행 팝업의 첫 selectbox가 카테고리)
        opened = False
        for sel in ['button[class*="selectbox_button"]',
                    'button[class*="categorySelect"]',
                    '.selectbox_button',
                    'button:has-text("카테고리")']:
            try:
                btn = frame.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click(timeout=2500)
                    page.wait_for_timeout(600)
                    opened = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not opened:
            log(f"카테고리 '{name}': 드롭다운을 열지 못함(기본 카테고리로 저장).")
            return False

        # 2) 목록에서 이름이 정확히 일치하는 항목 클릭
        for sel in (f'label:text-is("{name}")',
                    f'li[class*="selectbox"] >> text="{name}"',
                    f'button:text-is("{name}")',
                    f'span:text-is("{name}")',
                    f'a:text-is("{name}")'):
            try:
                item = frame.locator(sel).first
                if item.is_visible(timeout=1500):
                    item.click(timeout=2500)
                    page.wait_for_timeout(500)
                    log(f"카테고리 '{name}' 선택 완료.")
                    return True
            except Exception:  # noqa: BLE001
                continue

        # 🔴2026-09-09 사고: «지난기수»·«33기»를 지정했는데 상위 칸 «나는솔로»에 저장됐다.
        #   하위 칸은 드롭다운에서 들여쓰기·아이콘과 함께 렌더돼 `text-is`(정확일치)가 안 걸린 것으로
        #   보인다. → 정확일치가 실패하면 **부분일치**로 한 번 더 시도한다.
        #   ⚠️부분일치는 «33기»가 «133기»에 걸릴 수 있으니 **정확일치 뒤에만** 쓴다.
        for sel in (f'label:has-text("{name}")', f'li:has-text("{name}")',
                    f'span:has-text("{name}")', f'a:has-text("{name}")'):
            try:
                item = frame.locator(sel).last
                if item.is_visible(timeout=1200):
                    item.click(timeout=2500)
                    page.wait_for_timeout(500)
                    log(f"카테고리 '{name}' 선택 완료(부분일치).")
                    return True
            except Exception:  # noqa: BLE001
                continue
        log(f"🔴[경고] 카테고리 '{name}'을 목록에서 찾지 못했습니다 — **기본 카테고리로 저장됩니다.**")
        page.keyboard.press("Escape")  # 드롭다운만 닫음
        page.wait_for_timeout(300)
        return False
    except Exception as e:  # noqa: BLE001
        log(f"카테고리 선택 실패(무시하고 저장 진행): {str(e)[:120]}")
        return False


def _insert_shopping_connect(frame, page, query: str, log: Logger) -> bool:
    """본문 커서 자리에 '쇼핑커넥트' 상품 카드를 삽입한다.
    툴바 쇼핑커넥트 버튼 → 검색창에 제품명 → 검색 → 첫(관련도순) 상품 선택 → 확인.
    쿠팡이 아닌 네이버 쇼핑커넥트(naver.me) 제휴 링크가 카드로 붙는다.
    """
    q = (query or "").strip()
    if not q:
        return False
    try:
        # 1) 툴바 쇼핑커넥트 버튼
        clicked = False
        for bsel in ('button[data-name="shopping-connect"]', "button.se-shopping-connect-toolbar-button"):
            loc = frame.locator(bsel).first
            if loc.count():
                loc.scroll_into_view_if_needed(timeout=3000)
                loc.click(timeout=5000)
                clicked = True
                break
        if not clicked:
            log(f"쇼핑커넥트 버튼을 찾지 못함 — 건너뜀: {q}")
            return False
        page.wait_for_timeout(1500)

        # 2) 검색창에 제품명 입력 + 검색
        inp = frame.locator("input.se-popup-search-input").first
        inp.click()
        inp.fill(q)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")

        # 3) 결과 대기 → 첫 상품(관련도순) 선택
        try:
            frame.wait_for_selector("li.se-shopping-connect-item", timeout=9000, state="visible")
        except Exception:  # noqa: BLE001
            log(f"쇼핑커넥트 검색 결과 없음: {q}")
            try: page.keyboard.press("Escape")
            except Exception: pass
            return False
        # 링크로 걸릴 실제 상품명을 먼저 읽어 로그로 남긴다(본문 설명과 일치 확인용)
        item = frame.locator("li.se-shopping-connect-item").first
        picked = ""
        try:
            import re as _re
            picked = (item.inner_text(timeout=2000) or "").replace("\n", " ")
            picked = _re.sub(r"수수료\s*\d+%", "", picked)
            picked = _re.sub(r"\s+", " ", picked).strip()[:60]
        except Exception:  # noqa: BLE001
            pass
        item.click(timeout=4000)
        page.wait_for_timeout(700)

        # 4) 확인/추가 버튼
        confirmed = False
        for csel in ("button.se-popup-button-confirm", ".se-popup-button-confirm"):
            c = frame.locator(csel).first
            if c.count() and c.is_visible():
                c.click(timeout=3000)
                confirmed = True
                break
        page.wait_for_timeout(1800)

        # 5) 삽입된 카드 아래 본문 단락으로 caret 이동(다음 블록 이어쓰기)
        _exit_block_via_bottom_click(frame, page)
        log(f"쇼핑커넥트 상품 삽입 → 링크제품: [{picked or '(제목확인불가)'}] (검색어: {q}, 관련도 1위)")
        return confirmed
    except Exception as e:  # noqa: BLE001
        log(f"쇼핑커넥트 삽입 실패({q}): {str(e)[:120]}")
        try: page.keyboard.press("Escape")
        except Exception: pass
        return False


def _clear_alert(frame, page, log: Logger) -> str:
    """편집기 경고창(se-popup-alert)이 떠 있으면 **내용을 기록하고** 확인을 눌러 닫는다.

    🔴2026-09-10 사고: 표를 붙여넣은 직후 경고창이 떴고, 그 흐린 막(se-popup-dim)이 이후
      **모든 클릭**(사진·인용구·AI표기·태그)을 가로막았다. 확정 버튼만 JS로 눌려
      「예약 발행 완료」를 반환했지만 아무것도 안 만들어졌다. 경고창은 시작할 때만 닫고 있었다.
      → 블록마다, 그리고 표 붙여넣기 직후에 확인한다. 무슨 경고였는지도 남긴다(원인 추적용).
    """
    try:
        # 🔴무조건 「확인」을 누르면 안 된다(2026-09-10 실측). 편집기를 열 때 뜨는
        #   「작성 중인 글이 있습니다 … 이어서 작성하시겠습니까? [취소][확인]」에서 확인을 누르면
        #   **실패한 옛 업로드의 반쪽 글**을 불러와 그 위에 새 글을 덧쓴다.
        #   → 이어쓰기 창은 취소(새 글) / 버튼 하나짜리 알림은 확인 / **모르는 확인창은 취소**
        #     (모르는 걸 수락하지 않는다 — 문구는 로그에 남겨 다음에 규칙을 더한다).
        res = frame.evaluate("""() => {
            const a = Array.from(document.querySelectorAll('.se-popup-alert, [data-name^="se-popup-alert"]'))
                .find(e => e.offsetParent !== null);
            if (!a) return null;
            const t = (a.innerText || '').replace(/\\s+/g, ' ').trim();
            const ok = a.querySelector('button.se-popup-button-confirm');
            const no = a.querySelector('button.se-popup-button-cancel');
            let act;
            if (/이어서\\s*작성|작성\\s*중인\\s*글/.test(t) && no) { no.click(); act = '취소(새 글)'; }
            else if (!no && ok) { ok.click(); act = '확인(알림)'; }
            else if (no) { no.click(); act = '취소(모르는 확인창)'; }
            else { const b = a.querySelector('button'); if (b) b.click(); act = '닫기'; }
            return {t: t || '(내용 없음)', act};
        }""")
    except Exception:  # noqa: BLE001
        return ""
    if res:
        log(f"🔴 편집기 경고창: «{res['t'][:90]}» → {res['act']}")
        page.wait_for_timeout(800)
        return res["t"]
    return ""


def _clear_alert_wait(frame, page, log: Logger, wait_ms: int = 6000) -> None:
    """편집기를 연 직후 **늦게 뜨는** 경고창까지 기다렸다 처리한다.

    2026-09-10: 「이어서 작성?」 창이 `_dismiss_popups`의 1.5초 확인보다 늦게 떠서 놓쳤고,
    그 창이 제목·본문 클릭을 막아 업로드가 예외로 죽었다.
    """
    step = 500
    for _ in range(max(1, wait_ms // step)):
        if _clear_alert(frame, page, log):
            return
        page.wait_for_timeout(step)


def _paste_table(frame, page, html_path: str, log: Logger) -> bool:
    """표 HTML을 클립보드로 붙여넣어 네이버 '네이티브 표'(텍스트 표)로 삽입."""
    import re as _re
    try:
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        m = _re.search(r"<table.*?</table>", html, _re.S)
        if not m:
            return False
        table_html = m.group(0)
        page.evaluate(
            """async (html) => { const blob=new Blob([html],{type:'text/html'});
               await navigator.clipboard.write([new ClipboardItem({'text/html': blob})]); }""",
            table_html)
        page.wait_for_timeout(400)
        page.keyboard.press("Meta+v")
        page.wait_for_timeout(2800)
        _clear_alert(frame, page, log)              # 붙여넣기 직후 경고창이 뜬 적이 있다(2026-09-10)
        _exit_block_via_bottom_click(frame, page)   # 표 컴포넌트 아래 본문으로 탈출
        log("표를 텍스트 표로 붙여넣음")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"표 붙여넣기 실패: {str(e)[:120]}")
        return False


def _insert_oglink(frame, page, url: str, log: Logger) -> bool:
    """네이버 '링크' 버튼으로 URL 링크 카드를 삽입(깔끔한 카드만 남김) 후 하단클릭 탈출.

    미리보기 로드가 느릴 수 있어 '확인' 버튼이 활성화될 때까지 폴링(최대 ~14초)한다.
    """
    try:
        # 팝업이 열릴 때까지 버튼 재클릭 + 폴링(첫 클릭에 안 열리는 경우 대비)
        opened = False
        for _attempt in range(3):
            try:
                frame.locator("button.se-oglink-toolbar-button").first.click(timeout=3000)
            except Exception:  # noqa: BLE001
                pass
            for _ in range(6):            # ~3초 대기하며 input 등장 확인
                page.wait_for_timeout(500)
                loc = frame.locator("input.se-popup-oglink-input").first
                if loc.count() and loc.is_visible():
                    opened = True
                    break
            if opened:
                break
        if not opened:
            log(f"링크 팝업이 열리지 않아 건너뜀: {url}")
            try:
                shot = os.path.join(config.WORK_DIR, "oglink_fail.png")
                page.screenshot(path=shot)
                log(f"  (진단 스크린샷: {shot})")
            except Exception:  # noqa: BLE001
                pass
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return False
        inp = frame.locator("input.se-popup-oglink-input").first
        inp.click()
        inp.fill(url)
        page.wait_for_timeout(400)
        page.keyboard.press("Enter")      # 미리보기 로드 트리거
        # 확인 버튼이 활성화될 때까지 폴링
        enabled = False
        for _ in range(28):               # ~14초
            page.wait_for_timeout(500)
            dis = frame.evaluate(
                "() => { const b=document.querySelector('button.se-popup-button-confirm'); return b ? b.disabled : null; }")
            if dis is False:
                enabled = True
                break
        if not enabled:
            page.keyboard.press("Escape")
            log(f"링크 미리보기 실패로 건너뜀: {url}")
            return False
        frame.evaluate(
            "() => { const b=document.querySelector('button.se-popup-button-confirm'); if(b && !b.disabled) b.click(); }")
        page.wait_for_timeout(3000)       # 카드 렌더 대기
        _exit_block_via_bottom_click(frame, page)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"링크 카드 삽입 실패: {str(e)[:120]}")
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        return False


def save_draft(title: str, blocks: list[dict], thumb_path: str | None,
               log: Logger = _noop, publish: bool = False,
               category: str = "", reserve_at=None, align: str = "",
               ai_mark: bool = True) -> dict:
    """저장된 세션으로 글쓰기 → 본문 구성 → 임시저장(publish=True면 공개 발행).

    category: 지정하면 발행 팝업에서 해당 블로그 카테고리를 고른다(베스트 에포트 —
              실패해도 기본 카테고리로 임시저장은 정상 진행).

    text 블록의 서식(강점=굵게+빨강, 중요문장=노랑배경+키워드굵게)은 b["spans"]로 전달됨.
    반환: {"ok":bool, "message":str, "notes":[...]}
    """
    if not is_logged_in():
        return {"ok": False, "message": "먼저 네이버 로그인을 해주세요.", "notes": []}

    meta = load_meta()
    blog_id = meta.get("blog_id")
    if not blog_id:
        return {"ok": False, "message": "blogId를 알 수 없습니다. 다시 로그인해 주세요.", "notes": []}
    # 🔴 발행 직전 계정 확인 — 엉뚱한 블로그에 글을 올리는 것만은 절대 막는다(되돌릴 수 없다).
    _expect = getattr(config, "EXPECT_BLOG_ID", "")
    if _expect and blog_id != _expect:
        return {"ok": False, "notes": [],
                "message": (f"세션이 다른 블로그({blog_id})입니다. 이 자동화는 '{_expect}' 전용이라 "
                            f"발행을 중단했습니다. 에디 계정으로 다시 로그인하세요.")}

    notes: list[str] = []
    with sync_playwright() as p:
        # ★실제 크롬 우선(봇 감지·세션 만료 회피). 클립보드 권한은 open_browser가 미리 허용.
        context, _close_browser = open_browser(p, log, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15000)

        log("네이버 글쓰기 페이지로 이동합니다.")
        page.goto(WRITE_URL_TMPL.format(blog_id=blog_id), wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        frame = _get_editor_frame(page, log)
        _dismiss_popups(frame, page, log)
        _clear_alert_wait(frame, page, log)   # 늦게 뜨는 「이어서 작성?」까지 잡는다(2026-09-10)

        # 1) 제목
        title_el = _first_visible(frame, SEL_TITLE, timeout=8000)
        if title_el:
            try:
                title_el.click()
                page.keyboard.type(title, delay=45)
                log(f"제목 입력: {title}")
            except Exception as e:  # noqa: BLE001
                notes.append(f"제목 입력 실패: {e}")
        else:
            notes.append("제목 영역을 찾지 못함")

        # 2) 본문 영역 포커스
        body_el = _first_visible(frame, SEL_BODY, timeout=8000)
        if not body_el:
            _close_browser()
            return {"ok": False, "message": "본문 영역을 찾지 못했습니다(에디터 셀렉터 조정 필요).", "notes": notes}
        _clear_alert(frame, page, log)
        body_el.click()
        page.wait_for_timeout(300)
        _reset_formatting(frame, page, log)  # 취소선 등 잔재 서식 초기화

        # (썸네일은 더 이상 맨 위에 넣지 않는다 — 강점 카드 그룹과 함께 본문 중간에 배치.
        #  pipeline이 blocks 안에 kind=='thumb' 이미지 블록으로 이미 끼워 넣음.)

        # 4) 블록 순서대로 재생
        photo_pending = 0
        images_inserted = 0
        # 해시태그 목록(발행 시 본문 대신 '태그편집'에 넣음)
        tags = []
        for _b in blocks:
            if _b.get("type") == "hashtags":
                tags += [w.lstrip("#") for w in _b["text"].split() if w.startswith("#")]
        # ★가운데정렬(2026-08-31 에디님 지시, 연예편).
        #   홈판 연예 위너 12편을 재보니 «짧은 문단 + 가운데정렬»이 한 세트였다:
        #     14자/96% → 211문단 전부 가운데 · 14자/96% → 154문단 전부 · 19자/73% → 78/91
        #   반대로 긴 문단 글(32~171자)은 전부 왼쪽정렬이었다.
        #   에디터는 한 번 켜면 이후 문단이 따라오므로 본문 시작 전에 한 번만 누른다.
        if align == "center":
            try:
                frame.click("body")
                page.keyboard.press("Control+Shift+E")   # 네이버 에디터 가운데정렬
                log("본문 가운데정렬 적용")
            except Exception as e:  # noqa: BLE001
                log(f"가운데정렬 실패(무시하고 진행): {str(e)[:40]}")

        for b in blocks:
            t = b["type"]
            _clear_alert(frame, page, log)   # 앞 블록이 띄운 경고창이 뒤 클릭을 전부 막는다(2026-09-10)
            if t == "text":
                _type_rich(frame, page, b["text"], b.get("spans", []), log)
                page.keyboard.press("Enter")
                page.keyboard.press("Enter")   # 문단 끝 → 한 줄 띄우기(가독성)
            elif t == "subhead":
                _toggle_bold(frame, page)
                page.keyboard.type(b["text"], delay=18)
                _toggle_bold(frame, page)
                page.keyboard.press("Enter")
            elif t == "oglink":
                if not _insert_oglink(frame, page, b["url"], log):
                    # 실패 시 지저분한 URL 텍스트를 남기지 않고 건너뜀
                    notes.append(f"링크 카드 실패(건너뜀): {b.get('title','')[:20]}")
            elif t == "connect":
                # [커넥트 - 제품] 자리에 쇼핑커넥트 상품 카드(관련도 1위)를 자동 삽입
                if not _insert_shopping_connect(frame, page, b.get("query", ""), log):
                    notes.append(f"쇼핑커넥트 자동삽입 실패(수동 필요): {b.get('query', '')[:20]}")
                page.keyboard.press("Enter")
            elif t == "hashtags":
                # 태그는 본문에 절대 넣지 않음. 발행 시 '태그편집'에 입력(임시저장이면 생략).
                continue
            elif t == "blank":
                # 원본의 빈 줄은 무시(문단 끝마다 자동으로 한 줄 띄우므로 중복 방지)
                continue
            elif t == "marker":
                # 🔴그록 사진이 아직 없는 [사진N] 자리 — **빨강 굵게**로 남긴다(2026-09-16 에디님 지시).
                #   "이미지나 사진이 없거나 안 나오면 [사진...] 출처는 있어야 되잖아? 그래야지 내가 보고 이미지 올리지?"
                #   ★`text`가 아니라 **별도 타입**인 이유: pipeline의 서식 단계(노랑 문장·빨강 키워드·
                #     인용구·소주제)가 전부 «type == "text"»만 보고 돌기 때문이다. text로 넣었더니
                #     이 자리표시 줄에 **노랑 배경이 덧씌워졌다**(9/16 재생 시험에서 03편 사진2).
                #     타입이 다르면 그 단계들이 구조적으로 못 건드린다(photo·quote와 같은 관례).
                _mk = b.get("text") or ""
                _type_rich(frame, page, _mk,
                           [(0, len(_mk), {"bold": True, "color": EMPH_RED})], log)
                page.keyboard.press("Enter")
                page.keyboard.press("Enter")
            elif t == "photo":
                page.keyboard.type(b["text"], delay=18)
                page.keyboard.press("Enter")
                page.keyboard.press("Enter")   # 사진 마커 뒤에도 한 줄 띄우기
                photo_pending += 1
            elif t == "quote":
                ok = _insert_quote(frame, page, b["text"], log, style=b.get("nstyle", "default"))
                if not ok:
                    page.keyboard.type(b["text"], delay=18)
                    page.keyboard.press("Enter")
                    notes.append("인용구 서식 미적용(일반 문단으로 대체)")
            elif t == "table_paste":
                if not _paste_table(frame, page, b["html_path"], log):
                    notes.append("표 붙여넣기 실패")
            elif t == "image":
                if b.get("missing") or not b.get("path"):
                    notes.append(f"{b.get('label')} 이미지 없음")
                    continue
                if not _insert_image(frame, page, b["path"], log, b.get("label", "이미지"),
                                     caption=b.get("caption", "")):
                    notes.append(f"{b.get('label')} 이미지 삽입 실패")
                else:
                    images_inserted += 1
                page.keyboard.press("Enter")

        if photo_pending:
            notes.append(f"[사진] 자리표시자 {photo_pending}개 — 방송 캡처를 직접 삽입하세요.")

        # 5) 마무리
        page.wait_for_timeout(800)
        # AI 생성 이미지면 '전체 AI활용' 표기(이미지가 있을 때만).
        # 🔴2026-09-11 에디님: "AI 활용은 넣지 마" — 연예 글 사진은 그록이 뽑은 **방송 캡처**라
        #   AI 생성물이 아니다. 호출측이 ai_mark=False를 넘긴다(AI 블로그의 생성 이미지는 그대로 켠다).
        if images_inserted and ai_mark:
            _mark_all_ai(frame, page, log)
            page.wait_for_timeout(400)
        elif images_inserted:
            log("AI 활용 표기 안 함(방송 캡처 사진)")
        # 도움말 패널부터 닫는다
        _close_help_panel(frame, page, log)
        page.wait_for_timeout(400)

        # 5-a) 공개 발행 분기
        if publish:
            log("공개 발행을 진행합니다.")
            opened = frame.evaluate(
                "() => { const b=document.querySelector('button[data-click-area=\"tpb.publish\"]');"
                " if(b){ b.click(); return true; } return false; }")
            page.wait_for_timeout(2200)
            # 🔴카테고리 지정이 **임시저장 분기에만** 있었다(2026-09-15 발견).
            #   strpia는 전부 예약 발행이라 이 줄이 없어서 **17편 전부 기본 칸(자동화)**에 쌓였다.
            #   「AI 뉴스」 칸을 만들어 두고도 뉴스 4편이 자동화로 갔다 — 로그엔 요청만 찍히고
            #   선택 시도 기록이 아예 없어서 눈치채기까지 닷새가 걸렸다.
            #   데일리텐은 연예편이 임시저장이라 이 버그가 안 보였다.
            if category:
                if not _select_category(frame, page, category, log):
                    log(f"🔴[경고] 카테고리 '{category}' 지정 실패 — 이 글은 기본 칸으로 발행됩니다.")
                    notes.append(f"카테고리 '{category}' 지정 실패")
            # 태그를 '태그편집'에 입력(본문엔 안 넣음)
            _enter_tags(frame, page, tags, log)
            # 전체공개 보장(best-effort)
            try:
                frame.get_by_text("전체공개", exact=True).first.click(timeout=2000)
                page.wait_for_timeout(300)
            except Exception:  # noqa: BLE001
                pass
            # ★예약 발행(2026-08-06). 제이 블로그와 동일 방침:
            #   예약 설정에 실패했는데 그대로 확정을 누르면 **즉시 발행**된다 → 임시저장으로 뺀다.
            reserved_ok = True
            if reserve_at:
                reserved_ok = _set_reserve_time(frame, page, reserve_at.hour, reserve_at.minute, log)
                if reserved_ok:
                    notes.append(f"예약 발행 {reserve_at:%m/%d %H:%M}")
                else:
                    notes.append("예약 시간 설정 실패 → 즉시 발행을 막고 임시저장으로 대체")
                    log("예약 설정 실패 → 즉시 발행 위험. 임시저장으로 전환합니다.")
                    try:
                        page.keyboard.press("Escape")
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(500)
            published = reserved_ok and frame.evaluate(
                "() => { const b=document.querySelector('button[data-click-area=\"tpb*i.publish\"]');"
                " if(b){ b.click(); return true; } return false; }")
            if published:
                # 🔴확정 버튼을 «눌렀다»는 건 발행됐다는 뜻이 아니다(2026-09-10 사고).
                #   태그·AI표기가 줄줄이 시간초과된 상태에서 확정만 눌리고 아무것도 안 만들어졌는데
                #   「예약 발행 완료」를 반환했다 → 원고가 예약에도 임시저장에도 없이 사라졌다.
                #   성공하면 네이버가 글 목록(isAfterWrite=true / logNo=)으로 넘어간다 — 그걸 확인한다.
                done = False
                for _ in range(20):
                    page.wait_for_timeout(1000)
                    u = page.url or ""
                    # ★성공 신호는 둘 중 하나다(2026-09-10 실측).
                    #   · 글 목록/글 보기로 넘어감(isAfterWrite · logNo= · PostView) — 가봄사봄에서 본 모양
                    #   · **편집기를 떠나 블로그 홈으로** 넘어감(`…/strpia?Redirect=Write&` → `…/strpia`)
                    #   처음엔 앞의 것만 성공으로 봐서, 실제로 예약된 2편을 «발행 확인 안 됨»으로
                    #   오판했다(편집기 «예약 발행 2건»으로 확인). 로그인 페이지로 튕긴 건 성공이 아니다.
                    left_editor = (u.startswith("https://blog.naver.com/")
                                   and "Redirect=Write" not in u
                                   and "postwrite" not in u.lower()
                                   and "PostWriteForm" not in u)
                    if "isAfterWrite" in u or "logNo=" in u or "PostView" in u or left_editor:
                        done = True
                        break
                if done:
                    log(f"발행 확인됨 → {page.url[:90]}")
                    _close_browser()
                    return {"ok": True, "notes": notes,
                            "message": (f"예약 발행 완료({reserve_at:%m/%d %H:%M})." if reserve_at else "공개 발행 완료.")}
                log(f"🔴 확정 버튼은 눌렀지만 발행 확인 안 됨(주소 그대로: {(page.url or '')[:70]}) → 임시저장으로 살린다")
                notes.append("확정 후 발행 확인 실패 → 임시저장으로 대체")
                try:
                    page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(800)
            # 발행 확정 실패 → 글을 잃지 않도록 임시저장으로 폴백
            log(f"발행 확정 버튼 실패(레이어 열림={opened}) → 임시저장으로 대체")
            notes.append("발행 실패 → 임시저장으로 대체됨(수동 발행 필요)")
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(500)
            _close_help_panel(frame, page, log)
            # 아래 임시저장 코드로 진행

        # 5-b) 임시저장
        # 임시저장 전에 발행 팝업을 열어 '태그편집'에 태그만 입력하고(발행 안 함) 닫는다.
        # 태그편집 칸은 발행 팝업 안에만 있으므로, 팝업을 잠깐 열었다 Escape로 닫으면
        # 입력한 태그는 유지된 채 임시저장된다(본문엔 태그를 넣지 않음).
        # publish 분기에서 이미 태그를 넣고 폴백된 경우(publish=True)엔 중복 입력하지 않는다.
        if (tags or category) and not publish:
            try:
                opened_tag = frame.evaluate(
                    "() => { const b=document.querySelector('button[data-click-area=\"tpb.publish\"]');"
                    " if(b){ b.click(); return true; } return false; }")
                page.wait_for_timeout(2200)
                if category:
                    # 🔴결과를 버리면 «조용한 실패»가 된다(2026-09-09: 4편이 엉뚱한 칸으로 갔는데
                    #   배치 로그에 아무 흔적이 없었다). 실패를 눈에 띄게 남긴다.
                    if not _select_category(frame, page, category, log):
                        log(f"🔴[경고] 카테고리 '{category}' 지정 실패 — 이 글은 기본 칸에 있습니다. "
                            f"발행 전에 칸을 확인하세요.")
                _enter_tags(frame, page, tags, log)
                page.keyboard.press("Escape")   # 발행하지 않고 팝업만 닫음(태그·카테고리 유지)
                page.wait_for_timeout(700)
                _close_help_panel(frame, page, log)
                if not opened_tag:
                    log("태그편집 팝업을 열지 못해 태그 입력을 건너뜀.")
            except Exception as e:  # noqa: BLE001
                log(f"임시저장 전 태그 입력 실패(무시하고 저장 진행): {str(e)[:120]}")

        save_btn = _first_visible(frame, SEL_SAVE_BTN, timeout=6000)
        saved = False
        if save_btn:
            # (1) 일반 클릭 시도
            try:
                save_btn.click(timeout=4000)
                saved = True
            except Exception:  # noqa: BLE001
                pass
            # (2) 실패하면 JS 클릭으로 포인터 가로채기 우회
            if not saved:
                try:
                    save_btn.evaluate("el => el.click()")
                    saved = True
                    log("저장: JS 클릭으로 우회 성공.")
                except Exception as e:  # noqa: BLE001
                    notes.append(f"저장 버튼 클릭 실패: {str(e)[:150]}")
            if saved:
                page.wait_for_timeout(2500)
                log("임시저장 버튼 클릭 완료.")
        else:
            notes.append("저장 버튼을 찾지 못함 — 창에서 직접 저장해 주세요.")

        # 저장 실패 시엔 사용자가 직접 저장할 수 있게 창을 잠시 더 유지
        page.wait_for_timeout(6000 if not saved else 2500)
        # ★쿠키 갱신분을 다시 저장한다(2026-08-04 에디님: "로그인 세션 기억하고 진행하면 되는데
        #   왜 매번 물어보냐"). 네이버는 사용할 때마다 쿠키 만료를 연장해 주는데, 지금까지는
        #   로그인 시점에만 파일로 저장해서 그 연장이 반영되지 않았다.
        #   매 실행마다 갱신하면 매일 돌아가는 한 세션이 사실상 끊기지 않는다.
        try:
            context.storage_state(path=config.SESSION_FILE)
        except Exception:  # noqa: BLE001
            pass
        _close_browser()

    msg = "임시저장 완료(비공개). 네이버에서 확인 후 직접 발행하세요." if saved \
        else "임시저장을 자동 클릭하지 못했습니다. 열린 내용 확인 후 직접 저장하세요."
    return {"ok": saved, "message": msg, "notes": notes}
