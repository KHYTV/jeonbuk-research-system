import os
"""
전북 통합 파이프라인 메인 오케스트레이터
─────────────────────────────────────────────────
실행: python3 main.py [weekly|monthly]

단계:
  1. DB 초기화
  2. 공공 지표 수집 (경제·인구·환경·보건)
  3. 생활문화 데이터 수집 (카카오·네이버·TourAPI·빅카인즈)
  4. 이상 신호 탐지 (z-score + Mahalanobis + 패턴 매칭)
  5. 연구 브리핑 리포트 생성
"""
import sys, os, time, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.makedirs("./collectors", exist_ok=True)

from datetime import datetime
from utils import init_db, get_logger, get_db, log_collect
from collectors.public_collector  import (collect_sbiz, collect_mfds,
                                           collect_kosis_population,
                                           collect_airkorea, collect_hira)
from collectors.culture_collector import (collect_kakao, collect_naver_local,
                                           collect_tourapi, collect_bigkinds)
from collectors.news_collector import collect_all_news, get_news_summary
from engine.signal_engine         import run_signal_detection
from report.report_generator      import generate

log = get_logger("Pipeline")

# 수집기 정의 (이름, 함수, 설명)
COLLECTORS = [
    ("공공/sbiz",      collect_sbiz,              "소상공인 상권정보"),
    ("공공/mfds",      collect_mfds,              "식약처 음식점 인허가"),
    ("공공/population",collect_kosis_population,  "KOSIS 인구이동"),
    ("공공/airkorea",  collect_airkorea,           "에어코리아 대기오염"),
    ("공공/hira",      collect_hira,               "HIRA 의료기관"),
    ("문화/kakao",     collect_kakao,              "카카오 로컬 장소"),
    ("문화/naver",     collect_naver_local,        "네이버 지역검색"),
    ("문화/tourapi",   collect_tourapi,            "TourAPI 관광정보"),
    ("문화/bigkinds",  collect_bigkinds,           "빅카인즈 뉴스"),
    ("뉴스/multi",      collect_all_news,           "뉴스 멀티소스(네이버+RSS+도청)"),
]

def run(period="weekly"):
    run_id = f"{datetime.now():%Y%m%d_%H%M}_{uuid.uuid4().hex[:6]}"
    t_total = time.time()

    print("\n" + "═"*60)
    print(f"  🚀 전북 통합 파이프라인 시작")
    print(f"  run_id : {run_id}")
    print(f"  period : {period}")
    print(f"  시작   : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("═"*60)

    # 1. DB 초기화
    print("\n[Step 1] DB 초기화")
    init_db()
    print("  ✓ 완료")

    # 2 & 3. 수집
    print("\n[Step 2-3] 데이터 수집")
    total_collected = 0
    collect_summary = []
    for name, fn, desc in COLLECTORS:
        t0 = time.time()
        print(f"\n  ▸ {desc} ({name})")
        try:
            n = fn(run_id)
            elapsed = time.time() - t0
            total_collected += n
            collect_summary.append((name, "✓", n, elapsed))
        except Exception as e:
            elapsed = time.time() - t0
            log.error(f"  ✗ {name} 오류: {e}")
            log_collect(run_id, name, "error", 0, str(e), elapsed)
            collect_summary.append((name, "✗", 0, elapsed))

    # 수집 요약
    print("\n" + "─"*60)
    print("  수집 요약:")
    for name, status, n, elapsed in collect_summary:
        print(f"    {status} {name:<30} {n:>4}건  ({elapsed:.1f}s)")
    print(f"  총 수집: {total_collected}건")

    # 4. 신호 탐지
    print("\n[Step 4] 이상 신호 탐지")
    result = run_signal_detection(run_id)
    print(f"  ✓ 핫 플레이스: {[h['municipality'] for h in result['hot_places']]}")
    print(f"  ✓ 핫 아이템:   {len(result['hot_items'])}개 패턴")
    print(f"  ✓ 이상 신호:   {result['anomaly_count']}건")

    # 5. 리포트
    print("\n[Step 5] 리포트 생성")
    report_path = generate(result)
    print(f"  ✓ {report_path}")

    elapsed_total = time.time() - t_total
    print("\n" + "═"*60)
    print(f"  ✅ 완료 ({elapsed_total:.1f}s)")
    print("═"*60 + "\n")

    return result, report_path

if __name__ == "__main__":
    period = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    result, path = run(period)

    print("\n── 핫 플레이스 TOP 3 ──────────────────────")
    for hp in result["hot_places"]:
        print(f"  {hp['rank']}위 {hp['municipality']} — 신호강도 {hp['hot_score']}")
        for a in hp["anomaly_indicators"][:3]:
            print(f"     └ {a['indicator']} {a['dir']} (z={a['z']:.2f})")

    print("\n── 핫 아이템 패턴 ─────────────────────────")
    for it in result["hot_items"][:5]:
        print(f"  [{it['municipality']}] {it['pattern_label']} (신뢰도 {it['confidence']*100:.0f}%)")
        print(f"     └ {it['description'][:60]}…")

    print(f"\n리포트: {path}")
