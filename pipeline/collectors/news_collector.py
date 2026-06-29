import os
"""
뉴스 통합 수집기 (빅카인즈 없는 버전)
─────────────────────────────────────────────────
우선순위:
  1순위 네이버 뉴스 API     — API 키 있으면 즉시 연결, 무료 25,000건/일
  2순위 RSS 크롤링          — 연합뉴스·전북일보·KBS전주 등 키 불필요
  3순위 전북도청 보도자료   — 정책 맥락 보완
  4순위 Mock               — 위 전부 실패 시 폴백

네이버 API 발급: https://developers.naver.com → 애플리케이션 등록 → 뉴스 검색
"""
import requests, time, json, re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYS, MUNICIPALITIES
from utils import get_db, get_logger, log_collect

log = get_logger("NewsCollector")

# ── RSS 소스 목록 (API 키 불필요) ─────────────
RSS_SOURCES = [
    # 전국 통신사
    {"name": "연합뉴스",    "url": "https://www.yna.co.kr/rss/all.xml",         "region": "전국"},
    {"name": "뉴스1",       "url": "https://www.news1.kr/rss/section/100.xml",   "region": "전국"},
    # 전북 지역 언론
    {"name": "전북일보",    "url": "https://www.jjan.kr/rss/allArticle.xml",     "region": "전북"},
    {"name": "새전북신문",  "url": "https://www.sjbnews.com/rss/rss.php",        "region": "전북"},
    {"name": "전라일보",    "url": "https://www.jeollailbo.com/rss/allArticle.xml", "region": "전북"},
    {"name": "전북도민일보","url": "https://www.domin.co.kr/rss/allArticle.xml", "region": "전북"},
    # 지역 방송
    {"name": "KBS전주",     "url": "https://www.kbs.co.kr/rss/jeonju/news.xml",  "region": "전북"},
    {"name": "MBC전북",     "url": "https://www.jmbc.co.kr/rss/rss.xml",        "region": "전북"},
    # 전북도청 보도자료
    {"name": "전북도청",    "url": "https://www.jeonbuk.go.kr/board/rss.jeonbuk?boardId=BBS_0000061", "region": "전북"},
]

# ── 지역 키워드 ────────────────────────────────
JEONBUK_KEYWORDS = [
    "전북", "전라북도", "전주", "군산", "익산", "정읍", "남원", "김제",
    "완주", "진안", "무주", "장수", "임실", "순창", "고창", "부안",
    "새만금", "지방소멸", "전북특별자치도",
]

TOPIC_KEYWORDS = [
    "지역경제", "소상공인", "창업", "폐업", "인구", "청년", "귀농귀촌",
    "맛집", "핫플", "관광", "축제", "대기질", "미세먼지", "의료", "복지",
    "고용", "실업", "산업단지", "부동산", "환경",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


# ══════════════════════════════════════════════
# 유틸: 시군 감지 + DB 저장
# ══════════════════════════════════════════════
def _detect_municipality(text: str) -> str:
    for muni in MUNICIPALITIES:
        short = muni.replace("시","").replace("군","")
        if muni in text or short in text:
            return muni
    return "전북"

def _is_relevant(title: str, content: str = "") -> bool:
    """전북 관련 기사인지 판별"""
    combined = title + " " + content
    return any(kw in combined for kw in JEONBUK_KEYWORDS)

def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]

