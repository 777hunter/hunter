#!/usr/bin/env python3
"""물어보면서 끝까지 데려가는 실행기. 명령어를 외울 필요 없다.

    python3 motion/start.py

필요한 것은 알아서 설치하고, 브라우저 도구는 알아서 열어 주고, 저장한 파일은
알아서 찾아온다. 중간에 끊어도 다시 실행하면 이어서 한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENV = ROOT / ".venv"
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mpg", ".mpeg", ".wmv"}
BOOT_FLAG = "--bootstrapped"


# ── 화면 ────────────────────────────────────────────────────────
def title(text: str):
    print(f"\n{'━' * 58}\n  {text}\n{'━' * 58}")


def say(text: str = ""):
    print(text)


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        got = input(f"\n{prompt}{hint} > ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        say("\n중단했다. 다시 실행하면 이어서 한다.")
        sys.exit(0)
    return got or default


def confirm(prompt: str, default: bool = True) -> bool:
    got = ask(prompt + " (y/n)", "y" if default else "n").lower()
    return got.startswith("y") or got in ("네", "ㅇ", "예")


# ── 준비 ────────────────────────────────────────────────────────
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def bootstrap():
    """필요한 것이 없으면 전용 파이썬 환경을 만들고 거기서 다시 시작한다."""
    try:
        import cv2, mediapipe, numpy, PIL          # noqa: F401
        return
    except ImportError:
        pass

    if venv_python().exists() and Path(sys.executable) != venv_python():
        os.execv(str(venv_python()), [str(venv_python()), __file__, BOOT_FLAG, *sys.argv[1:]])

    title("처음 실행 — 필요한 것을 설치한다")
    say("영상 분석에 쓰는 도구를 내려받는다. 몇 분 걸린다.")
    if not confirm("계속할까"):
        sys.exit(0)
    if not VENV.exists():
        say("\n파이썬 환경 만드는 중...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    say("도구 설치 중... (진행 표시가 없어도 돌아가고 있다)")
    proc = subprocess.run([str(venv_python()), "-m", "pip", "install", "-q", "--upgrade",
                           "pip", "-r", str(HERE / "requirements.txt")],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        say("\n설치에 실패했다. 아래를 직접 실행해 볼 것:")
        say(f'  "{venv_python()}" -m pip install -r "{HERE / "requirements.txt"}"')
        say((proc.stderr or "")[-800:])
        sys.exit(1)
    say("설치 끝. 다시 시작한다.")
    os.execv(str(venv_python()), [str(venv_python()), __file__, BOOT_FLAG, *sys.argv[1:]])


def check_node() -> bool:
    return shutil.which("node") is not None and (HERE / "node_modules" / "docx").exists()


def try_npm_install() -> bool:
    if shutil.which("npm") is None:
        return False
    say("\n워드 문서 렌더러 설치 중...")
    proc = subprocess.run(["npm", "install", "--silent"], cwd=HERE,
                          capture_output=True, text=True)
    return proc.returncode == 0 and check_node()


# ── 파일 찾기 ───────────────────────────────────────────────────
def find_videos() -> list[Path]:
    seen, out = set(), []
    for folder in (Path.cwd(), ROOT, Path.home() / "Desktop", Path.home() / "Downloads",
                   Path.home() / "바탕 화면", Path.home() / "다운로드"):
        if not folder.is_dir():
            continue
        try:
            for f in sorted(folder.iterdir(), key=lambda p: -p.stat().st_mtime)[:120]:
                if f.suffix.lower() in VIDEO_EXT and f.resolve() not in seen:
                    seen.add(f.resolve())
                    out.append(f)
        except OSError:
            continue
    return out[:12]


def find_saved(pattern: str, out_dir: Path) -> Path | None:
    """브라우저가 내려받은 파일을 찾는다. 대개 다운로드 폴더에 있다."""
    cands = []
    for folder in (out_dir, Path.cwd(), Path.home() / "Downloads", Path.home() / "다운로드"):
        if not folder.is_dir():
            continue
        for f in folder.glob(pattern):
            try:
                cands.append((f.stat().st_mtime, f))
            except OSError:
                pass
    if not cands:
        return None
    return max(cands)[1]


def open_tool(name: str):
    url = (HERE / name).as_uri()
    try:
        webbrowser.open(url)
        say(f"브라우저에서 {name} 을 열었다.")
    except Exception:
        say(f"브라우저를 못 열었다. 이 파일을 직접 열 것:\n  {HERE / name}")


def reveal(folder: Path):
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(folder)])
        elif os.name == "nt":
            os.startfile(str(folder))          # noqa: S606
        else:
            subprocess.run(["xdg-open", str(folder)])
    except Exception:
        pass


# ── 단계 실행 ───────────────────────────────────────────────────
def run_stage(script: str, args: list[str]) -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, str(HERE / script), *args],
                          cwd=str(HERE), capture_output=True, text=True)
    noise = ("WARNING: All log", "I0000", "W0000", "INFO: Created TensorFlow", "[hands]",
             "[pose]", "[shots]")
    lines = [ln for ln in (proc.stdout or "").splitlines()
             if not ln.startswith(noise)]
    text = "\n".join(lines)
    if proc.returncode != 0:
        text += "\n" + (proc.stderr or "")[-1200:]
    return proc.returncode == 0, text


def main():
    args = [a for a in sys.argv[1:] if a != BOOT_FLAG]
    title("작업표준 만들기")
    say("작업 영상을 넣으면 작업지도서 초안까지 만든다.")
    say("중간에 브라우저 도구를 두 번 쓴다. 순서대로 안내한다.")

    # 1) 영상 고르기
    video = Path(args[0]).expanduser() if args else None
    if video is None or not video.exists():
        found = find_videos()
        if found:
            say("\n찾은 영상:")
            for i, f in enumerate(found, 1):
                size = f.stat().st_size / 1e6
                say(f"  {i}. {f.name}  ({size:.0f}MB, {f.parent})")
            got = ask("번호를 고르거나 영상 파일을 여기로 끌어다 놓을 것", "1")
        else:
            got = ask("영상 파일을 여기로 끌어다 놓거나 경로를 붙여넣을 것")
        if got.isdigit() and found and 1 <= int(got) <= len(found):
            video = found[int(got) - 1]
        else:
            video = Path(got).expanduser()
    if not video.exists():
        say(f"\n그런 파일이 없다: {video}")
        sys.exit(1)
    video = video.resolve()

    out_dir = video.parent / f"작업표준_{video.stem}"
    out_dir.mkdir(exist_ok=True)
    stem = video.stem
    say(f"\n영상   : {video.name}")
    say(f"결과   : {out_dir}")

    # 2) 사전 점검
    title("1단계 — 쓸 수 있는 영상인지 확인")
    ok, text = run_stage("preflight.py", [str(video), "--out-dir", str(out_dir)])
    say(text)
    if not ok:
        say("점검에 실패했다. 영상 파일이 정상인지 확인할 것.")
        sys.exit(1)
    if "재촬영 권장" in text and not confirm("\n그래도 계속할까", False):
        reveal(out_dir)
        sys.exit(0)

    # 3) 요소 분할 (존 없이)
    zones = out_dir / "zones.json"
    if not zones.exists():
        title("2단계 — 동작을 작업요소로 나눈다")
        say("영상 길이만큼 시간이 걸린다. 기다릴 것.")
        ok, text = run_stage("run_all.py", [str(video), "--out-dir", str(out_dir),
                                            "--to", "standard", "--no-next"])
        say(text)
        if not ok:
            sys.exit(1)

        title("3단계 — 화면의 어디가 무엇인지 알려준다")
        say("브라우저가 열리면 이렇게 한다.")
        say("  1. '결과 폴더' 에서 아래 폴더를 고른다")
        say(f"     {out_dir}")
        say("  2. '영상' 에서 원본 영상을 고른다 (안 열리면 건너뛰어도 된다)")
        say("  3. 붉은 점(집은 자리)과 주황 점(놓은 자리) 뭉치를 감싸게 사각형을 그린다")
        say("  4. 이름과 종류를 넣고 'zones.json 저장'")
        open_tool("zone_tool.html")
        ask("\n저장했으면 엔터")
        got = find_saved("zones*.json", out_dir)
        if got is None:
            say("zones.json 을 못 찾았다. 파일을 여기로 끌어다 놓을 것.")
            got = Path(ask("zones.json 경로")).expanduser()
        if got.resolve() != zones.resolve():
            shutil.copy(got, zones)
        say(f"가져왔다: {got.name}")

    # 4) 이름·사진·문서 초안
    title("4단계 — 이름 붙이고 사진 뽑고 문서 초안 만들기")
    job = ask("작업명 (엔터 치면 영상 이름)", stem)
    author = ask("작성자 (없으면 엔터)", "")
    node_ok = check_node() or try_npm_install()
    if not node_ok:
        say("\nNode.js 가 없어서 워드 파일 대신 인쇄용 HTML 로 만든다.")
        say("브라우저에서 열어 인쇄 > PDF 로 저장하거나 워드에 붙여넣으면 된다.")
    cmd = [str(video), "--out-dir", str(out_dir), "--zones", str(zones),
           "--job-name", job, "--force", "--no-next"]
    if author:
        cmd += ["--author", author]
    ok, text = run_stage("run_all.py", cmd)
    say(text)

    # 5) 검수
    title("5단계 — 검수")
    say("자동으로 만든 이름과 급소를 사람이 확인하는 단계다. 여기가 제일 중요하다.")
    say("특히 '급소의 이유' 는 영상에 없는 정보라 반드시 사람이 채워야 한다.")
    if confirm("\n지금 검수할까 (나중에 해도 된다)"):
        say("\n브라우저가 열리면 이렇게 한다.")
        say(f"  1. '결과 폴더' 에서 {out_dir.name} 을 고른다")
        say("  2. '영상' 에서 원본 영상을 고른다 — 구간이 반복 재생된다")
        say("  3. 요소마다 이름·급소·급소의 이유를 고치고 '확인하고 다음'")
        say("  4. 다 되면 'review.json 저장'")
        open_tool("review_tool.html")
        ask("\n저장했으면 엔터")
        got = find_saved("review*.json", out_dir)
        if got is None:
            typed = ask("review.json 을 못 찾았다. 파일을 끌어다 놓거나, 건너뛰려면 엔터", "")
            got = Path(typed).expanduser() if typed else None
        if got and Path(got).exists():
            review = out_dir / "review.json"
            if Path(got).resolve() != review.resolve():
                shutil.copy(got, review)
            title("6단계 — 최종 문서")
            cmd = [str(video), "--out-dir", str(out_dir), "--zones", str(zones),
                   "--review", str(review), "--job-name", job, "--force",
                   "--from", "ji", "--no-next"]
            if author:
                cmd += ["--author", author]
            ok, text = run_stage("run_all.py", cmd)
            say(text)

    # 6) 마무리
    title("끝")
    docx = out_dir / f"{stem}_작업지도서.docx"
    html = out_dir / f"{stem}_작업지도서.html"
    for f in (docx, html, out_dir / f"{stem}_shots.png", out_dir / f"{stem}_risks.csv"):
        if f.exists():
            say(f"  {f.name}")
    say(f"\n결과 폴더: {out_dir}")
    say("문서 마지막 장의 '승인 전 채워야 할 항목' 을 확인하고 승인 절차를 밟을 것.")
    reveal(out_dir)


if __name__ == "__main__":
    if BOOT_FLAG not in sys.argv:
        bootstrap()
    try:
        main()
    except KeyboardInterrupt:
        say("\n\n중단했다. 다시 실행하면 이어서 한다.")
