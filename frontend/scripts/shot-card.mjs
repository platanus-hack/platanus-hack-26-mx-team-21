import puppeteer from "puppeteer-core";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
  defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 2 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await page.goto("http://localhost:5173/", { waitUntil: "networkidle2" });
await page.waitForSelector('input[type="password"]');
await page.type('input[type="password"]', "citycrawl-dev-2026!");
await page.click('button[type="submit"]');
await page.waitForFunction(() => /CAPAS/i.test(document.body.innerText), { timeout: 20000 });
await wait(3500);
// generate a plan to get a clickable top-critical list in the right panel
await page.evaluate(() => {
  const b = [...document.querySelectorAll("button")].find((x) => /Generar plan/.test(x.textContent || ""));
  b && b.click();
});
await wait(2400);
// click first top-critical row (meta like "39 m² · $150,000") -> opens observation card
const ok = await page.evaluate(() => {
  const b = [...document.querySelectorAll("button")].find((x) => /m²\s*·\s*\$/.test(x.textContent || ""));
  if (b) b.click();
  return !!b;
});
console.log("list item clicked:", ok);
await wait(2000);
await page.screenshot({ path: "/tmp/citycrawl-card.png" });
console.log("card shot ok");
await browser.close();
