"""공개 블로그 한 번 읽어서 내 정보를 채운다 (수강생 배포판 · 공통 모듈).

수강생이 클로드 코드에 "내 블로그는 blog.naver.com/○○○야, 분석해줘" 한마디만 하면
클로드 코드가 이 파일을 실행한다:

    python blog_analyze.py <블로그ID>

하는 일 (로그인 없이, 공개 페이지만 읽는다):
  · 블로그 이름 · 한줄소개(별명/소개) · 카테고리 목록 · 최근 글 제목 20개를 읽는다
  · 그걸로 내정보.txt 의 빈칸(블로그ID·이름·한줄소개·카테고리·주제)을 채운다
  · 블로그분석.md 를 폴더에 만든다 (주제·말투·자주 쓰는 소재 요약)

⚠️ 남의 계정에 로그인하지 않는다. 공개된 화면만 본다.
"""
import sys, os, re, json

BASE = os.path.dirname(os.path.abspath(__file__))
INFO = os.path.join(BASE, "내정보.txt")
ANALYSIS = os.path.join(BASE, "블로그분석.md")


# 네이버 블로그 화면의 메뉴·버튼 글자(제목·카테고리 아님)
_JUNK = {"내 블로그", "이웃블로그", "블로그 홈", "글 제목", "메뉴 바로가기", "본문 바로가기",
         "프롤로그", "블로그", "지도", "서재", "메모", "안부", "태그", "카테고리", "전체보기",
         "목록열기", "목록닫기", "이전", "다음", "댓글", "공감", "구독", "이웃추가", "RSS",
         "글쓰기", "관리", "통계", "더보기", "TOP", "맨위로", "검색", "최근 글", "인기글",
         "이전 화면으로", "다음 화면으로", "이 블로그 전체 카테고리 글", "블로그 마켓 가입 완료",
         "블로그 마켓 탈퇴가완료되었습니다.", "전체글", "이 블로그", "카테고리 글", "포스트"}


def _is_junk(s):
    if s in _JUNK:
        return True
    for bad in ("블로그 마켓", "카테고리 글", "화면으로", "전체 카테고리"):
        if bad in s:
            return True
    return False


def _clean(s):
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _fetch(blog_id):
    """Playwright로 공개 블로그를 읽어 dict 로 돌려준다."""
    from playwright.sync_api import sync_playwright
    out = {"blog_id": blog_id, "name": "", "intro": "", "categories": [], "titles": []}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        # 1) 블로그 이름 — 페이지 제목에서 (":: 블로그ID" 앞부분)
        try:
            pg.goto(f"https://blog.naver.com/{blog_id}", wait_until="networkidle", timeout=30000)
            title = _clean(pg.title())
            title = re.split(r"[:：|\-]", title)[0].strip()
            if title and title not in _JUNK and "네이버" not in title:
                out["name"] = title[:40]
        except Exception as e:
            print(f"[안내] 블로그 첫 화면을 못 읽었습니다: {e}")
        # 2) 카테고리 (카테고리 전용 프레임)
        try:
            pg.goto(f"https://blog.naver.com/CategoryList.naver?blogId={blog_id}",
                    wait_until="domcontentloaded", timeout=20000)
            for el in pg.query_selector_all("a"):
                s = _clean(el.inner_text())
                if s and not _is_junk(s) and s not in out["categories"] and 1 < len(s) < 20 \
                        and not s.isdigit():
                    out["categories"].append(s)
        except Exception:
            pass
        # 3) 최근 글 제목 (PostList 목록)
        try:
            pg.goto(f"https://blog.naver.com/PostList.naver?blogId={blog_id}&categoryNo=0&from=postList",
                    wait_until="networkidle", timeout=30000)
            fr = pg.frame(name="mainFrame") or pg
            for el in fr.query_selector_all(".se-title-text, strong.itemSubjectBoldfont, .title, .pcol1"):
                s = _clean(el.inner_text())
                if s and not _is_junk(s) and s not in out["titles"] and 4 < len(s) < 60 \
                        and not s.isdigit():
                    out["titles"].append(s)
                if len(out["titles"]) >= 20:
                    break
        except Exception as e:
            print(f"[안내] 글 목록을 다 못 읽었습니다(공개 글이 적거나 화면이 바뀐 경우): {e}")
        b.close()
    # 정리: 카테고리/제목에서 서로 겹치는 메뉴 글자 한 번 더 제거
    out["categories"] = [c for c in out["categories"] if not _is_junk(c)][:12]
    out["titles"] = [t for t in out["titles"] if not _is_junk(t)][:20]
    if not out["name"]:
        out["name"] = blog_id
    return out


