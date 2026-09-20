"""생성용 템플릿 채우기: 강점시각화/장점/맹점/표 HTML + 실사 썸네일(제미나이 사진+텍스트 오버레이, 폴백 OpenAI)."""
from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.request

# 키는 내정보.txt(myinfo)에서 읽는다. .env 는 이 패키지 폴더에 있으면만 쓴다(선택).
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _env_key(name: str) -> str | None:
    try:
        for line in pathlib.Path(_ENV).read_text(errors="ignore").splitlines():
            if line.strip().startswith(name) and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return None


def _openai_key() -> str | None:
    return _env_key("OPENAI_API_KEY")


def _gemini_key() -> str | None:
    return _env_key("GEMINI_API_KEY")


def write_cards(out_dir: str, no: str, ko: str, en: str, c: dict, include_table: bool = True) -> None:
    stem = f"{no}_{ko}"
    li = lambda items: "".join(f'<li style="margin-bottom:6px">{x}</li>' for x in items)
    rows = [["한국어(English)", f"{ko}({en})"]] + c.get("표", [])
    trs = ""
    for i, (label, val) in enumerate(rows):
        bg = "#e8eaf6" if i % 2 else "#ffffff"
        trs += (f'<tr style="background:{bg}"><td style="width:30%;border:1px solid #ddd;padding:10px 14px;'
                f'font-weight:600">{label}</td><td style="width:70%;border:1px solid #ddd;padding:10px 14px">{val}</td></tr>')

    viz = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#faf7ef">
<div style="max-width:560px;margin:auto;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.08)">
<div style="background:linear-gradient(135deg,#fff8e1,#f6e7b8);padding:18px 22px">
<div style="font-size:13px;color:#8a6d00;letter-spacing:2px">GALLUP 강점 인사이트</div>
<div style="font-size:30px;font-weight:800;color:#1a237e">{ko}<span style="font-size:15px;color:#8a6d00;margin-left:8px">({en})</span></div></div>
<div style="padding:16px 22px;background:#fffdf7"><div style="font-size:12px;color:#999;margin-bottom:4px">핵심 정의</div>
<div style="font-size:15px;color:#333;line-height:1.6">{c.get('정의','')}</div></div>
<div style="padding:16px 22px;background:#e8f0fe"><div style="font-size:12px;color:#1a237e;font-weight:700;margin-bottom:4px">힘과 차별성</div>
<div style="font-size:15px;color:#333;line-height:1.6">{c.get('힘','')}</div></div>
<div style="padding:16px 22px;background:#e7f6ec"><div style="font-size:12px;color:#1b7a3e;font-weight:700;margin-bottom:4px">장벽이 되는 순간</div>
<div style="font-size:15px;color:#333;line-height:1.6">{c.get('장벽','')}</div></div>
<div style="padding:16px 22px;background:#f0e8fb"><div style="font-size:12px;color:#6a1b9a;font-weight:700;margin-bottom:4px">활용 팁</div>
<div style="font-size:15px;color:#333;line-height:1.6">{c.get('팁','')}</div></div>
<div style="padding:16px 22px;background:linear-gradient(135deg,#fff8e1,#f6e7b8)"><div style="font-size:12px;color:#8a6d00;font-weight:700;margin-bottom:6px">3단계 실행 (Name·Claim·Aim)</div>
<div style="font-size:14px;color:#333;line-height:1.7">{c.get('삼단계','')}</div></div></div>
<div style="max-width:560px;margin:8px auto 0;font-size:12px;color:#999;text-align:right">@출처 - Gallup, Inc.</div></body></html>"""

    merit = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:22px;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#eef4ff">
<div style="max-width:460px;margin:auto;border-radius:14px;background:#e8f0fe;padding:22px 24px;box-shadow:0 2px 10px rgba(0,0,0,.06)">
<div style="font-size:20px;font-weight:800;color:#1a237e;margin-bottom:12px">{ko}의 힘</div>
<ul style="font-size:15px;color:#333;line-height:1.6;padding-left:20px;margin:0">{li(c.get('장점',[]))}</ul>
<div style="margin-top:14px;padding-top:12px;border-top:1px dashed #9fb4e6;font-size:14px;color:#1a237e;font-weight:600">한 줄 요약 · {c.get('장점요약','')}</div></div>
<div style="max-width:460px;margin:8px auto 0;font-size:12px;color:#999;text-align:right">@출처 - Gallup, Inc.</div></body></html>"""

    blind = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:22px;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#eefaf1">
