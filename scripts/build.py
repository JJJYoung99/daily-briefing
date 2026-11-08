"""매일 아침 피드: AI·IT 소식과 주식·코인 시장을 초보용 한국어 브리핑 한 페이지로 만든다.

GitHub Actions가 매일 아침 이 스크립트를 실행하고, 결과(docs/)를 GitHub Pages로 공개한다.
- 뉴스와 시세는 공개 RSS·무료 API에서 직접 가져온다 (키 필요 없음).
- ANTHROPIC_API_KEY가 있으면 Claude가 초보 눈높이 설명을 써 준다.
- 키가 없거나 호출이 실패하면 제목과 숫자만으로 된 기본 브리핑을 만든다.
"""

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
KST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; daily-briefing/1.0; +https://github.com)"

AI_FEEDS = [
    ("긱뉴스", "https://news.hada.io/rss/news"),
    ("AI타임스", "https://www.aitimes.com/rss/allArticle.xml"),
]
MARKET_FEEDS = [
    ("한국경제 증권", "https://www.hankyung.com/feed/finance"),
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml"),
    ("블록미디어", "https://www.blockmedia.co.kr/feed"),
]


def gnews(query, lang="ko"):
    """Google 뉴스 검색 RSS 주소 (키 필요 없음)."""
    q = urllib.request.quote(query)
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


SKIN_FEEDS = [
    ("피부미용 뉴스", gnews("피부과 레이저 OR 리프팅 OR 보톡스 OR 필러 OR 스킨부스터 OR 미용의료기기 when:7d")),
    ("Aesthetic news", gnews('"aesthetic" (device OR laser OR "FDA clearance" OR injectable OR dermatology) when:7d', "en")),
]

# PubMed에서 최근 1주일 피부미용 관련 논문 검색어
PUBMED_TERM = (
    '(laser[tiab] OR "energy-based device"[tiab] OR radiofrequency[tiab] OR "focused ultrasound"[tiab] '
    'OR botulinum[tiab] OR "hyaluronic acid filler"[tiab] OR microneedling[tiab] OR "skin booster"[tiab] '
    'OR exosome[tiab] OR "poly-L-lactic"[tiab] OR polynucleotide[tiab] OR "intense pulsed light"[tiab]) '
    'AND (aesthetic[tiab] OR cosmetic[tiab] OR rejuvenation[tiab] OR melasma[tiab] OR scar[tiab] '
    'OR wrinkle[tiab] OR pigmentation[tiab] OR acne[tiab]) '
    'AND (skin[tiab] OR dermatol*[tiab] OR facial[tiab] OR face[tiab] OR cutaneous[tiab]) AND hasabstract'
)

