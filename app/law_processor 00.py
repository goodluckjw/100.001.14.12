import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import re
import os
import unicodedata
from collections import defaultdict

OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"

def highlight(text, query):
    """검색어를 HTML로 하이라이트 처리해주는 함수""" 
    if not query or not text:
        return text
    # 정규식 특수문자 이스케이프
    escaped_query = re.escape(query)
    # 대소문자 구분없이 검색
    pattern = re.compile(f'({escaped_query})', re.IGNORECASE)
    return pattern.sub(r'<mark>\1</mark>', text)

def get_law_list_from_api(query):
    exact_query = f'"{query}"'
    encoded_query = quote(exact_query)
    page = 1
    laws = []
    while True:
        url = f"{BASE}/DRF/lawSearch.do?OC={OC}&target=law&type=XML&display=100&page={page}&search=2&knd=A0002&query={encoded_query}"
        try:
            res = requests.get(url, timeout=10)
            res.encoding = 'utf-8'
            if res.status_code != 200:
                break
            root = ET.fromstring(res.content)
            for law in root.findall("law"):
                laws.append({
                    "법령명": law.findtext("법령명한글", "").strip(),
                    "MST": law.findtext("법령일련번호", "")
                })
            if len(root.findall("law")) < 100:
                break
            page += 1
        except Exception as e:
            print(f"법률 검색 중 오류 발생: {e}")
            break
    # 디버깅을 위해 검색된 법률 목록 출력
    print(f"검색된 법률 수: {len(laws)}")
    for idx, law in enumerate(laws):
        print(f"{idx+1}. {law['법령명']}")
    return laws

def get_law_text_by_mst(mst):
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&MST={mst}&type=XML"
    try:
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code == 200:
            return res.content
        else:
            print(f"법령 XML 가져오기 실패: 상태 코드 {res.status_code}")
            return None
    except Exception as e:
        print(f"법령 XML 가져오기 중 오류 발생: {e}")
        return None

def clean(text):
    return re.sub(r"\s+", "", text or "")

def normalize_number(text):
    try:
        return str(int(unicodedata.numeric(text)))
    except:
        return text

def make_article_number(조문번호, 조문가지번호):
    return f"제{조문번호}조의{조문가지번호}" if 조문가지번호 and 조문가지번호 != "0" else f"제{조문번호}조"

def has_batchim(word):
    """단어의 마지막 글자에 받침이 있는지 확인"""
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    return (code % 28) != 0

def has_rieul_batchim(word):
    """단어의 마지막 글자의 받침이 ㄹ인지 확인"""
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    return (code % 28) == 8  # ㄹ받침 코드는 8

def extract_article_num(loc):
    """조번호를 추출하여 정수로 변환하는 함수"""
    article_match = re.search(r'제(\d+)조(?:의(\d+))?', loc)
    if not article_match:
        return (0, 0)
    
    # 조번호를 정수로 변환 (37 < 357 정렬을 위해)
    article_num = int(article_match.group(1))
    article_sub = int(article_match.group(2)) if article_match.group(2) else 0
    
    return (article_num, article_sub)

