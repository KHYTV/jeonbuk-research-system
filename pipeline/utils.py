"""
공통 유틸리티: 로거 + DB 초기화
모든 수집기와 분석 모듈이 공유합니다.
"""
import sqlite3, logging, os, json
from datetime import datetime
from config import DB_PATH, LOG_PATH

os.makedirs(LOG_PATH, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ══════════════════════════════════════════════
# 로거 설정 — 파일 + 콘솔 동시 출력
# ══════════════════════════════════════════════
def get_logger(name: str) -> logging.Logger:
    log_file = os.path.join(LOG_PATH, f"{datetime.now():%Y-%m-%d}.log")
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("[%(asctime)s][%(name)-20s][%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt); ch.setLevel(logging.INFO)
    logger.addHandler(fh); logger.addHandler(ch)
    return logger

# ══════════════════════════════════════════════
# DB 초기화 — 전체 스키마
# ══════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── 수집 원본 통합 테이블 ──────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_indicators (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT NOT NULL,   -- 수집 소스 식별자
        municipality  TEXT NOT NULL,   -- 시군명
        indicator     TEXT NOT NULL,   -- 지표명
        category      TEXT,            -- E/P/H/V/W/C (경제·인구·보건·환경·복지·문화)
        value         REAL,
        value_str     TEXT,            -- 문자열 값 (업소명 등)
        ref_date      TEXT,            -- 기준일 YYYY-MM-DD
        collected_at  TEXT DEFAULT (datetime('now','localtime')),
        meta_json     TEXT             -- 원본 응답 일부 보관
    )""")

    # ── 생활문화 장소 DB ──────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS places (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT NOT NULL,   -- 'kakao'|'naver'|'tour'|'sbiz'|'mfds'
        place_id      TEXT,
        name          TEXT NOT NULL,
        category      TEXT,
        sub_category  TEXT,
        municipality  TEXT,
        address       TEXT,
        lat           REAL,
        lon           REAL,
        phone         TEXT,
        status        TEXT DEFAULT 'open',  -- open/closed/new
        open_date     TEXT,
        review_count  INTEGER DEFAULT 0,
        collected_at  TEXT DEFAULT (datetime('now','localtime')),
        meta_json     TEXT,
        UNIQUE(source, place_id)
    )""")

    # ── 뉴스 기사 ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS news (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT,
        article_id    TEXT,
        title         TEXT,
        content       TEXT,
        publisher     TEXT,
        municipality  TEXT,
        published_at  TEXT,
        collected_at  TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(source, article_id)
    )""")

    # ── 수집 실행 로그 ────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS collect_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT,
        source     TEXT,
        status     TEXT,   -- ok / error / mock
        count      INTEGER DEFAULT 0,
        message    TEXT,
        duration_s REAL,
        ts         TEXT DEFAULT (datetime('now','localtime'))
    )""")

    # ── 분석 결과 ─────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS analysis_results (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT,
        period_start TEXT,
        period_end   TEXT,
        result_json  TEXT,
        created_at   TEXT DEFAULT (datetime('now','localtime'))
    )""")

    conn.commit(); conn.close()
    return DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_collect(run_id, source, status, count, message="", duration=0.0):
    conn = get_db()
    conn.execute(
        "INSERT INTO collect_log (run_id,source,status,count,message,duration_s) VALUES(?,?,?,?,?,?)",
        (run_id, source, status, count, message, round(duration, 2)))
    conn.commit(); conn.close()
