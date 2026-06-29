import os
"""
생활문화 장소 통합 수집기
─────────────────────────────────────────────────
소스:
  카카오 로컬 API  — 음식점·카페·관광명소 좌표+리뷰수
  네이버 지역검색  — 블로그 언급수 기반 화제성
  TourAPI          — 공식 관광지·음식점·행사 정보
  소상공인 상가DB  — 업소 현황·신규등록 베이스라인
"""
import requests, json, time, random, math
from datetime import datetime, timedelta
from typing import List, Dict
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYS, ENDPOINTS, MUNICIPALITIES, KAKAO_CATEGORIES, TOUR_CONTENT_TYPES
from utils import get_db, get_logger, log_collect

log = get_logger("CultureCollector")

# ── 공통 요청 ─────────────────────────────────
def _get(url, params=None, headers=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"  HTTP 오류: {url[:60]}… → {e}")
        return None

def _save_places(places: List[Dict]) -> int:
    if not places:
        return 0
    conn = get_db()
    n = 0
    for p in places:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO places
                (source,place_id,name,category,sub_category,municipality,
                 address,lat,lon,phone,status,open_date,review_count,meta_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (p["source"], p.get("place_id",""), p["name"],
                  p.get("category",""), p.get("sub_category",""),
                  p.get("municipality",""), p.get("address",""),
                  p.get("lat"), p.get("lon"), p.get("phone",""),
                  p.get("status","open"), p.get("open_date"),
                  p.get("review_count",0),
                  json.dumps(p.get("meta",{}), ensure_ascii=False)))
            n += 1
        except Exception as e:
            log.debug(f"  장소 저장 오류: {e}")
    conn.commit(); conn.close()
    return n

# ── Mock 장소 생성 ────────────────────────────
_FOOD_TYPES = ["한식당","순대국밥","비빔밥","막걸리집","카페","베이커리",
               "전통시장","갈비집","회센터","두부요리","청국장"]
_ATTRACTIONS = ["전통시장","문화원","생태공원","출렁다리","둘레길","한옥마을",
                "수목원","폭포","박물관","체험농장"]

def _mock_places(muni: str, n_food=8, n_attr=4) -> List[Dict]:
    meta = MUNICIPALITIES[muni]
    lat0, lon0 = meta["lat"], meta["lon"]
    places = []
    for i in range(n_food):
        jitter_lat = lat0 + random.uniform(-0.03, 0.03)
        jitter_lon = lon0 + random.uniform(-0.04, 0.04)
        ft = random.choice(_FOOD_TYPES)
        suffix = f"{random.choice(['원조','할머니','신','본가','정통','옛날'])} {ft}"
        reviews = int(random.expovariate(1/80))  # 롱테일 분포
        places.append({
            "source": "kakao_mock",
            "place_id": f"KM_{muni[:2]}_F{i:03d}",
            "name": f"{muni[:2]} {suffix}",
            "category": "음식점", "sub_category": ft,
            "municipality": muni,
            "address": f"전북 {muni} 중앙로 {random.randint(10,300)}",
            "lat": jitter_lat, "lon": jitter_lon,
            "review_count": reviews,
            "status": "open",
            "meta": {"mock": True, "rating": round(random.uniform(3.5,5.0),1)},
        })
    for i in range(n_attr):
        at = random.choice(_ATTRACTIONS)
        places.append({
            "source": "tour_mock",
            "place_id": f"TM_{muni[:2]}_A{i:03d}",
            "name": f"{muni[:2]} {at}",
            "category": "관광지", "sub_category": at,
            "municipality": muni,
            "address": f"전북 {muni}",
            "lat": lat0 + random.uniform(-0.05,0.05),
            "lon": lon0 + random.uniform(-0.06,0.06),
            "review_count": int(random.expovariate(1/40)),
            "status": "open",
            "meta": {"mock": True},
        })
    return places