def extract_chunk_and_josa(token, searchword):
    """검색어를 포함하는 덩어리와 조사를 추출"""
    # 제외할 접미사 리스트 (덩어리에 포함시키지 않을 것들)
    suffix_exclude = ["의", "에", "에서", "에게", "으로서", "로서", "으로써", "로써", 
                     "등", "등의", "등인", "등만", "등에", "만", "만을", "만이", "만은", "만에", "만으로"]
    
    # 처리할 조사 리스트 (규칙에 따른 18가지 조사)
    josa_list = ["을", "를", "과", "와", "이", "가", "이나", "나", "으로", "로", "은", "는", "란", "이란", "라", "이라", "로서", "으로서", "로써", "으로써"]
    
    # 원본 토큰 저장
    original_token = token
    suffix = None
    
    # 검색어 자체가 토큰인 경우 바로 반환
    if token == searchword:
        return token, None, None
    
    # 토큰에 검색어가 포함되어 있지 않으면 바로 반환
    if searchword not in token:
        return token, None, None
    
    # 토큰이 검색어로 시작하는지 확인
    if not token.startswith(searchword):
        # 검색어가 토큰 중간에 있는 경우 (다른 단어의 일부)
        return token, None, None
    
    # 1. 접미사 제거 시도 (덩어리에 포함시키지 않음)
    for s in sorted(suffix_exclude, key=len, reverse=True):
        if token == searchword + s:
            # 정확히 "검색어+접미사"인 경우 (예: "지방법원에")
            print(f"접미사 처리: '{token}' = '{searchword}' + '{s}'")  # 디버깅
            return searchword, None, s
    
    # 2. 조사 확인 (조사는 규칙에 따라 처리)
    for j in sorted(josa_list, key=len, reverse=True):
        if token == searchword + j:
            # 정확히 "검색어+조사"인 경우 (예: "지방법원을")
            print(f"조사 처리: '{token}' = '{searchword}' + '{j}'")  # 디버깅
            return searchword, j, None
    
    # 3. 덩어리 처리 (검색어 뒤에 다른 문자가 있는 경우)
    if token.startswith(searchword) and len(token) > len(searchword):
        # 예: "지방법원판사", "지방법원장" 등 (검색어 뒤에 다른 단어가 붙음)
        print(f"덩어리 전체 처리: '{token}' (검색어: '{searchword}')")  # 디버깅
        return token, None, None
    
    # 기본 반환 - 토큰 전체
    return token, None, None