<div style="max-width:460px;margin:auto;border-radius:14px;background:#e7f6ec;padding:22px 24px;box-shadow:0 2px 10px rgba(0,0,0,.06)">
<div style="font-size:20px;font-weight:800;color:#1b7a3e;margin-bottom:12px">{ko}의 맹점</div>
<ul style="font-size:15px;color:#333;line-height:1.6;padding-left:20px;margin:0">{li(c.get('맹점',[]))}</ul>
<div style="margin-top:14px;padding-top:12px;border-top:1px dashed #9fd6ae;font-size:14px;color:#1b7a3e;font-weight:600">보완 팁 · {c.get('맹점보완','')}</div></div>
<div style="max-width:460px;margin:8px auto 0;font-size:12px;color:#999;text-align:right">@출처 - Gallup, Inc.</div></body></html>"""

    table = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:16px;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif">
<table style="border-collapse:collapse;max-width:620px;width:100%;font-size:15px">
<thead><tr><th colspan="2" style="background:#1a237e;color:#fff;padding:10px 14px;text-align:left;font-size:16px">강점 인사이트 · {ko}({en}) 한눈에 정리</th></tr></thead>
<tbody>{trs}</tbody></table>
<div style="max-width:620px;font-size:12px;color:#999;text-align:right;margin-top:6px">@출처 - Gallup, Inc.</div></body></html>"""

    pairs = [("강점시각화", viz), ("장점", merit), ("맹점", blind)]
    if include_table:
        pairs.append(("강점인사이트_표", table))
    for suffix, html in pairs:
        with open(os.path.join(out_dir, f"{stem}_{suffix}.html"), "w", encoding="utf-8") as f:
            f.write(html)


def write_celeb_table(out_dir: str, no: str, keyword: str, title: str, rows: list) -> None:
    """연예 글용 표(인물의 장면→강점 포인트→해석). rows: [[왼쪽,오른쪽], ...]."""
    trs = ""
    for i, row in enumerate(rows):
        label, val = (row + ["", ""])[:2]
        bg = "#eef2ff" if i % 2 else "#ffffff"
        trs += (f'<tr style="background:{bg}"><td style="width:32%;border:1px solid #dcdfe6;padding:10px 14px;'
                f'font-weight:600;color:#1a237e">{label}</td>'
                f'<td style="width:68%;border:1px solid #dcdfe6;padding:10px 14px;color:#333">{val}</td></tr>')
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:16px;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif">
<table style="border-collapse:collapse;max-width:620px;width:100%;font-size:15px">
<thead><tr><th colspan="2" style="background:#1a237e;color:#fff;padding:11px 14px;text-align:left;font-size:16px">{title}</th></tr></thead>
<tbody>{trs}</tbody></table>
<div style="max-width:620px;font-size:12px;color:#aaa;text-align:right;margin-top:6px">강점 분석 · 갤럽 공인 강점코치 관점</div></body></html>"""
    with open(os.path.join(out_dir, f"{no}_{keyword}_표.html"), "w", encoding="utf-8") as f:
        f.write(html)


def render_text_thumbnail(out_dir: str, filename: str, thumb: dict,
                          footer: str = "강점코치 에디의 시선") -> bool:
    """실인물 사진 없이(초상권 안전) 텍스트 중심 1:1 썸네일. 연예/이슈/쇼핑 글용.
    thumb: {intro, big, tail, badge}."""
    from playwright.sync_api import sync_playwright
    big = thumb.get("big", "")
    big_fs = 150 if len(big) <= 3 else (120 if len(big) <= 5 else (96 if len(big) <= 8 else 76))
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif">
<div id="card" style="position:relative;width:1024px;height:1024px;overflow:hidden;
 background:linear-gradient(150deg,#12224f 0%,#1b3a7a 55%,#2456b0 100%)">
<div style="position:absolute;left:-120px;top:-120px;width:420px;height:420px;border-radius:50%;background:rgba(224,181,58,.18)"></div>
<div style="position:absolute;right:-160px;bottom:-160px;width:520px;height:520px;border-radius:50%;background:rgba(255,255,255,.06)"></div>
<div style="position:absolute;left:72px;top:110px;right:72px;color:#fff">
<div style="display:inline-block;background:#e0b53a;color:#12224f;font-weight:800;font-size:30px;padding:8px 20px;border-radius:10px">{thumb.get('badge','강점 분석')}</div>
<div style="font-size:44px;font-weight:800;margin-top:34px;line-height:1.3;letter-spacing:-1px">{thumb.get('intro','')}</div>
<div style="width:170px;height:7px;background:#e0b53a;margin:22px 0 18px"></div>
<div style="font-size:{big_fs}px;font-weight:900;line-height:1.05;letter-spacing:-4px">{big}</div>
<div style="font-size:52px;font-weight:800;margin-top:20px;letter-spacing:-1px;color:#dce6ff">{thumb.get('tail','')}</div>
</div>
<div style="position:absolute;left:72px;bottom:70px;color:#aebee6;font-size:28px;font-weight:600">{footer}</div>
</div></body></html>"""
    hp = os.path.join(out_dir, "_ovl_celeb.html")
    open(hp, "w", encoding="utf-8").write(html)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1024, "height": 1024})
            pg.goto("file://" + hp)
            pg.wait_for_timeout(300)
            pg.locator("#card").screenshot(path=os.path.join(out_dir, filename))
            b.close()
    finally:
        try:
            os.remove(hp)
        except OSError:
            pass
    return True


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
_IMAGEN_MODELS = ("imagen-4.0-generate-001", "imagen-3.0-generate-002")
_GFLASH_MODELS = ("gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation")


