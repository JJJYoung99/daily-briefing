"""매일 아침 피드: AI·IT 소식과 주식·코인 시장을 초보용 한국어 브리핑 한 페이지로 만든다.

GitHub Actions가 매일 아침 이 스크립트를 실행하고, 결과(docs/)를 GitHub Pages로 공개한다.
- 뉴스와 시세는 공개 RSS·무료 API에서 직접 가져온다 (키 필요 없음).
- ANTHROPIC_API_KEY가 있으면 Claude가 초보 눈높이 설명을 써 준다.
- 키가 없거나 호출이 실패하면 제목과 숫자만으로 된 기본 브리핑을 만든다.
"""

import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
KST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; daily-briefing/1.0; +https://github.com)"

# 출처 등급: 공식 = 기관·회사의 1차 발표, 전문 = 전문지·통신사·경제지, 모음 = 다른 기사를 모은 곳
# (이름, 주소, 등급, 최대 개수)
AI_FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml", "공식", 6),
    ("Google AI", "https://blog.google/technology/ai/rss/", "공식", 5),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/", "전문", 8),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab", "전문", 8),
    ("AI타임스", "https://www.aitimes.com/rss/allArticle.xml", "전문", 15),
    ("긱뉴스", "https://news.hada.io/rss/news", "모음", 12),
]
MARKET_FEEDS = [
    ("한국은행", "https://www.bok.or.kr/portal/bbs/B0000501/news.rss?menuNo=201264", "공식", 5),
    ("미국 연준(Fed)", "https://www.federalreserve.gov/feeds/press_monetary.xml", "공식", 3),
    ("연합뉴스 경제", "https://www.yna.co.kr/rss/economy.xml", "전문", 10),
    ("한국경제 증권", "https://www.hankyung.com/feed/finance", "전문", 10),
    ("블록미디어", "https://www.blockmedia.co.kr/feed", "전문", 8),
]


def gnews(query, lang="ko"):
    """Google 뉴스 검색 RSS 주소 (키 필요 없음)."""
    q = urllib.request.quote(query)
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# 피부미용 뉴스는 아래 출처만 쓴다. 목록에 없는 곳(생활잡지·연예지·SNS·보도자료 배포 사이트·병원 블로그)은 버린다.
SKIN_SOURCES = {
    # 규제기관·학회 (공식)
    "mfds.go.kr": ("식약처", "공식"), "korea.kr": ("정책브리핑", "공식"), "fda.gov": ("FDA", "공식"),
    "gov.uk": ("영국 정부(MHRA)", "공식"), "ema.europa.eu": ("EMA", "공식"), "aad.org": ("AAD", "공식"),
    "asds.net": ("ASDS", "공식"), "theaestheticsociety.org": ("The Aesthetic Society", "공식"),
    # 의학 전문지
    "dermatologytimes.com": ("Dermatology Times", "전문"), "healio.com": ("Healio", "전문"),
    "practicaldermatology.com": ("Practical Dermatology", "전문"), "modernaesthetics.com": ("Modern Aesthetics", "전문"),
    "hcplive.com": ("HCPLive", "전문"), "medpagetoday.com": ("MedPage Today", "전문"),
    "medscape.com": ("Medscape", "전문"), "thedermdigest.com": ("The Dermatology Digest", "전문"),
    "plasticsurgerypractice.com": ("Plastic Surgery Practice", "전문"), "statnews.com": ("STAT", "전문"),
    "docdocdoc.co.kr": ("청년의사", "전문"), "doctorsnews.co.kr": ("의협신문", "전문"),
    "medicaltimes.com": ("메디칼타임즈", "전문"), "dailymedi.com": ("데일리메디", "전문"),
    "medigatenews.com": ("메디게이트뉴스", "전문"), "bosa.co.kr": ("의학신문", "전문"),
    "dailypharm.com": ("데일리팜", "전문"), "yakup.com": ("약업신문", "전문"), "hitnews.co.kr": ("히트뉴스", "전문"),
    # 통신사
    "reuters.com": ("Reuters", "전문"), "apnews.com": ("AP", "전문"), "yna.co.kr": ("연합뉴스", "전문"),
}
# 직접 읽는 피드: (주소, 최대 개수)
SKIN_RSS = [
    ("https://www.mfds.go.kr/www/rss/brd.do?brdId=ntc0021", 40),
    ("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml", 30),
    ("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", 30),
    ("https://www.dermatologytimes.com/rss", 40),
    ("https://www.healio.com/rss/dermatology", 30),
    ("https://www.medpagetoday.com/rss/dermatology.xml", 30),
    ("https://www.docdocdoc.co.kr/rss/allArticle.xml", 60),
    ("https://www.doctorsnews.co.kr/rss/allArticle.xml", 60),
    ("https://www.bosa.co.kr/rss/allArticle.xml", 60),
    ("https://www.hitnews.co.kr/rss/allArticle.xml", 60),
]