# 키가 없을 때 쓰는 '피부미용 기초 지식'
SKIN_BASICS = [
    ("피부의 세 층", "피부는 겉의 표피, 그 아래 콜라겐이 많은 진피, 지방이 있는 피하조직으로 나뉘어요. 레이저나 리프팅 기기는 어느 층을 겨냥하느냐에 따라 효과가 달라져요."),
    ("선택적 광열분해", "특정 파장의 빛이 멜라닌·헤모글로빈·물 같은 특정 대상에만 흡수되게 해서, 주변은 덜 다치게 하고 목표만 열로 파괴하는 원리예요. 거의 모든 피부 레이저의 기본 개념이에요."),
    ("나노초 vs 피코초 레이저", "빛을 쏘는 시간이 10억분의 1초(나노초)냐 1조분의 1초(피코초)냐의 차이예요. 피코초는 열보다 충격파로 색소를 잘게 부숴서 문신·색소 치료에 많이 써요."),
    ("프랙셔널 레이저", "피부 전체가 아니라 아주 작은 점들만 촘촘히 치료해서, 주변 정상 피부가 회복을 돕게 하는 방식이에요. 흉터와 모공 치료에 많이 써요."),
    ("고주파(RF)", "전류가 피부 조직을 지나며 생기는 열로 진피를 데워 콜라겐 수축과 재생을 유도해요. 써마지 같은 리프팅 장비가 대표적이에요."),
    ("HIFU(고강도 집속 초음파)", "돋보기로 햇빛을 모으듯 초음파를 한 점에 모아 깊은 층(근막층 포함)에 열 점을 만드는 원리예요. 울쎄라 같은 리프팅 장비가 여기에 속해요."),
    ("보툴리눔 톡신", "신경에서 근육으로 가는 신호(아세틸콜린 분비)를 잠시 막아 근육을 쉬게 해요. 표정 주름에 효과가 있고 보통 3~6개월 지속돼요."),
    ("히알루론산 필러", "피부에 원래 있는 성분인 히알루론산을 젤 형태로 넣어 볼륨을 채워요. 히알루로니다제라는 효소로 녹일 수 있다는 게 큰 장점이에요."),
    ("필러 혈관 폐색", "필러가 혈관을 막거나 누르면 피부 괴사나 드물게 시력 손상이 생길 수 있어요. 해부학 지식과 빠른 대처가 중요한 가장 심각한 합병증이에요."),
    ("콜라겐 자극제", "PLLA, PCL, CaHA 같은 성분은 바로 채우기보다 몸이 스스로 콜라겐을 만들도록 자극해요. 효과는 서서히 나타나고 오래가는 편이에요."),
    ("PDRN과 폴리뉴클레오타이드", "연어 DNA에서 얻은 성분으로 조직 재생과 염증 완화를 돕는다고 알려져 '스킨부스터'로 많이 써요. 근거 수준은 연구마다 차이가 있어요."),
    ("기미(멜라즈마)", "호르몬, 자외선, 혈관, 염증이 함께 얽혀 생기는 색소 질환이라 재발이 잦아요. 강한 레이저는 오히려 악화시킬 수 있어 조심스럽게 접근해요."),
    ("염증후 과색소침착(PIH)", "여드름이나 시술 뒤 염증이 지나간 자리에 색소가 남는 현상이에요. 아시아인 피부에서 특히 흔해서 시술 강도 조절이 중요해요."),
    ("피츠패트릭 피부 유형", "자외선에 타는 정도로 피부를 1~6형으로 나눈 기준이에요. 한국인은 주로 3~4형이고, 레이저 설정을 정할 때 기본 정보로 써요."),
    ("여드름 흉터 종류", "아이스픽, 박스카, 롤링형 등으로 나뉘어요. 흉터 모양마다 잘 맞는 치료(레이저, 서브시전, TCA 등)가 달라요."),
    ("IPL(광선 치료)", "레이저처럼 한 파장이 아니라 여러 파장의 빛을 한꺼번에 쏘는 장비예요. 홍조와 잡티를 함께 개선할 때 많이 써요."),
    ("마이크로니들링", "아주 가는 바늘로 미세한 상처를 내서 피부가 스스로 회복하며 콜라겐을 만들게 해요. 고주파를 함께 쓰는 '니들 RF'도 많아요."),
    ("UVA와 UVB", "UVB는 피부를 빨갛게 태우고, UVA는 깊이 들어가 노화와 색소를 만들어요. SPF는 UVB, PA는 UVA 차단 정도를 나타내요."),
    ("레티노이드", "비타민 A 유도체로 피부 세포 교체를 빠르게 하고 콜라겐 생성을 도와요. 근거가 가장 탄탄한 바르는 노화 방지 성분 중 하나예요."),
    ("피부 장벽", "각질층의 세포와 지질(세라마이드 등)이 벽돌과 시멘트처럼 수분을 지키고 자극을 막아요. 시술 후 회복의 핵심이에요."),
    ("엑소좀", "세포가 내보내는 아주 작은 주머니로, 재생 신호를 전달한다고 연구되고 있어요. 미용 분야에서 인기지만 아직 표준화와 근거가 부족한 편이에요."),
    ("레이저 토닝", "낮은 에너지로 여러 번 나눠 치료해서 색소를 조금씩 줄이는 방법이에요. 기미 치료에 많이 쓰지만 과하면 저색소 반점이 생길 수 있어요."),
]

