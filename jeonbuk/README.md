# jeonbuk — 전북 14개 시군 다변량 이상신호 탐지 + 인과 구조 추론

매주 경제·환경·보건·인구이동 지표를 결합해 다음 셋을 자동으로 뽑아낸다.

| 단계 | 질문 | 방법 |
|------|------|------|
| **핫 플레이스** | 이번 주 *어디서* 신호가 났나 | 시군별 롤링 베이스라인 + Ledoit-Wolf 공분산 기반 **Mahalanobis 거리** D², χ² 임계로 플래그 |
| **핫 아이템** | *무슨* 신호였나 (어떤 지표 조합) | D²의 지표별 **기여도 분해**(합 = D²) + 방향(↑/↓) |
| **인과 진단** | *왜* — 어떤 지표가 선행하나 | 정상성 보정(ADF+차분) 후 지표쌍 **Granger 인과** |

핵심: "핫 플레이스"는 수치가 단지 높은 곳이 아니라 **여러 지표가 동시에**
자기 과거 분포에서 벗어난 곳이다. 단변량 z-score 합으로는 지표 간 상관(예:
매출↓·폐업↑의 동조)을 못 걷어내므로 공분산을 반영하는 Mahalanobis를 쓴다.

## 설치
```bash
pip install -r jeonbuk/requirements.txt
```

## 즉시 검증 (데이터 없이)
```bash
python -m jeonbuk.run_weekly --demo
```
합성 패널에 *알려진* 이상신호(군산시: 카드매출↓·폐업↑·응급실내원↑)와
선행관계(신규창업→카드매출 +2주)를 주입한다. 엔진이 군산시를 1위 핫
플레이스로, 해당 3개 지표를 핫 아이템으로 복원하면 정상 동작.

## 실데이터 실행
입력은 **long-format** (CSV/Excel):

| region | week | indicator | value |
|--------|------|-----------|-------|
| 군산시 | 2026-06-22 | 카드매출지수 | 98.3 |

```bash
python -m jeonbuk.run_weekly --input data/panel.csv               # 최근 주
python -m jeonbuk.run_weekly --input data/panel.csv --week 2026-06-22
```
결과는 `jeonbuk/output/signal_<week>.{json,md}` 로 저장된다(JSON=기계용, MD=브리핑).

## 모듈 구조
```
jeonbuk/
  config.py      시군·지표 정의, 탐지/인과 파라미터  ← 여기만 고치면 튜닝 끝
  data.py        long↔wide 변환, 합성 데이터 생성기
  detector.py    Mahalanobis 핫 플레이스 + 핫 아이템 분해
  causal.py      ADF 정상화 + Granger 인과 그래프
  report.py      JSON/Markdown 리포트 + 연구적 해석 초안
  run_weekly.py  주간 파이프라인 진입점
```

## 실데이터 적용 시 점검할 것 (방법론 주의)
- **지표 컬럼명**: `config.INDICATORS` 를 실제 데이터에 맞춰 교체.
- **베이스라인 길이**: `BASELINE_WEEKS`(기본 26주). 짧으면 공분산 추정 불안정,
  길면 구조 변화에 둔감. 데이터 빈도/계절성에 맞춰 조정.
- **다중비교**: 14개 시군을 매주 검정하므로 α=0.01이라도 우연 양성이 생긴다.
  D² 랭킹 상위 + 다주 연속 지속 여부로 거른다(`ALPHA_PLACE` 조정 가능).
- **Granger ≠ 인과**: 예측적 선행일 뿐. 외생 사건 매칭(공시·뉴스·행정자료)과
  인접 시군 공간효과(공간자기상관)를 후속 확인할 것.
- **결측/단위**: 지표 단위·스케일이 달라도 Mahalanobis가 표준화·상관을 흡수하나,
  결측 보간 방식(`data.to_wide`의 선형보간)은 데이터 특성에 맞게 재검토.
