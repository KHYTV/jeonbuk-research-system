"""
detector.py - 핫 플레이스(Mahalanobis) + 핫 아이템(기여도 분해).

핵심 아이디어
  '핫 플레이스'는 수치가 단지 높은 곳이 아니라, 여러 지표가 '동시에'
  자기 과거 분포에서 벗어난 곳이다. 단변량 z-score들의 합으로는 지표 간
  상관(예: 매출↓와 폐업↑이 늘 같이 움직임)을 못 걷어내므로, 공분산을
  반영하는 Mahalanobis 거리 D² 를 쓴다.

      z   = (x_t - μ_base) / σ_base          (지표별 표준화)
      D²  = zᵀ R⁻¹ z                          (R: 베이스라인 상관행렬)
      D²  ~ χ²_p  (대략)  →  p-value 로 이상 여부 판정

핫 아이템
  D² 는 지표별 기여도로 정확히 분해된다(합 = D²):
      contrib_i = z_i · (R⁻¹ z)_i,   Σ contrib_i = zᵀ R⁻¹ z = D²
  기여도 상위 지표 + 방향(z_i 부호)이 곧 '무슨 신호였나'.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.covariance import LedoitWolf, OAS, EmpiricalCovariance

from . import config as C


@dataclass
class ItemContribution:
    indicator: str
    domain: str
    contribution: float   # D² 중 이 지표가 차지하는 절대 기여
    share: float          # 전체 D² 대비 비율 (0~1)
    z: float              # 표준화 편차 (방향·크기)
    direction: str        # "상승" | "하락"


@dataclass
class PlaceSignal:
    region: str
    week: pd.Timestamp
    d2: float                       # Mahalanobis D²
    p_value: float                  # χ²_p 기준 p-value
    is_hot: bool                    # 임계 초과 여부
    n_baseline: int                 # 사용한 베이스라인 주 수
    items: list[ItemContribution] = field(default_factory=list)

    @property
    def hot_items(self) -> list[ItemContribution]:
        """신호를 설명하는 상위 기여 지표(핫 아이템)."""
        sig = [it for it in self.items if it.share >= C.ITEM_CONTRIB_MIN]
        return sig[: C.TOP_K_ITEMS]


def _cov_estimator():
    return {"ledoit_wolf": LedoitWolf, "oas": OAS, "empirical": EmpiricalCovariance}[
        C.SHRINKAGE
    ]()


def _decompose(z: np.ndarray, Rinv: np.ndarray, cols: list[str]) -> tuple[float, list[ItemContribution]]:
    """D² 와 지표별 기여도 분해를 함께 계산."""
    rz = Rinv @ z
    d2 = float(z @ rz)
    contribs = z * rz                      # 합 = d2
    items: list[ItemContribution] = []
    for i, ind in enumerate(cols):
        share = float(contribs[i] / d2) if d2 > 1e-12 else 0.0
        items.append(
            ItemContribution(
                indicator=ind,
                domain=C.INDICATOR_DOMAIN.get(ind, "기타"),
                contribution=float(contribs[i]),
                share=share,
                z=float(z[i]),
                direction="상승" if z[i] >= 0 else "하락",
            )
        )
    items.sort(key=lambda it: it.contribution, reverse=True)
    return d2, items


def detect_region_week(
    wide: pd.DataFrame, target_week: pd.Timestamp
) -> PlaceSignal | None:
    """
    한 시군의 wide 패널에서 target_week 의 이상 신호를 계산.
    target_week 직전 BASELINE_WEEKS 구간을 분포 추정에 사용한다.
    """
    if target_week not in wide.index:
        return None

    hist = wide.loc[wide.index < target_week].tail(C.BASELINE_WEEKS)
    hist = hist.dropna(axis=1, how="any")          # 베이스라인에 결측 있는 지표 제외
    if len(hist) < C.MIN_BASELINE_WEEKS or hist.shape[1] < 2:
        return None

    cols = list(hist.columns)
    cur = wide.loc[target_week, cols]
    if cur.isna().any():
        return None

    mu = hist.mean().to_numpy()
    sd = hist.std(ddof=1).replace(0, np.nan).to_numpy()
    if np.isnan(sd).any():
        # 분산 0인 지표 제거
        keep = ~np.isnan(sd)
        cols = [c for c, k in zip(cols, keep) if k]
        if len(cols) < 2:
            return None
        hist = hist[cols]
        mu, sd = hist.mean().to_numpy(), hist.std(ddof=1).to_numpy()
        cur = wide.loc[target_week, cols]

    z = (cur.to_numpy() - mu) / sd
    Z = (hist.to_numpy() - mu) / sd                # 표준화된 베이스라인 → 상관행렬

    est = _cov_estimator().fit(Z)
    R = est.covariance_
    Rinv = np.linalg.pinv(R)                        # 안정적 역행렬

    d2, items = _decompose(z, Rinv, cols)
    p = len(cols)
    p_value = float(stats.chi2.sf(d2, df=p))
    return PlaceSignal(
        region=wide.attrs.get("region", "?"),
        week=target_week,
        d2=d2,
        p_value=p_value,
        is_hot=p_value < C.ALPHA_PLACE,
        n_baseline=len(hist),
        items=items,
    )


def scan_week(long_df: pd.DataFrame, target_week: pd.Timestamp) -> list[PlaceSignal]:
    """
    target_week 에 대해 14개 시군 전부를 스캔하고 D² 내림차순으로 정렬해 반환.
    is_hot=True 가 '핫 플레이스'.
    """
    from .data import to_wide

    signals: list[PlaceSignal] = []
    for region in C.REGIONS:
        wide = to_wide(long_df, region)
        wide.attrs["region"] = region
        sig = detect_region_week(wide, target_week)
        if sig is not None:
            signals.append(sig)
    signals.sort(key=lambda s: s.d2, reverse=True)
    return signals