# 키가 없을 때 쓰는 '오늘의 용어' (날짜에 따라 돌아가며 하나씩)
TERMS = [
    ("코스피(KOSPI)", "한국 유가증권시장에 상장된 회사들의 주가를 한데 모은 지수예요. 한국 대형주의 전체 분위기를 보여줘요."),
    ("나스닥(NASDAQ)", "애플, 엔비디아 같은 미국 기술 기업이 많이 상장된 시장이에요. AI·반도체 분위기를 볼 때 가장 많이 봐요."),
    ("시가총액", "주가 × 주식 수. 회사의 '몸값'이에요. 주가가 높다고 큰 회사인 건 아니에요."),
    ("PER(주가수익비율)", "주가가 1년 이익의 몇 배인지 보여줘요. 높으면 '기대가 크다', 낮으면 '싸거나 걱정이 많다'는 뜻일 수 있어요."),
    ("배당", "회사가 번 돈 일부를 주주에게 나눠 주는 것이에요. 은행 이자와 비슷하게 생각하면 쉬워요."),
    ("ETF", "여러 주식을 한 바구니에 담아 주식처럼 사고팔 수 있게 만든 상품이에요. 초보가 분산투자하기 좋은 방법이에요."),
    ("분산투자", "한 곳에 몰지 않고 여러 곳에 나눠 투자하는 것이에요. 하나가 떨어져도 전체 손실을 줄여 줘요."),
    ("기준금리", "중앙은행이 정하는 기본 금리예요. 오르면 대출이 비싸져 주식·코인에 부담, 내리면 반대예요."),
    ("인플레이션", "물가가 계속 오르는 현상이에요. 같은 돈으로 살 수 있는 게 줄어든다는 뜻이에요."),
    ("외국인 순매도", "외국인 투자자가 산 것보다 판 게 많다는 뜻이에요. 한국 증시에서는 외국인 비중이 커서 지수에 영향을 크게 줘요."),
    ("서킷브레이커", "주가가 너무 빨리 떨어질 때 거래를 잠시 멈추는 장치예요. 공포에 한꺼번에 파는 걸 막아 줘요."),
    ("변동성", "가격이 얼마나 크게 출렁이는지를 말해요. 코인은 주식보다 변동성이 훨씬 커요."),
    ("비트코인 반감기", "비트코인 채굴 보상이 약 4년마다 절반으로 줄어드는 일이에요. 새로 풀리는 양이 줄어들어요."),
    ("스테이블코인", "가격이 1달러 같은 기준에 묶이도록 설계된 코인이에요. 코인 거래에서 현금처럼 쓰여요."),
    ("거래소 지갑과 개인 지갑", "거래소에 맡긴 코인은 거래소가 보관하고, 개인 지갑은 내가 직접 열쇠(키)를 가져요. 키를 잃으면 되찾을 수 없어요."),
    ("손절", "손해를 보더라도 정해 둔 기준에서 팔아 더 큰 손실을 막는 것이에요. 미리 기준을 정해 두는 게 핵심이에요."),
    ("물타기", "가격이 떨어졌을 때 더 사서 평균 매수가를 낮추는 것이에요. 떨어지는 이유를 모르면 손실만 커질 수 있어요."),
    ("반도체 사이클", "반도체 수요와 가격이 좋아졌다 나빠졌다를 반복하는 흐름이에요. 삼성전자·SK하이닉스 주가가 크게 따라 움직여요."),
    ("LLM(대규모 언어 모델)", "엄청난 양의 글을 학습해 사람처럼 글을 이해하고 쓰는 AI예요. ChatGPT, Claude, Gemini가 여기에 속해요."),
    ("AI 에이전트", "질문에 답만 하는 게 아니라 검색, 파일 정리, 예약 같은 일을 스스로 여러 단계로 해 주는 AI예요."),
    ("GPU", "원래는 그래픽 처리용 칩인데, AI 학습에 꼭 필요해서 엔비디아가 큰돈을 벌게 된 부품이에요."),
    ("데이터센터", "수많은 서버 컴퓨터를 모아 둔 건물이에요. AI 서비스는 여기서 돌아가고, 전기를 엄청 많이 써요."),
    ("오픈소스", "누구나 코드를 보고 고치고 쓸 수 있게 공개한 소프트웨어예요. GitHub이 대표적인 공개 장소예요."),
    ("IPO(기업공개)", "회사가 주식시장에 처음 상장해서 누구나 그 회사 주식을 살 수 있게 되는 것이에요."),
]


