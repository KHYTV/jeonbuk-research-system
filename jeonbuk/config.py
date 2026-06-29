"""
config.py - 전북 신호탐지 엔진 중앙 설정.

시군 목록 / 지표 정의 / 탐지·인과 파라미터를 한 곳에서 관리한다.
"""

from pathlib import Path

# .env 자동 로드 — 저장소 루트(우선) + jeonbuk/.env (NAVER/BIGKINDS/ANTHROPIC 키)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")   # 저장소 루트
    load_dotenv(Path(__file__).parent / ".env")           # 패키지 로컬(있으면)
except Exception:
    pass

# ─── 전북 14개 시군 ──────────────────────────────────────────────────────────
REGIONS: list[str] = [
    "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군",
    "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군",
]

# ─── 지표 정의 (도메인 → 지표 목록) ────────────────────────────────────────
#  실제 데이터의 컬럼명에 맞춰 자유롭게 바꿔 쓰면 된다.
INDICATORS: dict[str, list[str]] = {
    "경제": ["카드매출지수", "신규창업수", "폐업수", "고용률", "사업체수"],
    "환경": ["미세먼지PM10", "대기질지수", "폐기물발생량", "용수사용량"],
    "보건": ["응급실내원", "감염병신고", "의료기관방문", "정신건강상담"],
    "인구이동": ["전입", "전출", "순이동", "인구수"],
}

# 평탄화된 전체 지표 리스트 / 지표→도메인 역매핑
ALL_INDICATORS: list[str] = [ind for inds in INDICATORS.values() for ind in inds]
INDICATOR_DOMAIN: dict[str, str] = {
    ind: dom for dom, inds in INDICATORS.items() for ind in inds
}

# ─── 핫 플레이스(Mahalanobis) 파라미터 ──────────────────────────────────────
BASELINE_WEEKS: int = 26        # 롤링 베이스라인 창 길이(주). 분포 추정용 과거 구간
MIN_BASELINE_WEEKS: int = 12    # 이보다 짧으면 거리 계산 보류
ALPHA_PLACE: float = 0.01       # χ² 유의수준. 작을수록 보수적(덜 잡음)
SHRINKAGE: str = "ledoit_wolf"  # 공분산 추정: "ledoit_wolf" | "oas" | "empirical"

# ─── 핫 아이템(기여도 분해) 파라미터 ────────────────────────────────────────
TOP_K_ITEMS: int = 4            # 신호를 설명하는 상위 기여 지표 개수
ITEM_CONTRIB_MIN: float = 0.05  # 전체 D² 대비 이 비율 미만 기여는 무시

# ─── 인과 진단(Granger) 파라미터 ────────────────────────────────────────────
GRANGER_MAXLAG: int = 4         # 검정 최대 시차(주)
ALPHA_CAUSAL: float = 0.05      # Granger 유의수준
ADF_ALPHA: float = 0.05         # 정상성(ADF) 유의수준. 실패 시 차분
MAX_DIFF: int = 2               # 정상성 확보 위한 최대 차분 횟수
CAUSAL_MIN_WEEKS: int = 40      # 인과검정에 필요한 최소 관측 길이

# ─── 뉴스 맥락 해석 파라미터 ────────────────────────────────────────────────
NEWS_PROVIDER: str = "naver"      # "naver" | "bigkinds"
NEWS_WINDOW_DAYS: int = 7         # 신호 주 기준 ± 검색 기간(일)
NEWS_MAX_ARTICLES: int = 20       # 핫 플레이스당 수집 상한
NEWS_TOP_KEYWORDS: int = 8        # 헤드라인에서 뽑을 상위 키워드 수

# 지표 → 뉴스 검색어 확장.  지표명 자체는 기사에 잘 안 나오므로
# 일상 용어로 풀어서 OR 결합한다(예: 카드매출지수 → 소비/매출/상권).
INDICATOR_KEYWORDS: dict[str, list[str]] = {
    "카드매출지수": ["소비", "매출", "상권"],
    "신규창업수": ["창업", "개업", "신규점포"],
    "폐업수": ["폐업", "폐점", "문닫"],
    "고용률": ["고용", "일자리", "채용"],
    "사업체수": ["기업", "공장", "사업체"],
    "미세먼지PM10": ["미세먼지", "황사", "대기질"],
    "대기질지수": ["대기질", "오염", "미세먼지"],
    "폐기물발생량": ["폐기물", "쓰레기", "소각"],
    "용수사용량": ["용수", "가뭄", "상수도"],
    "응급실내원": ["응급실", "응급환자", "사고"],
    "감염병신고": ["감염병", "코로나", "독감", "집단감염"],
    "의료기관방문": ["병원", "진료", "의료"],
    "정신건강상담": ["정신건강", "상담", "자살예방"],
    "전입": ["전입", "인구유입", "정착"],
    "전출": ["전출", "인구유출", "이탈"],
    "순이동": ["인구이동", "인구감소", "전입전출"],
    "인구수": ["인구", "고령화", "소멸위험"],
}

# ─── 파일 경로 ──────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent
DATA_DIR: Path = BASE_DIR / "data"
OUTPUT_DIR: Path = BASE_DIR / "output"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 표준 long-format 컬럼명
COL_REGION = "region"
COL_WEEK = "week"
COL_INDICATOR = "indicator"
COL_VALUE = "value"
