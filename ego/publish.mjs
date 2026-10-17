// 데일리텐 ⑤단계 — ego lite로 네이버에 글을 넣고 예약 발행한다 (2026-09-23 신설)
//   Playwright 대신 ego lite를 쓰는 이유(에디님): 사람이 클릭하는 방식이라 네이버가 AI로 보지 않아
//   임시저장이 아니라 **직접 발행**해도 안전하다.
// 입력: JSON 파일 경로 (argv[0]) — {title, blocks, category, align, tags, mode, schedule, profileId, spaceName}
//   mode: "draft"(임시저장) | "publish"(발행)  · schedule: {date:"2026.09.24", hour:"08", minute:"00"} | null
const fs = await import("node:fs/promises");

// 경로는 호출측(Python)이 이 스크립트 앞에 `const PAYLOAD_PATH = "...";` 한 줄을 붙여 준다.
//   ego 런타임에는 argv·env가 넘어오지 않는다(실측 2026-09-23).
const payloadPath = (typeof PAYLOAD_PATH !== "undefined") ? PAYLOAD_PATH : "/tmp/ego_payload.json";
const P = JSON.parse(await fs.readFile(payloadPath, "utf-8"));
const WRITE_URL = `https://blog.naver.com/${P.blogId}?Redirect=Write&`;
const log = (...a) => console.log("[ego]", ...a);

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// spans: [[start, end, {bold, color, bg}], ...] → HTML
function toHtml(text, spans) {
  if (!spans || !spans.length) return esc(text).replace(/\n/g, "<br>");
  const marks = [...spans].sort((a, b) => a[0] - b[0]);
  let out = "", cur = 0;
  for (const [s, e, st] of marks) {
    if (s < cur || s > text.length) continue;
    out += esc(text.slice(cur, s));
    let style = "";
    if (st.color) style += `color:${st.color};`;
    if (st.bg) style += `background-color:${st.bg};`;
    let piece = esc(text.slice(s, e));
    if (st.bold) piece = `<b>${piece}</b>`;
    out += style ? `<span style="${style}">${piece}</span>` : piece;
    cur = e;
  }
  out += esc(text.slice(cur));
  return out.replace(/\n/g, "<br>");
}

// ⚠️profileId는 **새 공간을 만들 때만** 받는다 — 이미 있는 공간에 넘기면 오류가 난다(실측).
//   처음엔 프로필을 지정해 만들고(데일리텐 계정), 그다음부터는 빼고 재사용한다.
const _spaceName = P.spaceName || "데일리텐 발행";
let task;
try {
  task = await taskSpace(_spaceName, P.profileId ? { profileId: P.profileId } : undefined);
} catch (e) {
  task = await taskSpace(_spaceName);
}
const page = task.page("p1");

// 🔴**쓴 공간은 닫는다**(2026-10-10 에디님: 「에고라이트 창이 쌓여서 팬이 계속 돈다」).
//   실측(CEO 창, 10/10 10:35): 작업 공간 **9개**가 남아 CPU **약 160%**(헬퍼 82% + 본체 37% +
//   렌더러 3개 ~45%)를 쓰고 있었다. 대부분 네이버 글쓰기 화면이고 **11시간째** 떠 있었다.
//   닫으니 12% 안팎으로 떨어졌다. 공간은 **이름으로 다시 만들어진다**(위 try/catch가 그대로 받는다).
//   ★`finish({keep:[]})`가 맞는 호출이다(실측: `close`·`dispose`는 없다. 닫은 뒤 목록에서 사라진다).
//   ★에디님이 직접 쓰고 계신 공간은 건드리지 않는다 — 우리가 만든 이 공간만 닫는다.
//     실패해도 삼킨다. **공간을 못 닫았다고 발행을 실패로 만들지 않는다.**
let _closed = false;
async function closeSpace() {
  if (_closed) return;
  _closed = true;
  try { await task.finish({ keep: [] }); log("작업 공간 닫음 ·", task.spaceId); }
  catch (e) { log("작업 공간을 못 닫았습니다(그대로 둡니다):", String(e).slice(0, 80)); }
}
// 나가는 길이 여러 갈래다(정상 끝 · exit 2·3·4 · 예외) — **모든 갈래에서** 닫는다.
process.on("unhandledRejection", async (e) => {
  console.log(JSON.stringify({ ok: false, why: `드라이버 예외: ${String(e).slice(0, 160)}` }));
  await closeSpace();
  process.exit(5);
});

// ── 1) 글쓰기 화면 ──────────────────────────────────────────────
// 작성 중 내용이 있으면 «나가시겠습니까» 대화상자가 뜬다 → 수락하고 다시 이동
try { await page.goto(WRITE_URL); }
catch (e) { try { await page.acceptDialog(); } catch {} await page.waitForTimeout(800); await page.goto(WRITE_URL); }
try { await page.dismissDialog(); log("네이티브 팝업 → 취소"); } catch { /* 없으면 통과 */ }
await page.waitForTimeout(2500);
// 🔴화면 크기 0 — 2026-10-14 집 맥 첫 아침: 창은 «최대화»인데 페이지 폭·높이가 0×0이라
//   «iframe is not visible»로 데일리텐 0편. 창을 normal로 풀고 크기를 다시 주면 살아난다(실측 1668×809).
try {
  const _sz = await page.evaluate(() => [innerWidth, innerHeight]);
  if (!_sz[0] || !_sz[1]) {
    const _w = await task.cdp("Browser.getWindowForTarget", { targetId: page.targetId });
    await task.cdp("Browser.setWindowBounds", { windowId: _w.windowId, bounds: { windowState: "normal" } });
    await task.cdp("Browser.setWindowBounds", { windowId: _w.windowId, bounds: { left: 100, top: 60, width: 1280, height: 900 } });
    await page.waitForTimeout(1500);
    log("화면 크기 0 → 창 다시 펼침:", JSON.stringify(await page.evaluate(() => [innerWidth, innerHeight])));
  }
} catch (e) { log("화면 크기 확인 실패(그대로 진행):", String(e).slice(0, 80)); }

