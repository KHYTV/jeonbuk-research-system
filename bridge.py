"""
bridge.py - 수집 레이어(pipeline) → 분석 레이어(jeonbuk) 연결 브리지.

pipeline/ 의 SQLite DB(raw_indicators)를 jeonbuk 분석엔진이 먹는
long-format( region | week | indicator | value )으로 변환한 뒤,
정밀 이상탐지(Mahalanobis) → 인과(Granger) → 토픽 → Claude 기사 →
웹 대시보드까지 한 번에 돌린다.

  python bridge.py            # DB가 있으면 실데이터, 없거나 이력이 얕으면 합성 데이터로 시연
  python bridge.py --demo     # 항상 합성 데이터

수집 → bridge 흐름:
  cd pipeline && python main.py weekly     # 데이터 수집(DB 적재)
  cd .. && python bridge.py                # 분석·기사·대시보드 갱신
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DB_PATH = ROOT / "pipeline" / "data" / "jeonbuk.db"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from jeonbuk import config as C
from jeonbuk.data import all_weeks, make_synthetic
from jeonbuk.report import build_weekly, save as save_signal
from jeonbuk import build_web
from jeonbuk import run_brief


def db_to_long() -> pd.DataFrame | None:
    """pipeline DB의 raw_indicators → jeonbuk long-format. 데이터 없으면 None."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT municipality AS region,
                   COALESCE(ref_date, substr(collected_at,1,10)) AS week,
                   indicator, value
            FROM raw_indicators
            WHERE value IS NOT NULL
        """).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if not rows:
        return None

    df = pd.DataFrame([dict(r) for r in rows])
    df[C.COL_WEEK] = pd.to_datetime(df["week"], errors="coerce")
    # 주(월요일) 단위로 스냅 → 같은 주 다중관측은 평균
    df = df.dropna(subset=[C.COL_WEEK])
    df[C.COL_WEEK] = df[C.COL_WEEK] - pd.to_timedelta(df[C.COL_WEEK].dt.weekday, unit="D")
    df = (df.groupby([C.COL_REGION, C.COL_WEEK, C.COL_INDICATOR])[C.COL_VALUE]
            .mean().reset_index())
    return df[[C.COL_REGION, C.COL_WEEK, C.COL_INDICATOR, C.COL_VALUE]]


def enough_history(long_df: pd.DataFrame) -> bool:
    """Mahalanobis 베이스라인을 세울 만큼 주(week) 이력이 쌓였는지."""
    if long_df is None or long_df.empty:
        return False
    return long_df[C.COL_WEEK].nunique() >= C.MIN_BASELINE_WEEKS + 1


def main() -> None:
    ap = argparse.ArgumentParser(description="수집 DB → 분석·기사·대시보드 브리지")
    ap.add_argument("--demo", action="store_true", help="항상 합성 데이터로 실행")
    ap.add_argument("--no-brief", action="store_true", help="뉴스·Claude 기사 단계 생략")
    args = ap.parse_args()

    long_df = None if args.demo else db_to_long()
    if enough_history(long_df):
        target = pd.Timestamp(all_weeks(long_df)[-1])
        print(f"[bridge] 실데이터 사용: {long_df[C.COL_WEEK].nunique()}주 × "
              f"{long_df[C.COL_REGION].nunique()}시군 → 분석주 {target.date()}")
    else:
        n = 0 if long_df is None else long_df[C.COL_WEEK].nunique()
        print(f"[bridge] DB 이력 부족({n}주) → 합성 데이터로 시연 "
              f"(주간 수집이 누적되면 자동으로 실데이터 전환)")
        long_df = make_synthetic(inject_week_idx=70)
        target = pd.Timestamp(all_weeks(long_df)[70])

    # 1) 신호 탐지 리포트
    report = build_weekly(long_df, target)
    week_str = str(target.date())
    save_signal(report, week_str)
    print(f"[bridge] 신호 리포트 저장: signal_{week_str}.json/md "
          f"(핫 플레이스 {report['n_hot_places']}곳)")

    # 2) 뉴스 토픽 + Claude 분석기사 브리프
    if not args.no_brief:
        brief = run_brief.run(long_df, target, provider=None)
        run_brief.save(brief)
        print(f"[bridge] 분석기사 브리프 저장: brief_{week_str}.json/md")

    # 3) 웹 대시보드 주입 (jeonbuk/web/index.html) + GitHub Pages용 docs/ 동기화
    build_web.build(C.OUTPUT_DIR / f"signal_{week_str}.json")
    import shutil
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    shutil.copy(C.BASE_DIR / "web" / "index.html", docs / "index.html")
    print("[bridge] 웹 대시보드 갱신 완료 → jeonbuk/web/index.html, docs/index.html")


if __name__ == "__main__":
    main()