def apply_josa_rule(orig, replaced, josa):
    """개정문 조사 규칙에 따라 적절한 형식 반환 (규칙 참조)"""
    # 동일한 단어면 변경할 필요 없음
    if orig == replaced:
        return f'"{orig}"를 "{replaced}"로 한다.'
        
    # 받침 여부 확인
    orig_has_batchim = has_batchim(orig)
    replaced_has_batchim = has_batchim(replaced)
    replaced_has_rieul = has_rieul_batchim(replaced)
    
    # 조사가 없는 경우 (규칙 0)
    if josa is None:
        if not orig_has_batchim:  # 규칙 0-1: A가 받침 없는 경우
            if not replaced_has_batchim or replaced_has_rieul:  # 규칙 0-1-1, 0-1-2-1
                return f'"{orig}"를 "{replaced}"로 한다.'
            else:  # 규칙 0-1-2-2: B의 받침이 ㄹ이 아닌 경우
                return f'"{orig}"를 "{replaced}"으로 한다.'
        else:  # 규칙 0-2: A가 받침 있는 경우
            if not replaced_has_batchim or replaced_has_rieul:  # 규칙 0-2-1, 0-2-2-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 0-2-2-2: B의 받침이 ㄹ이 아닌 경우
                return f'"{orig}"을 "{replaced}"으로 한다.'
    
    # 조사별 규칙 처리
    if josa == "을":  # 규칙 1
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 1-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 1-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 1-2
            return f'"{orig}을"을 "{replaced}를"로 한다.'
    
    elif josa == "를":  # 규칙 2
        if replaced_has_batchim:  # 규칙 2-1
            return f'"{orig}를"을 "{replaced}을"로 한다.'
        else:  # 규칙 2-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "과":  # 규칙 3
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 3-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 3-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 3-2
            return f'"{orig}과"를 "{replaced}와"로 한다.'
    
    elif josa == "와":  # 규칙 4
        if replaced_has_batchim:  # 규칙 4-1
            return f'"{orig}와"를 "{replaced}과"로 한다.'
        else:  # 규칙 4-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "이":  # 규칙 5
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 5-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 5-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 5-2
            return f'"{orig}이"를 "{replaced}가"로 한다.'
    
    elif josa == "가":  # 규칙 6
        if replaced_has_batchim:  # 규칙 6-1
            return f'"{orig}가"를 "{replaced}이"로 한다.'
        else:  # 규칙 6-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "이나":  # 규칙 7
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 7-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 7-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 7-2
            return f'"{orig}이나"를 "{replaced}나"로 한다.'
    
    elif josa == "나":  # 규칙 8
        if replaced_has_batchim:  # 규칙 8-1
            return f'"{orig}나"를 "{replaced}이나"로 한다.'
        else:  # 규칙 8-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "으로":  # 규칙 9
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 9-1-1
                return f'"{orig}으로"를 "{replaced}로"로 한다.'
            else:  # 규칙 9-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 9-2
            return f'"{orig}으로"를 "{replaced}로"로 한다.'
    
    elif josa == "로":  # 규칙 10
        if orig_has_batchim:  # 규칙 10-1: A에 받침이 있는 경우
            if replaced_has_batchim:
                if replaced_has_rieul:  # 규칙 10-1-1-1
                    return f'"{orig}"을 "{replaced}"로 한다.'
                else:  # 규칙 10-1-1-2
                    return f'"{orig}로"를 "{replaced}으로"로 한다.'
            else:  # 규칙 10-1-2
                return f'"{orig}"을 "{replaced}"로 한다.'
        else:  # 규칙 10-2: A에 받침이 없는 경우
            if replaced_has_batchim:
                if replaced_has_rieul:  # 규칙 10-2-1-1
                    return f'"{orig}"를 "{replaced}"로 한다.'
                else:  # 규칙 10-2-1-2
                    return f'"{orig}로"를 "{replaced}으로"로 한다.'
            else:  # 규칙 10-2-2
                return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "는":  # 규칙 11
        if replaced_has_batchim:  # 규칙 11-1
            return f'"{orig}는"을 "{replaced}은"으로 한다.'
        else:  # 규칙 11-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "은":  # 규칙 12
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 12-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 12-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 12-2
            return f'"{orig}은"을 "{replaced}는"으로 한다.'
    
    elif josa == "란":  # 규칙 13
        if replaced_has_batchim:  # 규칙 13-1
            return f'"{orig}란"을 "{replaced}이란"으로 한다.'
        else:  # 규칙 13-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "이란":  # 규칙 14
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 14-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 14-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 14-2
            return f'"{orig}이란"을 "{replaced}란"으로 한다.'
    
    elif josa == "로서" or josa == "로써":  # 규칙 15
        if orig_has_batchim:  # 규칙 15-1: A에 받침이 있는 경우
            if replaced_has_batchim:
                if replaced_has_rieul:  # 규칙 15-1-1-1
                    return f'"{orig}"을 "{replaced}"로 한다.'
                else:  # 규칙 15-1-1-2
                    return f'"{orig}{josa}"를 "{replaced}으{josa}"로 한다.'
            else:  # 규칙 15-1-2
                return f'"{orig}"을 "{replaced}"로 한다.'
        else:  # 규칙 15-2: A에 받침이 없는 경우
            if replaced_has_batchim:
                if replaced_has_rieul:  # 규칙 15-2-1-1
                    return f'"{orig}"를 "{replaced}"로 한다.'
                else:  # 규칙 15-2-1-2
                    return f'"{orig}{josa}"를 "{replaced}으{josa}"로 한다.'
            else:  # 규칙 15-2-2
                return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "으로서" or josa == "으로써":  # 규칙 16
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 16-1-1
                return f'"{orig}{josa}"를 "{replaced}로{josa[2:]}"로 한다.'
            else:  # 규칙 16-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 16-2
            return f'"{orig}{josa}"를 "{replaced}로{josa[2:]}"로 한다.'
    
    elif josa == "라":  # 규칙 17
        if replaced_has_batchim:  # 규칙 17-1
            return f'"{orig}라"를 "{replaced}이라"로 한다.'
        else:  # 규칙 17-2
            return f'"{orig}"를 "{replaced}"로 한다.'
    
    elif josa == "이라":  # 규칙 18
        if replaced_has_batchim:
            if replaced_has_rieul:  # 규칙 18-1-1
                return f'"{orig}"을 "{replaced}"로 한다.'
            else:  # 규칙 18-1-2
                return f'"{orig}"을 "{replaced}"으로 한다.'
        else:  # 규칙 18-2
            return f'"{orig}이라"를 "{replaced}라"로 한다.'
    
    # 기본 출력 형식
    if orig_has_batchim:
        return f'"{orig}"을 "{replaced}"로 한다.'
    else:
        return f'"{orig}"를 "{replaced}"로 한다.'

def format_location(loc):
    """위치 정보 형식 수정: 항번호가 비어있는 경우와 호번호, 목번호의 period 제거"""
    # 항번호가 비어있는 경우 "제항" 제거
    loc = re.sub(r'제(?=항)', '', loc)
    
    # 호번호와 목번호 뒤의 period(.) 제거
    loc = re.sub(r'(\d+)\.호', r'\1호', loc)
    loc = re.sub(r'([가-힣])\.목', r'\1목', loc)
    
    return loc

