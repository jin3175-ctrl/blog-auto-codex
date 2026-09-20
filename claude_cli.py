"""claude -p (구독 요금제, 헤드리스) 공용 호출 헬퍼."""
from __future__ import annotations

import re
import subprocess
import time


class NotLoggedInError(RuntimeError):
    """claude CLI가 구독 로그인되어 있지 않을 때."""


class UsageLimitError(RuntimeError):
    """`claude -p` 가 사용 한도 안내를 돌려준 경우. **재시도해도 안 풀린다**(초기화 시각까지 기다려야 한다)."""


#: 한도 안내 문구. 영문이라 한글 기반 제목 필터(`gen_common.looks_meta`)로는 못 걸러진다.
_USAGE_LIMIT = re.compile(
    r"hit your (?:session|usage) limit|usage limit reached|session limit"
    r"|rate limit|too many requests|limit .{0,20}resets", re.I)


#: 🔴로그인(OAuth) 만료 문구. 2026-09-12에 실제로 이게 나왔다 —
#   «Failed to authenticate. API Error: 401 OAuth access token has expired.»
#   종료코드 0으로 **본문처럼** 돌아와서, 홈판 공식이 빈 값이 되고도 아무 경고가 없었다
#   (한도 응답과 같은 구조다. 그때는 그 문장이 제목이 되어 발행까지 나갔다).
_AUTH_FAIL = re.compile(
    r"failed to authenticate|oauth .{0,30}expired|401 .{0,30}oauth"
    r"|re-?authenticate|invalid api key|authentication_error", re.I)


def auth_ok(timeout: int = 60) -> tuple:
    """claude CLI 로그인이 살아 있는가 → (True, '') / (False, 사유).
    새벽 배치 전·저녁 점검에서 **미리** 확인하려고 쓴다(만료를 새벽에 알면 그날 0편이다)."""
    try:
        run_claude_p("ok이라고만 답해줘", timeout=timeout)
        return True, ""
    except (NotLoggedInError, UsageLimitError) as e:
        return False, str(e)[:200]
    except Exception as e:  # noqa: BLE001
        return False, f"확인 실패: {str(e)[:160]}"


def run_claude_p(prompt: str, timeout: int = 300) -> str:
    """`claude -p` 로 프롬프트를 실행하고 텍스트 결과를 반환.

    구독 로그인이 안 돼 있으면 NotLoggedInError 발생.
    """
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if _AUTH_FAIL.search(combined):
        raise NotLoggedInError(
            "claude 로그인이 만료됐습니다(OAuth). 터미널에서 `claude login` 을 다시 실행하세요. "
            "원문: " + combined.strip().replace("\n", " ")[:160])
    if "Not logged in" in combined or "Please run /login" in combined:
        raise NotLoggedInError(
            "claude CLI가 구독 로그인되어 있지 않습니다. 터미널에서 `claude login` 을 한 번 실행해 "
            "구독(Max/Pro) 계정으로 로그인한 뒤 다시 시도하세요. (-p 방식은 로그인된 구독을 사용합니다)"
        )
    # 🔴🔴2026-09-09 사고: 새벽 02:17에 **사용 한도**에 걸리자 `claude -p`가 종료코드 0으로
    #   «You've hit your session limit · resets 5am (Asia/Seoul)» 를 stdout에 뱉었다.
    #   그걸 «본문/제목»으로 받아 써서 그 문장이 **글 제목이 되어 예약 발행**까지 나갔고,
    #   이후 편들도 전부 죽어 10편이 4편이 됐다.
    #   → 한도 응답은 **결과가 아니라 장애**다. 전용 예외로 올려서 그 편을 버리게 한다.
    if _USAGE_LIMIT.search(combined):
        raise UsageLimitError(
            "claude -p 사용 한도에 걸렸습니다: " + combined.strip().replace("\n", " ")[:160])
    out = proc.stdout.strip()
    if proc.returncode != 0 and not out:
        raise RuntimeError(
            f"claude -p 실패 (code {proc.returncode}): {(proc.stderr or proc.stdout).strip()[:500]}"
        )
    if not out:
        raise RuntimeError("claude -p 가 빈 결과를 반환했습니다.")
    return out


#: 재시도 대기(초). 연타하면 같은 장애를 그대로 다시 맞는다 → 점점 길게 쉰다.
BACKOFF = (20, 60, 120)


def run_claude_p_retry(prompt: str, timeout: int = 300, tries: int = 3,
                       ok=None, log=None, label: str = "") -> str:
    """`claude -p`를 **검증까지 하고** 실패 시 백오프 재시도한다.

    ★왜 필요한가 (2026-08-12 사고): 새벽 배치에서 claude가 일시적으로 빈/규격 밖 응답을 줬는데,
      ①재시도가 70초 안에 3연타로 끝나 회복할 시간이 없었고 ②받은 응답을 로그에 남기지 않아
      원인조차 알 수 없었다. 그 결과 AI 03편이 통째로 날아갔다(예약 3편).
      그래서 이 헬퍼는 **쉬면서 다시 걸고, 실패한 응답의 앞부분을 로그에 남긴다.**

    ok(out) -> bool 로 '쓸 만한 응답인지'까지 판정한다(파싱 실패도 재시도 대상).
    전부 실패하면 마지막 응답을 그대로 돌려준다(호출측이 길이·파싱으로 최종 판단).
    """
    last = ""
    for i in range(max(1, tries)):
        err = ""
        try:
            out = run_claude_p(prompt, timeout=timeout)
        except NotLoggedInError:
            raise                       # 로그인 문제는 쉬어도 안 낫는다 → 즉시 올린다
        except Exception as e:          # noqa: BLE001  타임아웃·빈 응답·비정상 종료
            out, err = "", str(e)[:140]
        else:
            if ok is None or ok(out):
                return out
        last = out or last
        if log:
            why = f"호출 실패({err})" if err else f"응답이 규격에 안 맞음 — 앞부분 {out.strip()[:160]!r}"
            log(f"{label} 재시도 {i + 1}/{tries}: {why}")
        if i < tries - 1:
            time.sleep(BACKOFF[min(i, len(BACKOFF) - 1)])
    return last
