"""
news.py - 뉴스 맥락 수집 (네이버 / 빅카인즈 / 오프라인 mock).

이상신호(시군 + 핫아이템 + 그 주)로부터 검색 쿼리를 자동 생성해
관련 기사를 모은다. 단순 크롤링이 아니라 '신호 기반 질의'가 핵심.

  - NaverProvider   : 즉시 발급·무료. 제목+요약 스니펫만(본문 없음).
  - BigKindsProvider: 승인·유료(2025~). 본문 전문 + 개체명/지역분류.
  - MockProvider    : 오프라인 검증용. 핫아이템 키워드로 그럴듯한 헤드라인 생성.

공통 반환 형식(Article):
  title / body / source / published(YYYY-MM-DD) / url
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config as C

try:
    import requests
    _HAS_REQUESTS = True
except Exception:
    _HAS_REQUESTS = False


@dataclass
class Article:
    title: str
    body: str
    source: str
    published: str
    url: str = ""

    @property
    def text(self) -> str:
        """토픽모델링 입력용 텍스트(제목 + 본문)."""
        return f"{self.title} {self.body}".strip()


# ─────────────────────────────────────────────────────────────────────────────
#  신호 → 검색 쿼리
# ─────────────────────────────────────────────────────────────────────────────
def build_query(region: str, hot_items: list[str]) -> str:
    """
    시군명 + 핫아이템 지표를 일상 검색어로 확장해 OR 결합.
    예: 군산시 + [카드매출지수, 폐업수] → "군산 (소비 OR 매출 OR 상권 OR 폐업 OR 폐점)"
    """
    region_kw = region.replace("시", "").replace("군", "")
    terms: list[str] = []
    for ind in hot_items:
        terms.extend(C.INDICATOR_KEYWORDS.get(ind, [ind]))
    seen, uniq = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return f"{region_kw} ({' OR '.join(uniq)})" if uniq else region_kw


def _window(week: str) -> tuple[str, str]:
    """신호 주 기준 ± NEWS_WINDOW_DAYS 의 (from, until) 날짜."""
    d = datetime.strptime(week, "%Y-%m-%d")
    lo = (d - timedelta(days=C.NEWS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    hi = (d + timedelta(days=C.NEWS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    return lo, hi


# ─────────────────────────────────────────────────────────────────────────────
#  Providers
# ─────────────────────────────────────────────────────────────────────────────
class NaverProvider:
    """네이버 뉴스 검색 API. 본문 없음(제목+요약 스니펫)."""

    ENDPOINT = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self) -> None:
        self.cid = os.getenv("NAVER_CLIENT_ID", "")
        self.csecret = os.getenv("NAVER_CLIENT_SECRET", "")

    def available(self) -> bool:
        return _HAS_REQUESTS and bool(self.cid and self.csecret)

    def search(self, query: str, week: str, limit: int) -> list[Article]:
        import re
        headers = {"X-Naver-Client-Id": self.cid, "X-Naver-Client-Secret": self.csecret}
        params = {"query": query, "display": min(limit, 100), "sort": "sim"}
        r = requests.get(self.ENDPOINT, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        tag = re.compile(r"<[^>]+>")
        out: list[Article] = []
        for it in r.json().get("items", []):
            pub = it.get("pubDate", "")
            try:
                pub = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d")
            except Exception:
                pub = week
            out.append(Article(
                title=tag.sub("", it.get("title", "")),
                body=tag.sub("", it.get("description", "")),
                source="naver", published=pub, url=it.get("originallink", ""),
            ))
        return out


class BigKindsProvider:
    """빅카인즈 Open API. 본문 전문 + 메타데이터(지역/개체명)."""

    ENDPOINT = "https://tools.kinds.or.kr/search/news"

    def __init__(self) -> None:
        self.key = os.getenv("BIGKINDS_API_KEY", "")

    def available(self) -> bool:
        return _HAS_REQUESTS and bool(self.key)

    def search(self, query: str, week: str, limit: int) -> list[Article]:
        lo, hi = _window(week)
        payload = {
            "access_key": self.key,
            "argument": {
                "query": query,
                "published_at": {"from": lo, "until": hi},
                "sort": {"date": "desc"},
                "return_from": 0, "return_size": min(limit, 100),
                "fields": ["title", "content", "published_at", "provider", "provider_link_page"],
            },
        }
        r = requests.post(self.ENDPOINT, json=payload, timeout=15)
        r.raise_for_status()
        docs = r.json().get("return_object", {}).get("documents", [])
        out: list[Article] = []
        for d in docs:
            pub = (d.get("published_at", "") or week)[:10]
            out.append(Article(
                title=d.get("title", ""),
                body=d.get("content", ""),
                source=d.get("provider", "bigkinds"),
                published=pub, url=d.get("provider_link_page", ""),
            ))
        return out


class MockProvider:
    """오프라인 검증용. 핫아이템 키워드로 그럴듯한 헤드라인/본문을 합성."""

    _TEMPLATES = [
        ("{kw} 관련 {region} 지역 동향 분석", "최근 {region} 일대에서 {kw} 변화가 관측되고 있다. 지자체와 상공계는 원인 파악에 나섰다."),
        ("{region} {kw} 급변… 지역경제 영향 주목", "{kw} 지표가 평소와 다른 움직임을 보이며 {region} 주민·업계의 관심이 커지고 있다."),
        ("[현장] {region}, {kw} 변화의 배경은", "전문가들은 {kw} 흐름이 인근 산업·고용과 맞물려 나타난 현상일 수 있다고 진단했다."),
    ]

    def available(self) -> bool:
        return True

    def search(self, query: str, week: str, limit: int) -> list[Article]:
        region = query.split(" ")[0]
        # 쿼리 괄호 안의 키워드 추출
        kws = []
        if "(" in query:
            kws = [k.strip() for k in query[query.find("(") + 1:query.rfind(")")].split("OR")]
        kws = kws or ["지역경제"]
        out: list[Article] = []
        i = 0
        while len(out) < limit:
            kw = kws[i % len(kws)]
            t, b = self._TEMPLATES[i % len(self._TEMPLATES)]
            out.append(Article(
                title=t.format(kw=kw, region=region),
                body=b.format(kw=kw, region=region),
                source="mock", published=week,
                url=f"https://example.com/news/{i}",
            ))
            i += 1
        return out


def get_provider(name: str | None = None):
    name = name or C.NEWS_PROVIDER
    if name == "naver":
        p = NaverProvider()
    elif name == "bigkinds":
        p = BigKindsProvider()
    else:
        return MockProvider()
    return p if p.available() else MockProvider()  # 키 없으면 자동 mock 폴백


def collect(region: str, hot_items: list[str], week: str,
            provider: str | None = None) -> list[Article]:
    """한 핫 플레이스에 대한 뉴스 맥락을 수집."""
    q = build_query(region, hot_items)
    p = get_provider(provider)
    try:
        arts = p.search(q, week, C.NEWS_MAX_ARTICLES)
    except Exception as e:
        print(f"[news] {region} 수집 실패({type(p).__name__}): {e} → mock 폴백")
        arts = MockProvider().search(q, week, C.NEWS_MAX_ARTICLES)
    return arts[: C.NEWS_MAX_ARTICLES]