def group_locations(loc_list):
    """위치 정보 그룹화 (조 > 항 > 호 > 목 순서로 사전식 정렬)
    - 조 또는 항이 바뀌면 콤마(,)로 연결
    - 같은 조항 내 호목은 가운뎃점(ㆍ)으로 연결
    - 마지막은 '및'으로 연결
    """
    if not loc_list:
        return ""
    
    # 각 위치 문자열에 형식 수정 적용
    formatted_locs = [format_location(loc) for loc in loc_list]
    
    # 조항호목 파싱 함수 (모든 정렬 기준 추출)
    def parse_location(loc):
        # 조번호 (정수로 변환)
        article_num, article_sub = extract_article_num(loc)
        
        # 항번호 (정수로 변환)
        clause_match = re.search(r'제(\d+)항', loc)
        clause_num = int(clause_match.group(1)) if clause_match else 0
        
        # 호번호 (정수로 변환)
        item_match = re.search(r'제(\d+)호', loc)
        item_num = int(item_match.group(1)) if item_match else 0
        
        # 목번호 (가나다 순서)
        subitem_match = re.search(r'([가-힣])목', loc)
        subitem_num = ord(subitem_match.group(1)) - ord('가') + 1 if subitem_match else 0
        
        # 제목 여부
        title_match = re.search(r'제목', loc)
        is_title = 1 if title_match else 0
        
        return (article_num, article_sub, clause_num, item_num, subitem_num, is_title)
    
    # 위치 정보 정렬 (사전식)
    sorted_locs = sorted(formatted_locs, key=parse_location)
    
    # 같은 조항끼리 그룹화
    groups = {}
    
    for loc in sorted_locs:
        # 조번호 추출
        article_match = re.match(r'(제\d+조(?:의\d+)?)', loc)
        if not article_match:
            continue
            
        article_num = article_match.group(1)
        rest_part = loc[len(article_num):]
        
        # 항번호 추출
        clause_part = ""
        clause_match = re.search(r'(제\d+항)', rest_part)
        if clause_match:
            clause_part = clause_match.group(1)
            rest_part = rest_part[rest_part.find(clause_part) + len(clause_part):]
        
        # 제목 여부 확인
        title_part = ""
        if " 제목" in loc:
            if " 제목 및 본문" in loc:
                title_part = " 제목 및 본문"
            else:
                title_part = " 제목"
            
            # 제목 부분 제거
            rest_part = rest_part.replace(title_part, "")
        
        # 호목 정보 추출
        item_goal_part = ""
        if "제" in rest_part and ("호" in rest_part or "목" in rest_part):
            # 호 또는 목 정보가 있는 경우
            item_match = re.match(r'^제\d+호|^[가-힣]목', rest_part.strip())
            if item_match:
                item_goal_part = rest_part.strip()
        
        # 조항(+제목) 기준으로 그룹화
        key = (article_num, clause_part, title_part)
        
        if key not in groups:
            groups[key] = []
            
        if item_goal_part:
            groups[key].append(item_goal_part)
    
    # 최종 결과 조합
    result_parts = []
    
    # 같은 조의 항은 함께 그룹화 시도
    article_groups = {}
    
    for (article_num, clause_part, title_part), items in groups.items():
        # 조번호가 같으면 항들을 그룹화
        if article_num not in article_groups:
            article_groups[article_num] = []
        
        # 항번호와 제목, 호목 정보 저장
        article_groups[article_num].append((clause_part, title_part, items))
    
    # 조별로 처리
    for article_num, clause_items in sorted(article_groups.items(), key=lambda x: extract_article_num(x[0])):
        # 같은 조의 항이 여러 개인 경우
        if len(clause_items) > 1:
            # 항만 있고 호목이 없는 경우
            clauses_no_items = [(clause, title) for clause, title, items in clause_items if not items]
            
            if clauses_no_items:
                # 항들을 모아서 "제X조제Y항 및 제Z항" 형식
                clause_parts = []
                for i, (clause, title) in enumerate(clauses_no_items):
                    if i == 0:
                        # 첫 번째 항은 조번호와 함께
                        clause_parts.append(f"{article_num}{title}{clause}")
                    else:
                        # 나머지 항은 항번호만
                        clause_parts.append(f"{clause}")
                
                if len(clause_parts) > 1:
                    # 여러 항인 경우 마지막만 '및'으로 구분
                    result_parts.append(", ".join(clause_parts[:-1]) + f" 및 {clause_parts[-1]}")
                else:
                    result_parts.append(clause_parts[0])
            
            # 호목이 있는 경우
            clauses_with_items = [(clause, title, items) for clause, title, items in clause_items if items]
            
            for clause, title, items in clauses_with_items:
                loc_str = f"{article_num}{title}{clause}"
                
                if items:
                    # 호/목은 가운뎃점(ㆍ)으로 연결
                    loc_str += ("제" + "ㆍ제".join([item.strip("제") for item in sorted(items, key=lambda x: parse_location(f"{article_num}{clause}제{x}"))]))
                
                result_parts.append(loc_str)
        else:
            # 단일 항인 경우
            clause, title, items = clause_items[0]
            loc_str = f"{article_num}{title}{clause}"
            
            if items:
                # 호/목은 가운뎃점(ㆍ)으로 연결
                loc_str += ("제" + "ㆍ제".join([item.strip("제") for item in sorted(items, key=lambda x: parse_location(f"{article_num}{clause}제{x}"))]))
            
            result_parts.append(loc_str)
    
    # 최종 연결 (쉼표로 구분하고 마지막은 '및'으로 연결)
    if len(result_parts) > 1:
        return ", ".join(result_parts[:-1]) + f" 및 {result_parts[-1]}"
    elif result_parts:
        return result_parts[0]
    else:
        return ""

