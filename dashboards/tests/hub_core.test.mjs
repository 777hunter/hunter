// 허브 규칙(HubCore)을 브라우저 없이 검사합니다. hub.html 에서 HubCore 구간만 떼어 실행합니다.
// 실행: node --test dashboards/tests/hub_core.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HUB = process.env.HUB_FILE || join(dirname(fileURLToPath(import.meta.url)), '..', 'hub.html');
const html = readFileSync(HUB, 'utf8');
const src = html.slice(html.indexOf('// ── HubCore 시작'), html.indexOf('// ── HubCore 끝'));
const C = new Function(src + '\nreturn HubCore;')();

const it = (o = {}) => ({ id: 'a', url: 'u', title: 'T', desc: '', cat: 'process', tags: [], updated: '2026-01-01',
                          hidden: false, pinned: false, status: 'ready', ...o });
const st = (o = {}) => C.normalizeState({ categories: C.clone(C.DEF_CATS), items: [], tombstones: [], ...o });
const cats = C.DEF_CATS;

test('normalizeState: 깨진 입력을 기본 모양으로', () => {
  for (const bad of [null, undefined, 3, 'x', []]) {
    const s = C.normalizeState(bad);
    assert.deepEqual(s, { categories: C.DEF_CATS, items: [], tombstones: [], version: 1, syncedAt: '' });
  }
  const s = C.normalizeState({ categories: [], items: 'x', tombstones: {}, version: '2', syncedAt: 5 });
  assert.deepEqual([s.categories, s.items, s.tombstones, s.version, s.syncedAt], [C.DEF_CATS, [], [], 1, '']);
  const keep = C.normalizeState({ categories: [{ id: 'z', label: 'Z' }], version: 3, syncedAt: '2026-01-01' });
  assert.deepEqual([keep.categories, keep.version, keep.syncedAt], [[{ id: 'z', label: 'Z' }], 3, '2026-01-01']);
  keep.categories.push(1);
  assert.equal(C.normalizeState(null).categories.length, 6, '기본 분류를 공유하면 안 됨');
});

test('normItem: 상태·불리언·태그 정리', () => {
  assert.deepEqual(C.normItem({ status: 'weird', hidden: 1, pinned: 0, tags: 'x' }),
                   { status: 'ready', hidden: true, pinned: false, tags: [] });
  assert.deepEqual(C.normItem({ status: 'new', hidden: false, pinned: true, tags: ['a'] }),
                   { status: 'new', hidden: false, pinned: true, tags: ['a'] });
  const s = C.normalizeState({ items: [{ status: '?' }, { status: 'new' }] });
  assert.deepEqual(s.items.map(x => x.status), ['ready', 'new']);
});

test('reviewed: new 만 ready 로', () => {
  assert.equal(C.reviewed({ status: 'new' }).status, 'ready');
  assert.equal(C.reviewed({ status: 'ready' }).status, 'ready');
});

test('저장 상태 전이표 전체', () => {
  const states = ['clean', 'dirty', 'saving', 'conflict', 'readonly'];
  const events = ['edit', 'save', 'ok', 'fail', 'conflict', 'readonly'];
  const want = {
    clean: { edit: 'dirty', readonly: 'readonly' },
    dirty: { edit: 'dirty', save: 'saving', readonly: 'readonly' },
    saving: { ok: 'clean', fail: 'dirty', conflict: 'conflict', readonly: 'readonly' },
    conflict: {}, readonly: {}
  };
  for (const s of states) for (const e of events) assert.equal(C.nextSave(s, e), want[s][e] || null, `${s} --${e}-->`);
  assert.deepEqual(states.filter(C.canEdit), ['clean', 'dirty']);
});

test('esc, ymd, 분류, id', () => {
  assert.equal(C.esc(`&<>"'`), '&amp;&lt;&gt;&quot;&#39;');
  assert.equal(C.esc(null), '');
  assert.equal(C.ymd(new Date(2026, 0, 5)), '2026-01-05');
  assert.equal(C.ymd(new Date(2026, 10, 16)), '2026-11-16');
  assert.equal(C.ymd(new Date(2026, 8, 10)), '2026-09-10');
  assert.equal(C.catId(cats, 'study'), 'study');
  assert.equal(C.catId(cats, 'nope'), 'unsorted');
  assert.equal(C.catLabel(cats, 'study'), '학습·자료');
  assert.equal(C.catLabel(cats, 'nope'), '미분류');
  assert.equal(C.idFromUrl('https://x/artifact/ABCDEF01-0000-4000-8000-00000000000A'), 'abcdef01-0000-4000-8000-00000000000a');
  assert.equal(C.idFromUrl('https://x/y'), '');
  assert.equal(C.idFromUrl(null), '');
});

