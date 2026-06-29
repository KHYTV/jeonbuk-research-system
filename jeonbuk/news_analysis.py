"""
news_analysis.py - 수집 뉴스 구조적 토픽모델링(STM 스타일) + 지역 드릴다운.

전체 코퍼스에 NMF 토픽모델을 적합한 뒤, '지역'을 공변량으로 보고
토픽 prevalence가 시군별로 어떻게 다른지를 분해한다(R의 stm 패키지가 하는
covariate-prevalence 분석의 파이썬 근사). 결과:

  - 전체: 토픽 K개(대표어 + 비중), 시군별 기사량
  - 지역별: 그 시군을 언급한 기사들의 토픽 분포 / 상위 키워드 / 대표 헤드라인

산출 JSON을 웹(news.html)이 읽어 '지역 클릭 → 지역 뉴스 빅데이터 분석'을 그린다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from . import config as C
from .topics import _tokenize   # 한국어 조사/어미 제거 토크나이저 재사용

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "pipeline" / "data" / "jeonbuk.db"

# 시군명 → 표준 시군 (태깅용 짧은 이름)
REGION_KEYS = {m.replace("시", "").replace("군", ""): m for m in C.REGIONS}


def _tag_regions(text: str) -> list[str]:
    """기사 텍스트에 언급된 시군 목록(복수 가능)."""
    return [full for short, full in REGION_KEYS.items() if short in text]


def load_news(real_only: bool = True) -> list[dict]:
    """DB에서 뉴스 적재 (+ 지역 태깅)."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = "SELECT title, content, publisher, published_at, source FROM news"
    if real_only:
        q += " WHERE source NOT LIKE '%mock%'"
    rows = conn.execute(q).fetchall()
    conn.close()
    out = []
    for r in rows:
        title = re.sub(r"&[a-z]+;|<[^>]+>", " ", r["title"] or "")
        body = re.sub(r"&[a-z]+;|<[^>]+>", " ", r["content"] or "")
        text = f"{title} {body}".strip()
        out.append({
            "title": title, "text": text,
            "publisher": r["publisher"] or r["source"],
            "published": (r["published_at"] or "")[:10],
            "regions": _tag_regions(text),
        })
    return out


def analyze(n_topics: int = 6, top_terms: int = 8) -> dict:
    """전체 구조적 토픽모델링 + 지역별 분해."""
    docs = load_news(real_only=True)
    texts = [d["text"] for d in docs if d["text"].strip()]
    if len(texts) < 5:
        return {"n_docs": len(texts), "topics": [], "regions": {}, "region_activity": {}}

    vec = TfidfVectorizer(tokenizer=_tokenize, lowercase=False, token_pattern=None,
                          max_df=0.9, min_df=2, ngram_range=(1, 1))
    X = vec.fit_transform(texts)
    vocab = vec.get_feature_names_out()

    k = max(2, min(n_topics, X.shape[0] - 1, X.shape[1]))
    nmf = NMF(n_components=k, init="nndsvda", random_state=0, max_iter=500)
    W = nmf.fit_transform(X)            # 문서 × 토픽
    H = nmf.components_                 # 토픽 × 단어

    # 전체 토픽 정의
    mass = W.sum(axis=0)
    total_mass = mass.sum() or 1.0
    topics = []
    for ti in range(k):
        terms = [vocab[i] for i in H[ti].argsort()[::-1][:top_terms]]
        topics.append({"id": ti, "keywords": terms,
                       "weight": round(float(mass[ti] / total_mass), 3)})
    # 비중 내림차순으로 토픽 재정렬 + 라벨(대표어 2개)
    order = sorted(range(k), key=lambda t: -mass[t])
    topics = [topics[t] for t in order]
    for rank, t in enumerate(topics):
        t["rank"] = rank + 1
        t["label"] = " · ".join(t["keywords"][:2])
    remap = {old: new for new, old in enumerate(order)}  # 원 토픽idx → 정렬 후 idx

    # 지역별 분해 (STM covariate-prevalence 근사)
    doc_sum = X.sum(axis=1).A1                      # 문서별 TF-IDF 총합(키워드 산정용)
    region_docs: dict[str, list[int]] = {m: [] for m in C.REGIONS}
    valid_idx = [i for i, d in enumerate(docs) if d["text"].strip()]
    for new_i, orig_i in enumerate(valid_idx):
        for m in docs[orig_i]["regions"]:
            region_docs[m].append(new_i)

    regions = {}
    region_activity = {}
    for m, idxs in region_docs.items():
        region_activity[m] = len(idxs)
        if not idxs:
            continue
        # 지역 토픽 분포(평균 W) → 정렬 후 토픽 순서로
        wmean = W[idxs].mean(axis=0)
        dist = [0.0] * k
        for old_t in range(k):
            dist[remap[old_t]] = float(wmean[old_t])
        s = sum(dist) or 1.0
        dist = [round(x / s, 3) for x in dist]
        # 지역 상위 키워드(해당 문서들 TF-IDF 합)
        sub = X[idxs].sum(axis=0).A1
        kw = [vocab[i] for i in sub.argsort()[::-1][:8]]
        # 대표 헤드라인(최대 토픽 loading 상위)
        scored = sorted(idxs, key=lambda i: -W[i].max())
        heads = []
        seen = set()
        for i in scored:
            t = docs[valid_idx[i]]["title"]
            if t and t not in seen:
                seen.add(t)
                heads.append({"title": t, "publisher": docs[valid_idx[i]]["publisher"]})
            if len(heads) >= 6:
                break
        regions[m] = {"n_docs": len(idxs), "topic_dist": dist,
                      "keywords": kw, "headlines": heads}

    return {
        "n_docs": len(texts), "n_topics": len(topics),
        "topics": topics, "regions": regions, "region_activity": region_activity,
    }


def save(result: dict, week: str) -> str:
    p = C.OUTPUT_DIR / f"news_analysis_{week}.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


_NEWS_PAT = re.compile(r"const NEWS = \{.*?\};", re.DOTALL)

def build_page(result: dict) -> str:
    """news.html 의 `const NEWS = {};` 를 분석결과로 주입 + docs 동기화."""
    html_path = C.BASE_DIR / "web" / "news.html"
    html = html_path.read_text(encoding="utf-8")
    data = json.dumps(result, ensure_ascii=False)
    html = _NEWS_PAT.sub(lambda _: f"const NEWS = {data};", html, count=1)
    html_path.write_text(html, encoding="utf-8")
    # GitHub Pages 용 docs 동기화
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "news.html").write_text(html, encoding="utf-8")
    return str(html_path)
