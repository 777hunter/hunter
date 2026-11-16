// 허브 화면의 저장·초안·편집 상태 전이를 실제 브라우저로 검증합니다.
// 실행: node dashboards/tests/hub_states.mjs   (Playwright 필요)
//
// claude.ai 런타임 대신 가짜 window.claude 를 넣습니다. publish 는 테스트가 고른 결과를
// 돌려주고, 성공하면 런타임처럼 "새 버전으로 다시 열기"를 흉내 냅니다.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const { chromium } = createRequire(import.meta.url)('playwright');

const HUB = join(dirname(fileURLToPath(import.meta.url)), '..', 'hub.html');
const URL = 'http://hub.test/';
const STATE_RE = /(<script id="state" type="application\/json">)([\s\S]*?)(<\/script>)/;

const readState = html => JSON.parse(STATE_RE.exec(html)[2]);
const withState = (html, s) => html.replace(STATE_RE, (_, a, __, c) => a + JSON.stringify(s).replace(/</g, '\\u003c') + c);

const STUB = `
  window.__beforeunload = 0;
  addEventListener('beforeunload', e => { if (e.defaultPrevented || e.returnValue === '') window.__beforeunload++; });
  window.claude = { use: name => new Promise(res => setTimeout(() => res(name === 'artifact' ? {
    publish: html => window.__pub(html).then(r => { if (r && r.error) throw { code: r.error }; })
  } : null), 20)) };
`;

async function setup(browser, { initial, writer = true } = {}) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const env = { published: initial ?? readFileSync(HUB, 'utf8'), next: 'ok', calls: 0, hold: null };
  await page.route(URL, r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: env.published }));
  await page.route('https://fonts.googleapis.com/**', r => r.abort());
  await page.route('https://fonts.gstatic.com/**', r => r.abort());
  await page.exposeFunction('__pub', async html => {
    env.calls++;
    if (!writer) return { error: 'not_writer' };
    if (env.next !== 'ok') { const e = env.next; env.next = 'ok'; return { error: e }; }
    env.published = html;          // 서버에는 이미 반영됨
    if (env.hold) await env.hold;  // 응답만 늦게 옴
    return null;
  });
  if (writer) await page.addInitScript(STUB);
  else await page.addInitScript(STUB.replace("name === 'artifact'", 'false'));
  const open = async () => { await page.goto(URL); await page.waitForSelector('.wrap'); if (writer) await page.waitForSelector('[data-act="admin"]'); };
  await open();
  const close = async () => { await ctx.close(); assert.deepEqual(errors, [], '페이지 오류'); };
  return { ctx, page, env, open, close, errors };
}

const S = page => page.evaluate(() => JSON.parse(document.getElementById('state').textContent));
const admin = page => page.click('[data-act="admin"]');
const row = (page, id) => page.locator(`.row[data-id="${id}"]`);

