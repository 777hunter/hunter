// Generates a comic-book style news card image from the latest news-YYYY-MM-DD.md
// using the Gemini image generation API. Run via GitHub Actions with GEMINI_API_KEY set.
import fs from 'node:fs';
import path from 'node:path';

const API_KEY = process.env.GEMINI_API_KEY;
if (!API_KEY) {
  console.error('GEMINI_API_KEY is not set');
  process.exit(1);
}

const repoRoot = process.cwd();

function findLatestNewsFile(dir) {
  const files = fs
    .readdirSync(dir)
    .filter((f) => /^news-\d{4}-\d{2}-\d{2}\.md$/.test(f));
  files.sort();
  return files[files.length - 1];
}

function extractHeadlines(content) {
  const match = content.match(/📰 오늘의 신문 헤드라인\s*\n\n([\s\S]*?)\n\n━/);
  if (!match) return [];
  return match[1]
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
}

function extractDate(content, fallbackFile) {
  const match = content.match(/(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일/);
  if (match) {
    const [, y, m, d] = match;
    return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
  }
  return fallbackFile.replace('news-', '').replace('.md', '');
}

const latestFile = findLatestNewsFile(repoRoot);
if (!latestFile) {
  console.error('No news-*.md file found');
  process.exit(1);
}

const content = fs.readFileSync(path.join(repoRoot, latestFile), 'utf-8');
const headlines = extractHeadlines(content);
const dateStr = extractDate(content, latestFile);

if (headlines.length === 0) {
  console.error('No headlines extracted from', latestFile);
  process.exit(1);
}

const outPath = path.join(repoRoot, 'comic-cards', `comic-${dateStr}.png`);
if (fs.existsSync(outPath)) {
  console.log('Comic card already exists for', dateStr, '- skipping');
  process.exit(0);
}

const prompt = `아래 오늘의 뉴스 내용을 소재로, 미국 코믹북 스타일(굵은 검정 잉크 윤곽선, 망점/하프톤 패턴, 강한 원색 대비, 말풍선, 의성어 효과)의 뉴스카드 이미지를 만들어줘. 인스타그램 세로형(1080x1350) 비율로.

브랜드명은 "헌터의 세상바라보기"로 상단에 로고처럼 넣고, 날짜는 "${dateStr}"로 표기해줘.

${headlines.map((h, i) => `[헤드라인 ${i + 1}] ${h}`).join('\n')}

각 헤드라인을 코믹 패널(칸)처럼 나눠서 배치하고, 장면에 어울리는 캐릭터·오브젝트를 재미있게 그려줘. 텍스트는 이 헤드라인 그대로 정확히 써줘.`;

const MODEL = 'gemini-2.5-flash-image';
const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${API_KEY}`;

const res = await fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    contents: [{ parts: [{ text: prompt }] }],
  }),
});

if (!res.ok) {
  const errText = await res.text();
  console.error('Gemini API error:', res.status, errText);
  process.exit(1);
}

const data = await res.json();
const parts = data?.candidates?.[0]?.content?.parts || [];
const imagePart = parts.find((p) => p.inlineData?.data);

if (!imagePart) {
  console.error('No image returned. Response:', JSON.stringify(data).slice(0, 500));
  process.exit(1);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, Buffer.from(imagePart.inlineData.data, 'base64'));
console.log('Saved', outPath);
