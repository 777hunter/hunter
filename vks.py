#!/usr/bin/env python3
"""
vks — 페이지 요약·분류 + 의미 기반 검색 에이전트

documents/ 폴더에 넣어둔 문서들을 Claude(Opus 4.8)가 읽어서
요약하고 카테고리로 분류한 뒤, 키워드를 넣으면 '의미가 통하는' 문서를
관련도 순으로 찾아줍니다. (단순 단어 매칭이 아니라 뜻 기반 검색)

사용법:
    python vks.py index            # documents/ 안의 문서를 요약·분류해서 색인 생성
    python vks.py search "키워드"   # 색인에서 의미 기반으로 관련 문서 검색
    python vks.py list             # 분류된 문서 목록 보기

필요한 것: ANTHROPIC_API_KEY 환경변수 (Anthropic API 키)
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import anthropic

# ──────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────

# 기본 모델. 더 저렴하게 쓰려면 "claude-haiku-4-5" 로 바꾸거나 --model 옵션 사용.
DEFAULT_MODEL = "claude-opus-4-8"

# 문서를 넣어두는 폴더와 색인 파일 위치
DOCS_DIR = Path("documents")
INDEX_FILE = Path("index.json")

# 읽어들일 파일 확장자
TEXT_EXTS = {".txt", ".md", ".markdown"}
PDF_EXTS = {".pdf"}


# 요약·분류 결과의 JSON 형식 (구조화 출력으로 항상 올바른 JSON을 받기 위함)
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "category": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "category", "keywords"],
    "additionalProperties": False,
}

# 검색 결과의 JSON 형식
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "relevance": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["file", "relevance", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


# ──────────────────────────────────────────────────────────────────────────
# 문서 읽기
# ──────────────────────────────────────────────────────────────────────────

def read_document(path: Path) -> str:
    """파일 하나를 읽어서 텍스트로 돌려준다. 지원하지 않으면 빈 문자열."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="replace")
    if ext in PDF_EXTS:
        try:
            from pypdf import PdfReader
        except ImportError:
            print(
                f"  ! PDF를 읽으려면 'pip install pypdf' 가 필요합니다 (건너뜀): {path}",
                file=sys.stderr,
            )
            return ""
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    return ""


def collect_documents() -> list[Path]:
    """documents/ 폴더 안에서 읽을 수 있는 파일들을 모은다."""
    if not DOCS_DIR.exists():
        return []
    allowed = TEXT_EXTS | PDF_EXTS
    files = [p for p in sorted(DOCS_DIR.rglob("*")) if p.is_file() and p.suffix.lower() in allowed]
    return files