def _sites(*domains):
    return "(" + " OR ".join(f"site:{d}" for d in domains) + ")"


_KO = "(필러 OR 보툴리눔 OR 톡신 OR 스킨부스터 OR 리프팅 OR 레이저 OR 고주파 OR 미용의료기기 OR 피부미용)"
_EN = '("aesthetic" OR "dermal filler" OR botulinum OR "laser" OR radiofrequency OR biostimulator OR melasma)'
SKIN_GNEWS = [
    gnews(f"{_KO} {_sites('medicaltimes.com', 'dailymedi.com', 'medigatenews.com', 'docdocdoc.co.kr', 'doctorsnews.co.kr')} when:14d"),
    gnews(f"{_KO} {_sites('bosa.co.kr', 'dailypharm.com', 'yakup.com', 'hitnews.co.kr', 'yna.co.kr', 'mfds.go.kr')} when:14d"),
    gnews(f"{_EN} {_sites('dermatologytimes.com', 'healio.com', 'practicaldermatology.com', 'modernaesthetics.com', 'thedermdigest.com', 'hcplive.com')} when:14d", "en"),
    gnews(f"{_EN} {_sites('fda.gov', 'gov.uk', 'medpagetoday.com', 'medscape.com', 'plasticsurgerypractice.com', 'reuters.com')} (skin OR facial OR cosmetic) when:14d", "en"),
]

# 피부미용과 관련 있는 글만 남기는 낱말 (제목·요약에서 찾음)
SKIN_WORDS = re.compile(
    r"필러|보툴리눔|톡신|보톡스|스킨\s?부스터|리프팅|레이저|고주파|하이푸|HIFU|초음파 (?:리프팅|수술기)|쥬베룩|리쥬란|스컬트라|엑소좀|"
    r"PDRN|폴리뉴클레오|콜라겐|미용\s?의료|피부\s?미용|미용\s?시술|기미|색소|흉터|여드름|주름|"
    r"aesthetic|cosmetic|filler|botulinum|botox|\btoxin\b|\blasers?\b|radiofrequency|microneedl|biostimulat|hyaluronic|poly-?l-?lactic|"
    r"hydroxylapatite|polynucleotide|exosome|rejuvenat|melasma|hyperpigment|\bscars?\b|\bacne\b|rosacea|wrinkle|skin (?:laxity|tightening)|photoaging",
    re.I)
# 레퍼런스로 쓰기 어려운 글 (실적·주가·모델·광고·행사)
SKIN_SKIP = re.compile(
    r"주가|목표가|실적|영업이익|매출|상장|공모|배당|지분|홍보대사|모델 발탁|화보|할인|이벤트|기부|후원|봉사|협약|MOU|부고|인사\]|채용|수출|점유율|투자|기증|수훈|포장|의료관광|관광객|외국인 환자|부가세|사격|갑상선|시상|수상|대회|창립|\d+돌|"
    r"워크숍|박람회|전시회|코스모프로프|심포지엄 개최|개최|참가|간담회|"
    r"수술용 로봇|백내장|라식|전립선|stock|shares|earnings|revenue|market size|forecast|CAGR|sponsored", re.I)

