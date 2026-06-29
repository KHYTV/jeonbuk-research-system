"""
run_brief.py - 주간 신호 → 뉴스 수집 → 토픽모델링 → LLM 분석기사 전체 파이프라인.

  탐지(detector/causal) → 뉴스(news) → 토픽(topics) → 기사(article)

사용법
  # 오프라인 검증 (합성 신호 + mock 뉴스 + 템플릿 기사)
  python -m jeonbuk.run_brief --demo

  # 실데이터 + 실제 뉴스/LLM (환경변수 설정 시 자동 사용)
  python -m jeonbuk.run_brief --input data/panel.csv --provider naver
"""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from . import article as article_mod
from . import config as C
from . import news as news_mod
from . import topics as topics_mod
from .data import all_weeks, load_long, make_synthetic
from .report import build_weekly


def run(long_df: pd.DataFrame, week: pd.Timestamp, provider: str | None) -> dict:
    week_str = str(pd.Timestamp(week).date())
    report = build_weekly(long_df, week)
    briefs = []

    for hp in report["hot_places"]:
        region = hp["region"]
        items = [it["indicator"] for it in hp["hot_items"]]
        print(f"[{region}] 뉴스 수집…")
        arts = news_mod.collect(region, items, week_str, provider=provider)
        topic = topics_mod.analyze([a.text for a in arts], n_topics=5)
        print(f"[{region}] 기사 {len(arts)}건 · 키워드: {topic.keyword_line(6)}")
        print(f"[{region}] 분석기사 작성…")
        art = article_mod.write(hp, topic, week_str)

        briefs.append({
            "region": region,
            "n_articles": len(arts),
            "top_keywords": [w for w, _ in topic.top_keywords],
            "topics": [{"rank": t.rank, "weight": round(t.weight, 3),
                        "keywords": t.keywords} for t in topic.topics],
            "article_title": art.title,
            "article_body": art.body,
            "article_model": art.model,
            "sources": [{"title": a.title, "source": a.source,
                         "published": a.published, "url": a.url} for a in arts[:8]],
        })

    out = {"week": week_str, "n_hot_places": len(briefs), "briefs": briefs}
    return out


def save(brief: dict) -> tuple[str, str]:
    week = brief["week"]
    jp = C.OUTPUT_DIR / f"brief_{week}.json"
    mp = C.OUTPUT_DIR / f"brief_{week}.md"
    jp.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    L = [f"# 전북 주간 분석 브리프 — {week}", ""]
    for b in brief["briefs"]:
        L.append(f"> 🔥 {b['region']} · 뉴스 {b['n_articles']}건 · "
                 f"키워드: {', '.join(b['top_keywords'][:6])} · 모델: {b['article_model']}")
        L.append("")
        L.append(b["article_body"])
        L.append("\n---\n")
    mp.write_text("\n".join(L), encoding="utf-8")
    return str(jp), str(mp)


def main() -> None:
    ap = argparse.ArgumentParser(description="전북 주간 신호 → 토픽 → LLM 분석기사")
    ap.add_argument("--input", help="long-format 패널 (CSV/Excel)")
    ap.add_argument("--week", help="대상 주 (YYYY-MM-DD)")
    ap.add_argument("--provider", choices=["naver", "bigkinds", "mock"], help="뉴스 소스")
    ap.add_argument("--demo", action="store_true", help="합성 데이터로 실행")
    args = ap.parse_args()

    demo_idx = 70
    if args.demo or not args.input:
        print("[demo] 합성 패널 + mock 뉴스 + (키 없으면) 템플릿 기사")
        long_df = make_synthetic(inject_week_idx=demo_idx)
        week = pd.Timestamp(all_weeks(long_df)[demo_idx])
        provider = args.provider or "mock"
    else:
        long_df = load_long(args.input)
        weeks = all_weeks(long_df)
        week = pd.Timestamp(args.week) if args.week else pd.Timestamp(weeks[-1])
        provider = args.provider

    brief = run(long_df, week, provider)
    jp, mp = save(brief)
    print(f"\n핫 플레이스 {brief['n_hot_places']}곳 브리프 생성.\n저장됨:\n  {jp}\n  {mp}")


if __name__ == "__main__":
    main()