test('rebase: 바뀐 것만 지금 버전 위에', () => {
  const base = st({ items: [it({ id: 'a', desc: 'b' }), it({ id: 'b' }), it({ id: 'g' })], tombstones: ['t1'] });
  const cur = st({ items: [it({ id: 'a', desc: 'b', title: '남이 고침' }), it({ id: 'b' }), it({ id: 'g' }),
                           it({ id: 'n', title: '동기화 신규' })], tombstones: ['t1'] });
  const draft = C.clone(base);
  draft.items[0].desc = '내 편집';                       // 필드 수정
  draft.items.push(it({ id: 'mine' }));                   // 새 항목
  draft.items = draft.items.filter(x => x.id !== 'b');   // 목록에서 제거
  draft.tombstones = ['b'];                               // t1 되살림 + b 제외
  const before = C.clone(cur);
  const r = C.rebase(cur, base, draft);
  assert.deepEqual(cur, before, '입력을 바꾸면 안 됨');
  const ids = r.state.items.map(x => x.id);
  assert.deepEqual(ids, ['a', 'g', 'n', 'mine']);
  assert.equal(r.state.items[0].desc, '내 편집');
  assert.equal(r.state.items[0].title, '남이 고침', '내가 안 건드린 필드는 지금 값');
  assert.deepEqual(r.state.tombstones.sort(), ['b']);
  assert.equal(r.changes, 5);
});

test('rebase: 이미 반영된 초안은 변경 0', () => {
  const base = st({ items: [it()] });
  const draft = C.clone(base); draft.items[0].pinned = true; draft.tombstones = ['x'];
  const cur = C.clone(draft);
  assert.equal(C.rebase(cur, base, draft).changes, 0);
});

test('rebase: 계속 제외 중인 항목은 그대로 둔다', () => {
  const base = st({ items: [it()], tombstones: ['k'] });
  const draft = C.clone(base); draft.items[0].pinned = true;
  const cur = st({ items: [it()], tombstones: ['k'] });
  const r = C.rebase(cur, base, draft);
  assert.deepEqual(r.state.tombstones, ['k']);
  assert.equal(r.changes, 1);
});

test('rebase: 다른 곳의 결정을 따르는 경우', () => {
  const base = st({ items: [it({ id: 'a' }), it({ id: 'b' })] });
  const draft = C.clone(base);
  draft.items[0].desc = '편집';                          // 그 사이 a 는 다른 곳에서 제거됨
  draft.items.push(it({ id: 'z' }));                     // z 는 그 사이 tombstone 됨
  draft.items.push(it({ id: 'y', title: '내 y' }));      // y 는 그 사이 동기화로 이미 들어옴
  draft.items = draft.items.filter(x => x.id !== 'b');   // b 는 이미 다른 곳에서 제거됨
  const cur = st({ items: [it({ id: 'y', title: '동기화 y' })], tombstones: ['z'] });
  const r = C.rebase(cur, base, draft);
  assert.deepEqual(r.state.items.map(x => [x.id, x.title]), [['y', '동기화 y']]);
  assert.deepEqual(r.state.tombstones, ['z']);
  assert.equal(r.changes, 0);
});

test('rebase: 옛 형식 초안(base 없음)은 추가·수정만', () => {
  const cur = st({ items: [it({ id: 'a' }), it({ id: 'b' })], tombstones: ['t'] });
  const draft = st({ items: [it({ id: 'a', desc: '편집' }), it({ id: 'new' }), it({ id: 't' })], tombstones: [] });
  const r = C.rebase(cur, null, draft);
  assert.deepEqual(r.state.items.map(x => x.id), ['a', 'b', 'new']);
  assert.equal(r.state.items[0].desc, '편집');
  assert.deepEqual(r.state.tombstones, ['t']);
  assert.equal(r.changes, 2);
});