# PubMed 피부미용 논문 검색어 (최근 45일에서 찾아 아래 기준으로 점수를 매긴다)
PUBMED_TERM = (
    '(laser[tiab] OR "energy-based device"[tiab] OR radiofrequency[tiab] OR "focused ultrasound"[tiab] '
    'OR botulinum[tiab] OR "hyaluronic acid"[tiab] OR filler[tiab] OR microneedling[tiab] OR "skin booster"[tiab] '
    'OR exosome[tiab] OR "poly-L-lactic"[tiab] OR "calcium hydroxylapatite"[tiab] OR polycaprolactone[tiab] '
    'OR polynucleotide[tiab] OR "intense pulsed light"[tiab] OR picosecond[tiab] OR "thread lift"[tiab] OR tranexamic[tiab]) '
    'AND (aesthetic[tiab] OR cosmetic[tiab] OR rejuvenation[tiab] OR melasma[tiab] OR scar[tiab] '
    'OR wrinkle[tiab] OR pigmentation[tiab] OR acne[tiab] OR rosacea[tiab] OR laxity[tiab] OR "vascular occlusion"[tiab]) '
    'AND (skin[tiab] OR dermatol*[tiab] OR facial[tiab] OR face[tiab] OR cutaneous[tiab]) AND hasabstract'
)
# 저널 점수 (3 = 종합·피부과 대표지, 2 = 피부·미용·레이저 전문지, 1 = 오픈액세스 전문지). 목록 밖은 0.
JOURNALS = {
    3: ["N Engl J Med", "Lancet", "JAMA", "BMJ", "Cochrane Database Syst Rev", "JAMA Dermatol", "J Am Acad Dermatol",
        "Br J Dermatol", "J Eur Acad Dermatol Venereol", "J Invest Dermatol", "Am J Clin Dermatol",
        "Plast Reconstr Surg", "Aesthet Surg J", "Lasers Surg Med", "Dermatol Surg"],
    2: ["Acta Derm Venereol", "J Dermatol", "Clin Exp Dermatol", "Int J Dermatol", "Dermatology", "J Dermatolog Treat",
        "Aesthetic Plast Surg", "Lasers Med Sci", "J Cosmet Dermatol", "J Cosmet Laser Ther", "Ann Dermatol",
        "Facial Plast Surg Aesthet Med", "Facial Plast Surg", "Dermatol Ther (Heidelb)", "J Drugs Dermatol",
        "Arch Dermatol Res", "J Plast Reconstr Aesthet Surg", "Ophthalmic Plast Reconstr Surg", "Toxins (Basel)",
        "Photodermatol Photoimmunol Photomed", "Pigment Cell Melanoma Res", "Contact Dermatitis"],
    1: ["Skin Res Technol", "Clin Cosmet Investig Dermatol", "Plast Reconstr Surg Glob Open", "Aesthet Surg J Open Forum",
        "J Clin Med", "J Clin Aesthet Dermatol", "Dermatol Res Pract", "Facial Plast Surg Clin North Am", "Dermatol Clin"],
}
JOURNAL_SCORE = {name.lower(): pt for pt, names in JOURNALS.items() for name in names}
# 근거로 쓰기 약한 글 종류는 뺀다
BAD_TYPES = {"Letter", "Comment", "Editorial", "Published Erratum", "Retracted Publication", "Retraction of Publication",
             "Case Reports", "News", "Personal Narrative", "Preprint", "Expression of Concern"}
PAPER_WORDS = re.compile(
    r"laser|radiofrequency|ultrasound|botulinum|hyaluronic|filler|microneedl|booster|exosome|lactic|hydroxylapatite|"
    r"polycaprolactone|polynucleotide|pulsed light|picosecond|thread|tranexamic|melasma|scar|rejuvenat|vascular occlusion", re.I)

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


def parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    for fn in (email.utils.parsedate_to_datetime, lambda t: dt.datetime.fromisoformat(t.replace("Z", "+00:00"))):
        try:
            d = fn(text)
            if d is None:
                continue
            return d if d.tzinfo else d.replace(tzinfo=KST)
        except (ValueError, TypeError, IndexError):
            continue
    return None


def clean(text):
    return re.sub(r"<!\[CDATA\[|\]\]>", "", text or "").strip()


def read_feed(source, url, limit=12, grade="", max_age_days=None):
    """RSS 2.0과 Atom 둘 다 읽는다. 실패하면 빈 목록."""
    try:
        root = ET.fromstring(fetch(url))
    except Exception as e:  # 피드 하나가 죽어도 나머지는 계속
        print(f"[warn] {source} 피드 실패: {e}", file=sys.stderr)
        return []
    atom = "{http://www.w3.org/2005/Atom}"
    items = []
    for it in root.iter("item"):
        pub = it.find("source")
        items.append({
            "source": source, "grade": grade,
            "title": clean(it.findtext("title")),
            "link": clean(it.findtext("link")),
            "summary": strip_tags(clean(it.findtext("description"))),
            "date": parse_date(it.findtext("pubDate")),
            "publisher": pub.get("url", "") if pub is not None else "",
        })
    for it in root.iter(atom + "entry"):
        link = it.find(atom + "link")
        items.append({
            "source": source, "grade": grade,
            "title": clean(it.findtext(atom + "title")),
            "link": link.get("href", "") if link is not None else "",
            "summary": strip_tags(it.findtext(atom + "content") or it.findtext(atom + "summary")),
            "date": parse_date(it.findtext(atom + "published") or it.findtext(atom + "updated")),
            "publisher": "",
        })
    for i in items:
        i["link"] = re.sub(r"[&?]utm_[^&]+", "", i["link"])
    if max_age_days is not None:
        oldest = dt.datetime.now(KST) - dt.timedelta(days=max_age_days)
        items = [i for i in items if i["date"] is None or i["date"] >= oldest]
    return [i for i in items if i["title"]][:limit]