// 🔴«작성 중인 글이 있습니다» — 페이지 안 모달이라 버튼을 눌러야 한다(네이티브 팝업 아님).
//   «취소»를 눌러 **새 글로 시작**한다. 확인을 누르면 지난 내용이 딸려 들어온다.
try {
  const snap0 = await page.snapshot();
  if (snap0.includes("작성 중인 글이 있습니다")) {
    await page.click('text="취소"', { label: "start a new post" });
    log("«작성 중인 글» 모달 → 취소(새 글로 시작)");
    await page.waitForTimeout(1200);
  }
} catch (e) { log("모달 처리 건너뜀:", String(e).slice(0, 60)); }

// 🔴**에디터 iframe이 «보이는» 상태가 될 때까지 기다린다**(2026-10-07).
//   10/7에 조립까지 다 해놓고 `page.click failed: iframe is not visible`로 **그날 0편**이 됐다.
//   창이 뒤에 있거나 에디터가 늦게 뜨면 2.5초 고정 대기로는 모자라다.
//   → 제목 칸이 보일 때까지 기다리고, 안 되면 **한 번 새로 고친 뒤** 다시 기다린다.
for (const attempt of [1, 2]) {
  try {
    await page.waitForSelector("css=.se-section-documentTitle .se-text-paragraph",
                               { state: "visible", timeout: 20000 });
    break;
  } catch (e) {
    if (attempt === 2) {
      console.log(JSON.stringify({ ok: false, why: `에디터가 안 열립니다(iframe 안 보임): ${String(e).slice(0, 120)}` }));
      await closeSpace();
      process.exit(4);
    }
    log("에디터가 아직 안 보입니다 — 새로 고치고 다시 기다립니다");
    try { await page.reload(); } catch {}
    await page.waitForTimeout(3000);
    try { const s2 = await page.snapshot();
          if (s2.includes("작성 중인 글이 있습니다")) await page.click('text="취소"'); } catch {}
  }
}

// 🔴계정 확인 — 다른 블로그에 올리는 사고를 막는다(2026-08-12 전례)
const url = await page.url();
if (!url.includes(P.blogId)) {
  console.log(JSON.stringify({ ok: false, why: `다른 계정 로그인: ${url}` }));
  await closeSpace();
  process.exit(2);
}

// ── 2) 제목 ────────────────────────────────────────────────────
// 제목 칸 — placeholder 글자를 누르면 덮은 div가 가로챈다. 검증된 CSS(naver.SEL_TITLE)를 쓴다.
await page.click("css=.se-section-documentTitle .se-text-paragraph", { label: "focus title" });
await page.waitForTimeout(400);
await page.keyboard.insertText(P.title);
log("제목 입력:", P.title.slice(0, 40));
await page.waitForTimeout(400);
await page.keyboard.press("Enter");          // 제목 → 본문으로 이동
await page.waitForTimeout(600);

// ★연예편 가운데정렬(2026-08-31 에디님) — 본문 시작 전에 한 번만 누르면 이후 문단이 따라온다.
if (P.align === "center") {
  try { await page.keyboard.press("Control+Shift+E"); log("본문 가운데정렬 적용"); }
  catch (e) { log("가운데정렬 실패(무시):", String(e).slice(0, 50)); }
}

// ── 3) 본문 블록 ───────────────────────────────────────────────
const notes = [];
let images = 0;

async function insertImage(b) {
  // ★프라미스를 먼저 만들되 **catch를 붙여 둔다** — 버튼 클릭이 막히면 잡히지 않은 거부로
  //   노드 프로세스가 통째로 죽는다(2026-09-23 실측: 인용구 패널이 사진 버튼을 덮어 exit 1).
  // ⚠️`>> nth=N`은 CSS·text·href 선택자에만 쓴다 — role 선택자에 붙이면 «Invalid locator»다(실측).
  const chooser = page.waitForFileChooser({ timeout: 12000 }).catch(() => null);
  try {
    await page.click('loc=role:button[name="사진 추가"]', { label: "add photo" });
  } catch (e) {
    await chooser;          // ★대기를 반드시 끝낸다 — 안 그러면 다음 편에서 «already waiting»이 난다
    throw e;
  }
  const ch = await chooser;
  if (!ch) throw new Error("파일 선택창이 안 열림(툴바가 가려졌을 수 있음)");
  await ch.setFiles(b.path);
  await page.waitForTimeout(3500);
  images += 1;
  if (b.caption) {
    // ★캡션 칸(div.se-caption)은 이미지를 클릭하기 전엔 크기가 0이라 바로 못 누른다(실측).
    //   ①이미지 클릭 → ②캡션 클릭 → ③타이핑 → ④본문 끝 복귀(안 하면 다음 문장이 캡션에 붙는다).
    try {
      await page.click("css=.se-component.se-image .se-image-resource >> nth=-1", { label: "select image" });
      await page.waitForTimeout(700);
      await page.click("css=div.se-caption >> nth=-1", { label: "focus caption" });
      await page.waitForTimeout(300);
      await page.keyboard.insertText(b.caption);
      await page.waitForTimeout(350);
      await page.keyboard.press("Escape");
      await page.waitForTimeout(200);
      await page.click("css=.se-component.se-text .se-text-paragraph >> nth=-1", { label: "back to body" });
      await page.waitForTimeout(200);
      await page.keyboard.press("ControlOrMeta+ArrowDown");
    } catch (e) { notes.push(`캡션 실패: ${b.caption.slice(0, 20)} / ${String(e).slice(0,60)}`); }
  }
}