test('visible: 숨김·분류·검색', () => {
  const f = (o = {}) => ({ q: '', cat: 'all', admin: false, showHidden: false, ...o });
  const h = it({ hidden: true });
  assert.equal(C.visible(h, f(), cats), false);
  assert.equal(C.visible(h, f({ admin: true }), cats), false);
  assert.equal(C.visible(h, f({ showHidden: true }), cats), false);
  assert.equal(C.visible(h, f({ admin: true, showHidden: true }), cats), true);
  assert.equal(C.visible(it(), f({ cat: 'process' }), cats), true);
  assert.equal(C.visible(it(), f({ cat: 'study' }), cats), false);
  assert.equal(C.visible(it({ cat: '모름' }), f({ cat: 'unsorted' }), cats), true);
  const x = it({ title: 'Alpha', desc: '열응력', tags: ['브레이징'], cat: 'study' });
  for (const q of ['alpha', ' ALPHA ', '응력', '브레이징', '학습']) assert.equal(C.visible(x, f({ q }), cats), true, q);
  assert.equal(C.visible(x, f({ q: '없는말' }), cats), false);
});

test('sortItems: 고정 먼저, 그다음 정렬 기준', () => {
  const list = [it({ id: '1', title: '나', updated: '2026-03-01', cat: 'report' }),
                it({ id: '2', title: '가', updated: '2026-01-01', cat: 'process' }),
                it({ id: '3', title: '다', updated: '2026-02-01', cat: 'process', pinned: true }),
                it({ id: '4', title: '라', updated: '2026-04-01', cat: 'process' })];
  const ids = (s) => C.sortItems(list, s, cats).map(x => x.id).join('');
  assert.equal(ids('updated'), '3412');
  assert.equal(ids('title'), '3214');
  assert.equal(ids('cat'), '3421');
  assert.deepEqual(list.map(x => x.id).join(''), '1234', '원본 순서 유지');
  const both = [it({ id: 'p', pinned: true, updated: '2026-01-01' }), it({ id: 'q', pinned: true, updated: '2026-02-01' })];
  assert.equal(C.sortItems(both, 'updated', cats).map(x => x.id).join(''), 'qp');
});

test('stats, chipCounts', () => {
  const items = [it({ hidden: true, status: 'new' }), it({ status: 'new', cat: 'study' }), it({ cat: '모름' })];
  assert.deepEqual(C.stats(items), { total: 3, hidden: 1, fresh: 2 });
  assert.deepEqual(C.chipCounts(items, { admin: false, showHidden: false }, cats), { all: 2, study: 1, unsorted: 1 });
  assert.deepEqual(C.chipCounts(items, { admin: true, showHidden: true }, cats), { all: 3, process: 1, study: 1, unsorted: 1 });
});

test('bmId: 아티팩트 id 그대로, 아니면 고정 해시', () => {
  assert.equal(C.bmId('https://claude.ai/code/artifact/AAAAAAAA-0000-4000-8000-000000000001'), 'aaaaaaaa-0000-4000-8000-000000000001');
  assert.equal(C.bmId('https://example.com/dash'), 'bm-d6ce9f348820');
  assert.notEqual(C.bmId('https://example.com/a'), C.bmId('https://example.com/b'));
  assert.match(C.bmId('x'), /^bm-[0-9a-f]{12}$/);
  assert.equal(C.normUrl('https://a/b///'), 'https://a/b');
  assert.equal(C.normUrl(null), '');
});

