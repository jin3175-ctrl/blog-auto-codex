// 제미나이 웹 그림 만들기 — ego lite로 (2026-10-17 에디님: "제미나이도 에고라이트에서 진행해")
//   전엔 자동화 전용 크롬(Playwright · session/gemini_profile)으로 했는데, 그 크롬의 구글 로그인이
//   10/14~17 풀려 썸네일·본문 그림이 전부 무료 사진으로 떨어졌다. ego lite는 에디님이 평소 쓰는
//   프로필의 구글 로그인을 그대로 쓴다.
// 입력(PAYLOAD_PATH JSON): {prompts:[...], outs:[...], perImageMs, budgetMs, profileId, spaceName}
// 출력(마지막 줄 JSON): {ok, results:[true|false...], why?}
const fs = await import("node:fs/promises");
const payloadPath = (typeof PAYLOAD_PATH !== "undefined") ? PAYLOAD_PATH : "/tmp/ego_gemini.json";
const P = JSON.parse(await fs.readFile(payloadPath, "utf-8"));
const log = (...a) => console.log("[gemini]", ...a);
const results = P.prompts.map(() => false);
const INPUT = "div.ql-editor[contenteditable='true'], rich-textarea div[contenteditable='true'], div[contenteditable='true'][role='textbox']";

let task;
try { task = await taskSpace(P.spaceName || "제미나이 그림", P.profileId ? { profileId: P.profileId } : undefined); }
catch (e) { task = await taskSpace(P.spaceName || "제미나이 그림"); }
const page = task.page("p1");
const done = async (extra = {}) => {
  try { await task.finish({ keep: [] }); } catch (e) {}
  console.log(JSON.stringify({ ok: results.some(Boolean), results, ...extra }));
};

const bigImgs = () => page.evaluate(() => [...document.querySelectorAll("img")]
  .filter(e => e.naturalWidth >= 512 && e.naturalHeight >= 512)
  .map(e => e.src).filter(s => s && (s.includes("googleusercontent") || s.startsWith("blob:") || s.startsWith("data:image"))));

try {
  await page.goto("https://gemini.google.com/app");
  await page.waitForTimeout(4000);
  const loggedOut = await page.evaluate(() =>
    document.body.innerText.includes("활동을 저장하려면 로그인") ||
    !![...document.querySelectorAll("a,button")].find(e => /^(로그인|Sign in)$/.test(e.innerText.trim())));
  if (loggedOut) { await done({ why: "logged_out" }); process.exit(0); }

  const t0 = Date.now();
  for (let i = 0; i < P.prompts.length; i++) {
    if (Date.now() - t0 > (P.budgetMs || 600000)) { log("예산 초과 — 남은 장은 넘김"); break; }
    try {
      const before = (await bigImgs()).length;
      await page.click(INPUT, { label: "focus prompt box" });
      await page.keyboard.type(P.prompts[i], { delay: 4 });
      await page.keyboard.press("Enter");
      let src = null;
      const until = Date.now() + (P.perImageMs || 150000);
      while (Date.now() < until) {
        await page.waitForTimeout(2500);
        const s = await bigImgs();
        if (s.length > before) { src = s[s.length - 1]; break; }
      }
      if (!src) { log(`${i + 1}장 시간 초과`); continue; }
      await page.waitForTimeout(1500);   // 다 그려질 때까지 조금 더
      let b64 = null;
      // ① 캔버스로 원본 크기 그대로 꺼낸다(10/17 실측: blob fetch는 TypeError, 다운로드 버튼은 이벤트가 안 잡힘)
      try {
        const jpg = /\.jpe?g$/i.test(P.outs[i]);
        b64 = await page.evaluate(([u, jpg]) => {
          const e = [...document.querySelectorAll("img")].find(x => x.src === u);
          if (!e) return null;
          const c = document.createElement("canvas"); c.width = e.naturalWidth; c.height = e.naturalHeight;
          c.getContext("2d").drawImage(e, 0, 0);
          return c.toDataURL(jpg ? "image/jpeg" : "image/png", 0.92).split(",")[1];
        }, [src, jpg]);
      } catch (e) { log("캔버스 실패", String(e).slice(0, 60)); }
      if (!b64) try {
        b64 = await page.evaluate(async (u) => {
          const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
          let s = ""; for (let k = 0; k < b.length; k++) s += String.fromCharCode(b[k]); return btoa(s);
        }, src);
      } catch (e) { log("fetch 실패 → 화면 캡처", String(e).slice(0, 60)); }
      if (b64) {
        await fs.writeFile(P.outs[i], Buffer.from(b64, "base64"));
      } else {
        // 🔴clip은 **문서 좌표**다(화면 좌표에 scrollX/Y를 더한다 — 데일리텐 10/14 실측)
        const r = await page.evaluate((u) => {
          const el = [...document.querySelectorAll("img")].find(e => e.src === u);
          if (!el) return null; el.scrollIntoView({ block: "center" });
          const b = el.getBoundingClientRect();
          return { x: b.left + scrollX, y: b.top + scrollY, width: b.width, height: b.height };
        }, src);
        if (!r) continue;
        await page.waitForTimeout(500);
        await page.screenshot({ path: P.outs[i], clip: r });
      }
      const st = await fs.stat(P.outs[i]).catch(() => null);
      results[i] = !!(st && st.size > 3000);
      log(`${i + 1}/${P.prompts.length} ` + (results[i] ? "생성" : "실패"));
    } catch (e) { log(`${i + 1}장 예외`, String(e).slice(0, 80)); }
  }
  await done();
} catch (e) {
  await done({ why: String(e).slice(0, 200) });
}
