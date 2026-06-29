"""
run_weekly.py - 주간 파이프라인 진입점.

사용법
  # 1) 실데이터 (long-format CSV/Excel)
  python -m jeonbuk.run_weekly --input data/panel.csv
  python -m jeonbuk.run_weekly --input data/panel.csv --week 2026-06-22

  # 2) 데이터 없이 합성 데이터로 즉시 검증 (군산시에 이상신호가 주입됨)
  python -m jeonbuk.run_weekly --demo
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

# Windows 콘솔(cp949)에서 한글·기호 출력 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from . import config as C
from .data import all_weeks, load_long, make_synthetic
from .report import build_weekly, save, to_markdown


def main() -> None:
    ap = argparse.ArgumentParser(description="전북 주간 다변량 신호 탐지")
    ap.add_argument("--input", help="long-format 패널 (CSV/Excel)")
    ap.add_argument("--week", help="대상 주 (YYYY-MM-DD). 미지정 시 가장 최근 주")
    ap.add_argument("--demo", action="store_true", help="합성 데이터로 실행")
    args = ap.parse_args()

    demo_inject_idx = 70
    is_demo = args.demo or not args.input
    if is_demo:
        print(f"[demo] 합성 패널 생성 (군산시 {demo_inject_idx}주차에 이상신호 주입)")
        long_df = make_synthetic(inject_week_idx=demo_inject_idx)
    else:
        long_df = load_long(args.input)

    weeks = all_weeks(long_df)
    if not weeks:
        raise SystemExit("데이터에 주(week)가 없습니다.")
    if args.week:
        target = pd.Timestamp(args.week)
    elif is_demo:
        target = pd.Timestamp(weeks[demo_inject_idx])  # 주입한 신호를 복원하는지 확인
    else:
        target = pd.Timestamp(weeks[-1])

    report = build_weekly(long_df, target)
    print("\n" + to_markdown(report) + "\n")

    week_str = str(pd.Timestamp(target).date())
    jp, mp = save(report, week_str)
    print(f"저장됨:\n  {jp}\n  {mp}")


if __name__ == "__main__":
    main()
