import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const URL = "http://localhost:5173/";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
  defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 2 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));

await page.goto(URL, { waitUntil: "networkidle2" });
await page.waitForSelector('input[type="password"]');
await page.screenshot({ path: "/tmp/citycrawl-login.png" });
console.log("login shot ok");

await page.type('input[type="password"]', "citycrawl-dev-2026!");
await page.click('button[type="submit"]');
await page.waitForFunction(() => /CAPAS/i.test(document.body.innerText), { timeout: 20000 });
await wait(4500);
// default map: volume pins + cluster zones + risk-ROIs + config dock
await page.screenshot({ path: "/tmp/citycrawl-map.png" });
console.log("map shot ok");

const clickText = (src) =>
  page.evaluate((s) => {
    const rx = new RegExp(s);
    const b = [...document.querySelectorAll("button")].find((x) => rx.test(x.textContent || ""));
    if (b) b.click();
    return !!b;
  }, src);

// generate a plan -> right panel swaps to the action-plan preview, map draws squads
console.log("generate:", await clickText("Generar plan"));
await wait(2600);
await page.screenshot({ path: "/tmp/citycrawl-plan.png" });
console.log("plan shot ok");

// open the history popover (icon button, title="Planes anteriores")
const histOk = await page.evaluate(() => {
  const b = document.querySelector('button[title="Planes anteriores"]');
  if (b) b.click();
  return !!b;
});
console.log("history:", histOk);
await wait(1200);
await page.screenshot({ path: "/tmp/citycrawl-history.png" });
console.log("history shot ok");

await browser.close();
