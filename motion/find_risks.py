#!/usr/bin/env python3
"""M5 — 포카요케 리스크 신호 검출.

    python motion/find_risks.py --standard out/work_standard.json \
        --zones zones.json --defects defects.csv --out-dir out

불량 이력(--defects)을 주면 신호에 실제 불량 모드를 연결하고 심각도를 올린다.
없으면 신호 검출과 후보 제안까지만 한다.
"""
from __future__ import annotations

import argparse
import json
import os

from risk import detect, load_defects, write_csv
from zones import load_zones


def main():
    ap = argparse.ArgumentParser(description="포카요케 리스크 신호 검출")
    ap.add_argument("--standard", required=True)
    ap.add_argument("--zones", default=None)
    ap.add_argument("--defects", default=None,
                    help="불량 이력 CSV (열: 불량모드, 건수, 키워드)")
    ap.add_argument("--out-dir", default="standard_out")
    args = ap.parse_args()

    with open(args.standard, encoding="utf-8") as fh:
        std = json.load(fh)
    zones = load_zones(args.zones)[0] if args.zones else None
    defects = load_defects(args.defects) if args.defects else None

    doc = detect(std, zones, defects)
    doc["source"] = os.path.basename(args.standard)
    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.standard))[0].replace("_standard", "")
    out_json = os.path.join(args.out_dir, f"{stem}_risks.json")
    out_csv = os.path.join(args.out_dir, f"{stem}_risks.csv")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    write_csv(out_csv, doc)

    s = doc["summary"]
    print(f'신호 {s["total"]}건 — 상 {s["by_severity"]["상"]} / '
          f'중 {s["by_severity"]["중"]} / 하 {s["by_severity"]["하"]}')
    if not s["defect_source"]:
        print("불량 이력을 주지 않았다. 지금 심각도는 관측 신호만 보고 매긴 값이고,")
        print("실제 우선순위는 불량 이력이나 공정 FMEA 를 붙여야 나온다.")
    else:
        print(f'불량 이력이 연결된 신호 {s["defect_linked"]}건')
    print()
    for r in doc["risks"]:
        where = ", ".join(f'{p}번' for p in r["positions"]) or "공정 전체"
        print(f'  [{r["severity"]}] {r["id"]} {r["signal"]}  ({where})')
        print(f'        근거: {r["evidence"]}')
        if r["defects"]:
            print(f'        불량 이력: ' +
                  ", ".join(f'{d["mode"]} {d["count"]}건' for d in r["defects"]))
        print(f'        후보: {r["countermeasures"][0]["text"]}')
        if r.get("needs"):
            print(f'        주의: {r["needs"]}')
    print(f"\nrisks_json : {out_json}\nrisks_csv  : {out_csv}")


if __name__ == "__main__":
    main()