def _guess_topic(info):
    """카테고리·제목에서 주제를 대충 뽑는다(참고용, 사람이 고칠 수 있게)."""
    words = " ".join(info["categories"] + info["titles"])
    for key in ("맛집", "카페", "여행", "건강", "육아", "재테크", "부동산", "주식",
                "요리", "인테리어", "반려", "운동", "뷰티", "패션", "IT", "AI", "교육", "책"):
        if key in words:
            return key
    for c in info["categories"]:
        if not _is_junk(c):
            return c
    return "(직접 적어주세요)"


def _fill_info(info):
    """내정보.txt 의 빈칸만 채운다(이미 적은 값은 건드리지 않는다)."""
    if not os.path.exists(INFO):
        print(f"[안내] 내정보.txt 가 없어 새로 만들 수 없습니다. 패키지 폴더에서 실행하세요.")
        return
    lines = open(INFO, encoding="utf-8").read().splitlines()
    topic = _guess_topic(info)
    fill = {
        "내 블로그ID": info["blog_id"],
        "내 블로그 이름": info["name"],
        "내 블로그 주제": topic,
        "내 카테고리": ", ".join(info["categories"][:5]),
    }
    out = []
    for ln in lines:
        done = False
        for k, v in fill.items():
            if ln.startswith(k) and ":" in ln and v:
                cur = ln.split(":", 1)[1].strip()
                if not cur or cur.startswith("("):   # 빈칸일 때만
                    out.append(f"{k}: {v}")
                    done = True
                    break
        if not done:
            out.append(ln)
    open(INFO, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("[완료] 내정보.txt 의 빈칸을 채웠습니다. (이미 적으신 값은 그대로 뒀습니다)")


def _write_analysis(info):
    topic = _guess_topic(info)
    md = [f"# 블로그 분석 — {info['name']} (blog.naver.com/{info['blog_id']})", ""]
    md += ["> 공개 화면만 읽어 자동 정리한 참고 자료입니다. 클로드 코드가 글을 쓸 때 씁니다.", ""]
    md += ["## 주제", f"- {topic}", ""]
    cats = [f"- {c}" for c in info["categories"]] or ["- (못 읽음)"]
    titles = [f"- {t}" for t in info["titles"]] or ["- (못 읽음)"]
    md += ["## 카테고리"] + cats + [""]
    md += ["## 최근 글 제목 (말투·자주 쓰는 소재 참고)"] + titles
    md += ["", "## 말투·소재 메모",
           "- 위 제목들의 말투(반말/존댓말, 감성/정보)를 따라간다.",
           "- 자주 나오는 소재를 이어서 쓴다(같은 독자가 온다).",
           "- ⚠️ 자동 요약이라 틀릴 수 있습니다. 클로드 코드에게 고쳐 달라고 하세요."]
    open(ANALYSIS, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"[완료] 블로그분석.md 를 만들었습니다.")


def main():
    if len(sys.argv) < 2:
        print("사용법: python blog_analyze.py <블로그ID>   (예: python blog_analyze.py abcd1234)")
        sys.exit(1)
    blog_id = sys.argv[1].strip().rstrip("/").split("/")[-1]
    print(f"[시작] blog.naver.com/{blog_id} 공개 화면을 읽습니다...")
    try:
        info = _fetch(blog_id)
    except Exception as e:
        print(f"\n[멈춤] 크롬 부품이 없거나 인터넷 문제입니다: {e}\n"
              "  설치_윈도우.bat 를 다시 한 번 더블클릭해 주세요.")
        sys.exit(1)
    print(f"  이름: {info['name']} · 카테고리 {len(info['categories'])}개 · 최근 글 {len(info['titles'])}개")
    _fill_info(info)
    _write_analysis(info)
    print("\n다 됐습니다. 내정보.txt 와 블로그분석.md 를 확인해 보세요.")


if __name__ == "__main__":
    main()
