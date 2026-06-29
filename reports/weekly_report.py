"""
weekly_report.py - 전북 지역동향 주간 리포트 PDF 생성기.

참고 포맷(슬라이드 덱형 연구보고서: 표지·목차·섹션구분·개조식 본문·표/차트·
출처각주·페이지번호)을 reportlab(가로 A4, 맑은 고딕)으로 구현하고,
pipeline/jeonbuk 실분석 산출(JSON)을 실어 15~20p 보고서를 만든다.

  python reports/weekly_report.py            # 기본 2026-06-30
  python reports/weekly_report.py 2026-06-30
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image,
                                NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).parent.parent
OUT = ROOT / "jeonbuk" / "output"
TMP = Path(__file__).parent / "_charts"
TMP.mkdir(exist_ok=True)

MALGUN = "C:/Windows/Fonts/malgun.ttf"
MALGUN_BD = "C:/Windows/Fonts/malgunbd.ttf"
pdfmetrics.registerFont(TTFont("Malgun", MALGUN))
pdfmetrics.registerFont(TTFont("MalgunBd", MALGUN_BD))
font_manager.fontManager.addfont(MALGUN)
plt.rcParams["font.family"] = font_manager.FontProperties(fname=MALGUN).get_name()
plt.rcParams["axes.unicode_minus"] = False

NAVY = colors.HexColor("#1b2a4a")
BLUE = colors.HexColor("#2e6cc4")
ACCENT = colors.HexColor("#e08a1e")
LGRAY = colors.HexColor("#eef1f6")
DGRAY = colors.HexColor("#5a6675")
DOMAIN_HEX = {"경제": "#2e6cc4", "환경": "#2faa6e", "보건": "#d8543e", "인구이동": "#8a6bd6"}

PW, PH = landscape(A4)
M = 16 * mm


def _s(name, **kw):
    base = dict(fontName="Malgun", fontSize=10.5, leading=15, textColor=colors.HexColor("#222a36"))
    base.update(kw)
    return ParagraphStyle(name, **base)

ST = {
    "cover_t": _s("cover_t", fontName="MalgunBd", fontSize=34, leading=42, textColor=NAVY, alignment=TA_CENTER),
    "cover_s": _s("cover_s", fontSize=15, leading=22, textColor=DGRAY, alignment=TA_CENTER),
    "cover_m": _s("cover_m", fontSize=11, leading=17, textColor=DGRAY, alignment=TA_CENTER),
    "title": _s("title", fontName="MalgunBd", fontSize=19, leading=23, textColor=NAVY),
    "lead": _s("lead", fontSize=11.5, leading=16, textColor=colors.HexColor("#2b3440")),
    "b1": _s("b1", fontSize=10.5, leading=16, leftIndent=10, spaceBefore=2),
    "b2": _s("b2", fontSize=9.8, leading=14.5, leftIndent=24, textColor=colors.HexColor("#39424f")),
    "src": _s("src", fontSize=8, leading=10, textColor=colors.HexColor("#9aa3b0")),
    "cell": _s("cell", fontSize=9.3, leading=12.5),
    "cellb": _s("cellb", fontName="MalgunBd", fontSize=9.3, leading=12.5, textColor=colors.white),
    "caption": _s("caption", fontSize=9, leading=12, textColor=DGRAY, alignment=TA_CENTER),
}


def bullet(text, level=1):
    mark = "▪" if level == 1 else "•"
    sty = "b1" if level == 1 else "b2"
    col = BLUE if level == 1 else DGRAY
    return Paragraph(f"<font color='{col}'>{mark}</font>&nbsp;&nbsp;{text}", ST[sty])


def title_block(title, lead):
    return [Spacer(1, 4), Paragraph(title, ST["title"]),
            Paragraph(f"<font color='#2e6cc4'>▪</font>&nbsp;&nbsp;{lead}", ST["lead"]),
            Spacer(1, 8)]


def styled_table(header, rows, col_widths, hot_rows=None):
    data = [[Paragraph(h, ST["cellb"]) for h in header]]
    for r in rows:
        data.append([Paragraph(str(c), ST["cell"]) for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LGRAY]),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2de")),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 6)]
    for hr in (hot_rows or []):
        style.append(("BACKGROUND", (0, hr), (-1, hr), colors.HexColor("#fdeccd")))
    t.setStyle(TableStyle(style))
    return t


DIV_W, DIV_H = 250 * mm, 165 * mm

def section_divider(num, name, subtitle=""):
    class _Div(Flowable):
        def __init__(self): super().__init__(); self.width = DIV_W; self.height = DIV_H
        def draw(self):
            c = self.canv
            c.setFillColor(NAVY); c.rect(0, 0, DIV_W, DIV_H, fill=1, stroke=0)
            c.setFillColor(ACCENT); c.rect(30 * mm, DIV_H * 0.40, 62 * mm, 3, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont("MalgunBd", 76); c.drawString(28 * mm, DIV_H * 0.55, num)
            c.setFont("MalgunBd", 30); c.drawString(30 * mm, DIV_H * 0.45, name)
            if subtitle:
                c.setFont("Malgun", 13); c.setFillColor(colors.HexColor("#aebbd0"))
                c.drawString(30 * mm, DIV_H * 0.34, subtitle)
    return [Spacer(1, 4), _Div()]


def _md_to_bullets(md: str, cap=4) -> list:
    out, body = [], []
    for line in md.splitlines():
        t = line.strip()
        if not t or t.startswith("#") or t.startswith("*("):
            continue
        body.append(t.replace("**", ""))
    for t in body[:cap]:
        out.append(bullet(t, 2))
    return out


# ── 차트 ───────────────────────────────────────────────────────────────────
def _bar(labels, vals, cols, xlabel, path, w=8.4, h=4.0):
    fig, ax = plt.subplots(figsize=(w, h), dpi=150)
    ax.barh(labels, vals, color=cols)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.tick_params(labelsize=9)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def make_charts(signal, news):
    rk = signal["ranking"][::-1]
    _bar([r["region"] for r in rk], [r["d2"] for r in rk],
         ["#e08a1e" if r.get("is_hot") else "#9bb4d4" for r in rk],
         "Mahalanobis D² (인구정규화 횡단면)", TMP / "rank.png", 8.4, 4.2)
    tp = news["topics"][::-1]
    _bar([f"T{t['rank']} {t['label']}" for t in tp], [t["weight"] * 100 for t in tp],
         "#2e6cc4", "코퍼스 내 비중 (%)", TMP / "topics.png", 8.4, 3.6)
    act = [(m, c) for m, c in sorted(news["region_activity"].items(), key=lambda x: x[1]) if c > 0]
    _bar([m for m, _ in act], [c for _, c in act], "#2faa6e", "언급 기사 수", TMP / "act.png", 8.4, 3.6)


def chart_items(items, path):
    it = items[::-1]
    _bar([i["indicator"] for i in it], [i["share"] * 100 for i in it],
         [DOMAIN_HEX.get(i["domain"], "#2e6cc4") for i in it], "D² 기여도 (%)", path, 5.0, 2.5)


# ── 빌드 ───────────────────────────────────────────────────────────────────
def make_onpage(ctx_label):
    def _p(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY); canvas.rect(0, PH - 18 * mm, PW, 18 * mm, fill=1, stroke=0)
        canvas.setFillColor(ACCENT); canvas.rect(0, PH - 18 * mm, 6 * mm, 18 * mm, fill=1, stroke=0)
        canvas.setFont("MalgunBd", 10); canvas.setFillColor(colors.white)
        canvas.drawString(12 * mm, PH - 12 * mm, ctx_label)
        canvas.drawRightString(PW - 12 * mm, PH - 12 * mm, "전북 지역동향 주간 리포트")
        canvas.setStrokeColor(colors.HexColor("#d5dae3")); canvas.setLineWidth(0.5)
        canvas.line(12 * mm, 12 * mm, PW - 12 * mm, 12 * mm)
        canvas.setFont("Malgun", 8); canvas.setFillColor(DGRAY)
        canvas.drawString(12 * mm, 7 * mm, "전북 생활문화 핫플레이스 신호탐지 시스템")
        canvas.drawRightString(PW - 12 * mm, 7 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()
    return _p


def _plain(canvas, doc):
    pass


def build(week: str):
    signal = json.loads((OUT / f"signal_{week}.json").read_text(encoding="utf-8"))
    brief = json.loads((OUT / f"brief_{week}.json").read_text(encoding="utf-8"))
    news = json.loads((OUT / f"news_analysis_{week}.json").read_text(encoding="utf-8"))
    briefs = {b["region"]: b for b in brief["briefs"]}
    make_charts(signal, news)

    cfh = PH - 18 * mm - 16 * mm    # content frame height (헤더18 + 푸터여백16 제외)
    def cframe():
        return Frame(M, 14 * mm, PW - 2 * M, cfh, id="c")
    SECTIONS = [("toc", "목차"), ("s1", "1. 리포트 개요"), ("s2", "2. 핫 플레이스 종합"),
                ("s3", "3. 핫 아이템 분석"), ("s4", "4. 뉴스 빅데이터 분석"), ("s5", "5. 종합 및 시사점")]
    templates = [PageTemplate(id="plain", frames=[Frame(M, M, PW - 2 * M, PH - 2 * M)], onPage=_plain)]
    for sid, label in SECTIONS:
        templates.append(PageTemplate(id=sid, frames=[cframe()], onPage=make_onpage(label)))

    s = []

    # 표지 (plain)
    s += [Spacer(1, PH * 0.28),
          Paragraph("전북 지역동향 주간 리포트", ST["cover_t"]), Spacer(1, 8),
          Paragraph("다변량 이상신호 탐지 · 인과 진단 · 뉴스 빅데이터 분석", ST["cover_s"]), Spacer(1, 42),
          Paragraph(f"분석 기준주 : {week}", ST["cover_m"]),
          Paragraph("전북 생활문화 핫플레이스 신호탐지 시스템", ST["cover_m"]),
          NextPageTemplate("toc"), PageBreak()]

    # 목차
    s += title_block("목차", "본 리포트는 5개 장으로 구성된다.")
    toc = [["1", "리포트 개요", "분석 대상·데이터 소스·방법론"],
           ["2", "핫 플레이스 종합", "시군별 이상신호 랭킹 및 상위 3곳 상세"],
           ["3", "핫 아이템 분석", "신호를 만든 지표 조합과 방향"],
           ["4", "뉴스 빅데이터 분석", "구조적 토픽모델링 및 지역별 드릴다운"],
           ["5", "종합 및 시사점", "연구적 함의·한계·후속 과제"]]
    s.append(styled_table(["장", "제목", "내용"], toc, [20 * mm, 70 * mm, 150 * mm]))

    def divider(num, name, next_tpl):
        return [NextPageTemplate("plain"), PageBreak(), *section_divider(num, name),
                NextPageTemplate(next_tpl), PageBreak()]

    # ── 1. 리포트 개요 ──
    s += divider("1", "리포트 개요", "s1")
    s += title_block("분석 개요",
                     "전북 14개 시군의 경제·환경·보건·인구이동 지표와 지역 뉴스를 결합해 주간 이상신호를 탐지한다.")
    s += [bullet("<b>분석 대상</b> : 전라북도 14개 시군 (전주·군산·익산·정읍·남원·김제·완주·진안·무주·장수·임실·순창·고창·부안)"),
          bullet("<b>분석 기준주</b> : " + week + " (주간)"),
          bullet("<b>분석 프레임</b> : ① 핫 플레이스(다변량 이상탐지) → ② 핫 아이템(기여 분해) → ③ 뉴스 맥락(토픽모델링)"),
          bullet("핫 플레이스 = 단순 수치가 높은 곳이 아니라 <b>여러 지표가 동시에 평소와 다르게 움직인 곳</b>", 2),
          bullet("개수형 지표는 <b>인구 1만명당으로 정규화</b>하여 도시 규모 효과를 제거", 2),
          Spacer(1, 6), bullet("<b>핵심 요약</b>"),
          bullet(f"이번 주 핫 플레이스 : <b>{', '.join(h['region'] for h in signal['hot_places'])}</b> (총 {signal['n_hot_places']}곳)", 2),
          bullet(f"뉴스 빅데이터 : 실수집 기사 <b>{news['n_docs']}건</b>을 {news.get('n_topics',0)}개 토픽으로 구조화", 2),
          Spacer(1, 6), Paragraph("* 출처 : 소상공인 상권정보·HIRA·에어코리아·네이버 뉴스 등 공공·민간 API", ST["src"]),
          PageBreak()]

    s += title_block("데이터 소스 현황", "도메인별 수집 소스와 실수집/추정 상태를 정리한다.")
    src_rows = [["경제", "소상공인 상권정보(음식점 수)", "data.go.kr", "● 실수집"],
                ["보건", "HIRA 의료기관 수", "data.go.kr", "● 실수집"],
                ["환경", "에어코리아 PM10·PM25", "data.go.kr", "● 실수집"],
                ["뉴스", "네이버 뉴스 + 전북 언론 RSS", "naver / RSS", "● 실수집"],
                ["경제", "음식점 신규·폐업 (식약처)", "foodsafetykorea", "○ 추정(키 필요)"],
                ["인구이동", "전입·전출·20대 순이동 (KOSIS)", "kosis.kr", "○ 추정(키 필요)"],
                ["보건", "감염병 신고수 (KDCA)", "data.go.kr", "○ 추정(키 필요)"]]
    s.append(styled_table(["도메인", "지표/소스", "제공처", "상태"], src_rows,
                          [26 * mm, 95 * mm, 50 * mm, 40 * mm], hot_rows=[1, 2, 3, 4]))
    s += [Spacer(1, 6),
          bullet("실수집 도메인(경제·보건·환경·뉴스)은 본 리포트에서 확정적으로 서술"),
          bullet("추정 도메인은 키 발급 전까지 참고용이며, 본문에 <b>‘추정’</b>으로 명시", 2),
          Spacer(1, 4), Paragraph("* 추정치는 모형 기반 보간값", ST["src"])]

    # ── 2. 핫 플레이스 종합 ──
    s += divider("2", "핫 플레이스 종합", "s2")
    s += title_block("시군별 이상신호 랭킹",
                     "14개 시군을 서로 비교한 횡단면 Mahalanobis 거리(인구정규화) 기준 랭킹이다.")
    s.append(Image(str(TMP / "rank.png"), width=205 * mm, height=103 * mm))
    s.append(Paragraph("〔그림 1〕 시군별 Mahalanobis D² (주황 = 핫 플레이스)", ST["caption"]))
    s += [Spacer(1, 2),
          bullet(f"상위 3개 시군 : <b>{', '.join(h['region'] for h in signal['hot_places'])}</b> — 인구 대비 지표가 비정상적인 군 지역이 상위에 위치"),
          PageBreak()]

    for rank, hp in enumerate(signal["hot_places"], 1):
        reg = hp["region"]; b = briefs.get(reg, {})
        chart_items(hp["hot_items"], TMP / f"item_{rank}.png")
        s += title_block(f"{rank}위 · {reg}",
                         f"Mahalanobis D² = {hp['d2']} (p = {hp['p_value']}) · {hp.get('method','')}")
        item_rows = [[it["indicator"], it["domain"], it["direction"], f"{it['z']:+.1f}",
                      f"{it['share']*100:.0f}%", "추정" if it.get("estimated") else "실수집"]
                     for it in hp["hot_items"]]
        left = [Paragraph("<b>핫 아이템 — 신호를 만든 지표</b>", ST["b1"]), Spacer(1, 4),
                styled_table(["지표", "도메인", "방향", "z", "기여", "출처"], item_rows,
                             [32 * mm, 20 * mm, 14 * mm, 14 * mm, 15 * mm, 17 * mm])]
        right = [Image(str(TMP / f"item_{rank}.png"), width=108 * mm, height=54 * mm)]
        s.append(Table([[left, right]], colWidths=[116 * mm, 116 * mm],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
        s += [Spacer(1, 4), bullet("<b>해석</b>")]
        s += _md_to_bullets(b.get("article_body", ""), cap=4)
        s += [Spacer(1, 3),
              Paragraph(f"* 뉴스 {b.get('n_articles',0)}건 분석 · 기사작성 모델 {b.get('article_model','-')}", ST["src"])]
        if rank < len(signal["hot_places"]):
            s.append(PageBreak())

    # ── 3. 핫 아이템 분석 ──
    s += divider("3", "핫 아이템 분석", "s3")
    s += title_block("지표 조합 종합", "핫 플레이스별로 신호를 만든 지표를 도메인 관점에서 종합한다.")
    allrows = []
    for hp in signal["hot_places"]:
        for it in hp["hot_items"][:3]:
            allrows.append([hp["region"], it["indicator"], it["domain"], it["direction"],
                            "추정" if it.get("estimated") else "실수집"])
    s.append(styled_table(["시군", "지표", "도메인", "방향", "출처"], allrows,
                          [34 * mm, 46 * mm, 30 * mm, 24 * mm, 30 * mm]))
    s += [Spacer(1, 8),
          bullet("도메인 교차 동조화(경제+인구이동+보건 동시 변동)는 국지적 충격의 부문 간 전이 가능성을 시사"),
          bullet("단, 인구이동·음식점 증감 등은 <b>추정치</b>로, 실측 전까지 확정 해석은 보류", 2),
          bullet("주간 데이터가 누적되면 시차 인과(Granger)로 선행→후행 구조 분석 가능", 2),
          Spacer(1, 4), Paragraph("* 방법 : D² 기여도 분해(기여 합 = D²)", ST["src"])]

    # ── 4. 뉴스 빅데이터 분석 ──
    s += divider("4", "뉴스 빅데이터 분석", "s4")
    s += title_block("구조적 토픽모델링 (STM 스타일)",
                     f"실수집 뉴스 {news['n_docs']}건을 NMF로 분해하고, 지역을 공변량으로 토픽 prevalence를 분석한다.")
    s.append(Image(str(TMP / "topics.png"), width=200 * mm, height=86 * mm))
    s.append(Paragraph("〔그림 2〕 코퍼스 전체 토픽 비중", ST["caption"]))
    top_rows = [[f"토픽 {t['rank']}", t["label"], ", ".join(t["keywords"][:6]), f"{t['weight']*100:.0f}%"]
                for t in news["topics"]]
    s += [Spacer(1, 2),
          styled_table(["#", "라벨", "대표어", "비중"], top_rows, [20 * mm, 40 * mm, 140 * mm, 20 * mm]),
          PageBreak()]

    s += title_block("시군별 뉴스 활동량 및 드릴다운", "시군 언급 기사 수와 활동량 상위 지역의 키워드를 정리한다.")
    s.append(Image(str(TMP / "act.png"), width=190 * mm, height=82 * mm))
    s.append(Paragraph("〔그림 3〕 시군별 언급 기사 수", ST["caption"]))
    act = sorted(news["region_activity"].items(), key=lambda x: -x[1])
    reg_rows = [[m, str(c), ", ".join(news["regions"].get(m, {}).get("keywords", [])[:6])]
                for m, c in act[:6] if c > 0]
    s += [Spacer(1, 2),
          styled_table(["시군", "기사", "상위 키워드"], reg_rows, [30 * mm, 18 * mm, 172 * mm]),
          Spacer(1, 3),
          Paragraph("* 지역 태깅 = 기사 내 시군명 매칭(스쳐 언급 포함). 형태소 분석기 미적용 시 일부 노이즈", ST["src"])]

    # ── 5. 종합 및 시사점 ──
    s += divider("5", "종합 및 시사점", "s5")
    s += title_block("종합 해석 및 연구적 함의", "이번 주 신호를 종합하고 연구·정책적 함의를 제시한다.")
    hot_names = ", ".join(h["region"] for h in signal["hot_places"])
    s += [bullet(f"<b>이번 주 핫 플레이스</b> : {hot_names} — 인구 대비 지표가 비정상적인 군 지역에서 신호 발생"),
          bullet("관광·생활인구 기반 군 지역은 상주인구 대비 상업·의료 밀도가 높아 신호로 포착됨", 2),
          bullet("<b>뉴스 맥락</b> : 'AI·반도체·새만금', '서남권 해상풍력' 등 대형 개발 의제가 코퍼스를 주도"),
          bullet("지역 경제 신호와 외부 투자/개발 뉴스의 연계는 후속 인과 분석 대상", 2),
          bullet("<b>연구적 함의</b> : 다변량 이상탐지 + 토픽모델링 결합으로 ‘무엇이·어디서·왜’를 정량+정성으로 동시 포착"),
          Spacer(1, 4), Paragraph("* Granger 등 시차 인과는 예측적 선행이며 인과 확정이 아님", ST["src"]),
          PageBreak()]

    s += title_block("한계 및 후속 과제", "본 리포트의 한계와 데이터·방법론 고도화 과제를 정리한다.")
    s += [bullet("<b>데이터</b> : 인구이동(KOSIS)·음식점 증감(식약처)·감염병(KDCA)은 키 발급 전까지 추정치"),
          bullet("키 확보 시 ‘청년 이탈’·‘폐업 급증’ 등 핵심 변화지표를 실측으로 전환", 2),
          bullet("<b>방법론</b> : 현재는 1주 횡단면 비교 → 주간 누적 시 시계열 이상탐지 및 Granger 인과 가능"),
          bullet("뉴스 지역 태깅 정밀화(제목 가중·개체명 인식)·형태소 분석기(konlpy) 적용으로 토픽 품질 향상", 2),
          bullet("<b>운영</b> : 매주 자동 수집·분석·리포트 생성 → 4주 누적 시 월간 리포트(30~40p) 산출"),
          Spacer(1, 6),
          bullet("본 주간 리포트는 자동 생성 결과이며, 추정 항목은 실측 확보 후 갱신 예정", 2),
          Paragraph("* 시스템 : github.com/KHYTV/jeonbuk-research-system", ST["src"])]

    out_pdf = Path(__file__).parent / f"주간리포트_{week}.pdf"
    doc = BaseDocTemplate(str(out_pdf), pagesize=landscape(A4),
                          leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=M,
                          title=f"전북 지역동향 주간 리포트 {week}", author="전북 신호탐지 시스템")
    doc.addPageTemplates(templates)
    doc.build(s)
    return out_pdf


if __name__ == "__main__":
    week = sys.argv[1] if len(sys.argv) > 1 else "2026-06-30"
    print("생성 완료:", build(week))