// 프레임(#mainFrame) 안의 버튼 상태를 읽고 누르는 헬퍼 — evaluate는 최상위 문서에서 도니 프레임을 직접 짚는다.
const frameDoc = () => {
  const f = document.querySelector("#mainFrame");
  return (f && f.contentDocument) ? f.contentDocument : document;
};

const RED = "rgb(255, 0, 16)", BLACK = "rgb(0, 0, 0)";

// 🔴굵게 단추 찾기(2026-10-09 실측) — `se-bold-toolbar-button`은 **떠 있는 툴바**에만 있어서
//   캐럿만 있을 때는 없다(클릭 3초 시간초과). 반면 **`button[class*="bold"]`는 캐럿만 있어도 먹는다**
//   — 실측으로 `<b>버튼굵게</b>`가 박혔고 색도 그대로 유지됐다.
//   ⚠️그 단추의 **정확한 이름은 어느 문서에서도 못 찾았다**(최상위·mainFrame·안쪽 iframe 전수 조사 0건 —
//     섀도 DOM으로 보인다). 그래서 «이름»이 아니라 «먹히는 선택자»를 쓰고, **결과로 확인**한다.
//   🔴단축키는 쓰지 말 것: `Control+b`는 맥에서 **캐럿을 한 글자 뒤로 옮겨** 글자를 뒤섞는다
//     (실측: 「B앞 컨트롤굵게 뒤」가 「B앞컨트롤굵 뒤게」로 박혔다). `Meta+b`는 문단을 비웠다.
const BOLD_SELS = ['css=button.se-bold-toolbar-button >> nth=0', 'css=button[class*="bold"] >> nth=0'];
let boldSel = null;
async function toggleBold() {
  if (boldDead) return false;
  if (boldSel) {
    try { await page.click(boldSel, { label: "bold" }); await page.waitForTimeout(160); return true; }
    catch (err) { boldDead = true; log("  ⚠️굵게 단추가 사라졌습니다 — 색만 입힙니다"); return false; }
  }
  for (const sel of BOLD_SELS) {
    try {
      await page.click(sel, { label: "bold", timeout: 2500 });
      await page.waitForTimeout(160);
      boldSel = sel;
      log("  [굵게] 단추:", sel);
      return true;
    } catch (err) { /* 다음 후보 */ }
  }
  boldDead = true;
  log("  ⚠️굵게 단추를 못 찾았습니다 — 이 편에서는 색만 입힙니다");
  return false;
}
// 팔레트가 열려 있는지 — 열린 채 남으면 다음 툴바 클릭이 통째로 막힌다(2026-09-23 실측).
async function paletteOpen() {
  return await page.evaluate(() => {
    const f = document.querySelector("#mainFrame");
    const d = (f && f.contentDocument) ? f.contentDocument : document;
    const p = [...d.querySelectorAll(".se-color-palette, [class*=color-palette]")];
    return p.some(x => x.offsetParent || x.getClientRects().length);
  });
}
async function closePalette() {
  for (let i = 0; i < 3; i++) {
    if (!(await paletteOpen())) return true;
    await page.keyboard.press("Escape");
    await page.waitForTimeout(250);
  }
  return !(await paletteOpen());
}
async function pickSwatch(rgb) {
  return await page.evaluate((want) => {
    const f = document.querySelector("#mainFrame");
    const d = (f && f.contentDocument) ? f.contentDocument : document;
    const btns = [...d.querySelectorAll("button.se-color-palette, .se-color-palette button, button[class*=color-palette]")];
    const t = btns.find(b => ((b.getAttribute("style") || "").replace(/\s+/g, "")).includes(String(want).replace(/\s+/g, "")));
    if (t) { t.click(); return true; }
    return false;
  }, rgb);
}
async function setFontColor(rgb) {
  try {
    await page.click("css=button.se-font-color-toolbar-button >> nth=0", { label: "font color" });
    await page.waitForTimeout(500);
    const ok = await pickSwatch(rgb);
    await page.waitForTimeout(250);
    const closed = await closePalette();
    log("  [색]", rgb, ok ? "적용" : "스와치 못찾음", closed ? "" : "(팔레트 안 닫힘)");
    await page.waitForTimeout(200);
  } catch (e) { log("  🔴[색] 실패", String(e).slice(0, 90)); }
}
async function setBgColor(rgb) {
  try {
    // 🔴«보일 때까지» 기다리지 말 것 — 이 버튼은 보이는 것으로 안 잡히는데 클릭은 먹는다
    //   (2026-10-09 실측: offsetParent·getClientRects로 세면 0개인데 클릭은 성공한다).
    //   기다리면 4초마다 시간초과로 **노랑이 통째로 빠진다.**
    await page.click("css=button.se-background-color-toolbar-button >> nth=0", { label: "highlight" });
    await page.waitForTimeout(500);
    const ok = await pickSwatch(rgb);
    await page.waitForTimeout(250);
    const closed = await closePalette();
    log("  [배경]", rgb, ok ? "적용" : "스와치 못찾음", closed ? "" : "(팔레트 안 닫힘)");
    await page.waitForTimeout(200);
  } catch (e) { log("  🔴[배경] 실패", String(e).slice(0, 90)); }
}
async function clearBgColor() {
  try {
    await page.click("css=button.se-background-color-toolbar-button >> nth=0", { label: "clear highlight" });
    await page.waitForTimeout(500);
    const ok = await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      const d = (f && f.contentDocument) ? f.contentDocument : document;
      const b = [...d.querySelectorAll("button")].find(x => (x.textContent || "").trim() === "색상 없음" && (x.offsetParent || x.getClientRects().length));
      if (b) { b.click(); return true; }
      return false;
    });
    if (!ok) await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  } catch {}
}

