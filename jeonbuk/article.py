"""
article.py - 구조화 신호 + 토픽 → LLM 분석기사 자동작성.

이상탐지/인과진단(정량) + 뉴스 토픽(정성)을 묶어 Claude 에 넘기고,
연구·보도 톤의 한국어 분석기사를 받는다.

모델: claude-opus-4-8 (어댑티브 thinking, 긴 출력은 streaming + get_final_message).
ANTHROPIC_API_KEY 가 없거나 SDK 미설치면 → 규칙기반 템플릿 초안으로 폴백
(파이프라인이 키 없이도 끝까지 돈다).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MODEL = "claude-opus-4-8"

SYSTEM = """당신은 지역경제·사회 데이터를 다루는 데이터 저널리스트 겸 연구분석가입니다.
전라북도 14개 시군의 주간 다변량 이상신호 탐지 결과와 뉴스 토픽을 바탕으로
연구 보고서에 실릴 분석기사를 작성합니다.

원칙:
- 제공된 수치·지표·토픽에만 근거해 서술하고, 주어지지 않은 통계나 고유명사는 지어내지 않는다.
- Mahalanobis 거리는 '여러 지표가 동시에 평소와 달리 움직인 정도'임을 독자가 이해하도록 풀어 쓴다.
- Granger 인과는 '예측적 선행'일 뿐 인과 확정이 아님을 반드시 명시한다.
- 뉴스 토픽은 '정황 단서'로만 쓰고, 기사 내용이 곧 원인이라고 단정하지 않는다.
- 과장·선정적 표현을 피하고, 후속 검증이 필요한 부분을 명확히 한다."""


@dataclass
class Article:
    title: str
    body: str          # 마크다운 본문
    model: str         # 생성에 쓴 모델 또는 "template-fallback"


def _build_prompt(hot_place: dict, topics, week: str) -> str:
    items = "\n".join(
        f"  - {it['indicator']}({it['domain']}) {it['direction']}, "
        f"기여 {it['share']*100:.0f}%, z={it['z']:+.1f}"
        for it in hot_place["hot_items"]
    )
    edges = "\n".join(
        f"  - {e['source']}({e['source_domain']}) → {e['target']}({e['target_domain']}), "
        f"{e['lag']}주 선행, p={e['p_value']}"
        for e in hot_place["causal_edges"][:6]
    ) or "  - (유의한 선행관계 미검출)"
    kw = topics.keyword_line(10) if topics and topics.top_keywords else "(수집 뉴스 없음)"
    tops = "\n".join(
        f"  - 토픽{t.rank}({t.weight*100:.0f}%): {', '.join(t.keywords)}"
        for t in (topics.topics if topics else [])
    ) or "  - (토픽 없음)"

    return f"""다음은 {week} 주, 전북 '{hot_place['region']}'에서 탐지된 다변량 이상신호입니다.

[이상 정도]
  Mahalanobis D² = {hot_place['d2']} (p = {hot_place['p_value']})

[핫 아이템 — 신호를 만든 지표]
{items}

[인과 진단 — Granger 선행관계]
{edges}

[뉴스 토픽 — 같은 기간 지역 보도]
  상위 키워드: {kw}
{tops}

위 자료만 근거로, 아래 4단 구성의 분석기사를 한국어 마크다운으로 작성하세요.
1. 무슨 신호인가 (어디서·어떤 지표가 동시에 움직였나)
2. 어떤 구조인가 (핫아이템 도메인 구성 + 선행관계 해석)
3. 정황은 무엇인가 (뉴스 토픽과의 연결 — 단서 수준으로만)
4. 연구적 함의와 후속 검증 (한계·다음 분석 제언)

제목(H1) 1개와 소제목(H2)을 포함하고, 분량은 600~900자 내외로 하세요."""


def _template(hot_place: dict, topics, week: str) -> Article:
    """API 키 없을 때의 규칙기반 초안."""
    region = hot_place["region"]
    items = hot_place["hot_items"]
    doms = sorted({it["domain"] for it in items})
    dirs = ", ".join(
        f"{it['indicator']}{'↑' if it['direction']=='상승' else '↓'}" for it in items
    )
    lead = hot_place["causal_edges"][0] if hot_place["causal_edges"] else None
    kw = topics.keyword_line(8) if topics and topics.top_keywords else "수집된 뉴스 없음"

    body = f"""# {region}, {' · '.join(doms)} 지표 동반 이상 신호 ({week})

## 무슨 신호인가
{region}에서 이번 주 Mahalanobis 거리 D²={hot_place['d2']}(p={hot_place['p_value']})의
다변량 이상이 탐지됐다. 단일 지표가 아니라 {dirs} 등 여러 지표가 평소 분포에서 동시에 벗어났다.

## 어떤 구조인가
신호는 {' · '.join(doms)} 도메인에 걸쳐 있다. """
    if lead:
        body += (f"Granger 검정에서는 `{lead['source']}`가 `{lead['target']}`를 "
                 f"{lead['lag']}주 선행해, 조기경보 후보로 볼 수 있다(예측적 선행이며 인과 확정은 아님).")
    else:
        body += "유의한 선행관계는 검출되지 않았다."
    body += f"""

## 정황은 무엇인가
같은 기간 지역 보도의 주요 키워드는 {kw} 등이다. 다만 이는 정황 단서일 뿐,
보도 내용이 신호의 원인이라고 단정할 수 없다.

## 연구적 함의와 후속 검증
도메인 교차 동조화는 국지적 충격의 부문 간 전이 가능성을 시사한다.
후속으로 외생 사건(공시·행정자료) 매칭과 인접 시군 공간효과를 확인할 필요가 있다.

*(자동 생성 초안 — ANTHROPIC_API_KEY 설정 시 Claude 기반 기사로 대체됩니다.)*"""
    return Article(title=f"{region} 분석기사(초안)", body=body, model="template-fallback")


def write(hot_place: dict, topics, week: str) -> Article:
    """핫 플레이스 1곳에 대한 분석기사 생성."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return _template(hot_place, topics, week)
    try:
        import anthropic
    except ImportError:
        return _template(hot_place, topics, week)

    client = anthropic.Anthropic()
    prompt = _build_prompt(hot_place, topics, week)
    try:
        # 긴 출력 가능 → streaming + get_final_message (타임아웃 방지)
        with client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
    except Exception as e:
        print(f"[article] Claude 호출 실패: {e} → 템플릿 폴백")
        return _template(hot_place, topics, week)

    text = next((b.text for b in msg.content if b.type == "text"), "").strip()
    if not text:
        return _template(hot_place, topics, week)
    title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")),
                 f"{hot_place['region']} 분석기사")
    return Article(title=title, body=text, model=MODEL)
