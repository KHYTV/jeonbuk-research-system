"""
build_web.py - 주간 JSON 결과를 web/index.html 대시보드에 주입.

index.html 안의  `const REPORT = {...};`  한 줄을 최신 결과로 교체한다.
대시보드는 데이터를 인라인 임베드하므로 별도 서버 없이 file:// 로 열린다.

사용법
  python -m jeonbuk.build_web                         # output 의 최신 signal_*.json 사용
  python -m jeonbuk.build_web --json output/signal_2025-05-05.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import config as C

HTML = C.BASE_DIR / "web" / "index.html"
_PAT = re.compile(r"const REPORT = \{.*?\};", re.DOTALL)
_BRIEF_PAT = re.compile(r"const BRIEF = \{.*?\};", re.DOTALL)


def latest_json() -> Path:
    files = sorted(C.OUTPUT_DIR.glob("signal_*.json"))
    if not files:
        raise SystemExit("output 에 signal_*.json 이 없습니다. 먼저 run_weekly 를 실행하세요.")
    return files[-1]


def _brief_for(week: str) -> dict:
    """해당 주의 brief_*.json → 시군명으로 키잉한 dict (없으면 빈 dict)."""
    p = C.OUTPUT_DIR / f"brief_{week}.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {b["region"]: b for b in data.get("briefs", [])}


def build(json_path: Path) -> None:
    data = json_path.read_text(encoding="utf-8").strip()
    week = json.loads(data).get("week", "")
    html = HTML.read_text(encoding="utf-8")
    if not _PAT.search(html):
        raise SystemExit("index.html 에서 'const REPORT = {...};' 패턴을 찾지 못했습니다.")
    # 함수형 치환: re.sub 의 치환문자열 백슬래시 해석(\n→줄바꿈)을 회피
    html = _PAT.sub(lambda _: f"const REPORT = {data};", html, count=1)

    brief = _brief_for(week)
    if _BRIEF_PAT.search(html):
        brief_js = json.dumps(brief, ensure_ascii=False)
        html = _BRIEF_PAT.sub(lambda _: f"const BRIEF = {brief_js};", html, count=1)
    HTML.write_text(html, encoding="utf-8")
    print(f"주입 완료: {json_path.name} (+ brief {len(brief)}곳) → {HTML}")


def main() -> None:
    ap = argparse.ArgumentParser(description="주간 결과를 웹 대시보드에 주입")
    ap.add_argument("--json", help="주입할 signal_*.json 경로 (미지정 시 최신)")
    args = ap.parse_args()
    build(Path(args.json) if args.json else latest_json())


if __name__ == "__main__":
    main()
