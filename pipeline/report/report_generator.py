import os
"""
주간 연구 브리핑 리포트 생성기
핫 플레이스·핫 아이템·원인진단·학술 함의를 HTML로 출력합니다.
"""
import json, os
from datetime import datetime
from typing import Dict, List
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REPORT_PATH
from utils import get_logger

log = get_logger("ReportGenerator")
os.makedirs(REPORT_PATH, exist_ok=True)


def generate(result: Dict) -> str:
    now_str = datetime.now().strftime("%Y년 %m월 %d일")
    hot_places = result.get("hot_places", [])
    hot_items  = result.get("hot_items", [])
    anomalies  = result.get("anomalies", [])
    maha       = result.get("mahalanobis_scores", {})

    # ── 핫 플레이스 카드 ──────────────────────
    rank_emoji = ["🥇","🥈","🥉"]
    place_cards = ""
    for hp in hot_places:
        muni = hp["municipality"]
        anoms = hp.get("anomaly_indicators", [])
        anom_html = "".join(
            f'<span class="pill pill-{"up" if a["dir"]=="↑" else "down"}">'
            f'{a["indicator"]} {a["dir"]} (z={a["z"]:.2f})</span>'
            for a in anoms[:4]
        )
        place_cards += f"""
        <div class="hot-card">
          <div class="hot-rank">{rank_emoji[hp["rank"]-1]} #{hp["rank"]}</div>
          <div class="hot-muni">{muni}</div>
          <div class="hot-score">종합 신호 강도 <strong>{hp["hot_score"]:.1f}점</strong>
            <span class="maha">Mahalanobis={hp["mahalanobis"]:.2f}</span>
          </div>
          <div class="hot-pills">{anom_html}</div>
          <div class="hot-count">이상 감지 지표 {hp["anomaly_count"]}개</div>
        </div>"""

    # ── 핫 아이템 테이블 ──────────────────────
    item_rows = ""
    for it in hot_items[:8]:
        conf_pct = int(it["confidence"] * 100)
        bar = f'<div class="conf-bar"><div class="conf-fill" style="width:{conf_pct}%"></div></div>'
        inds = ", ".join(it["matched_indicators"])
        item_rows += f"""
        <tr>
          <td><span class="pattern-label">{it["pattern_label"]}</span></td>
          <td>{it["municipality"]}</td>
          <td style="font-size:11px">{inds}</td>
          <td>{bar}<span style="font-size:11px">{conf_pct}%</span></td>
          <td style="font-size:11px;color:var(--muted)">{it["description"]}</td>
        </tr>"""

    # ── 학술 함의 블록 ────────────────────────
    unique_theories = list({it["theory"]: it for it in hot_items}.values())
    implications = ""
    for i, it in enumerate(unique_theories[:4], 1):
        implications += f"""
        <div class="impl-block">
          <div class="impl-num">implication {i}</div>
          <div class="impl-pattern">{it["pattern_label"]}</div>
          <p class="impl-desc">{it["description"]}</p>
          <p class="impl-theory">📚 {it["theory"]}</p>
        </div>"""

    if not implications:
        implications = '<p style="color:var(--muted);font-size:13px">이번 주는 유의한 패턴 없음 — 정상 범위 내 변동</p>'

    # ── 이상 신호 테이블 ─────────────────────
    anom_rows = ""
    for a in sorted(anomalies, key=lambda x: abs(x["z_score"]), reverse=True)[:12]:
        cls = "anom-up" if a["direction"]=="↑" else "anom-down"
        anom_rows += f"""
        <tr>
          <td>{a["municipality"]}</td>
          <td>{a["indicator"]}</td>
          <td class="{cls}">{a["direction"]} {a["value"]}</td>
          <td><code>z={a["z_score"]:+.2f}</code></td>
        </tr>"""

    # ── Mahalanobis 순위 ─────────────────────
    maha_sorted = sorted(maha.items(), key=lambda x: x[1], reverse=True)
    maha_bars = ""
    max_m = max(maha.values()) if maha else 1
    for muni, score in maha_sorted[:8]:
        pct = int(score / max(max_m, 0.01) * 100)
        color = "#e24b4a" if pct > 70 else "#ba7517" if pct > 40 else "#1d9e75"
        maha_bars += f"""
        <div class="maha-row">
          <span class="maha-muni">{muni}</span>
          <div class="maha-track">
            <div class="maha-fill" style="width:{pct}%;background:{color}"></div>
          </div>
          <span class="maha-val">{score:.2f}</span>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>전북 주간 신호 브리핑 — {result["period_end"]}</title>
<style>
:root{{--bg:#f8f9fa;--card:#fff;--text:#212529;--muted:#6c757d;--border:#dee2e6;
      --purple:#534ab7;--teal:#0f6e56;--coral:#993c1d;--amber:#854f0b}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,sans-serif;background:var(--bg);color:var(--text);padding:20px;font-size:13px}}
.header{{background:var(--purple);color:#fff;padding:22px 28px;border-radius:12px;margin-bottom:18px}}
.header h1{{font-size:18px;font-weight:600}}
.header .sub{{opacity:.85;font-size:12px;margin-top:4px}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px}}
.card-title{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
             color:var(--muted);margin-bottom:14px}}
/* 핫 플레이스 */
.hot-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;
           padding:14px 16px;margin-bottom:10px}}
.hot-rank{{font-size:18px;margin-bottom:4px}}
.hot-muni{{font-size:20px;font-weight:600;color:var(--purple);margin-bottom:6px}}
.hot-score{{font-size:12px;color:var(--muted);margin-bottom:8px}}
.hot-score strong{{color:var(--text);font-size:14px}}
.maha{{margin-left:10px;font-size:11px;background:#eeedfe;color:#534ab7;
       padding:1px 6px;border-radius:8px}}
.pill{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;
       margin:2px;font-weight:500}}
.pill-up{{background:#fee2e2;color:#991b1b}}
.pill-down{{background:#e1f5ee;color:#085041}}
.hot-count{{font-size:11px;color:var(--muted);margin-top:6px}}
/* 핫 아이템 테이블 */
table{{width:100%;border-collapse:collapse}}
th{{font-size:11px;color:var(--muted);text-align:left;padding:6px 8px;
    border-bottom:2px solid var(--border)}}
td{{padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:middle}}
.pattern-label{{font-size:11px;font-weight:600;color:var(--purple)}}
.conf-bar{{height:6px;background:var(--bg);border-radius:3px;width:80px;
           display:inline-block;margin-right:6px;vertical-align:middle}}
.conf-fill{{height:100%;background:var(--purple);border-radius:3px}}
/* 학술 함의 */
.impl-block{{border-left:3px solid var(--purple);padding:10px 14px;margin-bottom:12px;
             background:var(--bg);border-radius:0 8px 8px 0}}
.impl-num{{font-size:10px;color:var(--purple);text-transform:uppercase;font-weight:600}}
.impl-pattern{{font-size:14px;font-weight:600;margin:3px 0}}
.impl-desc{{font-size:12px;color:var(--muted);margin-bottom:4px}}
.impl-theory{{font-size:11px;color:var(--teal)}}
/* 이상 신호 */
.anom-up{{color:#991b1b;font-weight:600}}
.anom-down{{color:#085041;font-weight:600}}
code{{font-size:11px;background:#f1efe8;padding:1px 5px;border-radius:4px}}
/* Mahalanobis */
.maha-row{{display:flex;align-items:center;gap:8px;margin-bottom:7px}}
.maha-muni{{font-size:12px;width:60px;flex-shrink:0}}
.maha-track{{flex:1;height:10px;background:var(--bg);border-radius:5px;overflow:hidden}}
.maha-fill{{height:100%;border-radius:5px}}
.maha-val{{font-size:11px;width:36px;text-align:right;color:var(--muted)}}
/* 데이터 소스 뱃지 */
.src-badge{{display:inline-block;font-size:10px;padding:2px 7px;border-radius:8px;
            margin:2px;background:#eeedfe;color:#534ab7}}
@media(max-width:700px){{.grid3,.grid2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="header">
  <h1>📡 전북 지역 주간 신호 브리핑</h1>
  <div class="sub">
    분석 기간: {result.get("period_end","")}&nbsp;|&nbsp;
    생성: {now_str}&nbsp;|&nbsp;
    전북 14개 시군 × {result["panel_shape"][1]}개 지표
    &nbsp;|&nbsp; 이상 감지: {result["anomaly_count"]}건
  </div>
</div>

<!-- 핫 플레이스 -->
<div class="card" style="margin-bottom:16px">
  <div class="card-title">🔥 이번 주 핫 플레이스 (이상 신호 + 장소 활성도 종합)</div>
  <div class="grid3">{place_cards}</div>
</div>

<div class="grid2">
  <!-- 핫 아이템 -->
  <div class="card">
    <div class="card-title">⚡ 핫 아이템 — 지표 조합 패턴</div>
    <table>
      <thead><tr><th>패턴</th><th>시군</th><th>감지 지표</th><th>신뢰도</th><th>해석</th></tr></thead>
      <tbody>{item_rows if item_rows else "<tr><td colspan='5' style='color:var(--muted);padding:12px'>이번 주 유의한 패턴 없음</td></tr>"}</tbody>
    </table>
  </div>

  <!-- 다변량 이상 스코어 -->
  <div class="card">
    <div class="card-title">📐 다변량 이상 스코어 (Mahalanobis 거리)</div>
    {maha_bars}
    <p style="font-size:10px;color:var(--muted);margin-top:10px">
      전체 지표의 평균 패턴 대비 얼마나 이탈했는지 측정 — 높을수록 이상 신호 강함
    </p>
  </div>
</div>

<!-- 개별 이상 신호 -->
<div class="card" style="margin-bottom:16px">
  <div class="card-title">📊 지표별 이상 신호 (|z| ≥ 1.5)</div>
  <table>
    <thead><tr><th>시군</th><th>지표</th><th>관측값</th><th>z-score</th></tr></thead>
    <tbody>{anom_rows if anom_rows else "<tr><td colspan='4' style='color:var(--muted);padding:12px'>이번 주 이상 신호 없음</td></tr>"}</tbody>
  </table>
</div>

<!-- 학술 함의 -->
<div class="card" style="margin-bottom:16px">
  <div class="card-title">🎓 학술적 함의 초안 (연구자 검토 필요)</div>
  {implications}
</div>

<!-- 수집 소스 -->
<div class="card">
  <div class="card-title">📡 수집 데이터 소스</div>
  <div style="margin-bottom:8px">
    <span class="src-badge">소상공인 상권API</span>
    <span class="src-badge">식약처 음식점 인허가</span>
    <span class="src-badge">KOSIS 인구이동</span>
    <span class="src-badge">에어코리아</span>
    <span class="src-badge">HIRA 의료기관</span>
    <span class="src-badge">카카오 로컬</span>
    <span class="src-badge">네이버 지역검색</span>
    <span class="src-badge">TourAPI</span>
    <span class="src-badge">빅카인즈</span>
  </div>
  <p style="font-size:11px;color:var(--muted)">
    API 키 미연결 소스는 현실적 Mock 데이터로 대체됨.
    분석 방법: z-score 이상탐지 + Mahalanobis 다변량 거리 + 패턴 규칙 매칭
  </p>
</div>

</body>
</html>"""

    path = os.path.join(REPORT_PATH, f"briefing_{result['period_end']}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"  [리포트] 저장 → {path}")
    return path
