### hunter

# vks — 페이지 요약·분류 + 의미 기반 검색 에이전트

`documents/` 폴더에 넣어둔 문서들을 Claude(Opus 4.8)가 읽어서 **요약**하고
**카테고리로 분류**해 줍니다. 그리고 키워드를 넣으면 단순 단어 매칭이 아니라
**의미가 통하는 문서까지** 찾아서 관련도 순으로 보여줍니다.

## 1. 준비

```bash
# (선택) 가상환경 만들기
python3 -m venv .venv
source .venv/bin/activate

# 필요한 패키지 설치
pip install -r requirements.txt

# Anthropic API 키 설정 (https://console.anthropic.com 에서 발급)
export ANTHROPIC_API_KEY=sk-ant-...
```

## 2. 문서 넣기

`documents/` 폴더에 분석하고 싶은 파일을 넣습니다.
지원 형식: `.txt`, `.md`, `.pdf`

(예시로 `documents/예시-등산노트.md`, `documents/예시-파이썬학습.md` 가 들어 있습니다.)

## 3. 사용법

```bash
# 1) 문서를 요약·분류해서 색인 만들기
python vks.py index

# 2) 분류된 문서 목록 보기
python vks.py list

# 3) 의미 기반으로 검색하기
python vks.py search "운동"
python vks.py search "프로그래밍 자료구조"
```

### 검색 예시

`search "운동"` 이라고 하면, 문서에 '운동'이라는 단어가 직접 없어도
등산·러닝처럼 **뜻이 통하는** 등산노트를 찾아줍니다.

```
1. [ 85점] 북한산 백운대 등반 기록  (등산)
   파일: documents/예시-등산노트.md
   이유: 등산과 러닝 등 신체 활동을 다루고 있어 '운동'과 의미가 연결됩니다.
```

## 동작 방식

- **index**: 각 파일을 Claude가 읽어 제목·요약·분류·키워드를 뽑아 `index.json` 에 저장합니다.
  내용이 바뀌지 않은 파일은 다시 분석하지 않아 비용을 아낍니다.
- **search**: 요약 색인을 Claude가 의미 기반으로 훑어 관련 문서를 골라 점수를 매깁니다.
- 모델은 `--model` 옵션으로 바꿀 수 있습니다 (예: 더 저렴한 `--model claude-haiku-4-5`).

## 참고

- 문서 수가 아주 많아지면(수백 개 이상) 검색 시 한 번에 보내는 요약이 커질 수 있습니다.
  그때는 분류별로 나눠 검색하거나 임베딩 기반 검색으로 확장하는 방법이 있습니다.
- `index.json` 은 각자 생성하는 파일이라 저장소에는 올리지 않습니다(`.gitignore`).
