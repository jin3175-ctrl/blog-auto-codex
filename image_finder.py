"""비연예 글의 [사진N] 마커에 맞는 이미지를 Unsplash에서 찾아 다운로드."""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import urllib.request

def _load_key(name: str = "UNSPLASH_ACCESS_KEY") -> str | None:
    """이미지 키는 내정보.txt 에서 읽는다(myinfo).
       사진 키(Unsplash) = 'UNSPLASH_ACCESS_KEY', 제미나이 키 = 'GEMINI_API_KEY'."""
    try:
        import myinfo
        if "UNSPLASH" in name:
            return myinfo.photo_key() or None
        if "GEMINI" in name:
            return myinfo.gemini_key() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def _fetch_first(query: str, out_path: str, key: str) -> bool:
    """query로 Unsplash 검색 → 첫 결과 이미지를 out_path로 저장(단일 시도)."""
    try:
        url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode({
            "query": query, "per_page": 3, "orientation": "landscape", "content_filter": "high",
        })
        req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {key}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results") or []
        if not results:
            return False
        img_url = results[0]["urls"]["regular"]
        with urllib.request.urlopen(img_url, timeout=30) as ir:
            content = ir.read()
        with open(out_path, "wb") as f:
            f.write(content)
        return os.path.getsize(out_path) > 1000
    except Exception:  # noqa: BLE001
        return False


def search_download(query: str, out_path: str, key: str | None = None) -> bool:
    """query로 Unsplash 검색 → 첫 결과 저장. 정확 검색어에 결과가 없으면
    검색어를 점점 단순화(앞 2단어 → 첫 단어)하며 재시도해 빈손 확률을 줄인다."""
    key = key or _load_key()
    if not key:
        return False
    words = (query or "").split()
    variants = [query]
    if len(words) > 2:
        variants.append(" ".join(words[:2]))
    if len(words) > 1:
        variants.append(words[0])
    tried = set()
    for q in variants:
        q = (q or "").strip()
        if not q or q in tried:
            continue
        tried.add(q)
        if _fetch_first(q, out_path, key):
            return True
    return False


GEMINI_IMAGE_MODELS = ("gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation")


def generate_gemini(desc: str, out_path: str, key: str | None = None) -> bool:
    """Unsplash에서 못 찾은 사진을, 설명(desc)으로 Gemini가 직접 생성해 out_path에 저장.
    REST(generateContent)로 호출하며, 실패하면 False."""
    key = key or _load_key("GEMINI_API_KEY")
    if not key or not (desc or "").strip():
        return False
    prompt = (
        "Generate a realistic, high-quality photograph for a blog post. "
        "No text, no watermark, no logo, natural lighting, clean composition. "
        f"Scene: {desc.strip()}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode("utf-8")
    for model in GEMINI_IMAGE_MODELS:
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for cand in data.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        with open(out_path, "wb") as f:
                            f.write(base64.b64decode(inline["data"]))
                        if os.path.getsize(out_path) > 1000:
                            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def translate_queries(descriptions: list[str]) -> list[str]:
    """한국어 사진 설명들을 Unsplash 검색용 영어 키워드로 변환(claude -p). 실패 시 원문 반환."""
    if not descriptions:
        return []
    try:
        from claude_cli import run_claude_p
        numbered = "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))
        prompt = (
            "다음 한국어 사진 설명들을 각각 Unsplash 사진 검색에 적합한 '짧은 영어 키워드'로 바꿔줘.\n"
            "규칙: 입력 순서 그대로, 한 줄에 하나씩, 번호·설명·따옴표 없이 영어 키워드만.\n\n"
            + numbered
        )
        out = run_claude_p(prompt, timeout=90)
        lines = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip().strip("\"'") for l in out.splitlines() if l.strip()]
        if len(lines) >= len(descriptions):
            return lines[:len(descriptions)]
    except Exception:  # noqa: BLE001
        pass
    return list(descriptions)


if __name__ == "__main__":
    ok = search_download("korean office planning whiteboard schedule", "/tmp/_unsplash_test.jpg")
    print("다운로드 성공:", ok, "| 키 로드:", bool(_load_key()))
    if ok:
        print("크기:", os.path.getsize("/tmp/_unsplash_test.jpg"))

# ---------------------------------------------------------------------------
# 🔴뭉개진(생성 미완성) 이미지 걸러내기 — 2026-09-09 신설
# ---------------------------------------------------------------------------
#: 그록/제미나이 웹은 **생성 중 흐린 미리보기**를 먼저 그린다. 그걸 그대로 저장하면
#  형체를 알아볼 수 없는 얼룩이 본문에 그대로 올라간다.
#  2026-09-09 실측 — 예약된 02편 마지막 사진이 그렇게 나갔고, 같은 설명으로 다시 뽑으니
#  **재현됐다**(고장 2장: 강한엣지 2.20%·2.24% / 정상 26장: 최소 4.99%).
#  → 두 배 넘게 벌어지므로 3.5%를 문턱으로 잡는다.
#  ⚠️md5 중복검사로는 절대 안 걸린다(파일은 매번 다르다).
BROKEN_EDGE_RATIO = 0.035


def is_broken_image(path: str, thresh: float = BROKEN_EDGE_RATIO) -> bool:
    """생성이 덜 끝난 '흐린 얼룩' 이미지면 True. 판별 못 하면 False(통과시킨다)."""
    try:
        from PIL import Image, ImageFilter
        im = Image.open(path).convert("L").resize((256, 256))
        e = list(im.filter(ImageFilter.FIND_EDGES).getdata())
        ratio = sum(1 for v in e if v > 60) / len(e)
        return ratio < thresh
    except Exception:  # noqa: BLE001
        return False