# ---------- 데이터 가져오기 ----------

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def strip_tags(text, limit=220):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def read_feed(source, url, limit=12):
    """RSS 2.0과 Atom 둘 다 읽는다. 실패하면 빈 목록."""
    try:
        root = ET.fromstring(fetch(url))
    except Exception as e:  # 피드 하나가 죽어도 나머지는 계속
        print(f"[warn] {source} 피드 실패: {e}", file=sys.stderr)
        return []
    atom = "{http://www.w3.org/2005/Atom}"
    items = []
    for it in root.iter("item"):
        items.append({
            "source": source,
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "summary": strip_tags(it.findtext("description")),
        })
    for it in root.iter(atom + "entry"):
        link = it.find(atom + "link")
        items.append({
            "source": source,
            "title": (it.findtext(atom + "title") or "").strip(),
            "link": link.get("href", "") if link is not None else "",
            "summary": strip_tags(it.findtext(atom + "content") or it.findtext(atom + "summary")),
        })
    for i in items:
        i["link"] = re.sub(r"[&?]utm_[^&]+", "", i["link"])
    return [i for i in items if i["title"]][:limit]


def yahoo_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?range=5d&interval=1d"
    try:
        data = json.loads(fetch(url))["chart"]["result"][0]
        closes = [c for c in data["indicators"]["quote"][0]["close"] if c is not None]
        price = data["meta"]["regularMarketPrice"]
        prev = closes[-2] if len(closes) >= 2 else data["meta"].get("chartPreviousClose")
        when = dt.datetime.fromtimestamp(data["meta"]["regularMarketTime"], KST)
        return {"price": price, "change_pct": (price / prev - 1) * 100 if prev else None,
                "when": f"{when.month}/{when.day} 기준"}
    except Exception as e:
        print(f"[warn] {symbol} 시세 실패: {e}", file=sys.stderr)
        return None


def bitcoin_quote():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true"
    try:
        d = json.loads(fetch(url))["bitcoin"]
        now = dt.datetime.now(KST)
        return {"price": d["usd"], "change_pct": d.get("usd_24h_change"),
                "when": f"{now.month}/{now.day} {now.hour}시 (24시간)"}
    except Exception as e:
        print(f"[warn] 비트코인 시세 실패: {e}", file=sys.stderr)
        return None


def pubmed_recent(limit=12):
    """PubMed에서 최근 7일 안에 올라온 피부미용 논문의 제목·저널·초록 앞부분을 가져온다."""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    try:
        q = urllib.request.quote(PUBMED_TERM)
        ids = json.loads(fetch(f"{base}esearch.fcgi?db=pubmed&retmode=json&retmax={limit}"
                               f"&sort=pub_date&datetype=edat&reldate=7&term={q}"))["esearchresult"]["idlist"]
        if not ids:
            return []
        root = ET.fromstring(fetch(f"{base}efetch.fcgi?db=pubmed&retmode=xml&id={','.join(ids)}"))
    except Exception as e:
        print(f"[warn] PubMed 실패: {e}", file=sys.stderr)
        return []
    papers = []
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText"))
        papers.append({
            "source": art.findtext(".//Journal/ISOAbbreviation") or art.findtext(".//Journal/Title") or "PubMed",
            "title": title.strip(),
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "summary": strip_tags(abstract, 900),
        })
    return [p for p in papers if p["title"]]


