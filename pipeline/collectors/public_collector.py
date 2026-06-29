import os
"""
공공 지표 통합 수집기
─────────────────────────────────────────────────
수집 소스 (API 키 없으면 Mock 자동 폴백):
  E 경제  │ 소상공인 상권 API, 음식점 인허가
  P 인구  │ KOSIS 인구이동·출생사망
  H 보건  │ HIRA 의료기관, KDCA 감염병
  V 환경  │ 에어코리아 시군구 대기오염
"""
import requests, json, time, random
from datetime import datetime, timedelta
from typing import Dict, List
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYS, ENDPOINTS, MUNICIPALITIES
from utils import get_db, get_logger, log_collect

log = get_logger("PublicCollector")

# ══════════════════════════════════════════════
# 공통 요청 헬퍼
# ══════════════════════════════════════════════
def _get(url, params=None, headers=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type","") else r.text
    except Exception as e:
        log.warning(f"  HTTP 실패: {e}")
        return None

def _save(rows: List[Dict], run_id: str):
    if not rows:
        return 0
    conn = get_db()
    n = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT INTO raw_indicators
                (source, municipality, indicator, category, value, value_str, ref_date, meta_json)
                VALUES(?,?,?,?,?,?,?,?)
            """, (row["source"], row["municipality"], row["indicator"],
                  row.get("category"), row.get("value"), row.get("value_str"),
                  row.get("ref_date", datetime.now().strftime("%Y-%m-%d")),
                  json.dumps(row.get("meta"), ensure_ascii=False)))
            n += 1
        except Exception as e:
            log.debug(f"  저장 오류: {e}")
    conn.commit(); conn.close()
    return n

# ══════════════════════════════════════════════
# Mock 데이터 생성 (현실적 수치)
# ══════════════════════════════════════════════
def _mock_value(indicator: str, muni: str) -> float:
    scale = MUNICIPALITIES[muni]["pop"] / 100_000
    table = {
        "신규_음식점_등록":    max(1, scale * 8  + random.gauss(0, 2)),
        "음식점_폐업":         max(0, scale * 5  + random.gauss(0, 1.5)),
        "소상공인_신규_등록":  max(2, scale * 15 + random.gauss(0, 3)),
        "전입_인구":           max(30, scale * 150 + random.gauss(0, 20)),
        "전출_인구":           max(30, scale * 160 + random.gauss(0, 20)),
        "20대_순이동":         -8 + (2 if MUNICIPALITIES[muni]["urban"] else -10) + random.gauss(0,2),
        "PM10_일평균":         max(5, 35 + random.gauss(0, 10)),
        "PM25_일평균":         max(2, 18 + random.gauss(0, 6)),
        "감염병_신고수":       max(0, scale * 3 + random.gauss(0, 1)),
        "의료기관_수":         max(1, scale * 40 + random.gauss(0, 5)),
        "의료기관_신규":       max(0, scale * 0.8 + random.gauss(0, 0.3)),
        "의료기관_폐업":       max(0, scale * 0.5 + random.gauss(0, 0.2)),
    }
    return round(table.get(indicator, scale * 10 + random.gauss(0,2)), 2)


# ══════════════════════════════════════════════
# E. 경제 — 소상공인 상권 API
# ══════════════════════════════════════════════
def collect_sbiz(run_id: str) -> int:
    """소상공인진흥공단 상권정보 API → 음식점·카페 업종 시군별 신규·폐업 집계"""
    t0 = time.time()
    rows = []
    status = "mock"

    for muni, meta in MUNICIPALITIES.items():
        if KEYS["DATAGOKR"]:
            # 실제 API: 행정구역 코드로 조회
            params = {
                "serviceKey": KEYS["DATAGOKR"],
                "pageNo": 1, "numOfRows": 100,
                "divId": "adongCd",
                "key": meta["code"],
                "_type": "json",
            }
            data = _get(ENDPOINTS["소상공인_상권"], params)
            if data:
                items = (data.get("body", {}).get("items", {}).get("item", [])
                         if isinstance(data, dict) else [])
                # 음식점류 신규 등록 필터
                food_codes = ["Q12", "Q13"]  # 음식·음료업 대분류
                new_food = sum(1 for it in items
                               if it.get("indsLclsCd","") in food_codes
                               and it.get("opnSvcId",""))
                rows.append({"source":"sbiz","municipality":muni,
                             "indicator":"신규_음식점_등록","category":"C",
                             "value": float(new_food), "meta": {"api":"sbiz"}})
                status = "ok"
                continue

        # Mock 폴백
        rows.append({"source":"sbiz_mock","municipality":muni,
                     "indicator":"신규_음식점_등록","category":"C",
                     "value": _mock_value("신규_음식점_등록", muni),
                     "meta": {"mock": True}})
        rows.append({"source":"sbiz_mock","municipality":muni,
                     "indicator":"소상공인_신규_등록","category":"E",
                     "value": _mock_value("소상공인_신규_등록", muni),
                     "meta": {"mock": True}})

    n = _save(rows, run_id)
    log_collect(run_id, "sbiz", status, n, duration=time.time()-t0)
    log.info(f"  [소상공인] {status} — {n}건")
    return n


# ══════════════════════════════════════════════
# E. 경제 — 식약처 음식점 인허가 변경
# ══════════════════════════════════════════════
def collect_mfds(run_id: str) -> int:
    """식품의약품안전처 음식점 인허가 변경 정보 → 시군별 신규·폐업"""
    t0 = time.time()
    rows = []

    for muni, meta in MUNICIPALITIES.items():
        if KEYS["DATAGOKR"]:
            url = f"https://openapi.foodsafetykorea.go.kr/api/{KEYS['DATAGOKR']}/COOKRTRQESINFO/json/1/100"
            params = {"SIGUN_NM": muni.replace("시","").replace("군","")}
            data = _get(url, params)
            if data and isinstance(data, dict):
                items = data.get("COOKRTRQESINFO", {}).get("row", [])
                new_c  = sum(1 for it in items if it.get("BSNS_SE_NM") == "신규")
                close_c= sum(1 for it in items if it.get("BSNS_SE_NM") in ["폐업","취소"])
                rows += [
                    {"source":"mfds","municipality":muni,"indicator":"음식점_신규","category":"C","value":float(new_c)},
                    {"source":"mfds","municipality":muni,"indicator":"음식점_폐업","category":"C","value":float(close_c)},
                ]
                continue

        # Mock
        rows += [
            {"source":"mfds_mock","municipality":muni,"indicator":"음식점_신규","category":"C",
             "value":_mock_value("신규_음식점_등록", muni)},
            {"source":"mfds_mock","municipality":muni,"indicator":"음식점_폐업","category":"C",
             "value":_mock_value("음식점_폐업", muni)},
        ]

    n = _save(rows, run_id)
    log_collect(run_id, "mfds", "mock" if not KEYS["DATAGOKR"] else "ok", n, duration=time.time()-t0)
    log.info(f"  [식약처] {n}건")
    return n


# ══════════════════════════════════════════════
# P. 인구 — KOSIS 인구이동·출생사망
# ══════════════════════════════════════════════
def collect_kosis_population(run_id: str) -> int:
    t0 = time.time()
    rows = []
    ym = (datetime.now() - timedelta(days=40)).strftime("%Y%m")  # 약 1개월 전 확정치

    for muni, meta in MUNICIPALITIES.items():
        if KEYS["KOSIS"]:
            params = {
                "method": "getList", "apiKey": KEYS["KOSIS"],
                "itmId": "T20", "objL1": meta["kosis_code"],
                "objL2": "ALL", "prdSe": "M",
                "startPrdDe": ym, "endPrdDe": ym,
                "format": "json", "jsonVD": "Y",
            }
            data = _get(ENDPOINTS["KOSIS_인구이동"], params)
            if data and isinstance(data, list):
                for item in data[:5]:
                    indicator = item.get("itmNm", "인구이동")
                    val = float(item.get("DT", 0) or 0)
                    rows.append({"source":"kosis","municipality":muni,
                                 "indicator":indicator,"category":"P",
                                 "value":val,"ref_date":ym})
                continue

        # Mock
        rows += [
            {"source":"kosis_mock","municipality":muni,"indicator":"전입_인구","category":"P",
             "value":_mock_value("전입_인구",muni),"ref_date":ym},
            {"source":"kosis_mock","municipality":muni,"indicator":"전출_인구","category":"P",
             "value":_mock_value("전출_인구",muni),"ref_date":ym},
            {"source":"kosis_mock","municipality":muni,"indicator":"20대_순이동","category":"P",
             "value":_mock_value("20대_순이동",muni),"ref_date":ym},
        ]

    n = _save(rows, run_id)
    log_collect(run_id, "kosis_pop", "mock" if not KEYS["KOSIS"] else "ok", n, duration=time.time()-t0)
    log.info(f"  [KOSIS 인구] {n}건")
    return n


# ══════════════════════════════════════════════
# V. 환경 — 에어코리아 시군구 대기오염
# ══════════════════════════════════════════════
def collect_airkorea(run_id: str) -> int:
    t0 = time.time()
    rows = []

    if KEYS["DATAGOKR"]:
        params = {
            "serviceKey": KEYS["DATAGOKR"],
            "returnType": "json",
            "numOfRows": 100, "pageNo": 1,
            "sidoName": "전북",
            "searchCondition": "DAILY",
        }
        data = _get(ENDPOINTS["에어코리아_시군구"], params)
        if data:
            items = (data.get("response",{}).get("body",{})
                        .get("items",[]) if isinstance(data,dict) else [])
            # 실응답은 cityName(예: "전주","고창군")을 준다. 시/군 접미사를 떼고
            # 14개 시군 전체를 정규화 매핑한다(기존엔 stationName·6개만 봐서 0건 매칭→mock).
            def _norm(s): return s.replace("시","").replace("군","").strip()
            name_to_muni = {_norm(m): m for m in MUNICIPALITIES}
            def _num(v):
                try: return float(v)
                except (TypeError, ValueError): return None  # "-" 등 결측
            for it in items:
                muni = name_to_muni.get(_norm(it.get("cityName","")), None)
                if not muni:
                    continue
                pm10, pm25 = _num(it.get("pm10Value")), _num(it.get("pm25Value"))
                if pm10 is not None:
                    rows.append({"source":"airkorea","municipality":muni,
                                 "indicator":"PM10_일평균","category":"V","value":pm10})
                if pm25 is not None:
                    rows.append({"source":"airkorea","municipality":muni,
                                 "indicator":"PM25_일평균","category":"V","value":pm25})
            if rows:
                n = _save(rows, run_id)
                log_collect(run_id,"airkorea","ok",n,duration=time.time()-t0)
                log.info(f"  [에어코리아] ok — {n}건")
                return n

    # Mock
    for muni in MUNICIPALITIES:
        rows += [
            {"source":"airkorea_mock","municipality":muni,"indicator":"PM10_일평균","category":"V",
             "value":_mock_value("PM10_일평균",muni)},
            {"source":"airkorea_mock","municipality":muni,"indicator":"PM25_일평균","category":"V",
             "value":_mock_value("PM25_일평균",muni)},
        ]
    n = _save(rows, run_id)
    log_collect(run_id,"airkorea","mock",n,duration=time.time()-t0)
    log.info(f"  [에어코리아] mock — {n}건")
    return n


# ══════════════════════════════════════════════
# H. 보건 — HIRA 의료기관 현황
# ══════════════════════════════════════════════
def collect_hira(run_id: str) -> int:
    t0 = time.time()
    rows = []

    for muni, meta in MUNICIPALITIES.items():
        if KEYS["DATAGOKR"]:
            params = {
                "serviceKey": KEYS["DATAGOKR"],
                "pageNo":1, "numOfRows":100,
                "sidoCd":"45",
                "sgguCd": meta["code"][:5],
                "_type":"json",
            }
            data = _get(ENDPOINTS["HIRA_의료기관"], params)
            if data:
                items = (data.get("response",{}).get("body",{})
                            .get("items",{}).get("item",[])
                         if isinstance(data,dict) else [])
                rows.append({"source":"hira","municipality":muni,
                             "indicator":"의료기관_수","category":"H",
                             "value":float(len(items))})
                continue

        rows += [
            {"source":"hira_mock","municipality":muni,"indicator":"의료기관_수","category":"H",
             "value":_mock_value("의료기관_수",muni)},
            {"source":"hira_mock","municipality":muni,"indicator":"감염병_신고수","category":"H",
             "value":_mock_value("감염병_신고수",muni)},
        ]

    n = _save(rows, run_id)
    log_collect(run_id,"hira","mock" if not KEYS["DATAGOKR"] else "ok",n,duration=time.time()-t0)
    log.info(f"  [HIRA] {n}건")
    return n