// 🔴🔴서식 적용 방식 — **2026-10-09에 ③에서 ②로 되돌렸다**(ego 창에서 직접 재서 뒤집었다)
//   ①붙여넣기(HTML) → 네이버가 인라인 스타일을 덮어써 빨강·노랑이 전부 회색이 된다. ❌
//   ③평문으로 치고 **범위를 선택해** 서식을 건다(9/23~10/8) → **이제 안 된다.** ❌
//      10/9에 ego 창에서 재보니 네이버 에디터가 키 입력을 **숨은 `IFRAME#input_buffer…`**(IME 버퍼)로
//      받는다. 포커스가 거기 있어서 `insertText`(글자 넣기)는 먹지만 **선택을 만드는 방법이 없다**:
//        · `Home`·`ArrowRight`·`Shift+ArrowRight`·`Meta+a` → anchorOffset이 꼼짝하지 않음(`type:"Caret"`)
//        · 문단을 **클릭한 뒤**에도 같다(10/8까지 되던 길인데 지금은 안 된다 → 10/8 커밋이 원인이 아니다)
//        · 마우스 드래그·Shift+클릭·더블클릭 → 전부 캐럿만 움직이고 선택 0
//        · DOM Range는 선택이 잡히지만 **에디터가 자기 내부 모델에만 서식을 건다** →
//          팔레트는 «적용»을 찍는데 문단 HTML에 스타일이 **안 박힌다**(`execCommand`도 전부 false).
//   ②**서식을 켜고 타이핑한다** → ⭕ **이것만 실제로 박힌다**(10/9 실측):
//        빨강 `style="color: rgb(255, 0, 16)"` · 노랑 `se-highlight` + `<mark>` + `background-color`
//        끄기도 된다(검정 스와치 · «색상 없음»). 팔레트를 네 번 이어 써도 안 막혔다 —
//        9/23에 ②를 접은 이유(「팔레트가 한 번 쓰이면 다음 클릭이 막힌다」)는 지금 재현되지 않는다.
//   ⚠️**굵게는 못 켠다.** `button.se-bold-toolbar-button`은 **떠 있는 툴바**에만 있어서 캐럿만 있을 때는
//     없다(실측: 클릭 3초 시간초과). 빨강 키워드는 색만 입는다 — 굵게는 한 번 시도하고 접는다.
//   ⚠️이 전제도 또 뒤집힌다. 서식이 빠지면 **먼저 ego 창에서 「선택이 되는가」부터 재라.**
//     `ego/test_format.mjs`는 코드를 재고, 이 주석의 실측은 에디터를 재는 방법이다.
let boldDead = false;         // 굵게 버튼이 없으면 한 번만 겪고 다시 시도하지 않는다
const fmtWant = { red: 0, yellow: 0, bold: 0 };   // 입히려고 시도한 수 — 끝에 실제 DOM과 대조한다

async function typeRich(text, spans) {
  const marks = (spans || [])
    .map(([s, e, a]) => [Math.max(0, Math.min(s, text.length)), Math.max(0, Math.min(e, text.length)), a])
    .filter(([s, e]) => e > s)
    .sort((a, b) => a[0] - b[0]);
  if (!marks.length || text.includes("\n")) { await page.keyboard.insertText(text); return; }
  let cur = 0;
  for (const [s, e, a] of marks) {
    if (s < cur) continue;                               // 겹치는 구간은 뒤엣것을 버린다
    if (s > cur) await page.keyboard.insertText(text.slice(cur, s));
    const red = !!(a.color && a.color !== BLACK);
    if (a.bg) { await setBgColor(a.bg); fmtWant.yellow++; }
    if (red) { await setFontColor(a.color); fmtWant.red++; }
    // ★켜졌는지를 **반환값으로** 받아서, 켜진 것만 끈다. 안 켜진 걸 끄면 뒤 글자가 굵어진다.
    const boldOn = a.bold ? await toggleBold() : false;
    if (boldOn) fmtWant.bold++;
    await page.keyboard.insertText(text.slice(s, e));
    await page.waitForTimeout(150);
    // 🔴끄는 걸 빠뜨리면 **뒤 글자와 다음 문단까지 번진다**(9/23에 ③으로 간 이유가 이 번짐이었다).
    if (boldOn) await toggleBold();
    if (red) await setFontColor(BLACK);
    if (a.bg) await clearBgColor();
    log("  [서식]", text.slice(s, e).slice(0, 16), a.bg ? "노랑" : "", red ? "빨강" : "", boldOn ? "굵게" : "");
    cur = e;
  }
  if (cur < text.length) await page.keyboard.insertText(text.slice(cur));
}

