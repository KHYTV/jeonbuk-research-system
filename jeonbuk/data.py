"""
data.py - 데이터 적재 / 표준화 / 합성 데이터 생성.

표준 입력 형식 (long format):
    region | week (datetime, 주 시작일) | indicator | value

엔진 내부는 (region, week) × indicator 의 wide 패널로 변환해 쓴다.
실데이터가 없을 때를 위해 알려진 이상신호와 선행관계를 주입한
합성 패널 생성기를 함께 제공한다 → end-to-end 검증용.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


# ─────────────────────────────────────────────────────────────────────────────
#  적재
# ─────────────────────────────────────────────────────────────────────────────
def load_long(path: str) -> pd.DataFrame:
    """long-format CSV/Excel 적재 후 표준 컬럼·타입 검증."""
    p = str(path)
    df = pd.read_excel(path) if p.endswith((".xlsx", ".xls")) else pd.read_csv(path)

    required = {C.COL_REGION, C.COL_WEEK, C.COL_INDICATOR, C.COL_VALUE}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"입력에 다음 컬럼이 없습니다: {missing}. 필요한 컬럼: {required}")

    df[C.COL_WEEK] = pd.to_datetime(df[C.COL_WEEK])
    df[C.COL_VALUE] = pd.to_numeric(df[C.COL_VALUE], errors="coerce")
    return df


def to_wide(long_df: pd.DataFrame, region: str) -> pd.DataFrame:
    """특정 시군의 long → wide 패널 (index=week, columns=indicator)."""
    sub = long_df[long_df[C.COL_REGION] == region]
    wide = sub.pivot_table(
        index=C.COL_WEEK, columns=C.COL_INDICATOR, values=C.COL_VALUE, aggfunc="mean"
    ).sort_index()
    # 설정에 정의된 지표 순서로 정렬, 결측 보간(선형→앞뒤채움)
    cols = [c for c in C.ALL_INDICATORS if c in wide.columns]
    wide = wide[cols]
    wide = wide.interpolate(method="linear", limit_direction="both")
    return wide


def all_weeks(long_df: pd.DataFrame) -> list[pd.Timestamp]:
    return sorted(long_df[C.COL_WEEK].unique())


# ─────────────────────────────────────────────────────────────────────────────
#  합성 데이터 (검증용)
# ─────────────────────────────────────────────────────────────────────────────
def make_synthetic(
    n_weeks: int = 80,
    seed: int = 42,
    inject_region: str = "군산시",
    inject_week_idx: int = 70,
) -> pd.DataFrame:
    """
    알려진 구조를 가진 합성 패널을 만든다.

      - 모든 시군/지표: AR(1) + 완만한 트렌드 + 계절 + 잡음 의 정상 시계열
      - 선행관계 주입 : 모든 시군에서 '신규창업수'(t)가 '카드매출지수'(t+2)를 선행
      - 이상신호 주입 : inject_region 의 inject_week_idx 주에
                        카드매출지수↓ · 폐업수↑ · 응급실내원↑ 동시 충격
                        → 핫 플레이스로 잡히고, 핫 아이템으로 이 3개가 분해되어야 함
    반환: 표준 long-format DataFrame
    """
    rng = np.random.default_rng(seed)
    weeks = pd.date_range("2024-01-01", periods=n_weeks, freq="W-MON")
    rows = []

    for region in C.REGIONS:
        # 시군별 베이스 시계열을 미리 만들어 선행관계 주입에 사용
        series: dict[str, np.ndarray] = {}
        for ind in C.ALL_INDICATORS:
            base = 100.0 + rng.normal(0, 5)            # 지표별 평균 수준
            trend = rng.normal(0, 0.05)                # 주당 추세
            season = rng.normal(0, 1, size=n_weeks)    # 계절 성분(단순화)
            x = np.empty(n_weeks)
            x[0] = base
            phi = 0.6                                  # AR(1) 계수
            for t in range(1, n_weeks):
                x[t] = base + phi * (x[t - 1] - base) + trend * t + season[t] + rng.normal(0, 2)
            series[ind] = x

        # 선행관계: 신규창업수(t) → 카드매출지수(t+2)
        if "신규창업수" in series and "카드매출지수" in series:
            lead = series["신규창업수"]
            lagged = np.empty(n_weeks)
            lagged[:2] = series["카드매출지수"][:2]
            lagged[2:] = series["카드매출지수"][2:] + 0.4 * (lead[:-2] - lead[:-2].mean())
            series["카드매출지수"] = lagged

        # 이상신호 주입
        if region == inject_region:
            i = inject_week_idx
            sd = lambda s: np.std(series[s])
            series["카드매출지수"][i] -= 6 * sd("카드매출지수")
            series["폐업수"][i] += 5 * sd("폐업수")
            series["응급실내원"][i] += 5 * sd("응급실내원")

        for ind in C.ALL_INDICATORS:
            for t in range(n_weeks):
                rows.append((region, weeks[t], ind, float(series[ind][t])))

    return pd.DataFrame(rows, columns=[C.COL_REGION, C.COL_WEEK, C.COL_INDICATOR, C.COL_VALUE])
