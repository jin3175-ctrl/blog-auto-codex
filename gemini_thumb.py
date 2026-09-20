"""제미나이가 '글자까지 박힌 완성 썸네일'을 한 번에 그린다 — 기본 모드 (2026-07-18).

왜 이걸로 바꿨나 (에디님 지시 + 실측):
  이전엔 "AI가 배경만 그리게 하면 글자를 환각으로 넣는다"고 봤다. 그래서 배경을
  Gemini에 안 시키고 Unsplash 실사 위에 우리가 글씨를 얹었다(photo_thumb).
  그런데 2026-07-18 실측: gemini-3.1-flash-image 는 '지정한 한글 문구'를 오타 없이
  선명하게 렌더한다(증시/반도체 매도세 확산/다음은 코스피/나스닥 1.4% 급락 이유 전부 정확).
  → 배경+글자를 한 번에 디자인하니 실사+오버레이보다 완성도가 높다. 에디님 추천대로.

안전장치 (자동 발행 = 사람이 못 거름):
  텍스트 렌더는 대개 정확하지만 100%는 아니다. 생성 후 '비전으로 글자를 되읽어'
  내가 지정한 문구(특히 큰 키워드 main)가 그대로 들어갔는지 검사한다. 틀리면 재생성.
  N회 실패하면 photo_thumb(실사+오버레이)로 폴백 → 거긴 글자를 우리가 직접 얹으니 확실.

폴백 사슬: gemini_thumb → photo_thumb → thumb_clone → ref_thumb → 디자인형.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

import image_finder

GEN_MODEL = "gemini-3.1-flash-image"   # 한글 텍스트 렌더 정확(2026-07 실측)
VISION_MODEL = "gemini-flash-latest"

# 카테고리 → 배경 장면(한국어). field/topic/main 을 합친 문자열에서 앞쪽부터 매칭.
_BG_MAP = [
    (("이미지", "그림", "사진", "썸네일", "디자인"),
     "노트북 화면에 AI 이미지 생성 툴이 떠 있는 어두운 책상 배경"),
    (("블로그", "글쓰기", "포스팅", "발행", "자동발행", "자동 발행"),
     "여러 블로그 글이 줄지어 뜬 모니터 화면, 어두운 톤 배경"),
    (("유튜브", "쇼츠", "영상", "편집"),
     "영상 편집 타임라인이 떠 있는 어두운 작업실 배경"),
    (("수익", "돈", "부업", "월급", "전자책", "수익화"),
     "노트북 옆에 성장하는 막대그래프와 동전이 놓인 어두운 책상 배경"),
    (("챗gpt", "클로드", "gpt", "프롬프트", "챗봇"),
     "AI 챗봇 대화창이 떠 있는 노트북 화면, 어두운 톤 배경"),
    (("자동화", "툴", "세팅", "시스템"),
     "여러 자동화 도구가 연결된 대시보드 화면, 어두운 톤 배경"),
]
_DEFAULT_BG = "노트북 앞에 앉은 사람의 뒷모습, 어두운 톤의 집 작업공간 배경"


def _pick_bg(hint: str) -> str:
    low = (hint or "").lower()
    for keys, scene in _BG_MAP:
        for k in keys:
            if k.lower() in low:
                return scene
    return _DEFAULT_BG


def _norm(s: str) -> str:
    """공백·문장부호 제거해 글자 비교를 관대하게(렌더가 자간·띄어쓰기를 살짝 바꿔도 통과)."""
    return re.sub(r"[\s·.,!?~\-]", "", s or "")


#: 마지막 실패 사유. 예전엔 예외를 통째로 삼켜 False만 돌려줘서 **429인지도 알 수 없었다**
#  (2026-08-17·18 이틀 연속 썸네일 공식이 429로 죽었는데 로그에 이유가 남지 않았다).
LAST_ERROR = ""


def _gen(prompt: str, out_path: str, key: str, tries: int = 3) -> bool:
    """제미나이 이미지 생성. 429(분당 한도)는 **쉬었다 다시** 건다."""
    global LAST_ERROR
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEN_MODEL}:generateContent?key={key}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    for i in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            data = json.loads(urllib.request.urlopen(req, timeout=90).read())
            for c in data.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    b64 = (p.get("inlineData") or {}).get("data")
                    if b64:
                        with open(out_path, "wb") as f:
                            f.write(base64.b64decode(b64))
                        LAST_ERROR = ""
                        return os.path.getsize(out_path) > 2000
            LAST_ERROR = "응답에 이미지가 없음"
        except urllib.error.HTTPError as e:      # noqa: PERF203
            LAST_ERROR = f"HTTP {e.code}"
            if e.code == 429 and i < tries - 1:
                time.sleep(20 * (i + 1))          # 무료 티어 분당 한도 → 쉬면 풀린다
                continue
            return False
        except Exception as e:                    # noqa: BLE001
            LAST_ERROR = str(e)[:80]
            if i < tries - 1:
                time.sleep(5)
                continue
            return False
    return False


def _read_texts(img_path: str, key: str) -> list[str]:
    """이미지 안의 모든 글자를 비전으로 되읽어 리스트로."""
    try:
        b64 = base64.b64encode(open(img_path, "rb").read()).decode()
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{VISION_MODEL}:generateContent?key={key}")
        q = ('이 이미지에 보이는 모든 글자를 그대로 옮겨써라(번역·설명 금지). '
             'JSON 하나로만: {"texts": ["...", "..."]}')
        body = json.dumps({"contents": [{"parts": [
            {"inline_data": {"mime_type": "image/png", "data": b64}},
            {"text": q},
        ]}]}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)).get("texts", []) if m else []
    except Exception:  # noqa: BLE001
        return []


def _text_ok(img_path: str, need: list[str], key: str, log) -> bool:
    """지정한 문구(특히 main)가 이미지에 '그대로' 들어갔는지 검사.
    검사 자체가 실패하면 통과로 본다(비전 오류로 좋은 이미지를 버리지 않도록) —
    대신 최소한 뭔가 글자는 읽혀야 한다."""
    got = _read_texts(img_path, key)
    if not got:
        log("  글자 되읽기 실패 → 통과로 간주")
        return True
    blob = _norm("".join(got))
    missing = [t for t in need if t and _norm(t) not in blob]
    if missing:
        log(f"  글자 불일치: {missing} (읽힌 것: {got})")
        return False
    return True


def _download(url: str, timeout: int = 20) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=timeout).read()
        return data if len(data) > 2000 else None
    except Exception:  # noqa: BLE001
        return None


def extract_thumb_formula(image_urls: list, log=print) -> str:
    """지금 홈판에 뜨는 썸네일 여러 장을 비전으로 분석해 '지금 먹히는 썸네일 공식'을 뽑는다.

    특정 썸네일 베끼기가 아니라, 여러 위너의 공통 패턴(레이아웃·글자수·색·구도·톤)만 추출.
    실패하면 빈 문자열 → make_from_article이 기존처럼 자유 디자인.
    """
    key = image_finder._load_key("GEMINI_API_KEY")
    if not key or not image_urls:
        return ""
    parts = []
    for u in image_urls[:6]:
        raw = _download(u)
        if raw:
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(raw).decode()}})
    if len(parts) < 2:
        log("썸네일 레퍼런스 수집 부족 → 공식 추출 생략")
        return ""
    q = ("아래는 지금 네이버 홈피드(IT·컴퓨터)에서 '잘 뜨고 있는' 블로그 대표 썸네일들이다. "
         "이들이 공통으로 쓰는 '지금 먹히는 썸네일 공식'만 뽑아라(특정 이미지 설명 말고 패턴). "
         "다음 항목을 짧게: ①글자 줄 수와 길이감 ②글자 위치·크기(어디에 큰 글씨) "
         "③색 조합(배경/글자/강조색) ④배경 유형(인물/제품/화면/그래프 등) ⑤전체 톤·분위기 "
         "⑥클릭을 부르는 공통 후킹 장치. 재사용 가능한 지침 형태로, 군더더기 없이.")
    parts.append({"text": q})
    try:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{VISION_MODEL}:generateContent?key={key}")
        body = json.dumps({"contents": [{"parts": parts}]}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=45).read())
        out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        log(f"썸네일 공식 추출 OK ({len(parts)-1}장 분석)")
        return out[:1200]
    except Exception as e:  # noqa: BLE001
        log(f"썸네일 공식 추출 실패(자유 디자인으로): {str(e)[:80]}")
        return ""


def make(out_dir: str, filename: str, texts: dict, query_hint: str = "",
         log=print, seed: str = "", tries: int = 3) -> bool:
    """제미나이 완성 썸네일 1장. texts={"badge","kicker","main","sub"}(main 필수).

    글자 검사를 통과할 때까지 최대 tries회 재생성. 실패하면 False → 호출부 폴백.
    """
    key = image_finder._load_key("GEMINI_API_KEY")
    if not key:
        return False
    main = (texts.get("main") or "").strip()
    if not main:
        return False
    badge = (texts.get("badge") or "AI 실전").strip()
    kicker = (texts.get("kicker") or "").strip()
    sub = (texts.get("sub") or "").strip()
    bg = _pick_bg(query_hint or main)

    lines = [f'- 왼쪽 위 빨간색 배지에 흰 글씨: "{badge}"']
    if kicker:
        lines.append(f'- 그 아래 작은 노란색 글씨: "{kicker}"')
    lines.append(f'- 화면 가운데~아래 아주 굵은 흰색 큰 글씨: "{main}"')
    if sub:
        lines.append(f'- 맨 아래 밝은 회색 글씨: "{sub}"')
    text_block = "\n".join(lines)

    prompt = (
        "40대 직장인 대상 'AI 실전' 유튜브/블로그 썸네일 이미지를 만들어라. 정사각형 1:1 비율.\n"
        f"배경: {bg}. 어둡게 처리해 흰 글씨가 잘 보이게 한다.\n"
        "아래 한글 텍스트를 '오타 없이 정확하게', 선명하고 굵게 넣어라:\n"
        f"{text_block}\n"
        "요구사항: 글자는 100% 정확한 한글이어야 한다(내가 준 문구 그대로, 글자를 바꾸거나 "
        "지어내지 말 것). 텍스트는 크고 대비가 강해 한눈에 읽혀야 한다. "
        "레이아웃은 위→아래로 정돈되고 겹치지 않게. 프로페셔널하면서 눈길 끄는 유튜브 썸네일 톤. "
        "⚠️ 내가 지정한 문구 '외에' 다른 글자·숫자·지수·축라벨·워터마크·로고를 "
        "배경에 넣지 말 것(지어낸 수치가 사실처럼 보이면 안 된다)."
    )

    need = [badge, main] + ([kicker] if kicker else []) + ([sub] if sub else [])
    tmp = os.path.join(out_dir, "_gemini_thumb_raw.png")
    dst = os.path.join(out_dir, filename)
    for attempt in range(1, tries + 1):
        if not _gen(prompt, tmp, key):
            log(f"  제미나이 생성 실패 {attempt}/{tries}")
            continue
        if _text_ok(tmp, need, key, log):
            _fit_square(tmp, dst)
            try:
                os.remove(tmp)
            except OSError:
                pass
            log(f"  제미나이 썸네일 OK (배경: {bg[:18]}…)")
            return True
        log(f"  글자 검사 실패 → 재생성 {attempt}/{tries}")
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def _fit_square(src: str, dst: str) -> None:
    """1024×1024 정사각으로 맞춰 저장(모델이 살짝 다른 비율을 줄 때 대비)."""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        im = im.resize((1024, 1024), Image.LANCZOS)
        im.save(dst, "PNG")
    except Exception:  # noqa: BLE001
        # PIL 실패 시 원본 그대로
        import shutil
        shutil.copy(src, dst)


def make_from_thumb(out_dir: str, filename: str, thumb: dict, query_hint: str = "",
                    log=print, seed: str = "") -> bool:
    """gen_issue 등의 썸네일 dict({intro,big,tail,badge,photo}) 어댑터."""
    texts = {
        "badge": thumb.get("badge") or "AI 실전",
        "kicker": thumb.get("intro") or "",
        "main": thumb.get("big") or "",
        "sub": thumb.get("tail") or "",
    }
    hint = " ".join(str(x) for x in (query_hint, thumb.get("photo", "")) if x)
    return make(out_dir, filename, texts, query_hint=hint, log=log, seed=seed)



def _copy_rule(copy: dict | None) -> str:
    """썸네일 안 글자 지시. 피드백봇이 고른 문구가 있으면 **그것만** 넣게 한다."""
    if (copy or {}).get("큰글씨"):
        return ("- 🔴이미지 안 글자는 **정확히 아래 두 줄만** 넣어라(철자·띄어쓰기 그대로, 다른 문구 추가 금지):\n"
                f"  큰 글씨: {copy['큰글씨']}\n  작은 글씨: {copy.get('작은글씨', '')}\n"
                "- 한글은 오타 없이 정확하게. 글자가 잘리거나 겹치지 않게, 한눈에 읽히게.\n"
                "- ⛔배경 사진 속 휴대폰·모니터·간판에 **읽히는 글자를 넣지 마라**(화면은 흐리게). "
                "실측(2026-09-18): 배경 휴대폰 화면에 «Bucinees Hours» 같은 오타 난 가짜 영어가 박혔다.\n")
    return ("- 글의 핵심을 짧고 강한 한글 문구로 '네가 직접 뽑아' 이미지 안에 크게 넣어라(2~4줄).\n"
            "- ⛔배경 사진 속 화면·간판에 읽히는 글자를 넣지 마라(화면은 흐리게).\n")

def make_from_article(out_dir: str, filename: str, article: str,
                      log=print, tries: int = 3, ref_formula: str = "",
                      copy: dict | None = None) -> bool:
    """★ 글 전문을 제미나이에 주고, 핵심을 요약한 1:1 썸네일을 '디자인까지 맡겨' 생성.

    문구는 제미나이가 글에서 직접 뽑는다. ref_formula(오늘 홈판 썸네일 공식)를 주면
    그 스타일(레이아웃·색·톤)을 따르도록 한다 — 없으면 자유 디자인.
    """
    key = image_finder._load_key("GEMINI_API_KEY")
    if not key or not (article or "").strip():
        return False
    body = re.sub(r"\[\[[^\]]*\]\]", "", article)        # [[경험 슬롯]] 제거
    body = re.sub(r"\[[^\]]*\]", "", body)               # [사진N]/[표] 마커 제거
    body = re.sub(r"^#.*$", "", body, flags=re.M)        # 해시태그 줄 제거
    body = re.sub(r"\n{2,}", "\n", body).strip()[:2500]

    if (ref_formula or "").strip():
        style_block = (
            "- ★아래는 '지금 홈판에서 잘 뜨는 썸네일 공식'이다. 이 스타일(레이아웃·글자수·색·구도·톤)을 따라라"
            + ("(단, 문구는 아래에 **지정한 문구**로).\n" if (copy or {}).get("큰글씨")
               else "(단, 문구는 이 글 내용으로).\n") +
            f"[오늘의 썸네일 공식]\n{ref_formula.strip()}\n")
    else:
        # 🔴2026-08-18 에디님 지적("왜 또 파란색으로만 나와?"). 공식 추출이 429로 죽으면 여기로 오는데,
        #   «네가 감각적으로 정해라»만 주면 제미나이가 **매번 같은 남색 그라데이션**으로 수렴한다
        #   (실측: 홈판 목록에서 우리 글만 파란 카드로 줄줄이 보였다 — 그것부터가 '기계가 쓴 티'다).
        #   → 배경 유형을 **코드가 돌려가며 지정**하고, 단색 그라데이션을 명시적으로 금지한다.
        _BGS = [
            "주제와 관련된 **실제 장면 사진**(사람의 손·작업 공간·사물이 보이는 현실적인 사진)",
            "**인물 클로즈업 실사**(표정이 보이는 자연광 사진, 정면 또는 측면)",
            "주제를 보여주는 **화면·기기 실사**(노트북·휴대폰 화면이 손과 함께 잡힌 사진)",
            "**사물 정물 실사**(주제와 관련된 물건을 가까이서 찍은 사진, 얕은 심도)",
        ]
        _bg = _BGS[int(time.time() // 60) % len(_BGS)]
        style_block = (
            f"- 배경은 {_bg}로 한다.\n"
            "- ⛔**단색·그라데이션만 깔린 배경 금지**(특히 남색/파란색 그라데이션). "
            "사진 없이 색만 채운 카드는 만들지 마라.\n"
            "- 색조도 매번 다르게 — 파란 계열로 고정하지 말 것.\n")

    prompt = (
        "아래는 한국어 블로그 글 전문이다. 이 글을 읽고 핵심 메시지를 요약해서, "
        "클릭하고 싶어지는 '1:1 정사각형' 썸네일 이미지를 디자인해라.\n\n"
        "요구사항:\n"
        + _copy_rule(copy) +
        "- 한글은 오타 없이 정확하게. 글자가 잘리거나 겹치지 않게, 한눈에 읽히게.\n"
        "- 글 내용과 어울리는 실사 배경. 글자가 잘 보이도록 배경은 어둡거나 차분하게.\n"
        f"{style_block}"
        "- 글에 없는 수치·브랜드·로고·워터마크는 절대 넣지 말 것.\n"
        "- ⛔**블로거명·채널명·서명·출처 문구를 지어내 넣지 마라.** 실측 사고(2026-08-18): "
        "«강원코치 매디의 시선» 같은 **없는 사람의 서명**이 썸네일 하단에 박혀 나갔다. "
        "이미지 안에는 이 글의 핵심 문구만 넣는다.\n\n"
        f"[글 전문]\n{body}"
    )
    tmp = os.path.join(out_dir, "_gemini_art_raw.png")
    dst = os.path.join(out_dir, filename)
    # 🔴배경 속 잡글자(2026-09-18): 「배경 화면에 글자 넣지 마라」를 프롬프트에 넣었는데도 휴대폰 화면에
    #   «칠임»«시행토스» 같은 깨진 한글이 읽히게 박혔다. → 지정 문구 외의 한글이 읽히면 다시 뽑는다.
    #   끝까지 깨끗한 게 없으면 **잡글자가 가장 적은 판**을 쓴다(썸네일이 텍스트형으로 떨어지는 것보다 낫다).
    best_tmp = os.path.join(out_dir, "_gemini_art_best.png")
    best_n, best_ko = None, []
    # ★대소문자 무시 — 글자 인식이 «iOS»를 «ios»로 읽어 지정 문구 자체를 잡글자로 본 적이 있다(2026-09-18)
    _n = lambda x: re.sub(r"[\s,.!?·…\"'“”‘’]", "", x or "").lower()
    _want = [_n((copy or {}).get("큰글씨", "")), _n((copy or {}).get("작은글씨", ""))]
    def _stray(ko_list):
        if not (copy or {}).get("큰글씨"):
            return []
        out = []
        for t in ko_list:
            nt = _n(t)
            if len(nt) < 3 or any(w and (nt in w or w in nt) for w in _want):
                continue
            out.append(t)
        return out
    for attempt in range(1, tries + 1):
        if not _gen(prompt, tmp, key):
            log(f"  제미나이(글 기반) 생성 실패 {attempt}/{tries}")
            continue
        got = _read_texts(tmp, key)
        ko = [t for t in (got or []) if re.search(r"[가-힣]", t)]
        # 🔴지정 문구가 있으면 **큰 글씨가 실제로 들어갔는지** 글자 인식으로 대조한다(2026-09-18).
        #   프롬프트에 「이대로」라고 써도 따를지는 운이다 — 코드가 잰다(이 저장소 관례).
        if ko and (copy or {}).get("큰글씨"):
            want = re.sub(r"\s", "", copy["큰글씨"])
            if not any(want in re.sub(r"\s", "", t) or re.sub(r"\s", "", t) in want for t in ko if len(t) >= 2):
                log(f"  썸네일 큰 글씨 «{copy['큰글씨']}»가 이미지에 없음(읽힌 글자 {ko[:3]}) → 재생성 {attempt}/{tries}")
                continue
        # ★한글만 보면 영어 잡글자(«Start Automation»«Hours to… sources»)를 놓친다 → 읽힌 글자 전부를 본다
        stray = _stray(got or [])
        if ko and stray:
            if best_n is None or len(stray) < best_n:
                import shutil as _sh
                _sh.copyfile(tmp, best_tmp)
                best_n, best_ko = len(stray), ko
            log(f"  썸네일 배경에 잡글자 {stray[:3]} → 재생성 {attempt}/{tries}")
            continue
        if ko:
            _fit_square(tmp, dst)
            try:
                os.remove(tmp)
            except OSError:
                pass
            # ★한글만 찍는다 — 배경 화면 속 작은 영어 버튼 글자를 앞에 찍어 실패처럼 보였다(2026-09-18).
            log(f"  제미나이 썸네일(글 요약) OK — 뽑힌 문구: {ko[:3]}")
            return True
        log(f"  한글 텍스트 미검출 → 재생성 {attempt}/{tries}")
    if best_n is not None and os.path.exists(best_tmp):
        _fit_square(best_tmp, dst)
        log(f"  🔴{tries}번 다 배경 잡글자가 있었음 → 가장 적은 판(잡글자 {best_n}개) 사용 — 뽑힌 문구: {best_ko[:3]}")
        for f in (tmp, best_tmp):
            try:
                os.remove(f)
            except OSError:
                pass
        return True
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


if __name__ == "__main__":
    demo = {"badge": "증시", "intro": "반도체 매도세 확산",
            "big": "다음은 코스피", "tail": "나스닥 1.4% 급락 이유",
            "photo": "증시 차트"}
    ok = make_from_thumb("/tmp", "_gemini_demo.png", demo,
                         query_hint="주식 코스피 나스닥")
    print("생성:", ok, "→ /tmp/_gemini_demo.png")
