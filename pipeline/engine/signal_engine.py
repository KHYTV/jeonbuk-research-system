import os
"""
이상 신호 탐지 엔진
─────────────────────────────────────────────────
① z-score 단변량 이상 탐지 (지표별)
② Mahalanobis 거리 다변량 이상 탐지 (시군별)
③ 핫 플레이스 — 이상 스코어 상위 시군
④ 핫 아이템 — 신호를 만드는 지표 조합 패턴
"""
import json, math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import MUNICIPALITIES
from utils import get_db, get_logger

log = get_logger("SignalEngine")

# ══════════════════════════════════════════════
# 데이터 로드
# ══════════════════════════════════════════════
def load_panel(days_back: int = 30) -> pd.DataFrame:
    """DB에서 지표 패널 데이터 로드 → (municipality × indicator) pivot"""
    conn = get_db()
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT municipality, indicator, category, value, collected_at
        FROM raw_indicators
        WHERE collected_at >= ? AND value IS NOT NULL
        ORDER BY collected_at DESC
    """, (since,)).fetchall()
    conn.close()

    if not rows:
        log.warning("  DB에 데이터 없음")
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    # 시군 × 지표 최근값 pivot
    pivot = (df.groupby(["municipality","indicator"])["value"]
               .mean()
               .unstack(fill_value=np.nan))
    return pivot

def load_places_summary() -> pd.DataFrame:
    """장소 DB에서 시군별 업종 집계"""
    conn = get_db()
    rows = conn.execute("""
        SELECT municipality, category,
               COUNT(*) as count,
               AVG(review_count) as avg_reviews,
               SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) as open_count
        FROM places
        GROUP BY municipality, category
    """).fetchall()
    conn.close()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


# ══════════════════════════════════════════════
# ① z-score 이상 탐지
# ══════════════════════════════════════════════
def zscore_detect(panel: pd.DataFrame, threshold: float = 1.8) -> pd.DataFrame:
    """각 지표별 시군 z-score 계산 → 임계값 초과 탐지"""
    if panel.empty:
        return pd.DataFrame()

    scores = pd.DataFrame(index=panel.index, columns=panel.columns, dtype=float)
    for col in panel.columns:
        vals = panel[col].dropna()
        if len(vals) < 3:
            continue
        mu, sigma = vals.mean(), vals.std()
        if sigma < 1e-9:
            continue
        scores[col] = (panel[col] - mu) / sigma

    # 이상 여부 (|z| > threshold)
    anomalies = []
    for muni in scores.index:
        for ind in scores.columns:
            z = scores.loc[muni, ind]
            if pd.isna(z):
                continue
            if abs(z) >= threshold:
                direction = "↑" if z > 0 else "↓"
                anomalies.append({
                    "municipality": muni,
                    "indicator": ind,
                    "z_score": round(float(z), 3),
                    "direction": direction,
                    "value": round(float(panel.loc[muni, ind]), 2),
                })

    return pd.DataFrame(anomalies).sort_values("z_score", key=abs, ascending=False) if anomalies else pd.DataFrame()


# ══════════════════════════════════════════════
# ② Mahalanobis 거리 — 다변량 이상 스코어
# ══════════════════════════════════════════════
def mahalanobis_score(panel: pd.DataFrame) -> Dict[str, float]:
    """시군별 다변량 이상 스코어 계산"""
    if panel.empty or panel.shape[1] < 2:
        return {}

    # 결측치 컬럼평균으로 채우기
    filled = panel.fillna(panel.mean())
    if filled.shape[0] < 3:
        return {}

    X = filled.values.astype(float)
    mu = X.mean(axis=0)
    cov = np.cov(X.T)

    # 역행렬 (수치 안정을 위해 Ridge 정규화)
    try:
        ridge = cov + np.eye(cov.shape[0]) * 0.01 * np.trace(cov) / cov.shape[0]
        inv_cov = np.linalg.inv(ridge)
    except np.linalg.LinAlgError:
        log.warning("  공분산 역행렬 계산 실패 → 대각행렬 사용")
        inv_cov = np.diag(1.0 / (np.var(X, axis=0) + 1e-9))

    scores = {}
    for i, muni in enumerate(filled.index):
        diff = X[i] - mu
        d2 = float(diff @ inv_cov @ diff)
        scores[muni] = round(math.sqrt(max(0, d2)), 3)

    return scores


# ══════════════════════════════════════════════
# ③ 핫 플레이스 선정
# ══════════════════════════════════════════════
def find_hot_places(panel: pd.DataFrame,
                    anomalies: pd.DataFrame,
                    maha_scores: Dict[str, float],
                    places_df: pd.DataFrame,
                    top_n: int = 3) -> List[Dict]:
    """
    핫 플레이스 = 이상 신호 + 장소 활성도를 결합한 종합 스코어
    """
    # 시군별 이상 지표 수 집계
    anom_count = defaultdict(int)
    anom_detail = defaultdict(list)
    if not anomalies.empty:
        for _, row in anomalies.iterrows():
            anom_count[row["municipality"]] += 1
            anom_detail[row["municipality"]].append({
                "indicator": row["indicator"],
                "z": row["z_score"],
                "dir": row["direction"],
            })

    # 장소 활성도 점수 (시군별 평균 리뷰수 × 장소수)
    place_scores = {}
    if not places_df.empty:
        food_df = places_df[places_df["category"].isin(["음식점","카페"])]
        for muni in MUNICIPALITIES:
            sub = food_df[food_df["municipality"] == muni]
            if sub.empty:
                place_scores[muni] = 0.0
            else:
                place_scores[muni] = float(sub["avg_reviews"].mean() * math.log1p(sub["count"].sum()))

    # 종합 스코어 계산
    all_munis = list(MUNICIPALITIES.keys())
    max_maha = max(maha_scores.values()) if maha_scores else 1.0
    max_place = max(place_scores.values()) if place_scores else 1.0

    composite = {}
    for muni in all_munis:
        m_norm  = (maha_scores.get(muni, 0) / max(max_maha, 1e-9)) * 60   # 60점 배점
        a_norm  = min(anom_count.get(muni, 0) / 5.0, 1.0) * 25            # 25점 배점
        p_norm  = (place_scores.get(muni, 0) / max(max_place, 1e-9)) * 15  # 15점 배점
        composite[muni] = round(m_norm + a_norm + p_norm, 2)

    # 상위 top_n 선정
    ranked = sorted(composite.items(), key=lambda x: x[1], reverse=True)[:top_n]

    hot_places = []
    for rank, (muni, score) in enumerate(ranked, 1):
        hot_places.append({
            "rank": rank,
            "municipality": muni,
            "hot_score": score,
            "mahalanobis": maha_scores.get(muni, 0),
            "anomaly_count": anom_count.get(muni, 0),
            "anomaly_indicators": anom_detail.get(muni, []),
            "place_score": round(place_scores.get(muni, 0), 2),
        })

    return hot_places


# ══════════════════════════════════════════════
# ④ 핫 아이템 — 지표 조합 패턴 분류
# ══════════════════════════════════════════════
PATTERN_RULES = [
    {
        "name": "산업_위기",
        "label": "🏭 산업 위기",
        "conditions": [
            {"indicator": "음식점_폐업",         "dir": "↑"},
            {"indicator": "소상공인_신규_등록",   "dir": "↓"},
        ],
        "description": "음식점·소상공인 폐업 급증 + 창업 감소 → 지역 소비경제 침체 신호",
        "theory": "지역 경제 위기의 선행 지표 (Shutt & Waddington 1984; 지방소멸 문헌)",
    },
    {
        "name": "생활문화_활성화",
        "label": "🌟 생활문화 활성화",
        "conditions": [
            {"indicator": "신규_음식점_등록",     "dir": "↑"},
            {"indicator": "전입_인구",             "dir": "↑"},
        ],
        "description": "음식점 신규 등록 증가 + 전입 인구 유입 → 지역 상권 활성화",
        "theory": "Place vitality & amenity-led migration (Florida 2002; 창조경제론)",
    },
    {
        "name": "청년_이탈",
        "label": "👥 청년 이탈 가속",
        "conditions": [
            {"indicator": "20대_순이동",           "dir": "↓"},
            {"indicator": "음식점_폐업",           "dir": "↑"},
        ],
        "description": "20대 유출 심화 + 소비업종 폐업 증가 → 지방소멸 압박 동시 작동",
        "theory": "지방소멸 이론 (마스다 2014; 이상호 2018) — 청년 유출과 소비 감소의 악순환",
    },
    {
        "name": "관광_수요_급등",
        "label": "🎪 관광 수요 급등",
        "conditions": [
            {"indicator": "신규_음식점_등록",     "dir": "↑"},
            {"indicator": "PM10_일평균",           "dir": "↓"},  # 환경 좋아짐
        ],
        "description": "음식점 신규 등록 증가 + 대기질 개선 → 방문객 유입 환경 형성",
        "theory": "Amenity migration & tourism-led development (Graves 1983)",
    },
    {
        "name": "보건_위기",
        "label": "🏥 보건·의료 위기",
        "conditions": [
            {"indicator": "감염병_신고수",         "dir": "↑"},
            {"indicator": "의료기관_수",           "dir": "↓"},
        ],
        "description": "감염병 증가 + 의료기관 감소 → 의료 취약 지역의 이중 위기",
        "theory": "의료 접근성 격차 및 보건 취약성 (rural health disparity 문헌)",
    },
    {
        "name": "환경_압박",
        "label": "🌫️ 환경 압박",
        "conditions": [
            {"indicator": "PM10_일평균",           "dir": "↑"},
            {"indicator": "PM25_일평균",           "dir": "↑"},
        ],
        "description": "미세먼지 동반 상승 → 생활환경 악화, 외부 방문객 감소 가능성",
        "theory": "환경 어메니티와 인구 이동의 관계 (Cragg & Kahn 1997)",
    },
]

def find_hot_items(anomalies: pd.DataFrame) -> List[Dict]:
    """이상 지표 조합을 패턴 규칙과 매칭 → 핫 아이템 분류"""
    if anomalies.empty:
        return []

    # 시군별 이상 지표 dict 구성
    muni_anoms: Dict[str, Dict[str, str]] = defaultdict(dict)
    for _, row in anomalies.iterrows():
        muni_anoms[row["municipality"]][row["indicator"]] = row["direction"]

    matched_items = []
    for muni, ind_map in muni_anoms.items():
        for rule in PATTERN_RULES:
            # 모든 조건 충족 여부 확인
            match_count = sum(
                1 for cond in rule["conditions"]
                if ind_map.get(cond["indicator"]) == cond["dir"]
            )
            if match_count >= max(1, len(rule["conditions"]) - 1):  # 80% 이상 매칭
                confidence = round(match_count / len(rule["conditions"]), 2)
                matched_items.append({
                    "municipality": muni,
                    "pattern_name": rule["name"],
                    "pattern_label": rule["label"],
                    "description": rule["description"],
                    "theory": rule["theory"],
                    "confidence": confidence,
                    "matched_indicators": [
                        c["indicator"] for c in rule["conditions"]
                        if ind_map.get(c["indicator"]) == c["dir"]
                    ],
                })

    return sorted(matched_items, key=lambda x: x["confidence"], reverse=True)


# ══════════════════════════════════════════════
# 전체 신호 탐지 실행
# ══════════════════════════════════════════════
def run_signal_detection(run_id: str) -> Dict:
    log.info("\n  [신호탐지] 시작...")

    panel = load_panel(days_back=30)
    places_df = load_places_summary()

    if panel.empty:
        log.warning("  패널 데이터 없음 → Mock 패널 생성")
        panel = _generate_mock_panel()

    log.info(f"  패널: {panel.shape[0]}개 시군 × {panel.shape[1]}개 지표")

    anomalies   = zscore_detect(panel, threshold=1.5)
    maha_scores = mahalanobis_score(panel)
    hot_places  = find_hot_places(panel, anomalies, maha_scores, places_df, top_n=3)
    hot_items   = find_hot_items(anomalies)

    log.info(f"  이상 신호: {len(anomalies)}건")
    log.info(f"  핫 플레이스: {[h['municipality'] for h in hot_places]}")
    log.info(f"  핫 아이템 패턴: {len(hot_items)}건")

    result = {
        "run_id": run_id,
        "period_end": datetime.now().strftime("%Y-%m-%d"),
        "panel_shape": list(panel.shape),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies.to_dict("records") if not anomalies.empty else [],
        "mahalanobis_scores": maha_scores,
        "hot_places": hot_places,
        "hot_items": hot_items,
    }

    # DB 저장
    conn = get_db()
    conn.execute("""
        INSERT INTO analysis_results (run_id, period_start, period_end, result_json)
        VALUES(?,?,?,?)
    """, (run_id,
          (datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d"),
          datetime.now().strftime("%Y-%m-%d"),
          json.dumps(result, ensure_ascii=False)))
    conn.commit(); conn.close()

    return result


def _generate_mock_panel() -> pd.DataFrame:
    """DB 없을 때 테스트용 패널 생성"""
    import random
    random.seed(42)
    np.random.seed(42)

    indicators = ["신규_음식점_등록","음식점_폐업","소상공인_신규_등록",
                  "전입_인구","전출_인구","20대_순이동",
                  "PM10_일평균","PM25_일평균",
                  "감염병_신고수","의료기관_수"]
    data = {}
    for ind in indicators:
        base = random.uniform(10, 200)
        vals = {m: base * (MUNICIPALITIES[m]["pop"]/200000) + random.gauss(0, base*0.15)
                for m in MUNICIPALITIES}
        # 군산에 이상 신호 주입
        if ind in ["음식점_폐업","소상공인_신규_등록"]:
            vals["군산시"] *= 3.2
        if ind in ["신규_음식점_등록","전입_인구"]:
            vals["완주군"] *= 2.5
        data[ind] = vals

    return pd.DataFrame(data, index=list(MUNICIPALITIES.keys()))