def file_hash(text: str) -> str:
    """파일 내용의 해시. 내용이 안 바뀌면 다시 요약하지 않으려고 사용."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Claude 호출
# ──────────────────────────────────────────────────────────────────────────

def summarize_document(client: anthropic.Anthropic, model: str, filename: str, text: str) -> dict:
    """문서 하나를 요약하고 카테고리·키워드를 뽑는다."""
    system = (
        "너는 문서를 분석해 한국어로 요약하고 분류하는 도우미다. "
        "주어진 문서를 읽고 다음을 만들어라:\n"
        "- title: 문서를 대표하는 짧은 제목\n"
        "- summary: 문서의 핵심 내용을 3~5문장으로 정리한 요약\n"
        "- category: 문서를 한마디로 구분하는 분류명 (예: '회의록', '아이디어', '학습노트', '레시피' 등)\n"
        "- keywords: 이 문서를 잘 나타내는 핵심 키워드 4~8개\n"
        "모든 출력은 한국어로 작성한다."
    )
    user = f"파일명: {filename}\n\n=== 문서 내용 시작 ===\n{text}\n=== 문서 내용 끝 ==="

    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
    )
    # 구조화 출력을 쓰면 첫 번째 text 블록이 항상 올바른 JSON이다.
    raw = next(b.text for b in resp.content if b.type == "text")
    return json.loads(raw)


def semantic_search(client: anthropic.Anthropic, model: str, index: dict, query: str) -> list[dict]:
    """색인(요약 모음)을 의미 기반으로 훑어 관련 문서를 관련도 순으로 고른다."""
    # 각 문서의 요약·분류·키워드를 한데 모아 '카탈로그'를 만든다.
    lines = []
    for doc in index["documents"]:
        lines.append(
            f"[file] {doc['file']}\n"
            f"  제목: {doc['title']}\n"
            f"  분류: {doc['category']}\n"
            f"  키워드: {', '.join(doc['keywords'])}\n"
            f"  요약: {doc['summary']}\n"
        )
    catalog = "\n".join(lines)

    system = (
        "너는 의미 기반(semantic) 검색 엔진이다. 아래는 문서 카탈로그다. "
        "사용자의 검색어와 '뜻이 통하는' 문서를 찾아라. 똑같은 단어가 없어도 "
        "의미가 관련되면 포함한다. 각 결과에 대해:\n"
        "- file: 카탈로그의 [file] 값을 그대로\n"
        "- relevance: 0~100 사이 관련도 점수 (높을수록 관련 깊음)\n"
        "- reason: 왜 관련 있는지 한국어로 한두 문장\n"
        "관련 있는 문서만 relevance 높은 순으로 정렬해 반환하고, "
        "관련 문서가 없으면 빈 목록을 반환한다.\n\n"
        "=== 문서 카탈로그 ===\n" + catalog
    )

    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        thinking={"type": "adaptive"},  # 의미 판단을 위해 적응형 사고 사용
        system=[
            # 카탈로그는 잘 안 바뀌므로 캐시해 두면 반복 검색이 더 싸고 빠르다.
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": f"검색어: {query}"}],
        output_config={"format": {"type": "json_schema", "schema": SEARCH_SCHEMA}},
    )
    raw = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(raw)
    results = data.get("results", [])
    results.sort(key=lambda r: r.get("relevance", 0), reverse=True)
    return results


# ──────────────────────────────────────────────────────────────────────────
# 색인 저장/불러오기
# ──────────────────────────────────────────────────────────────────────────

def load_index() -> dict:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {"documents": []}


def save_index(index: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ──────────────────────────────────────────────────────────────────────────
# 명령어 처리
# ──────────────────────────────────────────────────────────────────────────

def make_client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "오류: 환경변수 ANTHROPIC_API_KEY 가 설정되지 않았습니다.\n"
            "  예) export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(1)
    return anthropic.Anthropic()


def cmd_index(model: str) -> None:
    files = collect_documents()
    if not files:
        print(f"'{DOCS_DIR}/' 폴더에 읽을 문서가 없습니다. txt/md/pdf 파일을 넣어주세요.")
        return

    client = make_client()
    old_index = load_index()
    # 이전에 만든 색인을 파일경로 -> 항목으로 매핑 (변경 없는 파일 재사용용)
    old_by_file = {d["file"]: d for d in old_index["documents"]}

    new_docs = []
    for path in files:
        rel = str(path)
        text = read_document(path)
        if not text.strip():
            print(f"  - 건너뜀(내용 없음): {rel}")
            continue

        h = file_hash(text)
        cached = old_by_file.get(rel)
        if cached and cached.get("hash") == h:
            print(f"  = 변경 없음, 재사용: {rel}")
            new_docs.append(cached)
            continue

        print(f"  + 분석 중: {rel}")
        try:
            info = summarize_document(client, model, rel, text)
        except Exception as e:  # 한 파일 실패가 전체를 막지 않도록
            print(f"    ! 분석 실패({rel}): {e}", file=sys.stderr)
            continue

        new_docs.append(
            {
                "file": rel,
                "title": info["title"],
                "summary": info["summary"],
                "category": info["category"],
                "keywords": info["keywords"],
                "chars": len(text),
                "hash": h,
            }
        )

    save_index({"documents": new_docs})
    print(f"\n완료: {len(new_docs)}개 문서를 '{INDEX_FILE}' 에 색인했습니다.")


def cmd_search(model: str, query: str) -> None:
    index = load_index()
    if not index["documents"]:
        print(f"색인이 비어 있습니다. 먼저 'python vks.py index' 를 실행하세요.")
        return

    client = make_client()
    print(f"'{query}' 와(과) 의미가 통하는 문서를 찾는 중...\n")
    results = semantic_search(client, model, index, query)

    if not results:
        print("관련 문서를 찾지 못했습니다.")
        return

    # 검색 결과에 분류·제목을 함께 보여주기 위해 색인에서 정보 보강
    by_file = {d["file"]: d for d in index["documents"]}
    for i, r in enumerate(results, 1):
        doc = by_file.get(r["file"], {})
        title = doc.get("title", r["file"])
        category = doc.get("category", "-")
        print(f"{i}. [{r.get('relevance', 0):>3}점] {title}  ({category})")
        print(f"   파일: {r['file']}")
        print(f"   이유: {r['reason']}")
        print()


def cmd_list() -> None:
    index = load_index()
    docs = index["documents"]
    if not docs:
        print(f"색인이 비어 있습니다. 먼저 'python vks.py index' 를 실행하세요.")
        return

    # 카테고리별로 묶어서 보여주기
    by_category: dict[str, list[dict]] = {}
    for d in docs:
        by_category.setdefault(d["category"], []).append(d)

    print(f"총 {len(docs)}개 문서, {len(by_category)}개 분류\n")
    for category in sorted(by_category):
        print(f"■ {category}")
        for d in by_category[category]:
            print(f"   - {d['title']}  ({d['file']})")
            print(f"     {d['summary']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="페이지 요약·분류 + 의미 기반 검색 에이전트 (vks)"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"사용할 Claude 모델 (기본: {DEFAULT_MODEL})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("index", help="documents/ 안의 문서를 요약·분류해 색인 생성")

    p_search = sub.add_parser("search", help="색인에서 의미 기반으로 관련 문서 검색")
    p_search.add_argument("query", help="검색할 키워드/문장")

    sub.add_parser("list", help="분류된 문서 목록 보기")

    args = parser.parse_args()

    if args.command == "index":
        cmd_index(args.model)
    elif args.command == "search":
        cmd_search(args.model, args.query)
    elif args.command == "list":
        cmd_list()


if __name__ == "__main__":
    main()
