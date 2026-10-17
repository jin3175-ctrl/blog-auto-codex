// 챗GPT 웹 그림 만들기 — ego lite로 (2026-10-18 · 사진 순서 3번째)
//   무료 사진·제미나이에서 못 채운 자리만 여기로 온다. 내가 로그인한 챗GPT 그대로 쓴다(무료 계정은 하루 몇 장 제한).
// 입력(PAYLOAD_PATH JSON): {prompts:[...], outs:[...], perImageMs, budgetMs, profileId, spaceName}
// 출력(마지막 줄 JSON): {ok, results:[true|false...], why?}
const fs = await import("node:fs/promises");
const payloadPath = (typeof PAYLOAD_PATH !== "undefined") ? PAYLOAD_PATH : "/tmp/ego_chatgpt.json";
const P = JSON.parse(await fs.readFile(payloadPath, "utf-8"));
const log = (...a) => console.log("[chatgpt]", ...a);
const results = P.prompts.map(() => false);
const INPUT = "#prompt-textarea, div.ProseMirror[contenteditable='true'], textarea[name='prompt-textarea']";

let task;
try { task = await taskSpace(P.spaceName || "챗GPT 그림", P.profileId ? { profileId: P.profileId } : undefined); }
catch (e) { task = await taskSpace(P.spaceName || "챗GPT 그림"); }
const page = task.page("p1");
const done = async (extra = {}) => {
  try { await task.finish({ keep: [] }); } catch (e) {}
  console.log(JSON.stringify({ ok: results.some(Boolean), results, ...extra }));
};

// 챗GPT가 만든 그림: oaiusercontent / estuary 주소의 큰 img
const genImgs = () => page.evaluate(() => [...document.querySelectorAll("img")]
  .filter(e => e.naturalWidth >= 512 && e.naturalHeight >= 512)
  .map(e => e.src).filter(s => s && /oaiusercontent|estuary|files\./.test(s)));

try {
  await page.goto("https://chatgpt.com/");
  await page.waitForTimeout(5000);
  const loggedOut = await page.evaluate(() =>
    !![...document.querySelectorAll("a,button")].find(e => /^(로그인|Log in)$/.test(e.innerText.trim())));
  if (loggedOut) { await done({ why: "logged_out" }); process.exit(0); }
  await page.waitForSelector(INPUT, { state: "visible", timeout: 20000 });

  const t0 = Date.now();
  for (let i = 0; i < P.prompts.length; i++) {
    if (Date.now() - t0 > (P.budgetMs || 900000)) { log("예산 초과 — 남은 장은 넘김"); break; }
    try {
      const before = new Set(await genImgs());
      await page.click(INPUT, { label: "focus prompt box" });
      await page.keyboard.type(P.prompts[i], { delay: 4 });
      await page.keyboard.press("Enter");
      let src = null;
      const until = Date.now() + (P.perImageMs || 180000);
      while (Date.now() < until) {
        await page.waitForTimeout(3000);
        const now = (await genImgs()).filter(s => !before.has(s));
        // 그리는 중엔 흐린 미리보기가 같은 자리에 바뀌며 뜬다 → 같은 주소가 두 번 연속 보이면 완성으로 본다
        if (now.length) {
          const last = now[now.length - 1];
          if (src === last) break;
          src = last;
        }
        const limited = await page.evaluate(() => /한도|limit reached|업그레이드하세요|try again later/i.test(document.body.innerText.slice(-3000)));
        if (limited && !src) { log("이미지 한도에 걸림"); await done({ why: "limit" }); process.exit(0); }
      }
      if (!src) { log(`${i + 1}장 시간 초과`); continue; }
      await page.waitForTimeout(2000);
      let b64 = null;
      try {
        b64 = await page.evaluate(async (u) => {
          const r = await fetch(u, { credentials: "include" }); const b = new Uint8Array(await r.arrayBuffer());
          let s = ""; for (let k = 0; k < b.length; k++) s += String.fromCharCode(b[k]); return btoa(s);
        }, src);
      } catch (e) { log("내려받기 실패 → 화면 캡처", String(e).slice(0, 60)); }
      if (b64) {
        await fs.writeFile(P.outs[i], Buffer.from(b64, "base64"));
      } else {
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
