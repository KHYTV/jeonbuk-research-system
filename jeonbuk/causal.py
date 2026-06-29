"""
causal.py - 인과 진단(Granger).

핫 플레이스로 잡힌 시군에서, '어떤 지표가 다른 지표를 선행하는가'를
구조화한다. Granger 인과는 과거의 X 가 Y 의 예측을 (Y 자기과거만 쓸 때보다)
유의하게 개선하면 'X → Y' 로 본다. 진짜 물리적 인과의 증거는 아니고
'예측적 선행' 이지만, 신호 발생의 구조를 좁혀주는 진단 도구로 쓴다.

전처리
  Granger 는 정상(stationary) 시계열을 전제하므로, 지표별로 ADF 검정을 하고
  실패하면 차분(최대 MAX_DIFF)해 정상성을 확보한다. 모든 지표를 동일 차분
  차수로 맞춰 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C

try:
    from statsmodels.tsa.stattools import adfuller, grangercausalitytests
    _HAS_SM = True
except Exception:  # statsmodels 미설치 시 우아하게 비활성
    _HAS_SM = False


@dataclass
class CausalEdge:
    source: str        # 선행 지표
    target: str        # 후행 지표
    best_lag: int      # 최소 p-value를 준 시차(주)
    p_value: float     # 최소 p-value
    source_domain: str
    target_domain: str


def _make_stationary(s: pd.Series) -> tuple[pd.Series, int]:
    """ADF로 정상성 확인, 실패 시 차분. (정상화된 시계열, 차분차수) 반환."""
    x = s.dropna()
    for d in range(C.MAX_DIFF + 1):
        if len(x) < 10:
            break
        try:
            pval = adfuller(x, autolag="AIC")[1]
        except Exception:
            pval = 1.0
        if pval < C.ADF_ALPHA:
            return x, d
        x = x.diff().dropna()
    return x, C.MAX_DIFF


def granger_pair(target: pd.Series, source: pd.Series, maxlag: int) -> tuple[int, float] | None:
    """source 가 target 을 Granger-선행하는지. (best_lag, min_p) 반환."""
    df = pd.concat([target, source], axis=1).dropna()
    if len(df) < C.CAUSAL_MIN_WEEKS:
        return None
    try:
        # grangercausalitytests: 2번째 컬럼이 1번째를 인과하는지 검정.
        # 이 함수는 결과 표를 stdout 으로 직접 찍으므로 캡처해 억제한다.
        import contextlib
        import io
        import warnings
        with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("ignore")
            res = grangercausalitytests(df.to_numpy(), maxlag=maxlag)
    except Exception:
        return None
    best_lag, best_p = 0, 1.0
    for lag, (stats_dict, _) in res.items():
        p = stats_dict["ssr_ftest"][1]
        if p < best_p:
            best_lag, best_p = lag, p
    return best_lag, float(best_p)


def diagnose(wide: pd.DataFrame, focus: list[str] | None = None) -> list[CausalEdge]:
    """
    한 시군의 wide 패널에서 지표쌍 Granger 인과 그래프를 만든다.

    focus 가 주어지면(예: 핫 아이템 지표들) 그 지표들과 얽힌 관계만 검정해
    조합 폭증을 막는다. 반환: 유의한 선행→후행 엣지 목록(p-value 오름차순).
    """
    if not _HAS_SM:
        return []

    cols = [c for c in wide.columns if wide[c].notna().sum() >= C.CAUSAL_MIN_WEEKS]
    if len(cols) < 2:
        return []

    # 정상화
    stat: dict[str, pd.Series] = {}
    for c in cols:
        s, _ = _make_stationary(wide[c])
        stat[c] = s

    # 검정 대상 쌍 구성
    focus = [f for f in (focus or cols) if f in cols]
    others = cols
    edges: list[CausalEdge] = []
    seen: set[tuple[str, str]] = set()

    for tgt in focus:
        for src in others:
            if src == tgt or (src, tgt) in seen:
                continue
            seen.add((src, tgt))
            df = pd.concat([stat[tgt], stat[src]], axis=1).dropna()
            r = granger_pair(df.iloc[:, 0], df.iloc[:, 1], C.GRANGER_MAXLAG)
            if r is None:
                continue
            lag, p = r
            if p < C.ALPHA_CAUSAL:
                edges.append(
                    CausalEdge(
                        source=src,
                        target=tgt,
                        best_lag=lag,
                        p_value=p,
                        source_domain=C.INDICATOR_DOMAIN.get(src, "기타"),
                        target_domain=C.INDICATOR_DOMAIN.get(tgt, "기타"),
                    )
                )
    edges.sort(key=lambda e: e.p_value)
    return edges
