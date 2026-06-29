"""
topics.py - 뉴스 코퍼스 토픽모델링 + 키워드 분석.

수집한 기사 텍스트에서
  (1) 상위 키워드   : TF-IDF 가중치 기준
  (2) 토픽          : NMF 로 분해한 잠재 주제별 대표어
를 뽑는다. 이 결과가 LLM 분석기사의 '근거 재료'가 된다.

한국어 형태소 분석기(konlpy)가 있으면 명사 추출에 쓰고,
없으면 정규식 토크나이즈 + 불용어 필터로 대체한다(의존성 최소화).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from . import config as C

# 한국어/영문/숫자 토큰 (2자 이상)
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+%?")

# 뉴스에서 흔하지만 의미 적은 불용어
_STOP = {
    "기자", "뉴스", "사진", "제공", "지역", "대한", "관련", "이번", "지난", "올해",
    "오늘", "내년", "지난해", "위해", "통해", "대해", "라고", "한다", "했다", "이라고",
    "에서", "으로", "그리고", "하지만", "또한", "전북", "전라북도", "도내", "현장",
    "분석", "동향", "주목", "배경", "전문가", "관측", "관심",
    "있다", "있는", "없다", "되고", "되는", "보이", "나서", "커지", "다는", "이라는",
    "quot", "amp", "nbsp", "lt", "gt", "apos",  # HTML 엔티티 잔여 노이즈
}

# 형태소 분석기가 없을 때 명사 어근에 가깝게 만드는 경량 조사/어미 제거.
# 긴 접미사부터 시도(욕심 매칭).
_SUFFIXES = [
    "에서는", "에게서", "으로서", "으로써", "이라고", "라고는", "에서도",
    "에서", "에게", "으로", "라고", "이라", "에는", "에도", "와는", "과는",
    "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "께",
]


def _strip_josa(tok: str) -> str:
    if not ("가" <= tok[0] <= "힣"):
        return tok
    for suf in _SUFFIXES:
        if len(tok) > len(suf) + 1 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


@dataclass
class Topic:
    rank: int
    keywords: list[str]      # 대표어
    weight: float            # 코퍼스 내 상대 비중


@dataclass
class TopicResult:
    top_keywords: list[tuple[str, float]]   # (단어, TF-IDF 합) 내림차순
    topics: list[Topic]
    n_docs: int

    def keyword_line(self, k: int = 10) -> str:
        return ", ".join(w for w, _ in self.top_keywords[:k])


def _tokenize(text: str) -> list[str]:
    out = []
    for raw in _TOKEN_RE.findall(text):
        t = _strip_josa(raw)
        if len(t) >= 2 and t not in _STOP:
            out.append(t)
    return out


def _okt_tokenize(text: str):
    """konlpy 가 설치돼 있으면 명사만 추출(없으면 None)."""
    try:
        from konlpy.tag import Okt
        okt = Okt()
        return [n for n in okt.nouns(text) if n not in _STOP and len(n) >= 2]
    except Exception:
        return None


def analyze(texts: list[str], n_topics: int = 5) -> TopicResult:
    """기사 텍스트 리스트 → 키워드 + 토픽."""
    docs = [t for t in texts if t and t.strip()]
    if len(docs) < 2:
        return TopicResult(top_keywords=[], topics=[], n_docs=len(docs))

    use_okt = _okt_tokenize(docs[0]) is not None
    tokenizer = _okt_tokenize if use_okt else _tokenize

    vec = TfidfVectorizer(
        tokenizer=tokenizer, lowercase=False, token_pattern=None,
        max_df=0.95, min_df=1, ngram_range=(1, 1),
    )
    X = vec.fit_transform(docs)
    vocab = vec.get_feature_names_out()

    # 상위 키워드: 문서 전체 TF-IDF 합
    sums = X.sum(axis=0).A1
    order = sums.argsort()[::-1]
    top_keywords = [(vocab[i], float(sums[i])) for i in order[: C.NEWS_TOP_KEYWORDS * 3]]
    top_keywords = top_keywords[: C.NEWS_TOP_KEYWORDS]

    # 토픽: NMF
    k = max(1, min(n_topics, X.shape[0], X.shape[1]))
    topics: list[Topic] = []
    if X.shape[1] >= 2:
        nmf = NMF(n_components=k, init="nndsvda", random_state=0, max_iter=400)
        W = nmf.fit_transform(X)
        H = nmf.components_
        topic_mass = W.sum(axis=0)
        total = topic_mass.sum() or 1.0
        for ti in topic_mass.argsort()[::-1]:
            terms = [vocab[i] for i in H[ti].argsort()[::-1][:6]]
            topics.append(Topic(rank=len(topics) + 1, keywords=terms,
                                 weight=float(topic_mass[ti] / total)))
    return TopicResult(top_keywords=top_keywords, topics=topics, n_docs=len(docs))