def trusted_source(url):
    """주소의 도메인이 SKIN_SOURCES에 있으면 (이름, 등급), 없으면 None."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    for domain, info in SKIN_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return info
    return None


# 먼저 보여 줄 글: 허가·안전성·임상 근거
SKIN_FIRST = re.compile(
    r"허가|승인|회수|안전성|부작용|이상반응|임상|무작위|지침|가이드라인|FDA|recall|safety|adverse|complication|trial|study|"
    r"randomi|meta-analysis|guideline|consensus|clearance|approv|warning", re.I)


def title_key(title):
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())[:40]


def skin_news_items(seen, limit=24):
    """공식기관·의학 전문지 글만 남긴 피부미용 소식. 이미 실은 글은 뺀다."""
    raw = []
    for url, n in SKIN_RSS:
        raw += read_feed(url, url, n, max_age_days=14)
    for url in SKIN_GNEWS:
        got = read_feed("Google 뉴스", url, 30, max_age_days=14)
        if not got:   # 요청이 몰리면 잠깐 막히므로 한 번만 더
            time.sleep(15)
            got = read_feed("Google 뉴스", url, 30, max_age_days=14)
        raw += got
        time.sleep(3)
    out, keys = [], set()
    for i in raw:
        info = trusted_source(i["publisher"] or i["link"])
        if not info:
            continue
        i["source"], i["grade"] = info
        i["title"] = re.sub(r"\s+-\s+[^-]{2,40}$", "", i["title"]) if i["publisher"] else i["title"]
        text = f"{i['title']} {i['summary']}"
        key = title_key(i["title"])
        if not SKIN_WORDS.search(text) or SKIN_SKIP.search(i["title"]) or i["link"] in seen or key in keys:
            continue
        keys.add(key)
        out.append(i)
    floor = dt.datetime(2000, 1, 1, tzinfo=KST)
    out.sort(key=lambda i: (i["grade"] != "공식", not SKIN_FIRST.search(i["title"]), -(i["date"] or floor).timestamp()))
    print(f"[info] 피부미용 뉴스 {len(raw)}개 중 {len(out)}개 통과")
    return out[:limit]


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


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


def paper_design(title, abstract, types):
    """제목·초록·논문 종류로 연구 설계를 어림한다. (이름, 점수)"""
    t, a = title.lower(), abstract.lower()
    if "Practice Guideline" in types or "Guideline" in types or re.search(r"\b(?:clinical|practice|treatment|management) guidelines?\b", t):
        return "진료지침", 6
    if "Meta-Analysis" in types or "meta-analysis" in t:
        return "메타분석", 6
    if "Systematic Review" in types or "systematic review" in t:
        return "체계적 문헌고찰", 5
    if "Randomized Controlled Trial" in types or re.search(r"\brandomi[sz]ed\b", t) or re.search(r"\bwere randomi[sz]ed\b|\brandomi[sz]ed (?:controlled|split)", a):
        return "무작위 대조시험", 5
    if re.search(r"split-face|split-body|split-scar|controlled (?:study|trial)", t + " " + a):
        return "비교 임상시험", 4
    if re.search(r"\bconsensus\b|\bdelphi\b", t):
        return "전문가 합의", 3
    if re.search(r"\bprospective\b", t + " " + a) or "Clinical Trial" in types:
        return "전향 연구", 3
    if re.search(r"\bretrospective\b|\bcohort\b", t + " " + a):
        return "후향·코호트 연구", 2
    if "Review" in types or re.search(r"\breview\b", t):
        return "종설", 1
    return "기타 연구", 1


def pubmed_recent(seen, limit=10):
    """최근 45일 피부미용 논문을 저널·연구 설계로 점수 매겨 좋은 것부터 준다. 이미 실은 논문은 뺀다."""
    try:
        q = urllib.parse.quote(PUBMED_TERM)
        ids = json.loads(fetch(f"{EUTILS}esearch.fcgi?db=pubmed&retmode=json&retmax=180"
                               f"&sort=pub_date&datetype=edat&reldate=45&term={q}"))["esearchresult"]["idlist"]
        if not ids:
            return []
        root = ET.fromstring(fetch(f"{EUTILS}efetch.fcgi?db=pubmed&retmode=xml&id={','.join(ids)}", 60))
    except Exception as e:
        print(f"[warn] PubMed 실패: {e}", file=sys.stderr)
        return []
    papers = []
    for art in root.iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        el = art.find(".//ArticleTitle")
        title = "".join(el.itertext()).strip() if el is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        types = {(t.text or "").strip() for t in art.iter("PublicationType")}
        if not title or link in seen or types & BAD_TYPES:
            continue
        if re.match(r"(response to|reply|comment|correction|erratum|retract)", title, re.I):
            continue
        # 실제 사람 시술이 아닌 연구(동물·세포·모의시험)는 뺀다
        if re.search(r"\b(rats?|mice|mouse|murine|porcine|rabbits?|in vitro|in silico|zebrafish|computational|cadaver)\b", title, re.I):
            continue
        journal = art.findtext(".//Journal/ISOAbbreviation") or art.findtext(".//Journal/Title") or ""
        js = JOURNAL_SCORE.get(journal.replace(".", "").lower(), 0)
        design, ds = paper_design(title, abstract, types)
        if js == 0 and ds < 5:   # 목록 밖 저널은 설계가 아주 좋을 때만
            continue
        doi = next((x.text for x in art.findall("./PubmedData/ArticleIdList/ArticleId") if x.get("IdType") == "doi"), "") or ""
        coi = re.sub(r"\s+", " ", art.findtext(".//CoiStatement") or "").strip()
        m = re.search(r"(conflicts? of interest|competing interests?|disclosures?)", coi, re.I)
        coi = coi[m.start():m.start() + 260] if m else coi[:260]
        papers.append({
            "source": journal, "grade": "논문", "title": title, "link": link, "doi": doi, "design": design,
            "year": art.findtext(".//Journal/JournalIssue/PubDate/Year") or "", "coi": coi,
            "summary": strip_tags(abstract, 1800),
            "score": ds * 2 + js * 2 + (2 if PAPER_WORDS.search(title) else 0),
        })
    papers.sort(key=lambda p: -p["score"])   # 점수가 같으면 최신순(검색 순서) 유지
    print(f"[info] PubMed {len(ids)}편 중 {len(papers)}편 통과")
    return papers[:limit]


def pubmed_review(query):
    """기초 지식 아래에 붙일 최근 종설 한 편 (대표·전문 저널만). 못 찾으면 None."""
    query = re.sub(r"[^A-Za-z0-9 \-]", " ", query or "").strip()
    if not query:
        return None
    try:
        term = urllib.parse.quote(f"({query}) AND (review[pt] OR systematic review[pt] OR meta-analysis[pt]) AND english[la]")
        ids = json.loads(fetch(f"{EUTILS}esearch.fcgi?db=pubmed&retmode=json&retmax=15&sort=relevance"
                               f"&datetype=pdat&reldate=2555&term={term}"))["esearchresult"]["idlist"]
        if not ids:
            return None
        res = json.loads(fetch(f"{EUTILS}esummary.fcgi?db=pubmed&retmode=json&id={','.join(ids)}"))["result"]
    except Exception as e:
        print(f"[warn] 종설 검색 실패: {e}", file=sys.stderr)
        return None
    for pmid in ids:
        r = res.get(pmid) or {}
        journal = r.get("source", "")
        if JOURNAL_SCORE.get(journal.replace(".", "").lower(), 0) >= 2 and "Retracted Publication" not in r.get("pubtype", []):
            return {"title": strip_tags(r.get("title", ""), 160), "journal": journal, "year": r.get("pubdate", "")[:4],
                    "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}
    return None


# ---------- Claude로 초보용 설명 쓰기 ----------

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "lede": {"type": "string"},
        "market_why": {"type": "array", "items": {"type": "string"}},
        "market_links": {"type": "array", "items": {"type": "string"}},
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
                           "why": {"type": "string"}, "link": {"type": "string"},
                           "basis": {"type": "string", "enum": ["규제기관 발표", "임상 연구 보도", "학회·전문가 의견", "업체 발표"]}},
            "required": ["title", "body", "why", "link", "basis"], "additionalProperties": False}},
        "skin_papers": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "design": {"type": "string"},
                           "level": {"type": "string", "enum": ["높음", "중간", "낮음"]},
                           "finding": {"type": "string"}, "meaning": {"type": "string"},
                           "limits": {"type": "string"}, "link": {"type": "string"}},
            "required": ["title", "design", "level", "finding", "meaning", "limits", "link"], "additionalProperties": False}},
        "skin_basic": {"type": "object", "properties": {"name": {"type": "string"}, "explain": {"type": "string"},
                                                        "pubmed_query": {"type": "string"}},
                       "required": ["name", "explain", "pubmed_query"], "additionalProperties": False},
    },
    "required": ["headline", "lede", "market_why", "market_links", "term", "news", "skin_tech", "skin_papers", "skin_basic"],
    "additionalProperties": False,
}

PROMPT = """너는 주식·코인 초보이면서 AI·IT에 관심 있는 한국 사람에게 아침 3분 브리핑을 써 주는 편집자야.
아래 자료(오늘 아침 모은 뉴스 제목·요약과 시세)만 근거로 써. 자료에 없는 사실이나 숫자는 지어내지 마.

