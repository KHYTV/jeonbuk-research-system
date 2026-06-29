"""
전북 통합 파이프라인 설정
─────────────────────────────────────────────────
모든 API 엔드포인트, 시군 코드, 지표 정의를 한곳에서 관리합니다.
API 키가 없으면 각 수집기가 Mock 데이터로 자동 폴백합니다.
"""
import os

# ══════════════════════════════════════════════
# API 키 (환경변수 또는 직접 입력)
# ══════════════════════════════════════════════
KEYS = {
    # data.go.kr 공통 키 (하나로 대부분 커버)
    "DATAGOKR":    os.getenv("DATAGOKR_API_KEY", ""),
    # 통계청 KOSIS
    "KOSIS":       os.getenv("KOSIS_API_KEY", ""),
    # 한국관광공사 TourAPI
    "TOURAPI":     os.getenv("TOURAPI_KEY", ""),
    # 카카오 로컬 REST API
    "KAKAO":       os.getenv("KAKAO_REST_KEY", ""),
    # 네이버 검색 API
    "NAVER_ID":    os.getenv("NAVER_CLIENT_ID", ""),
    "NAVER_SEC":   os.getenv("NAVER_CLIENT_SECRET", ""),
    # 빅카인즈
    "BIGKINDS":    os.getenv("BIGKINDS_API_KEY", ""),
}

# ══════════════════════════════════════════════
# API 엔드포인트
# ══════════════════════════════════════════════
ENDPOINTS = {
    # ── 경제 ──
    "소상공인_상권":       "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInAdmArea",
    "음식점_인허가":       "https://apis.data.go.kr/1741000/r2/foodFacility",
    "식약처_음식점변경":   "https://openapi.foodsafetykorea.go.kr/api/{key}/COOKRTRQESINFO/json/1/100",
    # ── 인구 ──
    "행안부_인구이동":     "https://jumin.mois.go.kr/ageStatMonth.do",        # 스크래핑 필요
    "KOSIS_인구이동":      "https://kosis.kr/openapi/statisticsData.do",
    "KOSIS_출생사망":      "https://kosis.kr/openapi/statisticsData.do",
    # ── 환경 ──
    "에어코리아_시군구":   "https://apis.data.go.kr/B552584/ArpltnStatsSvc/getCtprvnMesureSidoLIst",
    "에어코리아_실시간":   "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty",
    # ── 보건 ──
    "HIRA_의료기관":       "https://apis.data.go.kr/B551182/hospInfoServicev2/getHospBasisList",
    "KDCA_감염병":         "https://apis.data.go.kr/1790387/InfectionStatus/getInfectionStatus",
    # ── 관광/생활문화 ──
    "TourAPI_음식점":      "http://apis.data.go.kr/B551011/KorService1/searchKeyword1",
    "TourAPI_행사":        "http://apis.data.go.kr/B551011/KorService1/searchFestival1",
    "TourAPI_관광지":      "http://apis.data.go.kr/B551011/KorService1/areaBasedList1",
    "카카오_로컬":         "https://dapi.kakao.com/v2/local/search/category.json",
    "카카오_키워드":       "https://dapi.kakao.com/v2/local/search/keyword.json",
    "네이버_지역":         "https://openapi.naver.com/v1/search/local.json",
    "빅카인즈":            "https://www.bigkinds.or.kr/api/news/search.do",
}