def _save_articles(articles: List[Dict]) -> int:
    if not articles:
        return 0
    conn = get_db()
    n = 0
    for art in articles:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO news
                (source, article_id, title, content, publisher, municipality, published_at)
                VALUES (?,?,?,?,?,?,?)
            """, (art["source"], art["article_id"], art["title"],
                  art.get("content",""), art["publisher"],
                  art.get("municipality","전북"), art.get("published_at","")))
            n += 1
        except Exception as e:
            log.debug(f"  저장 오류: {e}")
    conn.commit(); conn.close()
    return n


# ══════════════════════════════════════════════
# 1순위: 네이버 뉴스 API
# ══════════════════════════════════════════════
def collect_naver_news(run_id: str) -> int:
    """
    네이버 뉴스 검색 API
    발급: https://developers.naver.com → 애플리케이션 등록 → 검색 API
    무료: 25,000건/일
    """
    if not (KEYS["NAVER_ID"] and KEYS["NAVER_SEC"]):
        log.info("  [네이버 뉴스] API 키 없음 → RSS로 폴백")
        return 0

    t0 = time.time()
    headers = {
        "X-Naver-Client-Id":     KEYS["NAVER_ID"],
        "X-Naver-Client-Secret": KEYS["NAVER_SEC"],
    }
    url = "https://openapi.naver.com/v1/search/news.json"

    articles = []
    # 전북 관련 핵심 키워드 조합
    queries = [
        f"전북 {kw}" for kw in ["지역경제", "소상공인", "인구", "관광", "맛집", "축제", "환경", "복지"]
    ] + ["전북특별자치도", "새만금", "지방소멸 전북"]

    for query in queries:
        params = {"query": query, "display": 20, "sort": "date"}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=8)
            r.raise_for_status()
            items = r.json().get("items", [])
            for item in items:
                title   = _clean_html(item.get("title",""))
                content = _clean_html(item.get("description",""))
                if not _is_relevant(title, content):
                    continue
                pub_date = item.get("pubDate","")
                # RFC 날짜 → YYYY-MM-DD 변환
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
                except:
                    pub_date = datetime.now().strftime("%Y-%m-%d")

                articles.append({
                    "source":       "naver",
                    "article_id":   item.get("link","")[-30:],
                    "title":        title,
                    "content":      content,
                    "publisher":    item.get("originallink","").split("/")[2] if item.get("originallink") else "네이버",
                    "municipality": _detect_municipality(title + " " + content),
                    "published_at": pub_date,
                })
            time.sleep(0.1)
        except Exception as e:
            log.warning(f"  네이버 API 오류 ({query}): {e}")

    n = _save_articles(articles)
    log_collect(run_id, "naver_news", "ok", n, duration=time.time()-t0)
    log.info(f"  [네이버 뉴스] ok — {n}건")
    return n


# ══════════════════════════════════════════════
# 2순위: RSS 멀티소스 크롤링
# ══════════════════════════════════════════════
def collect_rss(run_id: str) -> int:
    """RSS 피드 직접 수집 — 전북 지역 언론 + 연합뉴스"""
    t0 = time.time()
    articles = []
    success_sources = []
    fail_sources = []

    for src in RSS_SOURCES:
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=8)
            if r.status_code != 200:
                fail_sources.append(f"{src['name']}({r.status_code})")
                continue

            soup = BeautifulSoup(r.content, "lxml-xml")
            items = soup.find_all("item")
            if not items:
                fail_sources.append(f"{src['name']}(0건)")
                continue

            count = 0
            for item in items[:30]:
                title_tag   = item.find("title")
                content_tag = item.find("description") or item.find("content")
                link_tag    = item.find("link")
                date_tag    = item.find("pubDate") or item.find("dc:date")

                title   = _clean_html(title_tag.text if title_tag else "")
                content = _clean_html(content_tag.text if content_tag else "")
                link    = link_tag.text.strip() if link_tag else ""
                pub_str = date_tag.text.strip() if date_tag else ""

                # 날짜 파싱
                try:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(pub_str).strftime("%Y-%m-%d")
                except:
                    try:
                        pub_date = datetime.strptime(pub_str[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                    except:
                        pub_date = datetime.now().strftime("%Y-%m-%d")

                # 전북 지역 언론은 전부 저장, 전국 언론은 키워드 필터
                if src["region"] == "전국" and not _is_relevant(title, content):
                    continue

                articles.append({
                    "source":       f"rss_{src['name']}",
                    "article_id":   link[-40:] if link else f"{src['name']}_{hash(title)}",
                    "title":        title,
                    "content":      content,
                    "publisher":    src["name"],
                    "municipality": _detect_municipality(title + " " + content),
                    "published_at": pub_date,
                })
                count += 1

            success_sources.append(f"{src['name']}({count}건)")
        except Exception as e:
            fail_sources.append(f"{src['name']}({type(e).__name__})")
            log.debug(f"  RSS 오류 [{src['name']}]: {e}")

    n = _save_articles(articles)
    elapsed = time.time() - t0
    log_collect(run_id, "rss", "ok" if success_sources else "error", n,
                f"성공:{','.join(success_sources)} | 실패:{','.join(fail_sources)}", elapsed)

    if success_sources:
        log.info(f"  [RSS] 성공: {', '.join(success_sources)}")
    if fail_sources:
        log.warning(f"  [RSS] 실패: {', '.join(fail_sources)}")
    log.info(f"  [RSS] 총 {n}건 저장")
    return n


# ══════════════════════════════════════════════
# 3순위: 전북도청 보도자료 웹 크롤링
# ══════════════════════════════════════════════
def collect_jeonbuk_gov(run_id: str) -> int:
    """전북도청 공식 보도자료 스크래핑"""
    t0 = time.time()
    articles = []

    urls = [
        ("전북도청_보도자료", "https://www.jeonbuk.go.kr/board/list.jeonbuk?boardId=BBS_0000061"),
        ("전북도청_공지", "https://www.jeonbuk.go.kr/board/list.jeonbuk?boardId=BBS_0000001"),
    ]

    for pub_name, url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200:
                log.warning(f"  [{pub_name}] {r.status_code}")
                continue
            soup = BeautifulSoup(r.content, "html.parser")
            # 게시판 형태별 선택자 탐색
            selectors = [
                ".board-list tbody tr",
                "table.bbs-list tbody tr",
                ".list-body .item",
                "ul.board_list li",
            ]
            rows = []
            for sel in selectors:
                rows = soup.select(sel)
                if rows:
                    break

            for row in rows[:20]:
                a_tag = row.find("a")
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                href  = a_tag.get("href","")
                if not title or len(title) < 5:
                    continue
                articles.append({
                    "source":       "gov_jeonbuk",
                    "article_id":   href[-30:] or f"gov_{hash(title)}",
                    "title":        title,
                    "content":      "",
                    "publisher":    pub_name,
                    "municipality": _detect_municipality(title),
                    "published_at": datetime.now().strftime("%Y-%m-%d"),
                })
            log.info(f"  [{pub_name}] {len(rows)}건 파싱")
        except Exception as e:
            log.warning(f"  [{pub_name}] 오류: {e}")

    n = _save_articles(articles)
    log_collect(run_id, "gov_jeonbuk", "ok" if articles else "error", n, duration=time.time()-t0)
    log.info(f"  [전북도청] {n}건")
    return n


# ══════════════════════════════════════════════
# 4순위: Mock (위 전부 실패 시)
# ══════════════════════════════════════════════
def collect_mock_news(run_id: str, real_collected: int) -> int:
    """실제 수집이 0건일 때만 Mock 실행"""
    if real_collected > 0:
        return 0

    log.info("  [Mock 뉴스] 실제 수집 0건 → Mock 생성")
    articles = []
    templates = [
        ("{muni} 지역경제 동향 — 소상공인 창업 증가세",          "경제"),
        ("{muni} 인구 유입 현황 — 청년층 이동 패턴 분석",         "인구"),
        ("{muni} 관광 활성화 — 지역 맛집·축제 방문객 증가",       "문화"),
        ("{muni} 환경 지표 — 대기질 개선 노력 현황",              "환경"),
        ("{muni} 복지 사각지대 발굴 — 긴급복지지원 현황",         "복지"),
    ]
    munis = list(MUNICIPALITIES.keys())

    import random; random.seed(42)
    publishers = ["전북일보","새전북신문","전라일보","연합뉴스","KBS전주"]

    for i, (tmpl, cat) in enumerate(templates):
        for j, muni in enumerate(munis[:6]):
            articles.append({
                "source":       "mock_news",
                "article_id":   f"MOCK_{cat}_{muni[:2]}_{i}_{j}",
                "title":        tmpl.format(muni=muni),
                "content":      f"{muni} 지역의 {cat} 관련 최신 동향을 전합니다.",
                "publisher":    random.choice(publishers),
                "municipality": muni,
                "published_at": (datetime.now() - timedelta(days=j)).strftime("%Y-%m-%d"),
            })

    n = _save_articles(articles)
    log_collect(run_id, "mock_news", "mock", n)
    return n


# ══════════════════════════════════════════════
# 통합 실행 진입점
# ══════════════════════════════════════════════
def collect_all_news(run_id: str) -> int:
    """
    뉴스 수집 우선순위 실행:
    네이버 API → RSS → 전북도청 → Mock(폴백)
    """
    log.info("\n  [뉴스수집] 멀티소스 수집 시작")
    total = 0

    # 1순위: 네이버 API
    n = collect_naver_news(run_id)
    total += n

    # 2순위: RSS (네이버 결과와 중복 IGNORE)
    n = collect_rss(run_id)
    total += n

    # 3순위: 전북도청
    n = collect_jeonbuk_gov(run_id)
    total += n

    # 4순위: Mock (위 전부 실패했을 때만)
    n = collect_mock_news(run_id, total)
    total += n

    log.info(f"  [뉴스수집] 완료 — 총 {total}건 (중복 제외)")
    return total


# ══════════════════════════════════════════════
# 수집 결과 조회 헬퍼 (분석 엔진에서 사용)
# ══════════════════════════════════════════════
def get_news_summary(days_back: int = 7) -> Dict:
    """수집된 뉴스의 시군별·키워드별 요약 반환"""
    conn = get_db()
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # 시군별 기사 수
    muni_counts = {r[0]: r[1] for r in conn.execute("""
        SELECT municipality, COUNT(*) FROM news
        WHERE collected_at >= ? GROUP BY municipality
    """, (since,)).fetchall()}

    # 언론사별 기사 수
    pub_counts = {r[0]: r[1] for r in conn.execute("""
        SELECT publisher, COUNT(*) FROM news
        WHERE collected_at >= ? GROUP BY publisher ORDER BY 2 DESC LIMIT 10
    """, (since,)).fetchall()}

    # 소스별 현황
    src_counts = {r[0]: r[1] for r in conn.execute("""
        SELECT source, COUNT(*) FROM news
        WHERE collected_at >= ? GROUP BY source
    """, (since,)).fetchall()}

    # 키워드 빈도 (제목 기반)
    titles = [r[0] for r in conn.execute("""
        SELECT title FROM news WHERE collected_at >= ?
    """, (since,)).fetchall()]

    keyword_freq = {}
    for kw in TOPIC_KEYWORDS:
        cnt = sum(1 for t in titles if kw in t)
        if cnt > 0:
            keyword_freq[kw] = cnt

    # 최근 기사 5건
    recent = [{
        "title":   r[0], "publisher": r[1],
        "muni":    r[2], "date":      r[3], "source": r[4]
    } for r in conn.execute("""
        SELECT title, publisher, municipality, published_at, source
        FROM news WHERE collected_at >= ?
        ORDER BY collected_at DESC LIMIT 5
    """, (since,)).fetchall()]

    conn.close()
    return {
        "total":         sum(muni_counts.values()),
        "by_muni":       muni_counts,
        "by_publisher":  pub_counts,
        "by_source":     src_counts,
        "keyword_freq":  dict(sorted(keyword_freq.items(), key=lambda x:x[1], reverse=True)),
        "recent":        recent,
    }