// 저장 직전에 **실제로 박혔는지** 센다 — 「팔레트가 적용을 찍었다」와 「글에 색이 들어갔다」는 다르다.
//   ★색 값을 정규식으로 박아 세지 말 것: 10/9에 `rgb(255, 0, 16)`만 찾다가 멀쩡한 글도 0으로 셌다.
//     스타일에 `color:`/`background-color:`가 있는지로 센다.
async function countFormats() {
  try {
    return await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      const d = (f && f.contentDocument) ? f.contentDocument : document;
      const sp = [...d.querySelectorAll(".se-text-paragraph span")].filter(x => (x.textContent || "").trim());
      const st = (x) => x.getAttribute("style") || "";
      return {
        red: sp.filter(x => /(^|;)\s*color\s*:/.test(st(x)) && !/color\s*:\s*rgb\(0,\s*0,\s*0\)/.test(st(x))).length,
        yellow: sp.filter(x => /background-color\s*:/.test(st(x))).length,
        // 굵게는 `<b>`/`<strong>`로 박힌다(실측). font-weight로 넣는 판도 있어 같이 본다.
        bold: [...d.querySelectorAll(".se-text-paragraph b, .se-text-paragraph strong")]
                .filter(x => (x.textContent || "").trim()).length
              + sp.filter(x => /font-weight\s*:\s*(bold|[6-9]00)/.test(st(x))).length,
      };
    });
  } catch (err) { return { red: -1, yellow: -1, bold: -1 }; }
}

// 🔴인용구·링크 카드에서 **빠져나오지 않으면 뒤 본문이 그 박스 안으로 들어간다**(2026-09-23 에디님이
//   발행 화면에서 발견: 인용구 하나에 본문 세 문단이 딸려 들어가 있었다).
//   방법(naver._exit_block_via_bottom_click과 동일): 마지막 컴포넌트를 화면 가운데로 올리고
//   그 **아래 30px**을 클릭해 새 본문 단락으로 커서를 옮긴다. 말풍선 인용구는 꼬리가 있어 «바로 아래»로는 모자라다.
async function exitBlock() {
  try {
    const pt = await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      if (!f || !f.contentDocument) return null;
      const comps = f.contentDocument.querySelectorAll(".se-component");
      if (!comps.length) return null;
      const last = comps[comps.length - 1];
      last.scrollIntoView({ block: "center" });
      const r = last.getBoundingClientRect();
      const fr = f.getBoundingClientRect();
      return { x: fr.left + r.left + r.width / 2, y: fr.top + r.bottom + 30 };
    });
    if (!pt) return false;
    await page.waitForTimeout(250);
    await page.mouse.click(pt.x, pt.y, { label: "exit block" });
    await page.waitForTimeout(350);
    return true;
  } catch { return false; }
}

// 인용구 — 스타일을 **섞는다**(2026-09-23 에디님: "인용구도 인용구마다 적절하게 섞으면 더 좋을거고").
//   원고가 정한 스타일을 존중하되, 바로 앞 인용구와 같으면 다른 스타일로 바꿔 연달아 같은 모양이 안 되게 한다.
const QUOTE_STYLES = ["default", "quotation_line", "quotation_bubble", "quotation_underline", "quotation_postit", "quotation_corner"];
let lastQuoteStyle = "";

async function insertQuote(b) {
  let style = b.nstyle || b.style || "default";
  if (style === lastQuoteStyle) {
    const alts = QUOTE_STYLES.filter(x => x !== lastQuoteStyle);
    style = alts[Math.floor(Math.random() * alts.length)];
  }
  lastQuoteStyle = style;
  // ★스타일은 «삽입할 때» 고르는 것이다(실측: se-insert-menu-sub-panel-button-quotation-<style>).
  //   기본형은 «인용구 추가» 버튼, 그 외는 «인용구 선택»을 열어 스타일 버튼을 누른다.
  await page.click('loc=role:button[name="인용구 추가"]', { label: "insert quote" });
  await page.waitForTimeout(700);
  await toggleBold();                                   // 인용구 안 글자는 굵게
  const lines = String(b.text || "").split("\n");
  for (let i = 0; i < lines.length; i++) {
    if (i) await page.keyboard.press("Shift+Enter");     // 그냥 Enter는 인용구 밖(출처 칸)으로 빠진다
    await page.keyboard.type(lines[i], { delay: 16 });
  }
  await toggleBold();
  await page.waitForTimeout(250);
  // ★스타일은 글을 넣은 **직후**, 인용구가 선택돼 있어 «떠 있는 툴바»가 떠 있을 때 누른다.
  //   클래스 규칙: se-quotation-<style>-toolbar-button  (style에 quotation_ 접두사가 이미 들어 있다)
  if (style !== "default") {
    try {
      await page.waitForSelector(`css=button.se-quotation-${style}-toolbar-button`, { state: "visible", timeout: 3000 });
      await page.click(`css=button.se-quotation-${style}-toolbar-button >> nth=0`, { label: "quote style" });
      await page.waitForTimeout(450);
    } catch (e) { notes.push(`인용구 스타일 미적용: ${style}`); style = "default"; }
  }
  log("  [인용구]", style, "·", String(b.text || "").slice(0, 20));
  if (!(await exitBlock())) { await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter"); }
  // 🔴하위 패널이 열린 채 남으면 다음 «사진» 버튼이 막혀 파일 선택창이 안 열린다(실측).
  try {
    const open = await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      const d = (f && f.contentDocument) ? f.contentDocument : document;
      return [...d.querySelectorAll("[class*=se-insert-menu-sub-panel]")].some(x => x.offsetParent || x.getClientRects().length);
    });
    if (open) { await page.keyboard.press("Escape"); await page.waitForTimeout(300); }
  } catch {}
}