# ---------- Claude로 초보용 설명 쓰기 ----------

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "lede": {"type": "string"},
        "market_why": {"type": "array", "items": {"type": "string"}},
        "term": {"type": "object", "properties": {"name": {"type": "string"}, "explain": {"type": "string"}},
                 "required": ["name", "explain"], "additionalProperties": False},
        "news": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                           "why": {"type": "string"}, "link": {"type": "string"}},
            "required": ["title", "body", "why", "link"], "additionalProperties": False}},
        "skin_tech": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "body": {"type": "string"},
                           "why": {"type": "string"}, "link": {"type": "string"}},
            "required": ["title", "body", "why", "link"], "additionalProperties": False}},
        "skin_papers": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "journal": {"type": "string"},
                           "finding": {"type": "string"}, "meaning": {"type": "string"},
                           "link": {"type": "string"}},
            "required": ["title", "journal", "finding", "meaning", "link"], "additionalProperties": False}},
        "skin_basic": {"type": "object", "properties": {"name": {"type": "string"}, "explain": {"type": "string"}},
                       "required": ["name", "explain"], "additionalProperties": False},
    },
    "required": ["headline", "lede", "market_why", "term", "news", "skin_tech", "skin_papers", "skin_basic"],
    "additionalProperties": False,
}

PROMPT = """너는 주식·코인 초보이면서 AI·IT에 관심 있는 한국 사람에게 아침 3분 브리핑을 써 주는 편집자야.
아래 자료(오늘 아침 모은 뉴스 제목·요약과 시세)만 근거로 써. 자료에 없는 사실이나 숫자는 지어내지 마.

쓰는 법:
- headline: 오늘의 핵심을 담은 한 문장 (40자 안팎).
- lede: 왜 그게 중요한지 쉬운 말로 1~2문장.
- market_why: 시장이 왜 이렇게 움직였는지 2~4개. 각 항목은 "굵은 요점: 설명" 형식으로, 앞부분 요점은 10자 이내. 뉴스 자료에 근거가 없으면 "아직 뚜렷한 이유가 보도되지 않았어요"라고 써도 돼.
- term: 오늘 뉴스와 관련된 투자·경제 또는 AI 용어 하나. explain은 2~3문장으로 쉽게 설명하고 마지막 문장은 오늘 뉴스와 연결해.
- news: AI·IT 소식 정확히 5개. 초보도 알 만한 큰 소식(기업, 제품, 투자, 규제)을 우선하고 개발자 전용 도구는 많아야 1개. title은 쉬운 한국어로 다시 쓴 제목, body는 1~2문장, why는 "그래서 왜 중요한지" 한 문장, link는 자료에 있던 원문 링크 그대로.
- skin_tech: 피부미용의료(레이저, 리프팅·에너지 기기, 주사 시술, 스킨부스터, 신제품 허가, 업계 동향) 소식 3개. 특정 병원을 홍보하는 광고성 기사는 빼고, 새 기술·기계·허가·연구·업계 흐름을 우선해. 영어 기사는 한국어로 옮겨. 형식은 news와 같아. 쓸 만한 소식이 3개가 안 되면 있는 만큼만.
- skin_papers: 아래 PubMed 논문 중 피부미용 실무나 공부에 의미 있는 것 2개. title은 한국어로 옮긴 제목, journal은 저널 약어, finding은 무엇을 어떻게 연구해 무엇을 발견했는지 2~3문장(대상 수·비교군·주요 수치가 초록에 있으면 포함), meaning은 "그래서 실제로 무슨 의미인지"와 연구의 한계 한 문장. link는 PubMed 링크 그대로. 초록에 없는 내용은 쓰지 마.
- skin_basic: 피부미용의료 기초 지식 하나(피부 구조, 레이저·기기 원리, 주사 시술 기전, 합병증, 피부 질환 등). 4~6문장으로, 원리 → 실제 시술에서 왜 중요한지 순서로. 가능하면 오늘 skin_tech나 skin_papers 내용과 연결해.
- 말투는 친근한 해요체, 짧은 문장. 전문용어는 처음 나올 때 영어나 원어를 괄호로 함께 쓰고 바로 풀어서 설명해.
- 특정 종목·코인을 사라/팔라고 하거나 가격을 예측하지 마. 특정 병원·제품을 추천하거나 치료 효과를 장담하지 마.

최근 '오늘의 용어'로 이미 쓴 것(겹치지 않게): {recent_terms}
최근 '피부미용 기초 지식'으로 이미 쓴 것(겹치지 않게): {recent_skin}

=== 시세 ===
{market}

=== 시장·코인 뉴스 ===
{market_news}

=== AI·IT 뉴스 ===
{ai_news}

=== 피부미용의료 뉴스 ===
{skin_news}

=== 최근 7일 PubMed 피부미용 논문 (제목 | 초록 앞부분 | 링크) ===
{papers}
"""


