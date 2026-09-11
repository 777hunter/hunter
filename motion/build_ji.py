#!/usr/bin/env python3
"""M4 — TWI 작업지도서(3열) 생성.

    python motion/build_ji.py --standard out/work_standard.json \
        --shots out/work_shots.json --out-dir out \
        --job-name "브래킷 조립" --process "1공정 조립" --author "홍길동"

주요단계·시간·사진은 M1~M3 관측값이고, 급소는 관측에서 근거가 나온 것만 초안으로
넣는다. 급소의 이유는 영상에 없는 정보라 빈칸으로 둔다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess

from ji_spec import build_spec

HERE = os.path.dirname(os.path.abspath(__file__))


def render(spec_path: str, out_path: str) -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node 를 찾을 수 없다. Node.js 설치 후 다시 실행할 것.")
    script = os.path.join(HERE, "ji_sheet.js")
    proc = subprocess.run([node, script, spec_path, out_path],
                          capture_output=True, text=True, cwd=HERE)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip()
        if "Cannot find module 'docx'" in msg:
            raise SystemExit("docx 모듈이 없다. motion 폴더에서 `npm install docx` 실행할 것.")
        raise SystemExit(f"문서 생성 실패:\n{msg}")
    print(proc.stdout.strip())
    return out_path


def main():
    ap = argparse.ArgumentParser(description="TWI 3열 작업지도서 생성")
    ap.add_argument("--standard", required=True)
    ap.add_argument("--shots", default=None)
    ap.add_argument("--review", default=None, help="review_tool.html 로 만든 review.json")
    ap.add_argument("--risks", default=None, help="find_risks.py 가 만든 *_risks.json")
    ap.add_argument("--shot-dir", default=None,
                    help="사진 폴더 (기본: shots.json 옆의 shots/)")
    ap.add_argument("--out-dir", default="standard_out")
    ap.add_argument("--out", default=None, help="출력 .docx 경로")
    ap.add_argument("--job-name", default=None, help="작업명")
    ap.add_argument("--process", default="", help="공정명")
    ap.add_argument("--doc-no", default="", help="문서번호")
    ap.add_argument("--revision", default="", help="개정")
    ap.add_argument("--author", default="", help="작성자")
    ap.add_argument("--date", default=None, help="작성일 (기본: 오늘)")
    ap.add_argument("--equipment", default="", help="설비")
    ap.add_argument("--tooling", default="", help="치공구")
    ap.add_argument("--ppe", default="", help="보호구")
    ap.add_argument("--font-name", default="맑은 고딕", help="문서에 쓸 글꼴 이름")
    ap.add_argument("--font", default=None, help="차트용 한글 TTF 경로")
    args = ap.parse_args()

    with open(args.standard, encoding="utf-8") as fh:
        std = json.load(fh)
    shots = None
    if args.shots and os.path.exists(args.shots):
        with open(args.shots, encoding="utf-8") as fh:
            shots = json.load(fh)
    risks = None
    if args.risks and os.path.exists(args.risks):
        with open(args.risks, encoding="utf-8") as fh:
            risks = json.load(fh)
    review = None
    if args.review:
        with open(args.review, encoding="utf-8") as fh:
            review = json.load(fh)

    stem = os.path.splitext(os.path.basename(args.standard))[0].replace("_standard", "")
    os.makedirs(args.out_dir, exist_ok=True)
    # 검수 화면에서 입력한 값이 기본, CLI 인자를 주면 그쪽이 이긴다
    rev_header = (review or {}).get("header") or {}
    def pick(cli, key, fallback=""):
        return cli or rev_header.get(key) or fallback
    header = {
        "job_name": pick(args.job_name, "job_name",
                         std.get("meta", {}).get("video", stem)),
        "process": pick(args.process, "process"), "doc_no": pick(args.doc_no, "doc_no"),
        "revision": pick(args.revision, "revision"), "author": pick(args.author, "author"),
        "date": args.date or dt.date.today().isoformat(),
        "equipment": pick(args.equipment, "equipment"),
        "tooling": pick(args.tooling, "tooling"), "ppe": pick(args.ppe, "ppe"),
        "font_name": args.font_name, "font": args.font,
    }
    shot_dir = args.shot_dir
    if not shot_dir and args.shots:
        shot_dir = os.path.join(os.path.dirname(os.path.abspath(args.shots)), "shots")
    spec = build_spec(std, shots, header, args.out_dir, review=review,
                      shot_dir=shot_dir, risks=risks)
    spec_path = os.path.join(args.out_dir, f"{stem}_ji_spec.json")
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, ensure_ascii=False)

    out = args.out or os.path.join(args.out_dir, f"{stem}_작업지도서.docx")
    render(spec_path, out)

    auto = sum(1 for s in spec["steps"] for k in s["key_points"] if k["source"] == "자동")
    man = sum(1 for s in spec["steps"] for k in s["key_points"] if k["source"] == "검수")
    done = sum(1 for s in spec["steps"] if s["reasons"])
    print(f"\n  주요단계 {len(spec['steps'])}개 · 사진 "
          f"{sum(1 for s in spec['steps'] if s['photo'])}컷 · "
          f"급소 자동 {auto}건 / 검수 {man}건 · 이유 기입 {done}/{len(spec['steps'])}")
    print(f"  채워야 할 항목 {len(spec['blanks'])}개")
    for b in spec["blanks"][:6]:
        print(f"    ☐ {b}")
    if len(spec["blanks"]) > 6:
        print(f"    … 외 {len(spec['blanks']) - 6}건 (문서 마지막 장에 전체 목록)")
    if spec.get("risks"):
        sm = spec.get("risk_summary") or {}
        print(f'  포카요케 신호 {len(spec["risks"])}건 '
              f'(상 {sm.get("by_severity", {}).get("상", 0)} / '
              f'중 {sm.get("by_severity", {}).get("중", 0)} / '
              f'하 {sm.get("by_severity", {}).get("하", 0)})')
    print(f"\nspec_json : {spec_path}\ndocx      : {out}")


if __name__ == "__main__":
    main()