def run_amendment_logic(find_word, replace_word):
    """개정문 생성 로직"""
    amendment_results = []
    skipped_laws = []  # 디버깅을 위해 누락된 법률 추적
    
    # 부칙 정보 확인을 위한 변수
    부칙_검색됨 = False  # 부칙에서 검색어가 발견되었는지 여부
    
    laws = get_law_list_from_api(find_word)
    print(f"총 {len(laws)}개 법률이 검색되었습니다.")
    
    # 실제로 출력된 법률을 추적하기 위한 변수
    출력된_법률수 = 0
    
    for idx, law in enumerate(laws):
        law_name = law["법령명"]
        mst = law["MST"]
        print(f"처리 중: {idx+1}/{len(laws)} - {law_name} (MST: {mst})")
        
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            skipped_laws.append(f"{law_name}: XML 데이터 없음")
            continue
            
        try:
            tree = ET.fromstring(xml_data)
        except ET.ParseError as e:
            skipped_laws.append(f"{law_name}: XML 파싱 오류 - {str(e)}")
            continue
            
        articles = tree.findall(".//조문단위")
        if not articles:
            skipped_laws.append(f"{law_name}: 조문단위 없음")
            continue
            
        print(f"조문 개수: {len(articles)}")
        
        chunk_map = defaultdict(list)
        
        # 법률에서 검색어의 모든 출현을 찾기 위한 디버깅 변수
        found_matches = 0
        found_in_부칙 = False  # 부칙에서 검색어 발견됨
        
        # 법률의 모든 텍스트 내용을 검색
        for article in articles:
            # 조문
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = make_article_number(조번호, 조가지번호)
            
            # 조문의 부칙 여부 확인
            조문명 = article.findtext("조문명", "").strip()
            is_부칙 = "부칙" in 조문명
            
            # 조문 제목 검색 (추가)
            조문제목 = article.findtext("조문제목", "") or ""
            제목에_검색어_있음 = find_word in 조문제목
            
            # 조문내용에서 검색
            조문내용 = article.findtext("조문내용", "") or ""
            본문에_검색어_있음 = find_word in 조문내용
            
            if 제목에_검색어_있음 or 본문에_검색어_있음:
                found_matches += 1
                if is_부칙:
                    found_in_부칙 = True
                    continue  # 부칙은 검색에서 제외
                
                # 위치 정보에 제목 표시 추가
                location_suffix = ""
                if 제목에_검색어_있음 and 본문에_검색어_있음:
                    location_suffix = " 제목 및 본문"
                elif 제목에_검색어_있음:
                    location_suffix = " 제목"
                
                if 제목에_검색어_있음:
                    tokens = re.findall(r'[가-힣A-Za-z0-9]+', 조문제목)
                    for token in tokens:
                        if find_word in token:
                            chunk, josa, suffix = extract_chunk_and_josa(token, find_word)
                            replaced = chunk.replace(find_word, replace_word)
                            location = f"{조문식별자} 제목"
                            chunk_map[(chunk, replaced, josa, suffix)].append(location)
                
                if 본문에_검색어_있음:
                    print(f"매치 발견: {조문식별자}{location_suffix if not 제목에_검색어_있음 else ''}")
                    tokens = re.findall(r'[가-힣A-Za-z0-9]+', 조문내용)
                    for token in tokens:
                        if find_word in token:
                            chunk, josa, suffix = extract_chunk_and_josa(token, find_word)
                            replaced = chunk.replace(find_word, replace_word)
                            location = f"{조문식별자}{location_suffix if not 제목에_검색어_있음 else ''}"
                            chunk_map[(chunk, replaced, josa, suffix)].append(location)

            # 항 내용 검색
            for 항 in article.findall("항"):
                항번호 = normalize_number(항.findtext("항번호", "").strip())
                항번호_부분 = f"제{항번호}항" if 항번호 else ""
                
                항내용 = 항.findtext("항내용", "") or ""
                if find_word in 항내용:
                    found_matches += 1
                    if is_부칙:
                        found_in_부칙 = True
                        continue  # 부칙은 검색에서 제외
                        
                    print(f"매치 발견: {조문식별자}{항번호_부분}")
                    tokens = re.findall(r'[가-힣A-Za-z0-9]+', 항내용)
                    for token in tokens:
                        if find_word in token:
                            chunk, josa, suffix = extract_chunk_and_josa(token, find_word)
                            replaced = chunk.replace(find_word, replace_word)
                            location = f"{조문식별자}{항번호_부분}"
                            chunk_map[(chunk, replaced, josa, suffix)].append(location)
                
                # 호 내용 검색
                for 호 in 항.findall("호"):
                    호번호 = 호.findtext("호번호")
                    호내용 = 호.findtext("호내용", "") or ""
                    if find_word in 호내용:
                        found_matches += 1
                        if is_부칙:
                            found_in_부칙 = True
                            continue  # 부칙은 검색에서 제외
                            
                        print(f"매치 발견: {조문식별자}{항번호_부분}제{호번호}호")
                        tokens = re.findall(r'[가-힣A-Za-z0-9]+', 호내용)
                        for token in tokens:
                            if find_word in token:
                                chunk, josa, suffix = extract_chunk_and_josa(token, find_word)
                                replaced = chunk.replace(find_word, replace_word)
                                location = f"{조문식별자}{항번호_부분}제{호번호}호"
                                chunk_map[(chunk, replaced, josa, suffix)].append(location)

                    # 목 내용 검색
                    for 목 in 호.findall("목"):
                        목번호 = 목.findtext("목번호")
                        for m in 목.findall("목내용"):
                            if not m.text:
                                continue
                                
                            if find_word in m.text:
                                found_matches += 1
                                if is_부칙:
                                    found_in_부칙 = True
                                    continue  # 부칙은 검색에서 제외
                                    
                                print(f"매치 발견: {조문식별자}{항번호_부분}제{호번호}호{목번호}목")
                                줄들 = [line.strip() for line in m.text.splitlines() if line.strip()]
                                for 줄 in 줄들:
                                    if find_word in 줄:
                                        tokens = re.findall(r'[가-힣A-Za-z0-9]+', 줄)
                                        for token in tokens:
                                            if find_word in token:
                                                chunk, josa, suffix = extract_chunk_and_josa(token, find_word)
                                                replaced = chunk.replace(find_word, replace_word)
                                                location = f"{조문식별자}{항번호_부분}제{호번호}호{목번호}목"
                                                chunk_map[(chunk, replaced, josa, suffix)].append(location)

        # 검색 결과가 없으면 다음 법률로
        if not chunk_map:
            continue
        
        # 디버깅을 위해 추출된 청크 정보 출력
        print(f"추출된 청크 수: {len(chunk_map)}")
        for (chunk, replaced, josa, suffix), locations in chunk_map.items():
            print(f"청크: '{chunk}', 대체: '{replaced}', 조사: '{josa}', 접미사: '{suffix}', 위치 수: {len(locations)}")
        
        # 같은 출력 형식을 가진 항목들을 그룹화
        rule_map = defaultdict(list)
        
        for (chunk, replaced, josa, suffix), locations in chunk_map.items():
            # "로서/로써", "으로서/으로써" 특수 접미사 처리
            if suffix in ["로서", "로써", "으로서", "으로써"]:
                # 로서/로써인 경우는 규칙 15, 으로서/으로써인 경우는 규칙 16 적용
                if suffix.startswith("으"):
                    # 규칙 16
                    if has_batchim(replaced):
                        if has_rieul_batchim(replaced):  # 규칙 16-1-1
                            rule = f'"{chunk}{suffix}"를 "{replaced}로{suffix[2:]}"로 한다.'
                        else:  # 규칙 16-1-2
                            rule = f'"{chunk}"을 "{replaced}"으로 한다.'
                    else:  # 규칙 16-2
                        rule = f'"{chunk}{suffix}"를 "{replaced}로{suffix[2:]}"로 한다.'
                else:
                    # 규칙 15
                    if has_batchim(chunk):  # 규칙 15-1
                        if has_batchim(replaced):
                            if has_rieul_batchim(replaced):  # 규칙 15-1-1-1
                                rule = f'"{chunk}"을 "{replaced}"로 한다.'
                            else:  # 규칙 15-1-1-2
                                rule = f'"{chunk}{suffix}"를 "{replaced}으{suffix}"로 한다.'
                        else:  # 규칙 15-1-2
                            rule = f'"{chunk}"을 "{replaced}"로 한다.'
                    else:  # 규칙 15-2
                        if has_batchim(replaced):
                            if has_rieul_batchim(replaced):  # 규칙 15-2-1-1
                                rule = f'"{chunk}"를 "{replaced}"로 한다.'
                            else:  # 규칙 15-2-1-2
                                rule = f'"{chunk}{suffix}"를 "{replaced}으{suffix}"로 한다.'
                        else:  # 규칙 15-2-2
                            rule = f'"{chunk}"를 "{replaced}"로 한다.'
            # "등", "등인", "등만", "에" 등의 접미사는 덩어리에서 제외하고 일반 처리
            elif suffix in ["등", "등인", "등만", "등의", "등에", "에", "에게", "만", "만을", "만이", "만은", "만에", "만으로"]:
                # 규칙 0 적용 (조사가 없는 경우)
                rule = apply_josa_rule(chunk, replaced, josa)
            elif suffix and suffix != "의":  # "의"는 개별 처리하지 않음
                # 접미사가 있는 경우 접미사를 포함한 단어로 처리
                orig_with_suffix = chunk + suffix
                replaced_with_suffix = replaced + suffix
                rule = apply_josa_rule(orig_with_suffix, replaced_with_suffix, josa)
            else:
                # 일반 규칙 적용
                rule = apply_josa_rule(chunk, replaced, josa)
                
            rule_map[rule].extend(locations)
        
        # 그룹화된 항목들을 정렬하여 출력
        consolidated_rules = []
        for rule, locations in rule_map.items():
            # 중복 위치 제거 및 정렬
            unique_locations = sorted(set(locations))
            
            # 2개 이상의 위치가 있으면 '각각'을 추가
            if len(unique_locations) > 1 and "각각" not in rule:
                # "A"를 "B"로 한다 -> "A"를 각각 "B"로 한다 형식으로 변경
                parts = re.match(r'(".*?")(을|를) (".*?")(으로|로) 한다\.?', rule)
                if parts:
                    orig = parts.group(1)
                    article = parts.group(2)
                    replace = parts.group(3)
                    suffix = parts.group(4)
                    modified_rule = f'{orig}{article} 각각 {replace}{suffix} 한다.'
                    result_line = f"{group_locations(unique_locations)} 중 {modified_rule}"
                else:
                    # 정규식 매치 실패 시 원래 문자열 사용
                    result_line = f"{group_locations(unique_locations)} 중 {rule}"
            else:
                result_line = f"{group_locations(unique_locations)} 중 {rule}"
            
            consolidated_rules.append(result_line)
        
        # 출력 준비
        if consolidated_rules:
            출력된_법률수 += 1
            prefix = chr(9312 + 출력된_법률수 - 1) if 출력된_법률수 <= 20 else f'({출력된_법률수})'
            
            # HTML 형식으로 출력 (br 태그 사용)
            amendment = f"{prefix} {law_name} 일부를 다음과 같이 개정한다.<br>"
            
            # 각 규칙마다 br 태그로 줄바꿈 추가
            for i, rule in enumerate(consolidated_rules):
                amendment += rule
                if i < len(consolidated_rules) - 1:  # 마지막 규칙이 아니면 줄바꿈 두 번
                    amendment += "<br>"
                else:
                    amendment += "<br>"  # 마지막 규칙은 줄바꿈 한 번
            
            amendment_results.append(amendment)
        else:
            skipped_laws.append(f"{law_name}: 결과줄이 생성되지 않음")

    # 디버깅 정보 출력
    if skipped_laws:
        print("---누락된 법률 목록---")
        for law in skipped_laws:
            print(law)
        
    # 함수의 리턴문
    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]