쓰는 법:
- headline: 오늘의 핵심을 담은 한 문장 (40자 안팎).
- lede: 왜 그게 중요한지 쉬운 말로 1~2문장.
- market_why: 시장이 왜 이렇게 움직였는지 2~4개. 각 항목은 "굵은 요점: 설명" 형식으로, 앞부분 요점은 10자 이내. 뉴스 자료에 근거가 없으면 "아직 뚜렷한 이유가 보도되지 않았어요"라고 써도 돼. 금리·물가 이야기는 [공식](한국은행·연준) 자료가 있으면 그것을 먼저 근거로 해. 한 사람이나 한 증권사의 전망은 "~라는 의견도 있어요"처럼 의견으로 써.
- market_links: headline·lede·market_why를 쓸 때 실제로 근거로 삼은 기사 링크 2~5개(자료의 링크 그대로).
- term: 오늘 뉴스와 관련된 투자·경제 또는 AI 용어 하나. explain은 2~3문장으로 쉽게 설명하고 마지막 문장은 오늘 뉴스와 연결해.
- news: AI·IT 소식 정확히 5개. 초보도 알 만한 큰 소식(기업, 제품, 투자, 규제)을 우선하고 개발자 전용 도구는 많아야 1개. 같은 소식이 여러 곳에 있으면 [공식] > [전문] > [모음] 순서로 고르고, [모음] 출처는 다른 출처에 없는 중요한 소식일 때만 써. title은 쉬운 한국어로 다시 쓴 제목, body는 1~2문장, why는 "그래서 왜 중요한지" 한 문장, link는 자료에 있던 원문 링크 그대로.
- skin_tech: 피부미용의료(레이저, 리프팅·에너지 기기, 주사 시술, 스킨부스터, 허가·안전성, 진료지침) 소식 최대 3개. 레퍼런스로 쓸 수 있는 것만 골라. 우선순위는 ① 규제기관의 허가·회수·안전성 정보 ② 사람 대상 임상 연구를 다룬 전문지 기사 ③ 학회 발표·진료지침·전문가 의견 ④ 업체 신제품 발표.
  · 트렌드 예측, 유명인, 병원·행사·협약 홍보, 회사 실적·주가 기사는 쓰지 마. 피부미용과 관계없는 글(암·아토피 신약 등)도 쓰지 마.
  · ④는 많아야 1개이고, body에 "업체 발표이며 독립적으로 검증된 자료는 아니에요"라는 뜻을 꼭 넣어.
  · basis는 그 기사의 실제 근거에 맞게 골라. 전문지가 업체 보도자료를 옮긴 기사는 "업체 발표"야.
  · 연구 기사는 대상 수·비교군이 자료에 있으면 쓰고, 없으면 "기사 요약에는 대상 수가 없어요"라고 써.
  · 기준에 맞는 것이 없으면 빈 목록으로 둬. 개수를 채우려고 낮은 수준의 글을 넣지 마. 영어 기사는 한국어로 옮겨.