# ══════════════════════════════════════════════
# 카카오 로컬 API
# ══════════════════════════════════════════════
def collect_kakao(run_id: str) -> int:
    t0 = time.time()
    if not KEYS["KAKAO"]:
        log.info("  [카카오] API 키 없음 → Mock")
        places = []
        for muni in MUNICIPALITIES:
            places += _mock_places(muni)
        n = _save_places(places)
        log_collect(run_id,"kakao","mock",n,duration=time.time()-t0)
        return n

    headers = {"Authorization": f"KakaoAK {KEYS['KAKAO']}"}
    places = []
    for muni, meta in MUNICIPALITIES.items():
        for cat_name, cat_code in [("음식점","FD6"),("카페","CE7"),("관광명소","AT4")]:
            params = {
                "category_group_code": cat_code,
                "x": meta["lon"], "y": meta["lat"],
                "radius": 5000,
                "size": 15, "page": 1,
                "sort": "accuracy",
            }
            data = _get(ENDPOINTS["카카오_로컬"], params, headers)
            if not data:
                continue
            for doc in data.get("documents", []):
                places.append({
                    "source": "kakao",
                    "place_id": doc.get("id",""),
                    "name": doc.get("place_name",""),
                    "category": cat_name,
                    "sub_category": doc.get("category_name",""),
                    "municipality": muni,
                    "address": doc.get("road_address_name") or doc.get("address_name",""),
                    "lat": float(doc.get("y",0)),
                    "lon": float(doc.get("x",0)),
                    "phone": doc.get("phone",""),
                    "review_count": 0,  # 카카오 API는 리뷰수 미제공
                    "meta": {"place_url": doc.get("place_url","")},
                })
            time.sleep(0.1)

    n = _save_places(places)
    log_collect(run_id,"kakao","ok",n,duration=time.time()-t0)
    log.info(f"  [카카오] ok — {n}건")
    return n


# ══════════════════════════════════════════════
# 네이버 지역검색 — 블로그 언급수로 화제성 측정
# ══════════════════════════════════════════════
def collect_naver_local(run_id: str) -> int:
    t0 = time.time()
    if not (KEYS["NAVER_ID"] and KEYS["NAVER_SEC"]):
        log.info("  [네이버] API 키 없음 → Skip (카카오 Mock으로 커버)")
        log_collect(run_id,"naver_local","skip",0,duration=time.time()-t0)
        return 0

    headers = {
        "X-Naver-Client-Id": KEYS["NAVER_ID"],
        "X-Naver-Client-Secret": KEYS["NAVER_SEC"],
    }
    places = []
    for muni in list(MUNICIPALITIES.keys())[:5]:  # 요청 제한: 5개 시군만
        query = f"{muni} 맛집"
        data = _get(ENDPOINTS["네이버_지역"], {"query":query,"display":10}, headers)
        if not data:
            continue
        for item in data.get("items", []):
            places.append({
                "source": "naver",
                "place_id": item.get("link","")[-20:],
                "name": item.get("title","").replace("<b>","").replace("</b>",""),
                "category": "음식점",
                "sub_category": item.get("category",""),
                "municipality": muni,
                "address": item.get("roadAddress") or item.get("address",""),
                "lat": float(item.get("mapy",0)) / 1e7,
                "lon": float(item.get("mapx",0)) / 1e7,
                "phone": item.get("telephone",""),
                "meta": {"link": item.get("link","")},
            })
        time.sleep(0.1)

    n = _save_places(places)
    log_collect(run_id,"naver_local","ok",n,duration=time.time()-t0)
    log.info(f"  [네이버 지역] ok — {n}건")
    return n


