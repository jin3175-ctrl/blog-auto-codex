#!/usr/bin/env python3
"""네이버 세션 저녁 점검 (2026-08-12 신설).

★왜 필요한가
새벽 1:30 배치는 세션이 만료돼 있으면 **그날치를 통째로 못 만든다**(생성 전에 감지해서
멈추도록 되어 있다 — 낭비는 막지만 발행은 0편이다). 그런데 그 알림은 새벽에 뜨므로
사장님이 아침에야 본다. 하루가 날아간다.

그래서 **자기 전(21:00)에 미리 확인해 알린다.** 이때 로그인해두면 새벽 배치가 정상 작동한다.
세션이 살아 있으면 조용히 로그만 남긴다(알림으로 귀찮게 하지 않는다).

사용:
  python3 check_session.py          # 점검 후 만료면 알림
  python3 check_session.py --login  # 만료면 로그인 창까지 띄운다(사람이 앞에 있을 때)
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    import config
    import naver
    from run_ai_daily import _alert, _log

    # 🔴블로그가 둘이다(2026-09-08). 알림에 **어느 블로그인지**와 **그 블로그용 명령**을 넣지 않으면
    #   에디님이 데일리텐만 로그인하고 자러 가신다 → strpia는 그날 0편.
    _env = "" if config.BLOG == "dailyten" else f"EDI_BLOG={config.BLOG} "
    _cmd = f"{_env}python3 check_session.py --login"

    stamp = time.strftime("%Y-%m-%d %H:%M")
    _log(f"[세션점검] {stamp} {config.BLOG_NAME}({config.EXPECT_BLOG_ID}) 네이버 세션 확인")
    # 🔴claude 로그인도 같이 본다(2026-09-12: 낮에 «OAuth access token has expired»가 나왔다).
    #   글을 만드는 게 전부 `claude -p`라 이게 만료면 **그날 0편**이다 — 네이버 세션과 똑같이 자기 전에 알린다.
    try:
        import claude_cli
        _cok, _cwhy = claude_cli.auth_ok()
    except Exception as e:  # noqa: BLE001
        _cok, _cwhy = False, str(e)[:140]
    if _cok:
        _log("[세션점검] claude 로그인 정상")
    else:
        _log(f"[세션점검] 🔴claude 로그인 문제: {_cwhy}")
        _alert("🔴 claude 로그인 필요 (자기 전에)",
               f"claude -p 가 정상 응답하지 않습니다: {_cwhy}\n"
               "터미널에서 `claude login` 을 실행하세요. 이 상태로 두면 새벽 글 생성이 0편입니다.")
    try:
        alive = naver.session_alive(_log)
    except Exception as e:  # noqa: BLE001
        # 점검 자체가 실패한 것도 알린다(조용한 실패 금지 — 이 저장소 공통 방침)
        _log(f"[세션점검] 검사 실패: {e}")
        _alert(f"네이버 세션 점검 실패 — {config.BLOG_NAME}",
               f"검사 중 오류: {str(e)[:120]} — 직접 확인해 주세요.")
        return 2

    want = getattr(config, "EXPECT_BLOG_ID", "")
    got = (naver.load_meta() or {}).get("blog_id") or ""

    if alive and (not want or got == want):
        _log(f"[세션점검] 세션 정상({got or '계정 미기록'}) — {config.BLOG_NAME} 새벽 배치 진행 가능")
        return 0

    if alive:
        # 🔴 살아 있어도 '누구로' 살아 있는지가 중요하다(2026-08-12: 한성협 계정으로 로그인돼 있었다).
        #    발행은 코드가 막지만, 고치지 않으면 그날 글은 0편이다.
        _log(f"[세션점검] 세션은 살아 있으나 **다른 블로그**({got or '알 수 없음'})입니다")
        _alert(f"🔴 네이버 계정이 잘못됐습니다 — {config.BLOG_NAME}",
               f"저장된 세션이 '{got or '알 수 없음'}' 계정입니다(여기는 {want}). "
               f"{_cmd} 으로 {want} 계정으로 다시 로그인하세요.")
    else:
        _log("[세션점검] 세션 만료 — 지금 로그인해야 새벽 배치가 돕니다")
        _alert(f"🔴 네이버 로그인 필요 — {config.BLOG_NAME}({want}) (자기 전에)",
               f"세션이 만료됐습니다. 지금 로그인하지 않으면 새벽 글 발행이 0편입니다. "
               f"터미널에서 {_cmd} → '로그인 상태 유지' 켜기, 'IP 보안' 끄기.")

    if "--login" not in sys.argv:
        return 1

    # 잘못된 계정으로 **이미 로그인된 상태**면 로그인 창이 그냥 통과된다(그 쿠키가 살아 있으니까).
    # → 세션 파일을 옆으로 치워 로그인 화면부터 다시 시작한다(원본은 .bak 으로 남긴다).
    if alive:
        import shutil
        for f in (config.SESSION_FILE, config.BLOG_META_FILE):
            if os.path.exists(f):
                shutil.move(f, f + ".bak")
                _log(f"[세션점검] 잘못된 세션을 치웠습니다 → {os.path.basename(f)}.bak")

    _log("[세션점검] 로그인 창을 띄웁니다(직접 로그인하세요)")
    # 15분 — 5분은 사장님이 자리를 비웠다 돌아오면 이미 닫혀 있다(실측).
    r = naver.login_and_save(_log, timeout_sec=900)
    if r.get("ok") and (not want or r.get("blog_id") == want):
        _log(f"[세션점검] 로그인 완료 — 세션 저장됨({r.get('blog_id')})")
        return 0
    _log(f"[세션점검] 로그인 미완료: {r.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
