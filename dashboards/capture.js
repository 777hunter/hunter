/* 대시보드 HTML을 Chromium으로 렌더링해 screenshots/*.png 로 저장 */
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const dir = __dirname;
const files = fs.readdirSync(dir).filter(f => /^\d\d-.*\.html$/.test(f)).sort();

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1320, height: 1000 }, deviceScaleFactor: 2 });
  for (const f of files) {
    await page.goto('file://' + path.join(dir, f));
    await page.waitForTimeout(400);
    const out = path.join(dir, 'screenshots', f.replace(/\.html$/, '.png'));
    await page.screenshot({ path: out, fullPage: true });
    console.log('saved', path.basename(out));
  }
  await browser.close();
})();