def _gemini_imagen(full: str, key: str) -> bytes | None:
    """제미나이 Imagen(:predict) — 1:1 지원."""
    body = json.dumps({"instances": [{"prompt": full}],
                       "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}}).encode()
    for model in _IMAGEN_MODELS:
        req = urllib.request.Request(f"{_GEMINI_BASE}{model}:predict?key={key}", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=180).read())
            b64 = (r.get("predictions") or [{}])[0].get("bytesBase64Encoded")
            if b64:
                return base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            continue
    return None


def _gemini_flash(full: str, key: str) -> bytes | None:
    """제미나이 flash 이미지(generateContent) — inlineData 반환."""
    body = json.dumps({"contents": [{"parts": [{"text": full}]}],
                       "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}).encode()
    for model in _GFLASH_MODELS:
        req = urllib.request.Request(f"{_GEMINI_BASE}{model}:generateContent?key={key}", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=180).read())
            for part in r["candidates"][0]["content"]["parts"]:
                inl = part.get("inlineData") or part.get("inline_data")
                if inl and inl.get("data"):
                    return base64.b64decode(inl["data"])
        except Exception:  # noqa: BLE001
            continue
    return None


def _gen_photo(prompt: str, out_path: str) -> bool:
    """인물 실사 사진 생성. 제미나이(더 저렴) 우선, 실패 시 오픈AI 폴백."""
    full = (prompt + " 사실적인 실사 사진, 자연광. 인물은 화면 오른쪽에 배치하고 왼쪽 3분의 1은 밝은 여백. 글자·텍스트 없음.")
    # 1) 제미나이 우선(Imagen → flash)
    gkey = _gemini_key()
    if gkey:
        for fn in (_gemini_imagen, _gemini_flash):
            try:
                data = fn(full, gkey)
            except Exception:  # noqa: BLE001
                data = None
            if data:
                open(out_path, "wb").write(data)
                return True
    # 2) 폴백: 오픈AI(gpt-image-1)
    okey = _openai_key()
    if okey:
        body = json.dumps({"model": "gpt-image-1", "prompt": full,
                           "size": "1024x1024", "quality": "medium"}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=body,
                                     headers={"Authorization": f"Bearer {okey}", "Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=180).read())
            open(out_path, "wb").write(base64.b64decode(r["data"][0]["b64_json"]))
            return True
        except Exception:  # noqa: BLE001
            pass
    return False


def render_thumbnail(out_dir: str, filename: str, ko: str, thumb: dict) -> bool:
    """OpenAI 인물 사진 + HTML 텍스트 오버레이로 1:1 실사 썸네일."""
    from playwright.sync_api import sync_playwright
    photo = os.path.join(out_dir, "_photo.png")
    if not _gen_photo(thumb.get("photo", f"{ko}을 상징하는 40대 한국 직장인"), photo):
        return False
    big_fs = 132 if len(ko) <= 2 else (112 if len(ko) <= 4 else 92)
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif">
<div id="card" style="position:relative;width:1024px;height:1024px;overflow:hidden;background:#efece6 url('file://{photo}') no-repeat center/cover">
<div style="position:absolute;inset:0;background:linear-gradient(90deg,rgba(247,245,240,.96) 0%,rgba(247,245,240,.9) 34%,rgba(247,245,240,.45) 46%,rgba(247,245,240,0) 56%)"></div>
<div style="position:absolute;left:70px;top:96px;width:480px;color:#12224f">
<div style="font-size:46px;font-weight:800;letter-spacing:-1px">{thumb.get('intro','')}</div>
<div style="width:200px;height:6px;background:#e0b53a;margin:14px 0 6px"></div>
<div style="font-size:{big_fs}px;font-weight:900;line-height:1.05;letter-spacing:-4px;color:#16224e;white-space:nowrap">{ko}</div>
<div style="font-size:50px;font-weight:800;margin-top:6px;letter-spacing:-1px">{thumb.get('tail','')}</div>
<div style="display:inline-block;margin-top:26px;background:#16224e;color:#fff;border-radius:16px;padding:16px 24px;font-size:35px;font-weight:700;line-height:1.35">{thumb.get('box','')}<br><span style="font-weight:800">이 강점</span></div>
<div style="margin-top:26px;font-size:31px;font-weight:800;color:#16224e;display:flex;align-items:center;gap:10px">
<span style="display:inline-flex;width:40px;height:40px;border:3px solid #e0b53a;border-radius:50%;align-items:center;justify-content:center;color:#e0b53a;font-size:24px">&#10003;</span><span>{thumb.get('check','')}</span></div>
</div></div></body></html>"""
    hp = os.path.join(out_dir, "_overlay.html")
    open(hp, "w", encoding="utf-8").write(html)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1024, "height": 1024})
            pg.goto("file://" + hp)
            pg.wait_for_timeout(400)
            pg.locator("#card").screenshot(path=os.path.join(out_dir, filename))
            b.close()
    finally:
        for tmp in (photo, hp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return True
