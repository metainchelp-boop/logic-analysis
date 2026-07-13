"""엑셀/CSV 업로드·수동입력 파서 — API 없는 채널(당근·토스·모비온) 및 보조 입력용.

업로드 파일(.xlsx/.csv)의 제목줄을 키워드로 자동 인식해 정규화 형태(_common.ads_result)로 변환.
인식 컬럼: 노출/클릭/광고비/전환/전환매출/캠페인(소재)/날짜. 한글 헤더·cp949 인코딩 지원.
"""
import csv
import io

from ._common import ads_result

HEADER_MAP = {
    "impressions": ["노출", "노출수", "impression", "impressions", "imp"],
    "clicks":      ["클릭", "클릭수", "click", "clicks"],
    "spend":       ["광고비", "비용", "지출", "소진", "cost", "spend"],
    "conversions": ["전환수", "전환", "conversion", "conversions", "conv"],
    "conv_value":  ["전환매출", "매출", "전환금액", "revenue", "convvalue", "conv_value"],
    "name":        ["캠페인", "소재", "광고그룹", "광고", "캠페인명", "name", "campaign"],
    "date":        ["날짜", "일자", "date", "기간"],
    # 일괄 업로드 자동매칭용 — 광고 계정 식별자(GFA '광고 계정 ID/이름')
    "account_id":   ["광고계정id", "계정id", "accountid", "광고계정번호", "계정번호", "광고주id"],
    "account_name": ["광고계정이름", "광고계정명", "계정이름", "계정명", "accountname"],
}

# 단가·평균·비율·유형 컬럼은 '합계' 지표가 아니므로 매칭에서 제외한다.
# (예: 결과당 비용=0, 평균 CPC, 평균 CPM, 광고수익률(ROAS), 비용 유형 → 광고비로 오인 방지)
EXCLUDE_TOKENS = ["결과당", "전환당", "클릭당", "노출당", "당비용", "평균",
                  "cpc", "cpm", "단가", "수익률", "유형", "per"]


def _norm(s):
    return str(s or "").strip().lower().replace(" ", "")


def _match_col(header):
    """헤더 → 표준 키. '전환매출'이 '전환'보다 우선되도록 가장 긴(구체적) 키워드 매칭을 택한다.

    단, 단가·평균·비율 컬럼(결과당 비용·평균 CPC·광고수익률 등)은 합계 대상이 아니라 제외한다.
    """
    h = _norm(header)
    if not h:
        return None
    if any(tok in h for tok in EXCLUDE_TOKENS):
        return None
    best_key, best_len = None, 0
    for key, kws in HEADER_MAP.items():
        for kw in kws:
            nk = _norm(kw)
            if nk and nk in h and len(nk) > best_len:
                best_key, best_len = key, len(nk)
    return best_key


