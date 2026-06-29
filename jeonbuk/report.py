"""
report.py - 주간 신호 리포트 조립.

핫 플레이스 → 핫 아이템 → 인과 진단을 엮어
"이번 주 어디서 / 무슨 신호가 / 왜(구조적으로) / 연구적으로 무슨 의미인지"
를 사람이 읽는 마크다운 + 기계가 쓰는 JSON 두 형태로 낸다.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd

from . import config as C
from .causal import CausalEdge, diagnose
from .data import to_wide
from .detector import PlaceSignal, scan_week


def build_weekly(long_df: pd.DataFrame, target_week: pd.Timestamp) -> dict:
    """한 주의 전체 진단 결과를 구조화된 dict 로 반환."""
    signals = scan_week(long_df, target_week)
    hot = [s for s in signals if s.is_hot]

    report = {
        "week": str(pd.Timestamp(target_week).date()),
        "n_regions_scanned": len(signals),
        "n_hot_places": len(hot),
        "hot_places": [],
        "ranking": [
            {"region": s.region, "d2": round(s.d2, 2), "p_value": round(s.p_value, 5),
             "is_hot": s.is_hot}
            for s in signals
        ],
    }

    for s in hot:
        wide = to_wide(long_df, s.region)
        focus = [it.indicator for it in s.hot_items]
        edges: list[CausalEdge] = diagnose(wide, focus=focus)
        report["hot_places"].append({
            "region": s.region,
            "d2": round(s.d2, 2),
            "p_value": round(s.p_value, 6),
            "n_baseline_weeks": s.n_baseline,
            "hot_items": [
                {"indicator": it.indicator, "domain": it.domain,
                 "share": round(it.share, 3), "z": round(it.z, 2),
                 "direction": it.direction}
                for it in s.hot_items
            ],
            "causal_edges": [
                {"source": e.source, "target": e.target, "lag": e.best_lag,
                 "p_value": round(e.p_value, 4),
                 "source_domain": e.source_domain, "target_domain": e.target_domain}
                for e in edges[:10]
            ],
        })
    return report


def to_markdown(report: dict) -> str:
    """구조화 결과 → 사람이 읽는 주간 브리핑."""
    L: list[str] = []
    L.append(f"# 전북 주간 신호 리포트 — {report['week']}")
    L.append("")
    L.append(f"- 스캔 시군: **{report['n_regions_scanned']}개**  |  "
             f"핫 플레이스: **{report['n_hot_places']}개**")
    L.append("")

    if not report["hot_places"]:
        L.append("> 이번 주 임계를 넘는 다변량 이상 신호는 없습니다.")
    for hp in report["hot_places"]:
        L.append(f"## 🔥 {hp['region']}  (D²={hp['d2']}, p={hp['p_value']})")
        L.append("")
        L.append("**핫 아이템 — 이 신호를 만든 지표**")
        for it in hp["hot_items"]:
            arrow = "▲" if it["direction"] == "상승" else "▼"
            L.append(f"- {arrow} `{it['indicator']}` ({it['domain']}) "
                     f"· 기여 {it['share']*100:.0f}% · z={it['z']:+.1f}")
        L.append("")
        if hp["causal_edges"]:
            L.append("**인과 진단 — 선행 → 후행 (Granger)**")
            for e in hp["causal_edges"]:
                L.append(f"- `{e['source']}` ({e['source_domain']}) "
                         f"→ `{e['target']}` ({e['target_domain']}) "
                         f"· lag {e['lag']}주 · p={e['p_value']}")
        else:
            L.append("**인과 진단**: 유의한 선행관계 미검출 "
                     "(statsmodels 미설치이거나 관측 길이 부족 가능)")
        L.append("")
        L.append(_interpretation(hp))
        L.append("")
    return "\n".join(L)


def _interpretation(hp: dict) -> str:
    """핫 아이템 도메인 구성 + 인과 구조로부터 연구적 해석 초안을 생성."""
    domains = {it["domain"] for it in hp["hot_items"]}
    dirs = ", ".join(
        f"{it['indicator']}{'↑' if it['direction']=='상승' else '↓'}"
        for it in hp["hot_items"]
    )
    lead = hp["causal_edges"][0] if hp["causal_edges"] else None

    lines = ["**연구적 해석(초안)**", ""]
    if len(domains) >= 2:
        lines.append(
            f"- 단일 도메인이 아니라 **{' · '.join(sorted(domains))}** 이 동시에 움직였습니다 "
            f"({dirs}). 도메인 교차 동조화는 국지적 충격(사업체 폐업, 행사·재난 등)이 "
            f"여러 부문으로 전이됐을 가능성을 시사합니다."
        )
    else:
        dom = next(iter(domains))
        lines.append(
            f"- 신호가 **{dom}** 도메인에 집중되어 있어({dirs}), 부문 내부 요인일 가능성이 큽니다."
        )
    if lead:
        lines.append(
            f"- 선행 지표로 `{lead['source']}`({lead['source_domain']})가 "
            f"`{lead['target']}`({lead['target_domain']})를 {lead['lag']}주 앞서므로, "
            f"**{lead['source']}를 조기경보 변수로** 모니터링하면 다음 신호를 선제 포착할 수 있습니다."
        )
    lines.append(
        "- ※ Granger는 예측적 선행이지 인과 확정이 아닙니다. 후속으로 외생 사건 매칭"
        "(공시·뉴스·행정자료)과 인접 시군 공간효과를 함께 확인할 것을 권합니다."
    )
    return "\n".join(lines)


def _json_default(o):
    """numpy 스칼라 → 파이썬 기본형 변환 (json 직렬화용)."""
    import numpy as np
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"{type(o)} is not JSON serializable")


def save(report: dict, week_str: str) -> tuple[str, str]:
    """JSON + Markdown 동시 저장. 경로 튜플 반환."""
    json_path = C.OUTPUT_DIR / f"signal_{week_str}.json"
    md_path = C.OUTPUT_DIR / f"signal_{week_str}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return str(json_path), str(md_path)
