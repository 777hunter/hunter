"""Node.js 가 없을 때 쓰는 작업지도서 렌더러.

같은 스펙 JSON 으로 인쇄용 HTML 을 만든다. 브라우저에서 열어 인쇄 > PDF 로
저장하거나 워드에 붙여넣으면 된다. 사진은 파일 안에 넣어서 이 파일 하나만
보내도 열린다.
"""
from __future__ import annotations

import base64
import html
import mimetypes
import os


def _esc(v) -> str:
    return html.escape(str(v or ""))


def _img(path: str, style: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    return f'<img src="data:{mime};base64,{data}" style="{style}" alt="">'


CSS = """
@page { size: A4 landscape; margin: 10mm; }
* { box-sizing: border-box; }
body { margin:0; padding:14px 18px; background:#fff; color:#14191c;
  font:12px/1.6 "맑은 고딕","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif; }
h1 { font-size:24px; margin:0 0 2px; }
h1 small { font-size:12px; color:#767f7b; font-weight:400; margin-left:8px; }
h2 { font-size:15px; margin:22px 0 6px; }
.job { font-size:16px; font-weight:700; color:#1e4f52; margin:0 0 12px; }
table { border-collapse:collapse; width:100%; margin-bottom:10px; }
th,td { border:1px solid #d6dad4; padding:6px 8px; text-align:left; vertical-align:top; }
th { background:#e8edea; font-size:11px; color:#4a524f; font-weight:600; }
td.blank, th.blank { background:#fbf4e8; }
td.blank em { color:#767f7b; }
.note { color:#8e5a16; font-size:11px; margin:8px 0 14px; }
.muted { color:#767f7b; font-size:11px; }
.step-name { font-weight:700; font-size:13px; }
.kp { margin:0 0 4px; }
.kp:before { content:"· "; color:#1e4f52; }
.reason-blank { border-bottom:1px dotted #bbb; height:22px; }
.sev { text-align:center; font-weight:700; }
.sev-상 { background:#f6dfda; } .sev-중 { background:#f6ead7; } .sev-하 { background:#edefea; }
.chk { margin:3px 0; }
.page { page-break-before: always; }
.defect { color:#8e5a16; font-weight:700; }
img { display:block; }
"""


def render(spec: dict, path: str) -> str:
    h = spec.get("header") or {}
    p = [f'<!doctype html><html lang="ko"><head><meta charset="utf-8">',
         f'<title>작업지도서 — {_esc(h.get("job_name"))}</title>',
         f"<style>{CSS}</style></head><body>",
         f'<h1>작업지도서<small>Job Instruction Sheet</small></h1>',
         f'<p class="job">{_esc(h.get("job_name") or "(작업명 미기입)")}</p>']

    def kv_table(pairs, blank_keys=()):
        cells = "".join(
            f'<th style="width:8%">{_esc(k)}</th>'
            f'<td class="{"blank" if k in blank_keys else ""}" style="width:17%">'
            f'{("<em>" + _esc(v) + "</em>") if (k in blank_keys and v) else _esc(v)}</td>'
            for k, v in pairs)
        return f"<table><tr>{cells}</tr></table>"

    p.append(kv_table([("문서번호", h.get("doc_no")), ("개정", h.get("revision")),
                       ("작성일", h.get("date")), ("작성자", h.get("author")), ("승인", "")]))
    p.append(kv_table([("공정명", h.get("process")), ("설비", h.get("equipment") or "기입 필요"),
                       ("치공구", h.get("tooling") or "기입 필요"),
                       ("보호구", h.get("ppe") or "기입 필요")],
                      blank_keys={"설비", "치공구", "보호구"}))

    p.append("<h2>관측 요약</h2><table>")
    obs = spec.get("observation") or []
    for i in range(0, len(obs), 3):
        row = "".join(f"<th>{_esc(k)}</th><td>{_esc(v)}</td>" for k, v in obs[i:i + 3])
        p.append(f"<tr>{row}</tr>")
    p.append("</table>")
    p.append('<p class="note">이 문서는 작업 영상 분석으로 만든 <b>초안</b>이다. '
             "주요단계와 시간은 관측값이지만, 급소의 이유와 음영 칸은 작성자가 채워야 한다. "
             "승인 전에는 현장에 게시하지 말 것.</p>")

    p.append("<h2>작업분해</h2><table>"
             '<tr><th style="width:4%">순번</th><th style="width:22%">사진</th>'
             '<th style="width:22%">주요단계</th><th style="width:26%">급소</th>'
             '<th class="blank" style="width:26%">급소의 이유</th></tr>')
    for s in spec.get("steps", []):
        photo = _img((s.get("photo") or {}).get("path", ""), "width:100%;height:auto")
        cap = f'<div class="muted">{_esc((s.get("photo") or {}).get("caption"))}</div>' if s.get("photo") else ""
        if not photo:
            photo, cap = '<em class="muted">사진 없음 — 직접 촬영</em>', ""
        kps = "".join(
            f'<p class="kp">{_esc(k["text"])}</p>' if k["source"] != "빈칸"
            else '<p class="muted"><em>(관측에서 나온 신호 없음 — 기입 필요)</em></p>'
            for k in s.get("key_points", []))
        reason = (("".join(f"<p>{_esc(l)}</p>" for l in s["reasons"].split("\n")))
                  if (s.get("reasons") or "").strip()
                  else '<div class="reason-blank"></div><div class="reason-blank"></div>')
        blank = "" if (s.get("reasons") or "").strip() else " blank"
        p.append(
            f'<tr><td class="sev">{s["no"]}</td><td>{photo}{cap}</td>'
            f'<td><div class="step-name">{_esc(s["name"])}</div>'
            f'<div class="muted">{s["time_s"]}초 {_esc(s.get("spread"))}</div>'
            f'<div class="muted">동작 {_esc(s["signature"])} · 관측 {_esc(s["presence"])}</div></td>'
            f"<td>{kps}</td><td class=\"{blank.strip()}\">{reason}</td></tr>")
    p.append("</table>")

    p.append('<div class="page"><h2>부록 A. 관측 기록</h2>')
    p.append("<table><tr><th>사이클</th><th>소요시간</th><th>중앙값 대비</th></tr>")
    for r in spec.get("cycle_rows", []):
        p.append(f'<tr><td>{r["no"]}회차</td><td>{r["seconds"]}초</td><td>{_esc(r["delta"])}</td></tr>')
    p.append("</table>")
    if spec.get("variations"):
        p.append("<h2>변동 구간</h2><table><tr><th>위치</th><th>종류</th><th>내용</th></tr>")
        for v in spec["variations"]:
            p.append(f'<tr><td>{_esc(v["where"])}</td><td>{_esc(v["type"])}</td>'
                     f'<td>{_esc(v["detail"])}</td></tr>')
        p.append("</table>")
    p.append("</div>")

    chart = _img((spec.get("chart") or {}).get("path", ""), "width:100%;height:auto")
    if chart:
        p.append(f'<div class="page"><h2>부록 B. 사이클 정합</h2>{chart}'
                 '<p class="muted">맨 윗줄이 표준(중앙값), 아래가 관측한 각 사이클. '
                 "숫자는 요소 순번이고 붉은 테두리와 * 는 표준 순서를 벗어난 요소다.</p></div>")

    if spec.get("risks"):
        sm = spec.get("risk_summary") or {}
        p.append('<div class="page"><h2>부록 C. 포카요케 리스크 신호</h2>')
        p.append(f'<p class="note">신호 {sm.get("total", 0)}건. '
                 + ("불량 이력이 연결된 신호 "
                    f'{sm.get("defect_linked", 0)}건. 키워드 매칭이므로 확인할 것.'
                    if sm.get("defect_source") else
                    "불량 이력을 붙이지 않았으므로 심각도는 관측 신호만 보고 매긴 값이다.")
                 + "</p>")
        p.append("<table><tr><th>심각도</th><th>신호</th><th>대상 단계</th><th>근거</th>"
                 "<th>의심 불량 / 이력</th><th>포카요케 후보</th></tr>")
        for r in spec["risks"]:
            measures = "".join(f'<p class="kp">{_esc(m)}</p>' for m in r["measures"])
            defects = f'<p class="defect">{_esc(r["defects"])}</p>' if r["defects"] else ""
            needs = f'<p class="muted"><em>{_esc(r["needs"])}</em></p>' if r.get("needs") else ""
            p.append(f'<tr><td class="sev sev-{r["severity"]}">{r["severity"]}'
                     f'<div class="muted">{r["id"]}</div></td>'
                     f'<td><b>{_esc(r["signal"])}</b></td><td>{_esc(r["target"])}</td>'
                     f'<td>{_esc(r["evidence"])}{needs}</td>'
                     f'<td>{_esc(r["suspect"])}{defects}</td><td>{measures}</td></tr>')
        p.append("</table></div>")

    p.append('<div class="page"><h2>승인 전 채워야 할 항목</h2>')
    for b in spec.get("blanks", []):
        p.append(f'<p class="chk">☐ {_esc(b)}</p>')
    p.append("<h2>검토 및 승인</h2><table><tr>"
             '<th>작성</th><td class="blank"><em>서명 / 일자</em></td>'
             '<th>검토</th><td class="blank"><em>서명 / 일자</em></td></tr><tr>'
             '<th>승인</th><td class="blank"><em>서명 / 일자</em></td>'
             '<th>게시일</th><td class="blank"></td></tr></table></div>')

    p.append("</body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    return path