# ══════════════════════════════════════════════
# TourAPI — 관광지·음식점·행사 정보
# ══════════════════════════════════════════════
def collect_tourapi(run_id: str) -> int:
    t0 = time.time()
    if not KEYS["TOURAPI"]:
        log.info("  [TourAPI] API 키 없음 → Mock")
        places = []
        for muni in MUNICIPALITIES:
            places += _mock_places(muni, n_food=3, n_attr=5)
        n = _save_places(places)
        log_collect(run_id,"tourapi","mock",n,duration=time.time()-t0)
        return n

    places = []
    now = datetime.now()
    base_params = {
        "serviceKey": KEYS["TOURAPI"],
        "MobileOS": "ETC", "MobileApp": "JeonbukResearch",
        "_type": "json", "areaCode": "37",
        "numOfRows": 20, "pageNo": 1,
    }

    for muni, meta in MUNICIPALITIES.items():
        sigungu = meta["tour_code"].split(",")[1]

        # 지역 기반 음식점
        params = {**base_params, "contentTypeId":39, "sigunguCode":sigungu, "arrange":"R"}
        data = _get(ENDPOINTS["TourAPI_관광지"], params)
        for item in (data or {}).get("response",{}).get("body",{}).get("items",{}).get("item",[]):
            places.append({
                "source":"tourapi","place_id":str(item.get("contentid","")),
                "name":item.get("title",""),"category":"음식점",
                "sub_category":item.get("cat3",""),
                "municipality":muni,
                "address":item.get("addr1",""),
                "lat":float(item.get("mapy",0) or 0),
                "lon":float(item.get("mapx",0) or 0),
                "meta":{"firstimage":item.get("firstimage","")},
            })

        # 이번 달 행사·축제
        params = {**base_params, "contentTypeId":15, "sigunguCode":sigungu,
                  "eventStartDate":now.strftime("%Y%m01"),
                  "eventEndDate":(now + timedelta(days=30)).strftime("%Y%m%d")}
        data = _get(ENDPOINTS["TourAPI_행사"], params)
        for item in (data or {}).get("response",{}).get("body",{}).get("items",{}).get("item",[]):
            places.append({
                "source":"tourapi_event","place_id":str(item.get("contentid","")),
                "name":item.get("title",""),"category":"행사축제",
                "municipality":muni,
                "address":item.get("addr1",""),
                "lat":float(item.get("mapy",0) or 0),
                "lon":float(item.get("mapx",0) or 0),
                "open_date":str(item.get("eventstartdate","")),
                "meta":{"eventenddate":item.get("eventenddate","")},
            })
        time.sleep(0.15)

    n = _save_places(places)
    log_collect(run_id,"tourapi","ok",n,duration=time.time()-t0)
    log.info(f"  [TourAPI] ok — {n}건")
    return n


# ══════════════════════════════════════════════
# 빅카인즈 — 지역 뉴스 수집
# ══════════════════════════════════════════════
def collect_bigkinds(run_id: str, keywords: List[str] = None) -> int:
    t0 = time.time()
    keywords = keywords or ["전북","지방소멸","지역경제","새만금","전주","군산","익산"]
    date_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    if not KEYS["BIGKINDS"]:
        # Mock 뉴스
        conn = get_db()
        n = 0
        for kw in keywords[:3]:
            for i in range(3):
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO news
                        (source,article_id,title,content,publisher,municipality,published_at)
                        VALUES(?,?,?,?,?,?,?)
                    """, ("bigkinds_mock", f"BK-{kw[:3]}-{i}",
                          f"[전북] {kw} 관련 주요 동향 {i+1}",
                          f"전북 지역에서 {kw}과 관련된 새로운 움직임이 포착됐다.",
                          random.choice(["전북일보","새전북신문","전라일보"]),
                          random.choice(list(MUNICIPALITIES.keys())[:6]),
                          date_from))
                    n += 1
                except: pass
        conn.commit(); conn.close()
        log_collect(run_id,"bigkinds","mock",n,duration=time.time()-t0)
        log.info(f"  [빅카인즈] mock — {n}건")
        return n

    conn = get_db(); n = 0
    for kw in keywords:
        payload = {
            "access_key": KEYS["BIGKINDS"],
            "argument": {
                "query": kw,
                "published_at": {"from": date_from, "until": date_to},
                "provider": ["전북일보","새전북신문","전라일보","연합뉴스"],
                "fields": ["title","content","published_at","provider"],
                "sort": {"date":"desc"}, "page_size": 10,
            }
        }
        data = None
        try:
            r = requests.post(ENDPOINTS["빅카인즈"], json=payload, timeout=10)
            data = r.json()
        except: pass
        for doc in (data or {}).get("return_object",{}).get("documents",[]):
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO news
                    (source,article_id,title,content,publisher,municipality,published_at)
                    VALUES(?,?,?,?,?,?,?)
                """, ("bigkinds", doc.get("_id",""), doc.get("title",""),
                      doc.get("content","")[:500], doc.get("provider",""),
                      _detect_muni(doc.get("title","") + doc.get("content","")),
                      doc.get("published_at","")))
                n += 1
            except: pass
    conn.commit(); conn.close()
    log_collect(run_id,"bigkinds","ok",n,duration=time.time()-t0)
    log.info(f"  [빅카인즈] ok — {n}건")
    return n

def _detect_muni(text: str) -> str:
    for m in MUNICIPALITIES:
        if m[:2] in text:
            return m
    return "전북"