def run_search_logic(query, unit="법률"):
    """검색 로직 실행 함수"""
    result_dict = {}
    keyword_clean = clean(query)
    for law in get_law_list_from_api(query):
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue
        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        law_results = []
        for article in articles:
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = make_article_number(조번호, 조가지번호)
            조문내용 = article.findtext("조문내용", "") or ""
            항들 = article.findall("항")
            출력덩어리 = []
            조출력 = keyword_clean in clean(조문내용)
            첫_항출력됨 = False
            if 조출력:
                출력덩어리.append(highlight(조문내용, query))
            for 항 in 항들:
                항번호 = normalize_number(항.findtext("항번호", "").strip())
                항내용 = 항.findtext("항내용", "") or ""
                항출력 = keyword_clean in clean(항내용)
                항덩어리 = []
                하위검색됨 = False
                for 호 in 항.findall("호"):
                    호내용 = 호.findtext("호내용", "") or ""
                    호출력 = keyword_clean in clean(호내용)
                    if 호출력:
                        하위검색됨 = True
                        항덩어리.append("&nbsp;&nbsp;" + highlight(호내용, query))
                    for 목 in 호.findall("목"):
                        for m in 목.findall("목내용"):
                            if m.text and keyword_clean in clean(m.text):
                                줄들 = [line.strip() for line in m.text.splitlines() if line.strip()]
                                줄들 = [highlight(line, query) for line in 줄들]
                                if 줄들:
                                    하위검색됨 = True
                                    항덩어리.append(
                                        "<div style='margin:0;padding:0'>" +
                                        "<br>".join("&nbsp;&nbsp;&nbsp;&nbsp;" + line for line in 줄들) +
                                        "</div>"
                                    )
                if 항출력 or 하위검색됨:
                    if not 조출력 and not 첫_항출력됨:
                        출력덩어리.append(f"{highlight(조문내용, query)} {highlight(항내용, query)}")
                        첫_항출력됨 = True
                    elif not 첫_항출력됨:
                        출력덩어리.append(highlight(항내용, query))
                        첫_항출력됨 = True
                    else:
                        출력덩어리.append(highlight(항내용, query))
                    출력덩어리.extend(항덩어리)
            if 출력덩어리:
                law_results.append("<br>".join(출력덩어리))
        if law_results:
            result_dict[law["법령명"]] = law_results
    return result_dict

# 전체 파일 실행 시 필요한 코드
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("사용법: python law_processor.py <명령> <검색어> [바꿀단어]")
        print("  명령: search, amend")
        print("  예시1: python law_processor.py search 지방법원")
        print("  예시2: python law_processor.py amend 지방법원 지역법원")
        sys.exit(1)
    
    command = sys.argv[1]
    search_word = sys.argv[2]
    
    if command == "search":
        results = run_search_logic(search_word)
        for law_name, snippets in results.items():
            print(f"## {law_name}")
            for snippet in snippets:
                print(snippet)
                print("---")
    
    elif command == "amend":
        if len(sys.argv) < 4:
            print("바꿀단어를 입력하세요.")
            sys.exit(1)
        
        replace_word = sys.argv[3]
        results = run_amendment_logic(search_word, replace_word)
        
        for result in results:
            print(result)
            print("\n")
    
    else:
        print(f"알 수 없는 명령: {command}")
        sys.exit(1)