test('classifyBookmarks: 제외됨·이미 등록·자기 자신·파일 안 중복', () => {
  const S = st({ items: [it({ id: 'aaaaaaaa-0000-4000-8000-000000000001', url: 'https://reg/x' })],
                 tombstones: ['BBBBBBBB-0000-4000-8000-000000000002'], selfId: 'CCCCCCCC-0000-4000-8000-000000000003' });
  const rows = C.classifyBookmarks([
    { title: '등록', url: 'https://claude.ai/code/artifact/aaaaaaaa-0000-4000-8000-000000000001', folder: 'F' },
    { title: '제외', url: 'https://claude.ai/code/artifact/bbbbbbbb-0000-4000-8000-000000000002', folder: '' },
    { title: '허브', url: 'https://claude.ai/code/artifact/cccccccc-0000-4000-8000-000000000003', folder: '' },
    { title: '같은주소', url: 'https://reg/x/', folder: '' },
    { title: '새것', url: 'https://new/y', folder: 'G' },
    { title: '새것 중복', url: 'https://new/y/', folder: 'G' },
  ], S);
  assert.deepEqual(rows.map(r => [r.title, r.why, r.dup, r.sel]),
    [['등록', 'dup', true, false], ['제외', 'tomb', true, false], ['허브', 'dup', true, false],
     ['같은주소', 'dup', true, false], ['새것', '', false, false]]);
  assert.deepEqual(rows[4], { title: '새것', url: 'https://new/y', folder: 'G', id: C.bmId('https://new/y'), dup: false, why: '', sel: false });
});

test('importedItem, addManual, applyEdit, drop', () => {
  assert.deepEqual(C.importedItem({ id: 'i', url: 'u', title: 't', folder: 'F' }, '2026-11-16'),
    { id: 'i', url: 'u', title: 't', icon: '▤', cat: 'unsorted', desc: '', tags: ['F'], updated: '2026-11-16',
      added: '2026-11-16', hidden: false, pinned: false, status: 'new', titleLocked: true });
  assert.deepEqual(C.importedItem({ id: 'i', url: 'u', title: 't', folder: '' }, 'd').tags, []);

  const S = st({ items: [it({ id: 'have' })], tombstones: ['aaaaaaaa-0000-4000-8000-000000000001', 'keep'] });
  assert.deepEqual(C.addManual(S, { url: '  ' }, 'd', 'fb'), { error: 'no_url' });
  assert.deepEqual(C.addManual(S, { url: 'https://x/have-not-uuid' }, 'd', 'have'), { error: 'exists' });
  const r = C.addManual(S, { url: 'https://claude.ai/code/artifact/AAAAAAAA-0000-4000-8000-000000000001', cat: 'nope' }, 'd', 'fb');
  assert.deepEqual(r.item, { id: 'aaaaaaaa-0000-4000-8000-000000000001', url: 'https://claude.ai/code/artifact/AAAAAAAA-0000-4000-8000-000000000001',
    title: '제목 없음', icon: '▤', cat: 'unsorted', desc: '', tags: [], updated: 'd', added: 'd',
    hidden: false, pinned: false, status: 'ready', titleLocked: true });
  assert.deepEqual(S.tombstones, ['keep']);
  const r2 = C.addManual(S, { url: 'https://in/house', title: '사내', icon: '⚙️', cat: 'tool', desc: '용도' }, 'd', 'x1');
  assert.deepEqual([r2.item.id, r2.item.title, r2.item.icon, r2.item.cat, r2.item.desc], ['x1', '사내', '⚙️', 'tool', '용도']);
  assert.equal(S.items.length, 3);

  const e = it({ status: 'new', title: '원래', icon: '🔥', url: 'u0' });
  C.applyEdit(e, { title: '원래', desc: 'd', cat: 'study', icon: '', url: '', tags: ' a, ,b ' }, cats);
  assert.deepEqual([e.titleLocked, e.title, e.desc, e.cat, e.icon, e.url, e.tags, e.status],
                   [undefined, '원래', 'd', 'study', '🔥', 'u0', ['a', 'b'], 'ready']);
  C.applyEdit(e, { title: '새 제목', desc: '', cat: 'nope', icon: '⚡', url: 'u1', tags: '' }, cats);
  assert.deepEqual([e.titleLocked, e.title, e.cat, e.icon, e.url, e.tags], [true, '새 제목', 'unsorted', '⚡', 'u1', []]);
  C.applyEdit(e, { title: '', desc: '', cat: 'study', icon: '', url: '', tags: '' }, cats);
  assert.equal(e.title, '새 제목');

  const D = st({ items: [it({ id: 'a' }), it({ id: 'b' })], tombstones: ['a'] });
  C.drop(D, 'a'); C.drop(D, 'b');
  assert.deepEqual([D.items, D.tombstones], [[], ['a', 'b']]);
});