- skin_papers: 아래 PubMed 논문(좋은 설계·저널 순으로 정렬돼 있음) 중 피부미용 실무에 의미 있는 것 2개. 서로 다른 주제로 골라. title은 한국어로 옮긴 제목. design은 연구 설계와 규모(예: "무작위 대조시험 · 42명 · 12주"), 초록에 없는 값은 빼. finding은 비교군과 주요 수치(p값·신뢰구간이 있으면 포함)로 2~3문장. meaning은 "그래서 실제로 무슨 의미인지" 한 문장. limits는 한계와 이해관계(업체 지원·저자 소속이 자료에 있으면 포함)를 한두 문장. link는 PubMed 링크 그대로. 초록에 없는 내용은 쓰지 마.
  · level 기준: 높음 = 진료지침, 무작위시험을 모은 메타분석, 여러 기관의 큰 무작위시험(대략 100명 이상). 중간 = 작은 무작위시험, 반쪽 얼굴 비교, 체계적 문헌고찰. 낮음 = 비교군 없는 연구, 후향 연구, 종설, 전문가 의견. 초록에 GRADE 확실성이 있으면 그것을 우선해(여러 개면 주된 결과의 것). 애매하면 낮은 쪽으로 매겨.
- skin_basic: 피부미용의료 기초 지식 하나(피부 구조, 레이저·기기 원리, 주사 시술 기전, 합병증, 피부 질환 등). 4~6문장으로, 원리 → 실제 시술에서 왜 중요한지 순서로. 교과서 수준에서 널리 받아들여지는 내용만 쓰고, 근거가 엇갈리면 엇갈린다고 써. 가능하면 오늘 skin_tech나 skin_papers 내용과 연결해. pubmed_query는 이 주제의 종설을 찾을 영어 검색어 2~4단어(예: "picosecond laser pigmentation").
- 말투는 친근한 해요체, 짧은 문장. 전문용어는 처음 나올 때 영어나 원어를 괄호로 함께 쓰고 바로 풀어서 설명해.
- link는 반드시 아래 자료에 있는 링크를 글자 그대로 옮겨. 자료에 없는 링크는 자동으로 버려져.
- 특정 종목·코인을 사라/팔라고 하거나 가격을 예측하지 마. 특정 병원·제품을 추천하거나 치료 효과를 장담하지 마.

