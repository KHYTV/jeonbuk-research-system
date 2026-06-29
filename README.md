# 전북 생활문화 핫플레이스 신호탐지 시스템

전북 14개 시군 × **경제·인구·환경·보건·생활문화** 지표 + 뉴스를 매주 결합해
**"이번 주 어디서 무슨 신호가, 왜 났고, 연구적으로 뭘 의미하는지"** 를 자동으로 뽑아낸다.

> 텍스트 분석이 아니라 **다변량 이상신호 탐지(anomaly detection) + 인과 구조 추론** 문제로 접근한다.
> "핫플레이스"는 수치가 단지 높은 곳이 아니라 **여러 지표가 동시에 평소와 달리 움직인 곳**이다.

[![sample](https://img.shields.io/badge/sample-dashboard-4da3ff)](https://khytv.github.io/jeonbuk-research-system/)

---

## 아키텍처 — 수집 / 분석 두 레이어 + 브리지

```
┌─ pipeline/ ── 수집 레이어 ───────────────┐     ┌─ jeonbuk/ ── 분석 레이어 ──────────────┐
│  9개 수집기 → SQLite(jeonbuk.db)         │     │  detector  Mahalanobis(Ledoit-Wolf)     │
│   · 공공: 소상공인·식약처·KOSIS·          │     │            + D² 기여도 분해(핫아이템)    │
│           에어코리아·HIRA                 │ ──▶ │  causal    Granger(ADF 정상화) 선행관계 │
│   · 문화: 카카오·네이버지역·TourAPI       │bridge│  topics    TF-IDF + NMF 토픽모델링      │
│   · 뉴스: 네이버뉴스 + RSS(전북 언론)     │  .py │  article   Claude(claude-opus-4-8) 기사 │
│  main.py weekly                          │     │  web       인터랙티브 대시보드           │
└──────────────────────────────────────────┘     └─────────────────────────────────────────┘
```

- **수집 레이어 (`pipeline/`)** — 실데이터를 모아 SQLite DB에 적재. 키가 없으면 각 수집기가 Mock으로 폴백.
- **분석 레이어 (`jeonbuk/`)** — 다변량 이상탐지 → 인과진단 → 토픽 → LLM 분석기사 → 대시보드.
- **브리지 (`bridge.py`)** — DB(`raw_indicators`)를 분석엔진 입력(long-format)으로 변환해 둘을 연결.

---

## 빠른 시작

```bash
pip install -r requirements.txt
cp .env.example .env          # 키 채우기(없어도 Mock/합성으로 동작)

# (A) 키 없이 즉시 시연 — 합성 데이터로 전 과정 검증
python bridge.py --demo

# (B) 실데이터 — 수집 → 분석/기사/대시보드
cd pipeline && python main.py weekly && cd ..
python bridge.py
```

Windows는 `run.bat` 더블클릭이면 (A)+(B)가 한 번에 돈다.

---

## 데이터 소스 ↔ API 키

| 수집기 | 소스 | 엔드포인트 | 키 | 발급 |
|---|---|---|---|---|
| `sbiz` | 소상공인 상권정보 | data.go.kr | `DATAGOKR_API_KEY` | 즉시·무료 |
| `mfds` | 식약처 음식점 인허가 | foodsafetykorea | `DATAGOKR_API_KEY` | 즉시·무료 |
| `airkorea` | 에어코리아 대기 | data.go.kr | `DATAGOKR_API_KEY` | 즉시·무료 |
| `hira` | HIRA 의료기관 | data.go.kr | `DATAGOKR_API_KEY` | 즉시·무료 |
| `kosis_population` | 인구이동·출생사망 | kosis.kr | `KOSIS_API_KEY` | 즉시·무료 |
| `kakao` | 카카오 로컬 장소 | dapi.kakao.com | `KAKAO_REST_KEY` | 즉시·무료 |
| `naver_local` | 네이버 지역검색 | openapi.naver.com | `NAVER_CLIENT_ID/SECRET` | 5분·무료 |
| `tourapi` | TourAPI 음식점·행사 | data.go.kr | `TOURAPI_KEY` | 즉시·무료 |
| 뉴스 | 네이버뉴스 + RSS(전북 언론) | naver / RSS | `NAVER_*` (RSS는 키 불필요) | — |
| 기사작성 | Claude | api.anthropic.com | `ANTHROPIC_API_KEY` | 종량제 |

> **data.go.kr 키 1개**로 소상공인·식약처·에어코리아·HIRA가 모두 연결된다.

---

## 분석 방법론

1. **핫 플레이스 (Mahalanobis)** — 시군별 직전 26주를 베이스라인으로, 이번 주 지표 벡터의
   Mahalanobis 거리 D²를 Ledoit-Wolf 축소 공분산으로 산출. χ² 임계로 이상 플래그.
2. **핫 아이템 (D² 분해)** — D²를 지표별 기여도로 정확 분해(합 = D²) → 어떤 조합이 신호를 만들었나 + 방향.
3. **인과 진단 (Granger)** — ADF 정상성 보정 후 지표쌍 Granger 인과 → 선행→후행 그래프.
4. **토픽 + 기사** — 뉴스 코퍼스를 TF-IDF+NMF로 토픽화, Claude가 신호·인과·토픽을 묶어 분석기사 작성.

**주의**: Granger는 **예측적 선행**이지 인과 확정이 아니다. 14시군×매주 다중비교로 임계 부근 우연양성이
생기므로 D² 랭킹·다주 지속성으로 보정한다. 코드/대시보드/기사 모두 이 한계를 명시한다.

---

## 디렉터리

```
jeonbuk-research-system/
  pipeline/        수집 레이어 (collectors/ engine/ report/ main.py)
  jeonbuk/         분석 레이어 (detector causal topics article report web/)
  bridge.py        DB → 분석엔진 연결
  docs/            GitHub Pages 샘플 대시보드 (build 산출 동기화)
  run.bat          Windows 원클릭 실행
  .env.example     키 템플릿
```

## 자동화

`.github/workflows/weekly.yml` — 매주 월요일 새벽, 저장소 Secrets의 키로 수집·분석·대시보드 갱신 후
`docs/`를 커밋한다. GitHub **Settings → Pages → Source: `docs/`** 로 설정하면 샘플 사이트가 공개된다.

## 보안

`.env`, `*.db`, `logs/`, 산출물은 `.gitignore`로 커밋에서 제외된다. **API 키는 절대 커밋하지 말 것**
(키가 노출되면 발급처에서 재발급).