async function insertOgLink(url) {
  try {
    await page.click("css=button.se-oglink-toolbar-button", { label: "open link popup" });
    await page.waitForSelector("css=input.se-popup-oglink-input", { state: "visible", timeout: 8000 });
    await page.fill("css=input.se-popup-oglink-input", url);
    await page.waitForTimeout(400);
    await page.keyboard.press("Enter");                 // 미리보기 로드
    let enabled = false;
    for (let i = 0; i < 28; i++) {                      // 최대 ~14초 폴링
      await page.waitForTimeout(500);
      const dis = await page.evaluate(() => {
        const f = document.querySelector("#mainFrame");
        const d = (f && f.contentDocument) ? f.contentDocument : document;
        const b = d.querySelector("button.se-popup-button-confirm");
        return b ? b.disabled : null;
      });
      if (dis === false) { enabled = true; break; }
    }
    if (!enabled) { await page.keyboard.press("Escape"); return false; }
    await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      const d = (f && f.contentDocument) ? f.contentDocument : document;
      const b = d.querySelector("button.se-popup-button-confirm");
      if (b && !b.disabled) b.click();
    });
    await page.waitForTimeout(3000);                    // 카드 렌더 대기
    await exitBlock();
    return true;
  } catch (e) {
    try { await page.keyboard.press("Escape"); } catch {}
    return false;
  }
}

for (const b of P.blocks) {
  const t = b.type;
  try {
    if (t === "blank" || t === "hashtags") continue;
    if (t === "text" || t === "marker") {
      const spans = t === "marker"
        ? [[0, (b.text || "").length, { bold: true, color: RED }]]
        : (b.spans || []);
      await typeRich(b.text, spans);
      await page.waitForTimeout(120);
      await page.keyboard.press("Enter");
      await page.keyboard.press("Enter");
    } else if (t === "subhead") {
      await toggleBold();
      await page.keyboard.insertText(b.text);
      await toggleBold();
      await page.keyboard.press("Enter");
    } else if (t === "image") {
      if (!b.path) { notes.push("이미지 경로 없음"); continue; }
      await insertImage(b);
    } else if (t === "quote") {
      await insertQuote(b);
    } else if (t === "oglink") {
      // 🔴주소를 본문에 그냥 치면 카드가 안 되고 «주소 글자»가 그대로 남는다(2026-09-23 실측).
      //   반드시 «링크» 버튼 팝업으로 넣는다(naver._insert_oglink와 같은 절차).
      if (!(await insertOgLink(b.url))) notes.push(`링크 카드 실패(건너뜀): ${b.url.slice(-14)}`);
    } else if (t === "table_paste") {
      // 표는 «HTML을 클립보드로 붙여넣어» 네이버 네이티브 표로 만든다(naver._paste_table과 같은 방식).
      try {
        const raw = await fs.readFile(b.html_path, "utf-8");
        const m = raw.match(/<table[\s\S]*?<\/table>/);
        if (!m) { notes.push("표 HTML을 찾지 못함"); continue; }
        const plain = m[0].replace(/<\/(td|th)>/g, "\t").replace(/<\/tr>/g, "\n").replace(/<[^>]+>/g, "").trim();
        await page.keyboard.paste({ text: plain, html: m[0] });
        await page.waitForTimeout(2800);
        await exitBlock();
        log("  [표] 붙여넣음");
      } catch (e) { notes.push(`표 실패: ${String(e).slice(0, 60)}`); }
    } else {
      notes.push(`미지원 블록 건너뜀: ${t}`);
    }
  } catch (e) {
    notes.push(`${t} 실패: ${String(e).slice(0, 80)}`);
  }
}
// 🔴서식이 **실제로 박혔는지** 저장 전에 대조한다. 입히려 한 수와 글에 있는 수가 다르면 메모로 남긴다.
//   ★10/9에 팔레트는 «적용»을 찍고 글에는 하나도 안 들어갔다. 「눌렀다」와 「됐다」는 다르다.
if (fmtWant.red || fmtWant.yellow || fmtWant.bold) {
  const got = await countFormats();
  log("[계측] 저장 전 — 빨강", got.red + "/" + fmtWant.red,
      "· 노랑", got.yellow + "/" + fmtWant.yellow, "· 굵게", got.bold + "/" + fmtWant.bold);
  if (got.red === 0 && got.yellow === 0) {
    notes.push(`🔴서식이 하나도 안 박혔습니다(입히려 한 것 빨강 ${fmtWant.red}·노랑 ${fmtWant.yellow})`);
  } else if (got.red < fmtWant.red || got.yellow < fmtWant.yellow || got.bold < fmtWant.bold) {
    notes.push(`서식 일부 빠짐: 빨강 ${got.red}/${fmtWant.red} · 노랑 ${got.yellow}/${fmtWant.yellow} · 굵게 ${got.bold}/${fmtWant.bold}`);
  }
}
log("본문 완료 · 이미지", images, "장 · 메모", notes.length);

