# 앱별 수정 패치

각 앱은 자기 브랜치에만 있어서, 수정은 앱마다 커밋 하나로 만들어 여기 두었습니다.
해당 브랜치에서 그대로 적용하면 됩니다.

| 패치 | 적용할 브랜치 | 테스트 |
| --- | --- | --- |
| motion.patch | claude/video-motion-recognition-y0dk55 | `python3 -m unittest discover -s motion/tests` |
| kakao.patch | claude/july-15-news-kakao-send-ienj6y | `python3 -m unittest discover -s tests` |
| comic.patch | claude/news-card-august-1st-8ivdfe | `node scripts/generate-comic-card.mjs --plan` |
| vks.patch | claude/vks-page-summary-agent-jsxs68 | `python3 -m unittest discover -s tests` |
| camera.patch | claude/silent-camera-setup-qo106e | `node tests/stream_race.cjs index.html` |
| organizer.patch | ccr-dea50f74-1njgsl | (화면 확인) |

```bash
git switch claude/video-motion-recognition-y0dk55
git am reports/2026-11-16/patches/motion.patch   # 다른 브랜치에서 파일을 꺼내 쓰려면 git show 로
```
