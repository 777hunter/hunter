### hunter

# vks 도구 모음

Vatech 사내 위키(**Confluence, vks.vatech.com**) 페이지의 변경 내용을
기간·시간 간격별로 정리하고, 문서를 요약·분류·검색하는 도구입니다.

> ⚠️ **중요:** `vks.vatech.com`은 사내 로그인이 필요하고, 이 도구가 돌아가는
> 일부 환경(클라우드)에서는 접근이 차단됩니다. **vks에 접속 가능하고 로그인된
> 본인 PC(사내망/VPN)에서 실행**하세요.

---

## 1) 메인 도구 — `vks_timeline.py` (Confluence 페이지 변경 정리)

한 위키 페이지가 **특정 기간** 동안 어떻게 바뀌었는지를, **하루 단위(전일)** 또는
**N시간 간격**으로 묶어서 "무엇이 추가/수정/삭제됐는지" Claude가 요약해 줍니다.
(시간 기준 = 페이지 **수정 이력(버전)**)

### 준비

```bash
pip install -r requirements.txt

# Confluence 개인 액세스 토큰(PAT) 발급:
#   vks 로그인 → 우측 상단 프로필 → 설정/Personal Access Tokens 에서 생성
export VKS_TOKEN=...                     # 필수
export VKS_BASE_URL=https://vks.vatech.com   # 기본값이라 보통 생략 가능
export ANTHROPIC_API_KEY=sk-ant-...      # 요약(Claude)용

# (사내 인증서/로그인 방식에 따라)
# export VKS_AUTH=basic ; export VKS_USER=사번   # PAT 대신 ID/비번 방식이면
```

### 사용법

```bash
# 0) 먼저 연결·인증 점검 (Claude 호출 없이 버전 목록만)  ← 토큰 확인용으로 추천
python vks_timeline.py --page 123456 --from 2026-06-01 --to 2026-06-17 --list-versions

# 1) 하루 단위로 변경 내용 요약
python vks_timeline.py --page 123456 --from 2026-06-01 --to 2026-06-17 --bucket day

# 2) 6시간 간격으로 요약하고 파일로 저장
python vks_timeline.py \
    --page "https://vks.vatech.com/pages/viewpage.action?pageId=123456" \
    --from 2026-06-15 --to 2026-06-17 --bucket 6h --save report.md
```

- `--page` : 숫자 페이지 ID 또는 페이지 주소(`pageId=` / `/pages/숫자` 포함)
- `--from`, `--to` : 기간(YYYY-MM-DD, 한국시간 기준, `--to`는 그 날 포함)
- `--bucket` : `day`(전일) 또는 `6h`·`12h` 같은 N시간 간격
- `--list-versions` : 요약 없이 기간 내 편집 목록만 보기
- `--save` : 결과를 `.md` 파일로 저장

### 페이지 ID 찾는 법
페이지 우측 `···` → **페이지 정보(Page Information)** 에 들어가면 주소창에
`pageId=숫자` 가 보입니다. 그 숫자를 `--page` 에 넣으면 됩니다.

### 동작 방식
버전 이력 조회(`/rest/api/content/{id}/version`) → 기간 필터 → 날짜/N시간으로 묶기
→ 각 구간 끝 버전의 본문을 직전 구간과 비교(diff) → 그 변경분을 Claude가 한국어로 요약.

---

## 2) 보조 도구 — `vks.py` (문서 요약·분류 + 의미 기반 검색)

`documents/` 폴더에 넣어둔 파일(txt/md/pdf)을 요약·분류하고, 키워드를 넣으면
**뜻이 통하는** 문서를 찾아줍니다. vks에서 페이지를 저장(내보내기)해 폴더에 넣고
검색·분류하는 용도로 쓸 수 있습니다.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python vks.py index            # documents/ 안의 문서를 요약·분류해 색인 생성
python vks.py list             # 분류된 문서 목록 보기
python vks.py search "운동"     # 의미 기반 검색
```

---

## 참고
- 모델은 두 도구 모두 기본 `claude-opus-4-8`. `vks.py`는 `--model claude-haiku-4-5` 로 저렴하게 바꿀 수 있습니다.
- `index.json`, `report.md` 등 생성물은 각자 만들어 쓰는 파일이라 저장소에 올리지 않습니다(`.gitignore`).
- 이 환경에서는 vks 접속이 막혀 있어, vks 실제 호출 테스트는 본인 PC에서 해야 합니다.
