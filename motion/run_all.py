#!/usr/bin/env python3
"""영상 한 개를 넣어 작업지도서까지 한 번에 돌린다.

    # 1차 — 존 없이 돌려서 어디에 존을 그릴지 본다
    python motion/run_all.py work.mp4 --out-dir out

    # zone_tool.html 에서 존을 그린 뒤 2차
    python motion/run_all.py work.mp4 --out-dir out --zones zones.json

    # review_tool.html 에서 검수한 뒤 3차 (최종 문서)
    python motion/run_all.py work.mp4 --out-dir out --zones zones.json --review review.json

이미 만들어진 산출물은 건너뛴다. 다시 만들려면 --force.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = ["preflight", "standard", "shots", "risks", "ji"]
TUNABLE = ("close_curl", "open_curl", "still_speed", "move_speed")


def run(script: str, args: list[str], label: str) -> tuple[bool, str]:
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    t0 = time.time()
    print(f"\n── {label} ─────────────────────────────")
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    out = (proc.stdout or "").rstrip()
    noise = ("WARNING: All log messages", "I0000", "W0000", "INFO: Created TensorFlow")
    for line in out.splitlines():
        if not line.startswith(noise):
            print(line)
    if proc.returncode != 0:
        print((proc.stderr or "").strip()[-1500:])
        return False, out
    print(f"   ({time.time() - t0:.0f}초)")
    return True, out


def main():
    ap = argparse.ArgumentParser(description="영상 -> 작업지도서 전 과정")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default="standard_out")
    ap.add_argument("--zones", default=None)
    ap.add_argument("--review", default=None)
    ap.add_argument("--defects", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--rating", type=float, default=1.0)
    ap.add_argument("--allowance", type=float, default=0.15)
    ap.add_argument("--job-name", default=None)
    ap.add_argument("--process", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--doc-no", default="")
    ap.add_argument("--font", default=None)
    ap.add_argument("--no-auto-tune", action="store_true",
                    help="사전 점검이 추천한 임계값을 쓰지 않는다")
    ap.add_argument("--force", action="store_true", help="산출물이 있어도 다시 만든다")
    ap.add_argument("--no-next", action="store_true",
                    help="끝에 붙는 다음 단계 안내를 숨긴다 (start.py 가 쓴다)")
    ap.add_argument("--from", dest="from_stage", choices=STAGES, default="preflight")
    ap.add_argument("--to", dest="to_stage", choices=STAGES, default="ji")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        raise SystemExit(f"영상이 없다: {args.video}")
    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.video))[0]
    out = os.path.abspath(args.out_dir)
    video = os.path.abspath(args.video)
    path = lambda name: os.path.join(out, f"{stem}_{name}")
    todo = STAGES[STAGES.index(args.from_stage):STAGES.index(args.to_stage) + 1]

    def skip(stage: str, target: str) -> bool:
        if stage not in todo:
            return True
        if os.path.exists(target) and not args.force:
            print(f"\n── {stage}: 이미 있다 ({os.path.basename(target)}) — 건너뜀")
            return True
        return False

    common = ["--model", args.model] if args.model else []
    tuned = {}

    # 1. 사전 점검 — 쓸 수 있는 영상인지, 임계값을 얼마로 할지
    if not skip("preflight", path("preflight.json")):
        ok, _ = run("preflight.py", [video, "--out-dir", out, *common], "사전 점검")
        if not ok:
            raise SystemExit("사전 점검 실패")
    if os.path.exists(path("preflight.json")):
        with open(path("preflight.json"), encoding="utf-8") as fh:
            pf = json.load(fh)
        if pf.get("verdict") == "재촬영 권장":
            print("\n[중단] 사전 점검이 재촬영을 권했다:")
            for r in pf.get("reasons", []):
                print(f"  ! {r}")
            print("  그래도 돌려보려면 --from standard 로 다시 실행할 것.")
            if "standard" in todo and args.from_stage == "preflight":
                return
        if not args.no_auto_tune:
            tuned = {k: v for k, v in (pf.get("recommend") or {}).items() if k in TUNABLE}

    # 2. 작업요소와 표준 순서
    std_args = [video, "--out-dir", out, "--stride", str(args.stride),
                "--rating", str(args.rating), "--allowance", str(args.allowance), *common]
    for k, v in tuned.items():
        std_args += [f"--{k.replace('_', '-')}", str(v)]
    if args.zones:
        std_args += ["--zones", os.path.abspath(args.zones)]
    if not skip("standard", path("standard.json")):
        if tuned:
            print("\n사전 점검 추천 임계값 적용: " +
                  " ".join(f"{k}={v}" for k, v in tuned.items()))
        ok, _ = run("build_standard.py", std_args, "작업요소 분할과 사이클 정합")
        if not ok:
            raise SystemExit("요소 분할 실패 — therblig_tag.py 로 쥐기/놓기가 잡히는지 볼 것")

    # 3. 대표 사진
    if not skip("shots", path("shots.json")):
        shot_args = [video, "--standard", path("standard.json"), "--out-dir", out, *common]
        if args.zones:
            shot_args += ["--zones", os.path.abspath(args.zones)]
        if args.font:
            shot_args += ["--font", args.font]
        run("capture_shots.py", shot_args, "대표 사진 캡처")

    # 4. 포카요케 신호
    if not skip("risks", path("risks.json")):
        risk_args = ["--standard", path("standard.json"), "--out-dir", out]
        if args.zones:
            risk_args += ["--zones", os.path.abspath(args.zones)]
        if args.defects:
            risk_args += ["--defects", os.path.abspath(args.defects)]
        run("find_risks.py", risk_args, "포카요케 리스크 신호")

    # 5. 작업지도서
    if "ji" in todo:
        ji_args = ["--standard", path("standard.json"), "--out-dir", out]
        for flag, value in (("--shots", path("shots.json")), ("--risks", path("risks.json"))):
            if os.path.exists(value):
                ji_args += [flag, value]
        if args.review:
            ji_args += ["--review", os.path.abspath(args.review)]
        for flag, value in (("--job-name", args.job_name), ("--process", args.process),
                            ("--author", args.author), ("--doc-no", args.doc_no),
                            ("--font", args.font)):
            if value:
                ji_args += [flag, value]
        ok, _ = run("build_ji.py", ji_args, "작업지도서 생성")
        if not ok:
            print("   문서 생성만 실패했다. motion 폴더에서 `npm install` 후 "
                  "`--from ji` 로 다시 돌리면 된다.")

    # 다음에 할 일
    if args.no_next:
        return
    print("\n── 다음 ───────────────────────────────")
    if not args.zones:
        print(f"1. zone_tool.html 을 브라우저에서 열고 영상과 "
              f"{stem}_elements.csv 를 얹어 존을 그린다")
        print(f"2. python motion/run_all.py {args.video} --out-dir {args.out_dir} "
              f"--zones zones.json")
    elif not args.review:
        print(f"1. review_tool.html 을 열고 결과 폴더({args.out_dir})와 영상을 넣어 검수한다")
        print(f"2. python motion/run_all.py {args.video} --out-dir {args.out_dir} "
              f"--zones zones.json --review review.json --force")
    else:
        docx = os.path.join(out, f"{stem}_작업지도서.docx")
        print(f"작업지도서: {docx}")
        print("문서 마지막 장의 체크리스트를 확인하고 승인 절차를 밟을 것.")


if __name__ == "__main__":
    main()
