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

const HUB = process.env.HUB_FILE || join(dirname(fileURLToPath(import.meta.url)), '..', 'hub.html');
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
  page.setDefaultTimeout(5000);   // 정상이면 1초 안에 끝남. 망가진 변이를 빨리 끝내기 위함
  const errors = [];
  page.on('pageerror', e => { errors.push(e.message); lastErrors.push(e.message); });
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
  async '화면: 통계·분류 칩·바닥글 숫자가 레지스트리와 맞다'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base);
    st.items[0].hidden = true; st.items[1].status = 'new'; st.tombstones = ['zz'];
    st.syncedAt = '2026-11-09';
    const { page, close } = await setup(browser, { initial: withState(base, st) });
    const stat = async n => page.locator(`.stat:has(dt:text-is("${n}")) dd`).innerText();
    assert.deepEqual([await stat('전체'), await stat('표시'), await stat('숨김'), await stat('신규')], ['10', '9', '1', '1']);
    const chip = async v => page.locator(`.chip[data-v="${v}"] .n`).innerText();
    assert.equal(await chip('all'), '9');
    const visibleProcess = st.items.filter(x => !x.hidden && x.cat === 'process').length;
    assert.equal(await chip('process'), String(visibleProcess));
    assert.equal(await page.locator('.chip[data-v="unsorted"]').count(), 0, '항목 없는 분류 칩은 숨김');
    assert.equal(await page.getAttribute('.chip[data-v="all"]', 'aria-pressed'), 'true');
    await page.click('.chip[data-v="study"]');
    assert.equal(await page.getAttribute('.chip[data-v="study"]', 'aria-pressed'), 'true');
    assert.equal(await page.getAttribute('.chip[data-v="all"]', 'aria-pressed'), 'false');
    assert.equal(await page.locator('.row').count(), st.items.filter(x => !x.hidden && x.cat === 'study').length);
    const ft = await page.locator('.ft').innerText();
    assert.match(ft, /2026-11-09/); assert.match(ft, /등록 10건/); assert.match(ft, /제외 1건/);
    assert.match(await page.locator('.row').first().innerText(), /최종 수정 \d{4}-\d\d-\d\d/);
    await close();
  },

  async '화면: 행 표시(신규·고정·숨김 표시, 태그, 빈 용도 안내)'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base);
    const [a, b] = st.items;
    a.status = 'new'; a.pinned = true; a.desc = ''; a.tags = ['태그1', '태그2']; b.tags = [];
    const { page, close } = await setup(browser, { initial: withState(base, st) });
    const ra = await row(page, a.id).innerText();
    assert.match(ra, /신규 편입/); assert.match(ra, /고정/); assert.match(ra, /#태그1 #태그2/); assert.match(ra, /용도가 아직 비어/);
    assert.equal(await row(page, b.id).locator('.tagline').count(), 0);
    assert.equal(await row(page, b.id).locator('.flag-new').count(), 0);
    assert.equal(await row(page, a.id).locator('.tile').innerText(), a.icon);
    assert.equal(await row(page, a.id).locator('.tile').getAttribute('aria-hidden'), 'true');
    assert.equal(await page.locator('.row').first().getAttribute('data-id'), a.id, '고정이 맨 위');
    assert.equal(await row(page, a.id).locator('[data-act="hide"]').count(), 0, '관리자 모드 전에는 버튼 없음');
    await close();
  },

  async '화면: 숨긴 항목은 관리자 모드에서 "숨긴 항목도 보기"를 켜야 보인다'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base);
    st.items[0].hidden = true;
    const { page, close } = await setup(browser, { initial: withState(base, st) });
    assert.equal(await row(page, st.items[0].id).count(), 0);
    await admin(page);
    assert.equal(await page.getAttribute('#root', 'data-admin'), 'on');
    assert.equal(await row(page, st.items[0].id).count(), 0);
    assert.equal(await page.locator('.add').count(), 0, '추가 폼은 처음엔 닫힘');
    await page.check('[data-act="showhidden"]');
    assert.match(await row(page, st.items[0].id).innerText(), /숨김/);
    await row(page, st.items[0].id).locator('[data-act="hide"]').click();   // 표시로 되돌림
    await page.uncheck('[data-act="showhidden"]');
    assert.equal(await row(page, st.items[0].id).count(), 1);
    await admin(page);
    assert.equal(await page.getAttribute('#root', 'data-admin'), 'off');
    await close();
  },

  async '화면: 정렬·분류 선택은 다시 열어도 유지된다'(browser) {
    const { page, open, close } = await setup(browser);
    await page.selectOption('.sort', 'title');
    await page.click('.chip[data-v="report"]');
    await open();
    assert.equal(await page.inputValue('.sort'), 'title');
    assert.equal(await page.getAttribute('.chip[data-v="report"]', 'aria-pressed'), 'true');
    const titles = await page.locator('.row .title').allInnerTexts();
    assert.deepEqual(titles, [...titles].sort((x, y) => x.localeCompare(y, 'ko')));
    await page.selectOption('.sort', 'cat');
    assert.equal(await page.inputValue('.sort'), 'cat');
    await page.selectOption('.sort', 'updated');
    assert.equal(await page.inputValue('.sort'), 'updated');
    await close();
  },

  async '화면: 편집 폼은 지금 값으로 채워지고, 편집 중에는 그 행 버튼이 숨는다'(browser) {
    const { page, close } = await setup(browser);
    await admin(page);
    const it = (await S(page)).items.find(x => x.tags.length);
    await row(page, it.id).locator('[data-act="edit"]').click();
    const r = row(page, it.id);
    assert.equal(await r.locator('[data-f="cat"]').inputValue(), it.cat);
    assert.equal(await r.locator('[data-f="tags"]').inputValue(), it.tags.join(', '));
    assert.equal(await r.locator('[data-f="icon"]').inputValue(), it.icon);
    assert.equal(await r.locator('[data-act="pin"]').count(), 0);
    await r.locator('[data-act="cancel"]').click();
    assert.equal(await r.locator('.form').count(), 0);
    await close();
  },

  async '화면: 저장 버튼은 바뀐 게 있을 때만 켜지고, 저장하면 문서 모양과 동기화 날짜가 맞다'(browser) {
    const base = readFileSync(HUB, 'utf8');
    const st = readState(base); st.syncedAt = '';
    const { page, env, close } = await setup(browser, { initial: withState(base, st) });
    await admin(page);
    assert.ok(await page.locator('[data-act="save"]').isDisabled());
    assert.equal(await page.locator('[data-act="save"]').innerText(), '저장됨');
    await page.locator('[data-act="pin"]').first().click();
    assert.ok(await page.locator('[data-act="save"]').isEnabled());
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    assert.ok(env.published.startsWith('<!doctype html>\n<html lang="ko">'));
    assert.match(readState(env.published).syncedAt, /^\d{4}-\d\d-\d\d$/);
    assert.match(env.published, /<script id="app">[\s\S]*HubCore/);
    await close();
  },

  async '화면: 충돌이면 잠기고, 너무 크면 알려 준다'(browser) {
    const { page, env, close } = await setup(browser);
    await admin(page);
    await page.locator('[data-act="pin"]').first().click();
    env.next = 'too_large';
    await page.click('[data-act="save"]');
    assert.match(await page.locator('.status').innerText(), /너무 큽니다/);
    env.next = 'conflict';
    await page.click('[data-act="save"]');
    await page.waitForSelector('.status.warn');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'conflict');
    assert.ok(await page.locator('[data-act="pin"]').first().isDisabled());
    assert.ok(await page.locator('[data-act="addform"]').isDisabled());
    await page.click('.chip[data-v="report"]');           // 보기 조작은 잠기지 않음
    assert.equal(await page.getAttribute('.chip[data-v="report"]', 'aria-pressed'), 'true');
    await close();
  },

  async '화면: 보기 전용이 되면 열린 폼이 모두 닫힌다'(browser) {
    const { page, env, close } = await setup(browser);
    await admin(page);
    await page.locator('[data-act="pin"]').first().click();
    await page.click('[data-act="addform"]');
    env.next = 'not_writer';
    await page.click('[data-act="save"]');
    await page.waitForSelector('.status.err');
    assert.equal(await page.locator('.add').count(), 0);
    assert.equal(await page.locator('[data-act="admin"]').count(), 0);
    assert.equal(await page.getAttribute('#root', 'data-admin'), 'off');
    await close();
  },

  async '화면: 바뀐 게 있으면 떠날 때 묻는다'(browser) {
    const { page, close } = await setup(browser);
    await admin(page);
    const ask = () => page.evaluate(() => { const e = new Event('beforeunload', { cancelable: true }); dispatchEvent(e); return e.defaultPrevented; });
    assert.equal(await ask(), false);
    await page.locator('[data-act="pin"]').first().click();
    assert.equal(await ask(), true);
    await close();
  },

  async '화면: 추가 폼 열기·취소, 주소 없이 추가하면 안내'(browser) {
    const { page, close } = await setup(browser);
    await admin(page);
    await page.click('[data-act="addform"]');
    await page.click('[data-act="addsave"]');
    assert.match(await page.locator('.status.err').innerText(), /주소를 입력/);
    await page.click('[data-act="addcancel"]');
    assert.equal(await page.locator('.add').count(), 0);
    await page.click('[data-act="addform"]');
    await page.fill('[data-n="url"]', (await S(page)).items[0].url);
    await page.click('[data-act="addsave"]');
    assert.match(await page.locator('.status.warn').innerText(), /이미 등록/);
    await page.fill('[data-n="url"]', 'https://in.house/new');
    await page.click('[data-act="addsave"]');
    assert.equal(await page.locator('.add').count(), 0, '추가하면 폼이 닫힘');
    assert.match(await page.locator('.status.ok').innerText(), /추가했습니다/);
    await close();
  },

  async '화면: 즐겨찾기 가져오기의 폴더·선택·취소'(browser) {
    const { page, close } = await setup(browser);
    await admin(page);
    const file = '<DL><DT><H3>가</H3><DL><DT><A HREF="https://a.test/1">A1</A><DT><A HREF="https://a.test/2">A2</A></DL>' +
                 '<DT><H3>나</H3><DL><DT><A HREF="https://b.test/1">B1</A></DL>' +
                 '<DT><A HREF="https://c.test/x">C</A><DT><A HREF="javascript:void(0)">JS</A></DL>';
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.waitForSelector('.imp-row');
    const add = page.locator('[data-act="impadd"]');
    assert.ok(await add.isDisabled());
    assert.equal(await page.locator('.imp-sel-count').innerText(), '0');
    assert.deepEqual(await page.locator('.imp-chips .chip').allInnerTexts(), ['전체4', '가2', '나1', '(폴더 없음)1']);
    assert.deepEqual(await page.locator('.imp-t').allInnerTexts(), ['A1', 'A2', 'B1', 'C']);
    await page.click('.imp-chips .chip[data-v="가"]');
    assert.equal(await page.getAttribute('.imp-chips .chip[data-v="가"]', 'aria-pressed'), 'true');
    assert.equal(await page.getAttribute('.imp-chips .chip[data-v="all"]', 'aria-pressed'), 'false');
    assert.equal(await page.locator('.imp-row').count(), 2);
    await page.click('[data-act="impall"]');
    assert.equal(await add.innerText(), '선택한 2건 추가');
    await page.click('.imp-chips .chip[data-v="all"]');
    const box = t => page.locator('.imp-row').filter({ has: page.locator('.imp-t', { hasText: new RegExp('^' + t + '$') }) }).locator('input');
    assert.equal(await box('A1').isChecked(), true, '고른 행은 체크로 보임');
    assert.equal(await box('C').isChecked(), false, '안 고른 행은 체크 안 됨');
    await page.locator('.imp-row', { hasText: 'C' }).locator('input').check();
    assert.equal(await page.locator('.imp-sel-count').innerText(), '3');
    assert.ok(await add.isEnabled());
    await page.locator('.imp-row', { hasText: 'C' }).locator('input').uncheck();
    assert.equal(await add.innerText(), '선택한 2건 추가');
    await page.click('.imp-chips .chip[data-v="가"]');
    await page.click('[data-act="impnone"]');
    assert.equal(await add.innerText(), '선택한 0건 추가');
    await page.click('[data-act="impall"]');
    await page.click('[data-act="impclear"]');
    assert.equal(await add.innerText(), '선택한 0건 추가');
    await page.click('[data-act="impcancel"]');
    assert.equal(await page.locator('.imp').count(), 0);
    await page.setInputFiles('[data-act="bmfile"]', { name: 'e.html', mimeType: 'text/html', buffer: Buffer.from('<p>없음</p>') });
    await page.waitForSelector('.status.warn');
    assert.match(await page.locator('.status.warn').innerText(), /웹 주소를 찾지 못했습니다/);
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.waitForSelector('.imp-row');
    assert.equal(await page.locator('.adm .status').count(), 0, '제대로 읽으면 앞선 경고는 지움');
    await page.click('[data-act="impcancel"]');
    assert.equal(await page.getAttribute('#root', 'data-save-state'), 'clean');
    await close();
  },

  async '화면: 가져오기 창을 연 채로 저장해도 가져오기는 그대로'(browser) {
    const { page, env, close } = await setup(browser);
    await admin(page);
    await page.locator('[data-act="pin"]').first().click();
    const file = '<DL><DT><A HREF="https://a.test/1">A1</A></DL>';
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.waitForSelector('.imp-row');
    await page.click('[data-act="impall"]');
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    assert.equal(await page.locator('.imp').count(), 1);
    assert.ok(!readState(env.published).items.some(x => x.url === 'https://a.test/1'));
    await close();
  },

  async '화면: 가져오기에서 고른 것만, 선택 0건이면 안내'(browser) {
    const { page, env, close } = await setup(browser);
    await admin(page);
    const file = '<DL><DT><A HREF="https://a.test/1">A1</A><DT><A HREF="https://a.test/2">A2</A></DL>';
    await page.setInputFiles('[data-act="bmfile"]', { name: 'b.html', mimeType: 'text/html', buffer: Buffer.from(file) });
    await page.waitForSelector('.imp-row');
    await page.locator('.imp-row', { hasText: 'A2' }).locator('input').check();
    await page.click('[data-act="impadd"]');
    assert.match(await page.locator('.status.ok').innerText(), /1건을 목록에 넣었습니다/);
    await page.click('[data-act="save"]');
    await page.waitForFunction(() => document.getElementById('root').dataset.saveState === 'clean');
    const out = readState(env.published);
    assert.ok(out.items.some(x => x.url === 'https://a.test/2'));
    assert.ok(!out.items.some(x => x.url === 'https://a.test/1'));
    const added = out.items.find(x => x.url === 'https://a.test/2');
    assert.deepEqual([added.hidden, added.pinned, added.titleLocked, added.status], [false, false, true, 'new']);
    await close();
  },

  async '화면: 편집 권한 런타임이 없는 곳에서도 목록이 보인다'(browser) {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route(URL, r => r.fulfill({ contentType: 'text/html; charset=utf-8', body: readFileSync(HUB, 'utf8') }));
    await page.route('https://fonts.googleapis.com/**', r => r.abort());
    await page.goto(URL);
    await page.waitForSelector('.row', { timeout: 3000 });
    assert.equal(await page.locator('[data-act="admin"]').count(), 0);
    await ctx.close();
    assert.deepEqual(errors, []);
  },

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

const lastErrors = [];  // 실패 메시지에 페이지 오류를 같이 보여 주기 위함
const browser = await chromium.launch();
let failed = 0;
const only = process.argv[2];
for (const [name, fn] of Object.entries(tests)) {
  if (only && !name.includes(only)) continue;
  lastErrors.length = 0;
  try { await fn(browser); console.log('ok   ' + name); }
  catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + String(e.message).split('\n')[0] +
    (lastErrors.length ? '\n     페이지 오류: ' + lastErrors.join(' / ') : '')); if (process.env.FAIL_FAST) break; }
}
await browser.close();
process.exit(failed ? 1 : 0);