def fmt_items(items):
    return "\n".join(f"- [{i['source']}] {i['title']} | {i['summary']} | {i['link']}" for i in items)


def ask_claude(market, market_news, ai_news, skin_news, papers, recent_terms, recent_skin):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[info] ANTHROPIC_API_KEY 없음: 기본 브리핑으로 만듭니다.")
        return None
    try:
        import anthropic
    except ImportError:
        print("[warn] anthropic 패키지가 없어 기본 브리핑으로 만듭니다.", file=sys.stderr)
        return None

    client = anthropic.Anthropic()
    prompt = PROMPT.format(
        recent_terms=", ".join(recent_terms) or "없음",
        market=json.dumps(market, ensure_ascii=False),
        market_news=fmt_items(market_news),
        ai_news=fmt_items(ai_news),
        skin_news=fmt_items(skin_news) or "(없음)",
        papers=fmt_items(papers) or "(이번 주 검색된 논문 없음)",
        recent_skin=", ".join(recent_skin) or "없음",
    )
    try:
        resp = client.beta.messages.create(
            model=os.environ.get("BRIEFING_MODEL") or "claude-opus-5-5",
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        print("[warn] API 키가 올바르지 않아요. GitHub Secrets의 ANTHROPIC_API_KEY를 확인하세요.", file=sys.stderr)
        return None
    except anthropic.RateLimitError:
        print("[warn] 요청 한도 초과. 기본 브리핑으로 만듭니다.", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"[warn] Claude API 오류 {e.status_code}: {e.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError:
        print("[warn] Claude API 연결 실패. 기본 브리핑으로 만듭니다.", file=sys.stderr)
        return None

    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"[warn] Claude 응답이 완성되지 않음 ({resp.stop_reason}).", file=sys.stderr)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("[warn] Claude 응답을 읽지 못함.", file=sys.stderr)
        return None
    print(f"[info] Claude 요약 완료 (입력 {resp.usage.input_tokens} / 출력 {resp.usage.output_tokens} 토큰)")
    return data


def basic_briefing(today, market_news, ai_news, skin_news, papers, recent_terms, recent_skin):
    """키 없이 만드는 기본 브리핑: 제목과 원문 요약을 그대로 보여준다."""
    unused = [t for t in TERMS if t[0] not in recent_terms] or TERMS
    name, explain = unused[today.toordinal() % len(unused)]
    news = [{"title": i["title"], "body": i["summary"], "why": "", "link": i["link"]} for i in ai_news[:5]]
    skin_unused = [t for t in SKIN_BASICS if t[0] not in recent_skin] or SKIN_BASICS
    skin_pick = skin_unused[today.toordinal() % len(skin_unused)]
    return {
        "headline": "오늘의 AI·IT와 시장 소식",
        "lede": "주요 숫자와 헤드라인을 모았어요. (AI 요약을 켜면 초보 눈높이 설명이 붙어요.)",
        "market_why": [f"{i['source']}: {i['title']}" for i in market_news[:4]],
        "term": {"name": name, "explain": explain},
        "news": news,
        "skin_tech": [{"title": i["title"], "body": "", "why": "", "link": i["link"]} for i in skin_news[:3]],
        "skin_papers": [{"title": p["title"], "journal": p["source"], "finding": p["summary"][:300], "meaning": "", "link": p["link"]} for p in papers[:2]],
        "skin_basic": dict(zip(("name", "explain"), skin_pick)),
    }


# ---------- HTML 만들기 ----------

def esc(s):
    return html.escape(str(s or ""), quote=True)


def tile(label, q, money_fmt):
    if not q:
        return f'<div class="tile"><div class="k">{label}</div><div class="v">-</div><div class="when">불러오지 못함</div></div>'
    pct = q["change_pct"]
    if pct is None:
        d = ""
    else:
        cls, arrow = ("up", "▲") if pct >= 0 else ("dn", "▼")
        d = f'<div class="d {cls}">{arrow} {abs(pct):.2f}%</div>'
    return (f'<div class="tile"><div class="k">{label}</div><div class="v">{money_fmt(q["price"])}</div>'
            f'{d}<div class="when">{esc(q["when"])}</div></div>')


def render(today, brief, market, sources, archive_dates, is_index):
    wd = "월화수목금토일"[today.weekday()]
    why_html = ""
    for w in brief["market_why"]:
        if ":" in w and len(w.split(":", 1)[0]) <= 14:
            head, rest = w.split(":", 1)
            why_html += f"<li><b>{esc(head)}:</b>{esc(rest)}</li>"
        else:
            why_html += f"<li>{esc(w)}</li>"
    news_html = ""
    for n in brief["news"][:5]:
        link = n["link"] if n["link"].startswith("http") else ""
        title = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(n["title"])}</a>' if link else esc(n["title"])
        why = f' <span class="so">{esc(n["why"])}</span>' if n.get("why") else ""
        news_html += f"<li><h3>{title}</h3><p>{esc(n['body'])}{why}</p></li>"
    skin_html = ""
    for n in brief.get("skin_tech", [])[:3]:
        link = n["link"] if n["link"].startswith("http") else ""
        title = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(n["title"])}</a>' if link else esc(n["title"])
        why = f' <span class="so">{esc(n["why"])}</span>' if n.get("why") else ""
        body = f"<p>{esc(n['body'])}{why}</p>" if (n.get("body") or why) else ""
        skin_html += f"<li><h3>{title}</h3>{body}</li>"
    paper_html = ""
    for p in brief.get("skin_papers", [])[:2]:
        link = p["link"] if p["link"].startswith("http") else ""
        title = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(p["title"])}</a>' if link else esc(p["title"])
        meaning = f'<p class="so">{esc(p["meaning"])}</p>' if p.get("meaning") else ""
        paper_html += f'<li><div class="jr">{esc(p["journal"])}</div><h3>{title}</h3><p>{esc(p["finding"])}</p>{meaning}</li>'
    skin_tech_block = f'<ol class="news">{skin_html}</ol>' if skin_html else '<p class="small">이번 주에는 눈에 띄는 기기·기술 소식이 없었어요.</p>'
    paper_block = f'<ol class="news papers">{paper_html}</ol>' if paper_html else '<p class="small">최근 1주일 새 논문을 찾지 못했어요.</p>'
    sb = brief.get("skin_basic") or {"name": "", "explain": ""}
    src_html = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)}</a></li>' for n, u in sources)
    prefix = "archive/" if is_index else ""
    arch_html = "".join(f'<a href="{prefix}{d}.html">{d[5:].replace("-", "/")}</a>' for d in archive_dates[:14])
    home = "" if is_index else '<a class="home" href="../index.html">← 오늘 브리핑</a>'

    return fill(TEMPLATE,
        date=f"{today.year}년 {today.month}월 {today.day}일 ({wd})",
        headline=esc(brief["headline"]), lede=esc(brief["lede"]),
        kospi=tile("코스피", market.get("kospi"), lambda v: f"{v:,.2f}"),
        nasdaq=tile("나스닥", market.get("nasdaq"), lambda v: f"{v:,.0f}"),
        btc=tile("비트코인", market.get("btc"), lambda v: f"${v:,.0f}"),
        why=why_html, term_name=esc(brief["term"]["name"]), term_explain=esc(brief["term"]["explain"]),
        news=news_html, skin_tech=skin_tech_block, skin_papers=paper_block,
        skin_basic_name=esc(sb["name"]), skin_basic_explain=esc(sb["explain"]),
        sources=src_html, archive=arch_html, home=home,
        updated=dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        mode="Claude 요약" if brief.get("_ai") else "기본 모드",
    )