// ── 3-b) AI 생성 이미지 표기 ────────────────────────────────────
//   🔴strpia(AI·자동화)의 본문 사진은 **그록·제미나이가 만든 그림**이다 → 표기를 켠다.
//   데일리텐 연예편은 방송 캡처라 껐다(2026-09-11 에디님) → 호출측이 aiMark를 안 보내면 건너뛴다.
//   Playwright 쪽 `naver._mark_all_ai`와 같은 절차: 이미지 하나를 고르면 «전체AI활용»이 나온다.
//   베스트 에포트 — 실패해도 발행은 그대로 간다(메모만 남긴다).
if (P.aiMark && images > 0) {
  try {
    // 🔴이미지가 여러 장이면 이 선택자는 «모호함»으로 죽는다(2026-09-27 첫 실측:
    //   ElementResolutionError). 툴바 버튼 두 개 때와 같은 함정 → nth=0으로 고정한다.
    await page.click("css=.se-component.se-image >> nth=0", { label: "select first image" });
    await page.waitForTimeout(700);
    const didAll = await page.evaluate(() => {
      const f = document.querySelector("#mainFrame");
      const d = (f && f.contentDocument) ? f.contentDocument : document;
      const norm = s => (s || "").replace(/\s+/g, "");
      const vis = e => e && e.offsetParent !== null;
      const el = [...d.querySelectorAll("button,a,span,div[role=button]")]
        .find(e => vis(e) && ["전체AI활용", "전체 AI활용"].includes(norm(e.textContent)));
      if (el) { (el.closest("button") || el).click(); return true; }
      return false;
    });
    if (didAll) {
      await page.waitForTimeout(600);
      await page.evaluate(() => {            // 확인/적용 팝업이 뜨면 누른다
        const f = document.querySelector("#mainFrame");
        const d = (f && f.contentDocument) ? f.contentDocument : document;
        const norm = s => (s || "").replace(/\s+/g, "");
        const b = [...d.querySelectorAll("button")]
          .find(x => ["확인", "적용", "설정", "표시"].includes(norm(x.textContent)) && x.offsetParent);
        if (b) b.click();
      });
      log("AI 활용 표기: '전체AI활용'로 일괄 처리");
    } else {
      // 폴백 — 이미지마다 토글을 켠다(이미 켜진 건 두고 간다)
      let on = 0;
      for (let i = 0; i < images; i++) {
        try {
          const r = await page.evaluate((idx) => {
            const f = document.querySelector("#mainFrame");
            const d = (f && f.contentDocument) ? f.contentDocument : document;
            const comp = d.querySelectorAll(".se-component.se-image")[idx];
            if (!comp) return "no-image";
            comp.scrollIntoView({ block: "center" });
            comp.click();
            return "clicked";
          }, i);
          if (r !== "clicked") continue;
          await page.waitForTimeout(350);
          const st = await page.evaluate(() => {
            const f = document.querySelector("#mainFrame");
            const d = (f && f.contentDocument) ? f.contentDocument : document;
            const vis = e => e && e.offsetParent !== null;
            const t = [...d.querySelectorAll(".se-set-ai-mark-button-toggle")].find(vis);
            if (!t) return "notfound";
            const cont = t.closest(".se-set-ai-mark-button") || t;
            const isOn = /is-selected|is-on|se-is-active|is-checked/.test(cont.className)
              || t.getAttribute("aria-pressed") === "true"
              || t.getAttribute("aria-checked") === "true";
            if (isOn) return "already-on";
            (t.closest("button") || t).click();
            return "turned-on";
          });
          if (st === "turned-on" || st === "already-on") on++;
          await page.waitForTimeout(200);
        } catch { /* 한 장 실패는 넘어간다 */ }
      }
      log("AI 활용 표기: 개별 토글", on, "/", images);
      if (!on) notes.push("AI 활용 표기 실패");
    }
    await exitBlock();
  } catch (e) {
    notes.push(`AI 활용 표기 실패: ${String(e).slice(0, 60)}`);
  }
}

// ── 4) 카테고리 · 태그 · 발행/예약 ──────────────────────────────
//   ★클래스 해시(publish_btn__v_kS9 등)는 네이버가 자주 바꾼다 → **접두사**로 잡는다.
async function openPublishPanel() {
  await page.click('css=button[class*="publish_btn"]', { label: "open publish panel" });
  await page.waitForTimeout(2000);
}

// 🔴카테고리·태그는 **발행 패널 안에만** 있다. 임시저장일 때도 넣어야 한다
//   (2026-09-28 에디님: "임시저장시 카테고리도 하나도 안하고, 태그편집도 하나도 안넣었네").
//   기존 Playwright 구현과 같은 방법 — 패널을 잠깐 열어 채우고 Escape로 닫은 뒤 저장한다.
async function setCategoryAndTags() {
    // 카테고리
    //   🔴선택자 하나만 쓰다 2026-09-27 첫 실측에서 실패해 «자동화»가 기본 칸으로 갔다.
    //     2026-09-15에 플레이라이트 쪽에서 똑같이 당한 자리다(17편이 통째로 기본 칸).
    //     → 검증된 사다리(naver._select_category)를 그대로 옮긴다: 여는 버튼 후보 → 정확일치 → 부분일치.
    //     ★열기와 고르기가 **둘 다** 돼야 성공이다. 실패하면 메모에 남겨 배치가 알린다.
    if (P.category) {
      const cat = P.category;
      let opened = false;
      for (const sel of ['css=button[aria-label="카테고리 목록 버튼"]',
                         'css=button[class*="selectbox_button"] >> nth=0',
                         'css=.selectbox_button >> nth=0',
                         'button:has-text("카테고리") >> nth=0']) {
        try { await page.click(sel, { label: "open category list" }); opened = true; break; }
        catch { /* 다음 후보 */ }
      }
      if (!opened) {
        notes.push(`카테고리 드롭다운을 열지 못함(기본 칸): ${cat}`);
      } else {
        await page.waitForTimeout(900);
        let picked = false;
        for (const sel of [`label:text-is("${cat}") >> nth=0`,
                           `span:text-is("${cat}") >> nth=0`,
                           `a:text-is("${cat}") >> nth=0`,
                           `text="${cat}"`,
                           `label:has-text("${cat}") >> nth=-1`,
                           `li:has-text("${cat}") >> nth=-1`]) {
          try { await page.click(sel, { label: "pick category" }); picked = true; log("카테고리:", cat, "·", sel); break; }
          catch { /* 다음 후보 */ }
        }
        await page.waitForTimeout(600);
        if (!picked) notes.push(`카테고리 선택 실패(기본 칸): ${cat}`);
      }
    }

    // 태그 — 본문에 넣지 않고 태그편집 칸에 넣는다
    const tags = (P.tags || "").split(/\s+/).filter(w => w.startsWith("#")).map(w => w.slice(1));
    if (tags.length) {
      try {
        await page.click('css=input[class*="tag_input"]', { label: "focus tags" });
        for (const t of tags) {
          await page.keyboard.insertText(t);
          await page.keyboard.press("Enter");
          await page.waitForTimeout(180);
        }
        log("태그", tags.length, "개 입력");
      } catch (e) { notes.push("태그 입력 실패"); }
    }

}