최근 '오늘의 용어'로 이미 쓴 것(겹치지 않게): {recent_terms}
최근 '피부미용 기초 지식'으로 이미 쓴 것(겹치지 않게): {recent_skin}
최근 피부미용 소식·논문으로 이미 실은 것(같은 내용은 다른 매체 기사라도 다시 싣지 마): {recent_titles}

=== 시세 ===
{market}

=== 시장·코인 뉴스 ===
{market_news}

=== AI·IT 뉴스 ===
{ai_news}

=== 피부미용의료 뉴스 ===
{skin_news}

=== 최근 PubMed 피부미용 논문 (저널 · 설계 | 제목 | 초록 | 이해관계 | 링크) ===
{papers}
"""


def fmt_items(items):
    return "\n".join(f"- [{i['source']}{' · ' + i['grade'] if i.get('grade') else ''}] {i['title']} | {i['summary']} | {i['link']}"
                     for i in items)


def fmt_papers(papers):
    return "\n".join(f"- [{p['source']} · {p['design']}] {p['title']} | {p['summary']} | 이해관계: {p['coi'] or '자료 없음'} | {p['link']}"
                     for p in papers)


def ask_claude(market, market_news, ai_news, skin_news, papers, recent_terms, recent_skin, recent_titles):
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
        papers=fmt_papers(papers) or "(기준을 통과한 새 논문 없음)",
        recent_skin=", ".join(recent_skin) or "없음",
        recent_titles=" / ".join(recent_titles) or "없음",
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
        "skin_tech": [{"title": i["title"], "body": "", "why": "", "link": i["link"], "basis": ""} for i in skin_news[:3]],
        "skin_papers": [{"title": p["title"], "design": p["design"], "level": "", "finding": p["summary"][:300], "meaning": "", "limits": "", "link": p["link"]} for p in papers[:2]],
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


def src_tag(n, basis=None):
    """소식 위에 붙는 출처 줄: 매체 이름 · 등급 · 근거"""
    parts = [x for x in (n.get("_source"), {"공식": "공식 발표", "전문": "", "모음": "모음 사이트"}.get(n.get("_grade"), ""), basis) if x]
    return f'<div class="src">{esc(" · ".join(dict.fromkeys(parts)))}</div>' if parts else ""


def attach_sources(brief, items):
    """Claude가 준 링크를 원자료와 맞춰 본다. 자료에 없는 링크의 글은 버리고, 출처·저널은 원자료 값으로 붙인다."""
    by_link = {i["link"]: i for i in items}
    for key in ("news", "skin_tech", "skin_papers"):
        kept = []
        for n in brief.get(key, []):
            src = by_link.get(n["link"])
            if not src:
                print(f"[warn] 자료에 없는 링크라 뺌: {key} {n['link']}", file=sys.stderr)
                continue
            if key == "skin_papers" and src.get("grade") != "논문":
                continue
            n["_source"], n["_grade"] = src["source"], src.get("grade", "")
            n["_doi"], n["_year"] = src.get("doi", ""), src.get("year", "")
            kept.append(n)
        brief[key] = kept


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
        news_html += f"<li>{src_tag(n)}<h3>{title}</h3><p>{esc(n['body'])}{why}</p></li>"
    skin_html = ""
    for n in brief.get("skin_tech", [])[:3]:
        link = n["link"] if n["link"].startswith("http") else ""
        title = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(n["title"])}</a>' if link else esc(n["title"])
        why = f' <span class="so">{esc(n["why"])}</span>' if n.get("why") else ""
        body = f"<p>{esc(n['body'])}{why}</p>" if (n.get("body") or why) else ""
        skin_html += f"<li>{src_tag(n, n.get('basis'))}<h3>{title}</h3>{body}</li>"
    paper_html = ""
    for p in brief.get("skin_papers", [])[:2]:
        link = p["link"] if p["link"].startswith("http") else ""
        title = f'<a href="{esc(link)}" target="_blank" rel="noopener">{esc(p["title"])}</a>' if link else esc(p["title"])
        meaning = f'<p class="so">{esc(p["meaning"])}</p>' if p.get("meaning") else ""
        limits = f'<p class="lim">한계: {esc(p["limits"])}</p>' if p.get("limits") else ""
        level = f'<span class="lv lv{["낮음", "중간", "높음"].index(p["level"])}">근거 {esc(p["level"])}</span>' if p.get("level") else ""
        doi = f' · <a href="https://doi.org/{esc(p["_doi"])}" target="_blank" rel="noopener">DOI</a>' if p.get("_doi") else ""
        jr = " ".join(x for x in (p.get("_source", ""), p.get("_year", "")) if x)
        paper_html += (f'<li><div class="jr">{esc(jr)}{doi} {level}</div><h3>{title}</h3>'
                       f'<p class="ds">{esc(p["design"])}</p><p>{esc(p["finding"])}</p>{meaning}{limits}</li>')
    skin_tech_block = f'<ol class="news">{skin_html}</ol>' if skin_html else '<p class="small">오늘은 공식기관·의학 전문지에 새로 실을 만한 소식이 없었어요.</p>'
    paper_block = f'<ol class="news papers">{paper_html}</ol>' if paper_html else '<p class="small">기준을 통과한 새 논문을 찾지 못했어요.</p>'
    sb = brief.get("skin_basic") or {"name": "", "explain": ""}
    rv = sb.get("_review")
    review_html = (f'<p class="small">더 읽을 종설(자동 검색): <a href="{esc(rv["link"])}" target="_blank" rel="noopener">{esc(rv["title"])}</a> '
                   f'{esc(rv["journal"])} {esc(rv["year"])}</p>') if rv else ""
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
        skin_basic_name=esc(sb["name"]), skin_basic_explain=esc(sb["explain"]), skin_basic_review=review_html,
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

    if "seen_skin" in state:
        seen_list = state["seen_skin"]
    else:   # 처음 한 번: 지난 7일 브리핑에 실린 링크를 읽어 다시 싣지 않는다
        old = sorted((DOCS / "archive").glob("????-??-??.html"))[-7:]
        seen_list = [html.unescape(u) for f in old for u in
                     re.findall(r'href="(https://(?:pubmed\.ncbi\.nlm\.nih\.gov|news\.google\.com)/[^"]+)"', f.read_text(encoding="utf-8"))]
    seen = set(seen_list)
    recent_titles = state.get("recent_skin_titles", [])[-24:]

    ai_news = [i for src, url, g, n in AI_FEEDS for i in read_feed(src, url, n, g, 4)]
    skin_news = skin_news_items(seen)
    papers = pubmed_recent(seen)
    market_news = [i for src, url, g, n in MARKET_FEEDS for i in read_feed(src, url, n, g, 4)]
    market = {"kospi": yahoo_quote("^KS11"), "nasdaq": yahoo_quote("^IXIC"), "btc": bitcoin_quote()}
    if not ai_news and not market_news:
        sys.exit("뉴스를 하나도 가져오지 못했어요. 네트워크를 확인하세요.")

    brief = ask_claude(market, market_news, ai_news, skin_news, papers, recent_terms, recent_skin, recent_titles)
    if brief:
        brief["_ai"] = True
    else:
        brief = basic_briefing(today, market_news, ai_news, skin_news, papers, recent_terms, recent_skin)
    attach_sources(brief, ai_news + skin_news + papers)
    if brief["skin_basic"].get("pubmed_query"):
        brief["skin_basic"]["_review"] = pubmed_review(brief["skin_basic"]["pubmed_query"])

    # 시장 설명에 실제로 쓴 기사만 출처에 싣는다 (기본 브리핑은 앞의 4개를 그대로 보여 주므로 4개)
    used_market = set(brief.get("market_links") or [i["link"] for i in market_news[:4]])
    sources = [(f"{i['source']} · {i['title'][:40]}", i["link"]) for i in market_news if i["link"] in used_market]
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
    shown = brief.get("skin_tech", []) + brief.get("skin_papers", [])
    state["seen_skin"] = (seen_list + [n["link"] for n in shown])[-150:]
    state["recent_skin_titles"] = (recent_titles + [n["title"] for n in shown])[-24:]
    state["last_run"] = dt.datetime.now(KST).isoformat()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {today} 브리핑 생성: {brief['headline']}")


if __name__ == "__main__":
    main()