TEMPLATE = (ROOT / "scripts" / "template.html").read_text(encoding="utf-8")


def fill(template, **values):
    """template.html의 %%이름%% 자리를 채운다 (CSS 중괄호와 안 부딪히게)."""
    for k, v in values.items():
        template = template.replace(f"%%{k}%%", v)
    return template


def main():
    today = dt.datetime.now(KST).date()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "archive").mkdir(exist_ok=True)
    state_path = DOCS / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    recent_terms = state.get("recent_terms", [])[-20:]
    recent_skin = state.get("recent_skin", [])[-20:]

    ai_news = [i for src, url in AI_FEEDS for i in read_feed(src, url, 15)]
    skin_news = [i for src, url in SKIN_FEEDS for i in read_feed(src, url, 12)]
    papers = pubmed_recent()
    market_news = [i for src, url in MARKET_FEEDS for i in read_feed(src, url, 10)]
    market = {"kospi": yahoo_quote("^KS11"), "nasdaq": yahoo_quote("^IXIC"), "btc": bitcoin_quote()}
    if not ai_news and not market_news:
        sys.exit("뉴스를 하나도 가져오지 못했어요. 네트워크를 확인하세요.")

    brief = ask_claude(market, market_news, ai_news, skin_news, papers, recent_terms, recent_skin)
    if brief:
        brief["_ai"] = True
    else:
        brief = basic_briefing(today, market_news, ai_news, skin_news, papers, recent_terms, recent_skin)

    sources = [(f"{i['source']} · {i['title'][:40]}", i["link"]) for i in market_news[:4]]
    used = {n["link"] for n in brief["news"]}
    sources += [(f"{i['source']} · {i['title'][:40]}", i["link"]) for i in ai_news if i["link"] in used]
    used_skin = {n["link"] for n in brief.get("skin_tech", [])} | {p["link"] for p in brief.get("skin_papers", [])}
    sources += [(f"{i['source']} · {i['title'][:40]}", i["link"]) for i in skin_news + papers if i["link"] in used_skin]

    archive_dates = sorted({p.stem for p in (DOCS / "archive").glob("????-??-??.html")} | {today.isoformat()},
                           reverse=True)
    (DOCS / "archive" / f"{today.isoformat()}.html").write_text(
        render(today, brief, market, sources, archive_dates, False), encoding="utf-8")
    (DOCS / "index.html").write_text(render(today, brief, market, sources, archive_dates, True), encoding="utf-8")

    state["recent_terms"] = (recent_terms + [brief["term"]["name"]])[-20:]
    if brief.get("skin_basic", {}).get("name"):
        state["recent_skin"] = (recent_skin + [brief["skin_basic"]["name"]])[-20:]
    state["last_run"] = dt.datetime.now(KST).isoformat()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {today} 브리핑 생성: {brief['headline']}")


if __name__ == "__main__":
    main()