def _to_num(v):
    if v is None:
        return 0
    s = str(v).replace(",", "").replace("원", "").replace("%", "").replace("₩", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0


def _rows_from_bytes(data, filename):
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        return [list(row) for row in ws.iter_rows(values_only=True)]
    # csv (utf-8-sig → cp949 폴백)
    text = None
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if text is None:
        text = data.decode("utf-8", "ignore")
    return [row for row in csv.reader(io.StringIO(text))]


def _detect_header(rows):
    """앞 6행 중 노출/클릭/광고비 1개 이상 + 총 2개 이상 매칭되는 첫 행 → (idx, colmap)."""
    for i, row in enumerate(rows[:6]):
        m = {}
        for j, cell in enumerate(row):
            k = _match_col(cell)
            if k and k not in m:
                m[k] = j
        if any(k in m for k in ("impressions", "clicks", "spend")) and len(m) >= 2:
            return i, m
    return None, {}


def _cell(row, colmap, key):
    j = colmap.get(key)
    return row[j] if (j is not None and j < len(row)) else None


def _aggregate(data_rows, colmap):
    """헤더 이후 행들 → (totals, items). 빈/전부0 행은 스킵."""
    items = []
    t = {"impressions": 0, "clicks": 0, "spend": 0.0, "conversions": 0, "conv_value": 0.0}
    for row in data_rows:
        if not row or all(c in (None, "") for c in row):
            continue
        imp = int(_to_num(_cell(row, colmap, "impressions")))
        clk = int(_to_num(_cell(row, colmap, "clicks")))
        sp = _to_num(_cell(row, colmap, "spend"))
        cn = int(_to_num(_cell(row, colmap, "conversions")))
        cv = _to_num(_cell(row, colmap, "conv_value"))
        if imp == 0 and clk == 0 and sp == 0 and cv == 0:
            continue
        nm = _cell(row, colmap, "date") or _cell(row, colmap, "name") or "(행)"
        t["impressions"] += imp; t["clicks"] += clk; t["spend"] += sp
        t["conversions"] += cn; t["conv_value"] += cv
        items.append({
            "name": str(nm), "impressions": imp, "clicks": clk,
            "spend": round(sp), "roas": round(cv / sp * 100) if sp else None,
        })
    t["spend"] = round(t["spend"]); t["conv_value"] = round(t["conv_value"])
    return t, items


def parse_upload(channel, data, filename):
    rows = [r for r in _rows_from_bytes(data, filename) if r and any(c not in (None, "") for c in r)]
    if not rows:
        raise RuntimeError("빈 파일이에요. 데이터가 있는 엑셀/CSV를 올려주세요.")
    header_idx, colmap = _detect_header(rows)
    if header_idx is None:
        raise RuntimeError("표의 제목줄을 못 찾았어요. '노출·클릭·광고비·전환·매출·캠페인' 같은 열 제목이 필요해요.")
    t, items = _aggregate(rows[header_idx + 1:], colmap)
    if not items:
        raise RuntimeError("숫자 데이터가 있는 행을 못 찾았어요. 표 내용과 열 제목을 확인해주세요.")
    return ads_result(channel, t, items, period="업로드", note="엑셀/CSV 업로드 데이터")


def parse_upload_multi(channel, data, filename):
    """파일을 '광고 계정 ID'(없으면 계정 이름)별로 분리해 per-account 결과 리스트를 반환.

    반환: [{"account_id": str|None, "account_name": str|None, "data": ads_result}]
    계정 식별 컬럼이 없으면 파일 전체를 1건(account_id=None)으로 묶는다(자동매칭 불가→이름/단일).
    일괄 업로드(여러 파일/여러 계정 한 파일) 자동매칭용.
    """
    rows = [r for r in _rows_from_bytes(data, filename) if r and any(c not in (None, "") for c in r)]
    if not rows:
        raise RuntimeError("빈 파일이에요. 데이터가 있는 엑셀/CSV를 올려주세요.")
    header_idx, colmap = _detect_header(rows)
    if header_idx is None:
        raise RuntimeError("표의 제목줄을 못 찾았어요. '노출·클릭·광고비' 같은 열 제목이 필요해요.")
    groups = {}  # key → {"account_id","account_name","rows":[]}
    for row in rows[header_idx + 1:]:
        if not row or all(c in (None, "") for c in row):
            continue
        aid = str(_cell(row, colmap, "account_id") or "").strip()
        anm = str(_cell(row, colmap, "account_name") or "").strip()
        key = aid or anm or "__ALL__"
        g = groups.setdefault(key, {"account_id": aid, "account_name": anm, "rows": []})
        if not g["account_id"] and aid:
            g["account_id"] = aid
        if not g["account_name"] and anm:
            g["account_name"] = anm
        g["rows"].append(row)
    out = []
    for g in groups.values():
        t, items = _aggregate(g["rows"], colmap)
        if not items:
            continue
        out.append({
            "account_id": g["account_id"] or None,
            "account_name": g["account_name"] or None,
            "data": ads_result(channel, t, items, period="업로드", note="일괄 업로드"),
        })
    if not out:
        raise RuntimeError("숫자 데이터가 있는 행을 못 찾았어요. 표 내용과 열 제목을 확인해주세요.")
    return out


def manual_entry(channel, totals, items=None, period=""):
    keys = ["impressions", "clicks", "spend", "conversions", "conv_value"]
    t = {}
    for k in keys:
        v = _to_num((totals or {}).get(k, 0))
        t[k] = int(v) if k in ("impressions", "clicks", "conversions") else round(v)
    its = items or [{
        "name": "전체", "impressions": t["impressions"], "clicks": t["clicks"],
        "spend": t["spend"], "roas": round(t["conv_value"] / t["spend"] * 100) if t["spend"] else None,
    }]
    return ads_result(channel, t, its, period=period or "수동입력", note="마케터 수동 입력")