# ══════════════════════════════════════════════
# 전북 14개 시군 코드 매핑
# ══════════════════════════════════════════════
MUNICIPALITIES = {
    "전주시": {
        "code": "45111", "kosis_code": "45110", "tour_code": "37,1",
        "lat": 35.8242, "lon": 127.1480,
        "air_station": "전주",  "pop": 650000, "urban": True
    },
    "군산시": {
        "code": "45130", "kosis_code": "45130", "tour_code": "37,2",
        "lat": 35.9676, "lon": 126.7368,
        "air_station": "군산",  "pop": 270000, "urban": True
    },
    "익산시": {
        "code": "45140", "kosis_code": "45140", "tour_code": "37,3",
        "lat": 35.9483, "lon": 126.9577,
        "air_station": "익산",  "pop": 280000, "urban": True
    },
    "정읍시": {
        "code": "45180", "kosis_code": "45180", "tour_code": "37,4",
        "lat": 35.5697, "lon": 126.8561,
        "air_station": "정읍",  "pop": 110000, "urban": False
    },
    "남원시": {
        "code": "45190", "kosis_code": "45190", "tour_code": "37,5",
        "lat": 35.4164, "lon": 127.3902,
        "air_station": "남원",  "pop": 80000,  "urban": False
    },
    "김제시": {
        "code": "45210", "kosis_code": "45210", "tour_code": "37,6",
        "lat": 35.8035, "lon": 126.8808,
        "air_station": "김제",  "pop": 85000,  "urban": False
    },
    "완주군": {
        "code": "45710", "kosis_code": "45710", "tour_code": "37,7",
        "lat": 35.9072, "lon": 127.1621,
        "air_station": "전주",  "pop": 95000,  "urban": False
    },
    "진안군": {
        "code": "45720", "kosis_code": "45720", "tour_code": "37,8",
        "lat": 35.7913, "lon": 127.4243,
        "air_station": "전주",  "pop": 25000,  "urban": False
    },
    "무주군": {
        "code": "45730", "kosis_code": "45730", "tour_code": "37,9",
        "lat": 36.0071, "lon": 127.6605,
        "air_station": "전주",  "pop": 23000,  "urban": False
    },
    "장수군": {
        "code": "45740", "kosis_code": "45740", "tour_code": "37,10",
        "lat": 35.6475, "lon": 127.5210,
        "air_station": "전주",  "pop": 21000,  "urban": False
    },
    "임실군": {
        "code": "45750", "kosis_code": "45750", "tour_code": "37,11",
        "lat": 35.6178, "lon": 127.2893,
        "air_station": "전주",  "pop": 28000,  "urban": False
    },
    "순창군": {
        "code": "45760", "kosis_code": "45760", "tour_code": "37,12",
        "lat": 35.3744, "lon": 127.1379,
        "air_station": "전주",  "pop": 27000,  "urban": False
    },
    "고창군": {
        "code": "45770", "kosis_code": "45770", "tour_code": "37,13",
        "lat": 35.4350, "lon": 126.7022,
        "air_station": "정읍",  "pop": 56000,  "urban": False
    },
    "부안군": {
        "code": "45790", "kosis_code": "45790", "tour_code": "37,14",
        "lat": 35.7317, "lon": 126.7330,
        "air_station": "군산",  "pop": 52000,  "urban": False
    },
}

# ── TourAPI 카테고리 코드 ──────────────────────
TOUR_CONTENT_TYPES = {
    "관광지": 12, "문화시설": 14, "축제행사": 15,
    "여행코스": 25, "레포츠": 28, "숙박": 32,
    "쇼핑": 38, "음식점": 39,
}

# ── 카카오 카테고리 코드 ──────────────────────
KAKAO_CATEGORIES = {
    "음식점": "FD6", "카페": "CE7", "관광명소": "AT4",
    "숙박": "AD5", "문화시설": "CT1", "마트": "MT1",
}

# ── KOSIS 지표 코드 ──────────────────────────
KOSIS_CODES = {
    "인구이동_시군구": {"tbl": "DT_1B26001", "itm": "T20"},
    "출생":           {"tbl": "DT_1B8000F", "itm": "T00"},
    "사망":           {"tbl": "DT_1B8000G", "itm": "T00"},
    "연령별인구":     {"tbl": "DT_1B040A3", "itm": "T2"},
}

# 경로는 이 파일(pipeline/) 기준으로 고정 → 어느 cwd 에서 실행해도 동일
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "jeonbuk.db")
LOG_PATH = os.path.join(BASE_DIR, "logs")
REPORT_PATH = os.path.join(BASE_DIR, "report")