if (P.mode === "draft") {
  try {
    await openPublishPanel();
    await setCategoryAndTags();
    await page.keyboard.press("Escape");      // 발행하지 않고 패널만 닫는다
    await page.waitForTimeout(800);
  } catch (e) { notes.push(`카테고리·태그 건너뜀: ${String(e).slice(0, 60)}`); }
  await page.click('css=button[class*="save_btn"]', { label: "save draft" });
  await page.waitForTimeout(4000);
  log("임시저장 완료");
  console.log(JSON.stringify({ ok: true, stage: "draft_saved", images, notes, spaceId: task.spaceId }));
} else {
  await openPublishPanel();

  await setCategoryAndTags();
  // 발행 시간 — 예약이면 날짜/시/분을 채운다(분은 10분 단위만 가능)
  if (P.schedule) {
    try {
      await page.click('text="예약"', { label: "choose scheduled publish" });
      await page.waitForTimeout(800);
      // ⚠️날짜 칸은 **읽기 전용**이다(달력에서 고른다). 평소엔 «당일» 예약이라 손댈 일이 없고,
      //   날짜가 다를 때만 달력을 열어 그 날짜를 누른다.
      const curDate = await page.evaluate(() => {
        const f = document.querySelector("#mainFrame");
        const d = (f && f.contentDocument) ? f.contentDocument : document;
        return d.querySelector('input[class*="input_date"]')?.value || "";
      });
      if (curDate.replace(/\s/g, "") !== P.schedule.date.replace(/\s/g, "")) {
        await page.click('css=input[class*="input_date"]', { label: "open date picker" });
        await page.waitForTimeout(700);
        const dayNum = String(parseInt(P.schedule.date.split(".")[2].trim(), 10));
        const picked = await page.evaluate((want) => {
          const f = document.querySelector("#mainFrame");
          const d = (f && f.contentDocument) ? f.contentDocument : document;
          const cells = [...d.querySelectorAll("td, button, a, span")]
            .filter(x => (x.offsetParent || x.getClientRects().length) && (x.textContent || "").trim() === want);
          const t = cells.find(x => !/disabled|off|prev|next/i.test(x.className));
          if (t) { t.click(); return true; }
          return false;
        }, dayNum);
        await page.waitForTimeout(600);
        if (!picked) log("  ⚠️달력에서 날짜를 못 골랐습니다:", P.schedule.date);
      }
      await page.waitForTimeout(300);
      await page.selectOption('css=select[class*="hour_option"]', P.schedule.hour);
      await page.waitForTimeout(250);
      await page.selectOption('css=select[class*="minute_option"]', P.schedule.minute);
      await page.waitForTimeout(400);
      log("예약:", P.schedule.date, P.schedule.hour + ":" + P.schedule.minute);
      // 🔴들어간 값을 되읽어 확인한다 — 예약이 안 걸린 채 «현재»로 발행되면 즉시 공개된다.
      const got = await page.evaluate(() => {
        const f = document.querySelector("#mainFrame");
        const d = (f && f.contentDocument) ? f.contentDocument : document;
        return {
          date: d.querySelector('input[class*="input_date"]')?.value || "",
          hour: d.querySelector('select[class*="hour_option"]')?.value || "",
          minute: d.querySelector('select[class*="minute_option"]')?.value || "",
        };
      });
      const want = P.schedule;
      // 🔴**날짜도 대조한다**(2026-09-29). 시·분만 보다가, 달력에서 날짜를 못 고른 채
      //   지난 시각으로 «발행»된 두 편이 블로그에 아예 안 남았다. 되읽기는 값 전부를 봐야 한다.
      const norm = s => (s || "").replace(/\s/g, "");
      if (got.hour !== want.hour || got.minute !== want.minute || norm(got.date) !== norm(want.date)) {
        console.log(JSON.stringify({ ok: false, why: `예약이 안 들어갔습니다(원함 ${want.date} ${want.hour}:${want.minute} / 실제 ${got.date} ${got.hour}:${got.minute}) — 발행하지 않음`, notes }));
        await closeSpace();
        process.exit(3);
      }
      log("예약 확인:", got.date, got.hour + ":" + got.minute);
    } catch (e) {
      console.log(JSON.stringify({ ok: false, why: `예약 설정 실패 — 발행하지 않음: ${String(e).slice(0, 120)}`, notes }));
      await closeSpace();
      process.exit(3);
    }
  }

  if (P.dryPublish) {   // 시험용: 여기까지만 하고 실제 발행은 누르지 않는다
    log("[시험] 발행 버튼은 누르지 않았습니다");
    console.log(JSON.stringify({ ok: true, stage: "ready_not_published", images, notes, spaceId: task.spaceId }));
  } else {
    await page.click('css=button[class*="confirm_btn"]', { label: "publish" });
    await page.waitForTimeout(6000);
    log("발행 완료");
    console.log(JSON.stringify({ ok: true, stage: "published", images, notes, url: await page.url(), spaceId: task.spaceId }));
  }
}
await closeSpace();
