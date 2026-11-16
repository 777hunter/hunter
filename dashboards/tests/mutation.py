#!/usr/bin/env python3
"""변이 테스트: 코드를 일부러 한 군데씩 틀리게 만들고 테스트가 잡아내는지 본다.

살아남은 변이(테스트가 못 잡은 것)의 비율 = 리팩토링 중 생긴 버그가 테스트를 빠져나갈 확률의
근사치. 허브 화면 코드(hub.html 의 <script id="app">)와 sync.py 를 대상으로 한다.

    python3 dashboards/tests/mutation.py sync          # 수 초
    python3 dashboards/tests/mutation.py hub -j 4      # 수 분 (Playwright)
    python3 dashboards/tests/mutation.py hub --only rebase,go   # 이름이 든 줄만

결과: 생존율과 살아남은 변이 목록(파일:줄, 바꾼 내용). 같은 동작이 되는 변이(동등 변이)는
사람이 보고 --equivalent 파일에 적어 두면 분모에서 뺀다.
"""
import argparse
import ast
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EQUIV_FILE = os.path.join(HERE, "mutation_equivalent.json")

JS_OPS = [
    ("eq", r"===|!==", lambda m: "!==" if m == "===" else "==="),
    ("andor", r"&&|\|\|", lambda m: "||" if m == "&&" else "&&"),
    ("bool", r"\b(?:true|false)\b", lambda m: "false" if m == "true" else "true"),
    ("not", r"(?<![=!])!(?=[\w(])", lambda m: ""),
    ("cmp", r" (?:<=|>=|<|>) ", lambda m: {" < ": " >= ", " >= ": " < ", " > ": " <= ", " <= ": " > "}[m]),
]
CALL_LINE = re.compile(r"^(\s+)([\w.]+\(.*\);)\s*$")


def js_mutants(src):
    """(줄 번호, 종류, 원래 줄, 바뀐 줄) 목록."""
    out = []
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("//") or line.strip().startswith("*") or line.strip().startswith("/*"):
            continue
        for kind, pat, fn in JS_OPS:
            for m in re.finditer(pat, line):
                new = line[:m.start()] + fn(m.group(0)) + line[m.end():]
                out.append((i, kind, line, new))
        cm = CALL_LINE.match(line)
        if cm:
            out.append((i, "call", line, cm.group(1) + "/* removed */"))
    return out


class PyMutator(ast.NodeTransformer):
    SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE,
            ast.LtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}

    def __init__(self, target):
        self.target, self.n, self.desc = target, -1, None

    def hit(self, desc):
        self.n += 1
        if self.n == self.target:
            self.desc = desc
            return True
        return False

    def visit_Compare(self, node):
        self.generic_visit(node)
        if type(node.ops[0]) in self.SWAP and self.hit(("cmp", node.lineno)):
            node.ops[0] = self.SWAP[type(node.ops[0])]()
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self.hit(("andor", node.lineno)):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self.hit(("not", node.lineno)):
            return node.operand
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool) and self.hit(("bool", node.lineno)):
            return ast.Constant(not node.value)
        return node

    def visit_Expr(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Call) and self.hit(("call", node.lineno)):
            return ast.Pass()
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        if self.hit(("if-true", node.lineno)):
            node.test = ast.Constant(True)
        return node


def py_mutants(src):
    tree = ast.parse(src)
    counter = PyMutator(-1)
    counter.visit(tree)
    out = []
    for t in range(counter.n + 1):
        m = PyMutator(t)
        new = m.visit(ast.parse(src))
        ast.fix_missing_locations(new)
        out.append((m.desc[1], m.desc[0], ast.unparse(new)))
    return out


def run_hub(mutated_html):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(mutated_html)
    try:
        p = subprocess.run(["node", os.path.join(HERE, "hub_states.mjs")], capture_output=True, text=True,
                           env={**os.environ, "HUB_FILE": fh.name, "FAIL_FAST": "1"}, timeout=300)
        return p.returncode != 0
    except subprocess.TimeoutExpired:
        return True
    finally:
        os.unlink(fh.name)


def run_sync(mutated_py):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "sync.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(mutated_py)
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", HERE, "-p", "test_sync.py", "-f"],
                       capture_output=True, text=True, env={**os.environ, "SYNC_PY": path}, timeout=120)
    return p.returncode != 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=["hub", "sync"])
    ap.add_argument("-j", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--only", help="쉼표로 구분한 단어가 든 줄만 변이")
    ap.add_argument("--json", help="결과를 JSON 으로 저장할 경로")
    args = ap.parse_args()
    try:
        with open(EQUIV_FILE, encoding="utf-8") as fh:
            equivalent = set(json.load(fh).get(args.target, []))
    except OSError:
        equivalent = set()

    jobs = []
    if args.target == "hub":
        html = open(os.path.join(ROOT, "hub.html"), encoding="utf-8").read()
        m = re.search(r'(<script id="app">)(.*?)(</script>)', html, re.S)
        js, base = m.group(2), html[:m.start(2)]
        first_line = base.count("\n") + 1
        lines = js.split("\n")
        for i, kind, old, new in js_mutants(js):
            if args.only and not any(w in old for w in args.only.split(",")):
                continue
            mutated = lines[:i] + [new] + lines[i + 1:]
            label = f"hub.html:{first_line + i} [{kind}] {old.strip()[:70]}  →  {new.strip()[:70]}"
            jobs.append((label, html[:m.start(2)] + "\n".join(mutated) + html[m.end(2):], run_hub))
    else:
        src = open(os.path.join(ROOT, "sync.py"), encoding="utf-8").read()
        src_lines = src.split("\n")
        for lineno, kind, mutated in py_mutants(src):
            old = src_lines[lineno - 1].strip()
            if args.only and not any(w in old for w in args.only.split(",")):
                continue
            jobs.append((f"sync.py:{lineno} [{kind}] {old[:90]}", mutated, run_sync))

    survived, killed = [], 0
    with cf.ThreadPoolExecutor(max_workers=args.j) as pool:
        futs = {pool.submit(fn, body): label for label, body, fn in jobs}
        for f in cf.as_completed(futs):
            if f.result():
                killed += 1
            else:
                survived.append(futs[f])
    real_survivors = sorted(s for s in survived if s not in equivalent)
    total = len(jobs) - (len(survived) - len(real_survivors))
    rate = 100.0 * len(real_survivors) / total if total else 0.0
    print(f"{args.target}: 변이 {len(jobs)}개, 잡음 {killed}, 생존 {len(real_survivors)}, "
          f"동등(제외) {len(survived) - len(real_survivors)} → 생존율 {rate:.1f}%")
    for s in real_survivors:
        print("  생존: " + s)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"target": args.target, "mutants": len(jobs), "killed": killed,
                       "survived": real_survivors, "equivalent_excluded": len(survived) - len(real_survivors),
                       "survival_rate": rate}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
