import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const URL = "http://localhost:5173/showcase.html";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
  defaultViewport: { width: 1200, height: 1600, deviceScaleFactor: 2 },
});
const page = await browser.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

await page.goto(URL, { waitUntil: "networkidle2" });
await page.waitForSelector("[data-showcase-ready]");

const cardBorderColor = await page.$eval("[data-slot=card]", (card) =>
  getComputedStyle(card).borderColor,
);

if (pageErrors.length > 0) {
  throw new Error(`Showcase page errors:\n${pageErrors.join("\n")}`);
}

if (cardBorderColor !== "rgb(227, 231, 238)") {
  throw new Error(
    `Card border does not match --line: received ${cardBorderColor}`,
  );
}

await page.screenshot({ path: "/tmp/citycrawl-showcase.png", fullPage: true });
console.log("showcase shot ok");

await browser.close();
