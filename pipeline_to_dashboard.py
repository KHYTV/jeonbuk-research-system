"""
pipeline_to_dashboard.py - pipeline 실분석 결과 → jeonbuk 웹 대시보드.

bridge.py 가 jeonbuk '시계열' 엔진(26주 이력 필요)을 쓰는 것과 달리,
이 어댑터는 pipeline 의 '횡단면' 분석 결과(14개 시군을 서로 비교한
Mahalanobis + 인구정규화 z-score)를 그대로 대시보드 스키마로 변환한다.
→ 이력 누적을 기다리지 않고 '지금 수집된 실데이터'가 사이트에 바로 뜬다.

  cd pipeline && python main.py weekly   # 실수집 + 횡단면 분석(DB 저장)
  cd .. && python pipeline_to_dashboard.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from scipy import stats

ROOT = Path(__file__).parent
DB_PATH = ROOT / "pipeline" / "data" / "jeonbuk.db"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from jeonbuk import config as C
from jeonbuk import news as news_mod
from jeonbuk import topics as topics_mod
from jeonbuk import article as article_mod
from jeonbuk import build_web
from jeonbuk.report import save as save_signal

# 지표 → 도메인 (대시보드 색상/범례용)
INDICATOR_DOMAIN = {
    "음식점_수":"경제","음식점_폐업":"경제","음식점_신규":"경제","신규_음식점_등록":"경제",
    "소상공인_신규_등록":"경제","고용률":"경제","카드매출지수":"경제","사업체수":"경제",
    "PM10_일평균":"환경","PM25_일평균":"환경","대기질지수":"환경","폐기물발생량":"환경",
    "의료기관_수":"보건","감염병_신고수":"보건","응급실내원":"보건","의료기관방문":"보건",
    "전입_인구":"인구이동","전출_인구":"인구이동","20대_순이동":"인구이동","인구수":"인구이동",
}
def _domain(ind: str) -> str:
    return INDICATOR_DOMAIN.get(ind, "경제")


def load_result() -> tuple[dict, str]:
    """DB의 최신 pipeline 분석 결과."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT result_json, period_end FROM analysis_results ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        raise SystemExit("pipeline 분석 결과가 없습니다. 먼저 'cd pipeline && python main.py weekly' 실행.")
    return json.loads(row[0]), row[1]


def real_indicators() -> set[str]:
    """DB에서 실수집(_mock 아님) 소스로 들어온 지표 집합."""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT DISTINCT indicator FROM raw_indicators WHERE source NOT LIKE '%\\_mock' ESCAPE '\\'"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return {r[0] for r in rows}


def to_report(result: dict, week: str, real_inds: set[str]) -> dict:
    """pipeline 결과 → jeonbuk 대시보드 REPORT 스키마."""
    maha = result.get("mahalanobis_scores", {})
    hot_set = {h["municipality"] for h in result.get("hot_places", [])}

    ranking = [
        {"region": m, "d2": round(s, 2),
         "p_value": round(float(stats.chi2.sf(s * s, df=3)), 5),
         "is_hot": m in hot_set}
        for m, s in sorted(maha.items(), key=lambda x: -x[1])
    ]

    hot_places = []
    for hp in result.get("hot_places", []):
        inds = hp.get("anomaly_indicators", [])
        ssum = sum(a["z"] ** 2 for a in inds) or 1.0
        items = [{
            "indicator": a["indicator"], "domain": _domain(a["indicator"]),
            "share": round(a["z"] ** 2 / ssum, 3), "z": round(a["z"], 2),
            "direction": "상승" if a["dir"] == "↑" else "하락",
            "estimated": a["indicator"] not in real_inds,   # 실수집 아님 → 추정치
        } for a in inds]
        d2 = hp.get("mahalanobis", 0) ** 2
        hot_places.append({
            "region": hp["municipality"],
            "d2": round(d2, 2),
            "p_value": round(float(stats.chi2.sf(d2, df=max(1, len(inds)))), 6),
            "method": "전북 14개 시군 횡단면 비교 (인구정규화)",
            "n_baseline_weeks": 1,
            "hot_items": items[:4],
            "causal_edges": [],   # 횡단면이라 시계열 Granger 없음(이력 누적 시 추가)
        })

    return {
        "week": week, "n_regions_scanned": len(maha),
        "n_hot_places": len(hot_places),
        "hot_places": hot_places, "ranking": ranking,
    }


def build_brief(report: dict, week: str) -> dict:
    """핫 플레이스별 실제 네이버 뉴스 + Claude 분석기사."""
    briefs = []
    for hp in report["hot_places"]:
        region = hp["region"]
        items = [it["indicator"] for it in hp["hot_items"]]
        print(f"[{region}] 뉴스 수집…")
        arts = news_mod.collect(region, items, week, provider=None)
        topic = topics_mod.analyze([a.text for a in arts], n_topics=5)
        print(f"[{region}] 기사 {len(arts)}건 · 키워드 {topic.keyword_line(5)} · Claude 작성…")
        art = article_mod.write(hp, topic, week)
        briefs.append({
            "region": region, "n_articles": len(arts),
            "top_keywords": [w for w, _ in topic.top_keywords],
            "topics": [{"rank": t.rank, "weight": round(t.weight, 3),
                        "keywords": t.keywords} for t in topic.topics],
            "article_title": art.title, "article_body": art.body,
            "article_model": art.model,
            "sources": [{"title": a.title, "source": a.source,
                         "published": a.published, "url": a.url} for a in arts[:8]],
        })
    return {"week": week, "n_hot_places": len(briefs), "briefs": briefs}


def main() -> None:
    result, week = load_result()
    if not week:
        week = datetime.now().strftime("%Y-%m-%d")
    real_inds = real_indicators()
    print(f"[adapter] 실수집 지표: {sorted(real_inds)}")
    report = to_report(result, week, real_inds)
    save_signal(report, week)
    print(f"[adapter] 실분석 REPORT 저장 (핫 플레이스 {report['n_hot_places']}곳): "
          f"{[h['region'] for h in report['hot_places']]}")

    brief = build_brief(report, week)
    import jeonbuk.run_brief as rb
    rb.save(brief)

    build_web.build(C.OUTPUT_DIR / f"signal_{week}.json")
    import shutil
    (ROOT / "docs").mkdir(exist_ok=True)
    shutil.copy(C.BASE_DIR / "web" / "index.html", ROOT / "docs" / "index.html")
    print(f"[adapter] 실데이터 대시보드 갱신 완료 → docs/index.html (week {week})")


if __name__ == "__main__":
    main()