const tests = {
  async '기존 기능: 편집·추가·제거·가져오기 뒤 저장하면 발행본에 모두 반영된다'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base);
    st.items[0].status = 'new';
    const { page, env, close } = await setup(browser, { initial: withState(base, st) });
    await admin(page);
    const [a, b] = st.items;
    await row(page, a.id).locator('[data-act="edit"]').click();
    await row(page, a.id).locator('[data-f="title"]').fill('고친 제목');
    await row(page, a.id).locator('[data-f="tags"]').fill('가, 나');
    await row(page, a.id).locator('[data-act="apply"]').click();
    page.once('dialog', d => d.accept());
    await row(page, b.id).locator('[data-act="edit"]').click();
    await row(page, b.id).locator('[data-act="drop"]').click();
    await page.click('[data-act="addform"]');
    await page.fill('[data-n="url"]', 'https://claude.ai/code/artifact/cccccccc-0000-4000-8000-000000000003');
    await page.fill('[data-n="title"]', '손으로 넣은 대시보드');
    await page.click('[data-act="addsave"]');
    const file = '<DL><DT><H3>폴더</H3><DL><DT><A HREF="https://example.com/dash">사내 대시보드</A></DL></DL>';
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.click('[data-act="impall"]');
    await page.click('[data-act="impadd"]');
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    const out = readState(env.published);
    const ea = out.items.find(x => x.id === a.id);
    assert.equal(ea.title, '고친 제목'); assert.equal(ea.titleLocked, true); assert.equal(ea.status, 'ready');
    assert.deepEqual(ea.tags, ['가', '나']);
    assert.ok(!out.items.some(x => x.id === b.id)); assert.ok(out.tombstones.includes(b.id));
    assert.equal(out.items.find(x => x.id === 'cccccccc-0000-4000-8000-000000000003').status, 'ready');
    const bm = out.items.find(x => x.url === 'https://example.com/dash');
    assert.equal(bm.status, 'new'); assert.deepEqual(bm.tags, ['폴더']); assert.match(bm.id, /^bm-/);
    await close();
  },

  async '기존 기능: 저장하지 않고 다시 열면 복원 안내가 뜨고 복원된다'(browser) {
    const { page, env, open, close } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id;
    await row(page, id).locator('[data-act="hide"]').click();
    await open();
    assert.match(await page.locator('.recover').innerText(), /1건/);
    await page.click('[data-act="restore"]');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'dirty');
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    assert.equal(readState(env.published).items.find(x => x.id === id).hidden, true);
    await close();
  },

  async '기존 기능: 옛 형식 초안(상태 통째)도 복원된다'(browser) {
    const { page, open, close } = await setup(browser);
    const st = await S(page);
    st.items[0].desc = '옛 초안의 설명';
    await page.evaluate(d => sessionStorage.setItem('hub.draft', JSON.stringify(d)), st);
    await open();
    await page.click('[data-act="restore"]');
    await admin(page);
    assert.match(await page.locator('.list').innerText(), /옛 초안의 설명/);
    await close();
  },

  async '기존 기능: 편집 권한이 없는 화면은 관리자 버튼 없이 목록만 보인다'(browser) {
    const { page, close } = await setup(browser, { writer: false });
    await page.waitForTimeout(100);
    assert.equal(await page.locator('[data-act="admin"]').count(), 0);
    assert.ok(await page.locator('.row').count() > 0);
    await page.fill('.search', 'MSDS');
    assert.equal(await page.locator('.row').count(), 1);
    await close();
  },

  async '편집 중인 입력이 검색·다른 행 조작으로 지워지지 않는다'(browser) {
    const { close, page } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id, other = (await S(page)).items[1].id;
    await row(page, id).locator('[data-act="edit"]').click();
    await row(page, id).locator('[data-f="desc"]').fill('새 용도 설명');
    await row(page, other).locator('[data-act="pin"]').click();
    await page.fill('.search', '');
    await page.type('.search', ' ');
    assert.equal(await row(page, id).locator('[data-f="desc"]').inputValue(), '새 용도 설명');
    await close();
  },

  async '충돌 뒤 복원해도 다른 곳에서 들어온 항목을 지우지 않는다'(browser) {
    const { close, page, env, open } = await setup(browser);
    await admin(page);
    const st = await S(page);
    const id = st.items[0].id;
    await row(page, id).locator('[data-act="pin"]').click();
    // 그 사이 주간 동기화가 새 항목을 넣어 발행함
    const theirs = readState(env.published);
    theirs.items.push({ id: 'aaaaaaaa-0000-4000-8000-000000000001', url: URL + 'x', title: '동기화로 들어온 새 대시보드',
      icon: '▤', cat: 'unsorted', desc: '', tags: [], updated: '2026-11-16', added: '2026-11-16', hidden: false, pinned: false, status: 'new' });
    env.published = withState(env.published, theirs);
    env.next = 'conflict';
    await page.click('[data-act="save"]');
    await page.waitForSelector('.status.warn');
    await open(); // 런타임이 이긴 버전으로 다시 엶
    await admin(page);
    await page.click('[data-act="restore"]');
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.querySelector('[data-act="save"]')?.textContent !== '저장 중…');
    const after = readState(env.published);
    assert.ok(after.items.some(x => x.id === 'aaaaaaaa-0000-4000-8000-000000000001'), '동기화 항목이 사라짐');
    assert.equal(after.items.find(x => x.id === id).pinned, !st.items[0].pinned, '내 편집이 빠짐');
    await close();
  },

  async '저장이 끝나고 다시 열리면 복구 안내가 뜨지 않는다'(browser) {
    const { close, page, env, open } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id;
    await row(page, id).locator('[data-act="pin"]').click();
    let release; env.hold = new Promise(r => (release = r));
    await page.click('[data-act="save"]');
    // 런타임은 발행 직후 모든 화면을 새 버전으로 다시 엶. then 이 돌기 전에 열릴 수 있음
    await page.waitForFunction(() => true);
    while (!env.calls) await new Promise(r => setTimeout(r, 10));
    await open();
    release();
    assert.equal(await page.locator('.recover').count(), 0, '저장이 끝났는데 복구 안내가 뜸');
    await close();
  },

  async '저장 중에는 편집이 잠기고 떠날 때 경고하지 않는다'(browser) {
    const { close, page, env } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id;
    await row(page, id).locator('[data-act="pin"]').click();
    let release; env.hold = new Promise(r => (release = r));
    await page.click('[data-act="save"]');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'saving');
    assert.ok(await row(page, id).locator('[data-act="hide"]').isDisabled(), '저장 중 편집 가능');
    const warned = await page.evaluate(() => { const e = new Event('beforeunload', { cancelable: true }); dispatchEvent(e); return e.defaultPrevented; });
    assert.equal(warned, false, '저장 중 떠나기 경고');
    release();
    await close();
  },

  async '보기 전용 계정은 저장 실패 뒤 떠나기 경고에 갇히지 않는다'(browser) {
    const { close, page, env } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id;
    await row(page, id).locator('[data-act="pin"]').click();
    env.next = 'not_writer';
    await page.click('[data-act="save"]');
    await page.waitForSelector('.status.err');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'readonly');
    const warned = await page.evaluate(() => { const e = new Event('beforeunload', { cancelable: true }); dispatchEvent(e); return e.defaultPrevented; });
    assert.equal(warned, false);
    await close();
  },

  async '일시 오류 뒤에는 다시 저장할 수 있다'(browser) {
    const { close, page, env } = await setup(browser);
    await admin(page);
    const id = (await S(page)).items[0].id;
    await row(page, id).locator('[data-act="pin"]').click();
    env.next = 'rate_limited';
    await page.click('[data-act="save"]');
    await page.waitForSelector('.status.warn');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'dirty');
    assert.ok(await page.locator('[data-act="save"]').isEnabled());
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    assert.equal(readState(env.published).items.find(x => x.id === id).pinned, true);
    await close();
  },

  async '제외한 항목은 즐겨찾기 가져오기에서 "제외됨"으로 보인다'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base);
    st.tombstones = ['bbbbbbbb-0000-4000-8000-000000000002'];
    const { close, page } = await setup(browser, { initial: withState(base, st) });
    await admin(page);
    const file = '<DL><DT><A HREF="https://claude.ai/code/artifact/bbbbbbbb-0000-4000-8000-000000000002">옛 대시보드</A></DL>';
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.waitForSelector('.imp-row');
    assert.match(await page.locator('.imp-row .flag').innerText(), /제외됨/);
    await close();
  },
};

const browser = await chromium.launch();
let failed = 0;
const only = process.argv[2];
for (const [name, fn] of Object.entries(tests)) {
  if (only && !name.includes(only)) continue;
  try { await fn(browser); console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + String(e.message).split('\n')[0]); }
}
await browser.close();
process.exit(failed ? 1 : 0);
