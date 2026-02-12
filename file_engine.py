import pandas as pd
import os
import glob
import warnings
import io
import re

# 경고 무시
warnings.filterwarnings("ignore")

# 기본 중복 방지 목록
DEFAULT_IGNORE_KEYWORDS = ["가앤", "프레피스", "케이에스넷", "KSNET", "나이스페이", "토스페이"]

# =============================================================================
# [공통] 파일 읽기 + 헤더 탐색 유틸리티 (load_and_classify_data + read_single_file 공용)
# =============================================================================

def _read_raw_dataframes(file):
    """파일을 읽어서 candidate DataFrame 리스트를 반환"""
    candidate_dfs = []
    try:
        with open(file, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        return [], f"파일 열기 실패: {e}"

    # 1. CSV
    if file.lower().endswith('.csv'):
        try:
            for enc in ['utf-8', 'cp949', 'euc-kr']:
                try:
                    df = pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, header=None)
                    df['__row_idx'] = range(len(df))
                    candidate_dfs.append(df)
                    break
                except:
                    pass
        except:
            pass

    # 2. Excel (CSV가 아닌 경우만)
    if not file.lower().endswith('.csv'):
        try:
            if file.lower().endswith('.xls'):
                excel_data = pd.read_excel(file, header=None, engine='xlrd', sheet_name=None)
            elif file.lower().endswith('.xlsx'):
                excel_data = pd.read_excel(file, header=None, sheet_name=None)
            else:
                excel_data = None

            if excel_data is not None:
                if isinstance(excel_data, dict):
                    for _, df in excel_data.items():
                        if not df.empty:
                            df['__row_idx'] = range(len(df))
                            candidate_dfs.append(df)
                else:
                    excel_data['__row_idx'] = range(len(excel_data))
                    candidate_dfs.append(excel_data)
        except:
            pass

    # 3. HTML (다른 방식으로 읽지 못한 경우)
    if not candidate_dfs:
        for enc in ['utf-8', 'cp949', 'euc-kr', 'utf-8-sig']:
            try:
                decoded_html = raw_bytes.decode(enc)
                dfs = pd.read_html(io.StringIO(decoded_html), header=None)
                if dfs:
                    for df in dfs:
                        df['__row_idx'] = range(len(df))
                    candidate_dfs.extend(dfs)
                    break
            except:
                pass

    if not candidate_dfs:
        return [], "내용을 읽을 수 없음"

    return candidate_dfs, "OK"


def _find_header_and_build_df(candidate_dfs):
    """candidate_dfs에서 헤더를 탐색하여 정제된 DataFrame을 반환"""
    final_df = None
    for raw_df in candidate_dfs:
        if raw_df is None or raw_df.empty:
            continue
        if raw_df.shape[1] < 4:
            continue

        found_header = False
        for i in range(min(50, len(raw_df))):
            row_values = raw_df.iloc[i].astype(str).tolist()
            row_str = "".join(row_values).replace(" ", "")
            is_tax = ("작성일자" in row_str) and (
                ("합계금액" in row_str) or ("공급가액" in row_str) or
                ("공급받는자" in row_str) or ("등록번호" in row_str)
            )
            is_bank = (
                ("일자" in row_str) or ("날짜" in row_str) or ("거래일" in row_str)
            ) and (
                ("입금" in row_str) or ("출금" in row_str) or ("찾으신" in row_str) or
                ("맡기신" in row_str) or ("내용" in row_str) or ("적요" in row_str) or
                ("지급" in row_str) or ("의뢰인" in row_str)
            )

            if is_tax or is_bank:
                try:
                    final_df = raw_df.iloc[i+1:].copy()
                    final_df.columns = raw_df.iloc[i]
                    cols = pd.Series(final_df.columns)
                    for dup in cols[cols.duplicated()].unique():
                        cols[cols[cols == dup].index.values.tolist()] = [
                            dup + '_' + str(j) if j != 0 else dup
                            for j in range(sum(cols == dup))
                        ]
                    final_df.columns = cols
                    found_header = True
                    break
                except:
                    continue
        if found_header:
            break

    return final_df


# =============================================================================
# [메인 함수 1] load_and_classify_data — 01_Finance.py / main.py 용
# =============================================================================

def load_and_classify_data(workspaces_dir, rules):
    """
    폴더 내의 모든 엑셀/HTML 파일을 읽어서 통합 DataFrame과 로딩 로그를 반환합니다.
    (수정: 투자 우선순위, 컬럼매핑 first-match, 출금 != 0)
    """
    load_status = {}

    user_ignore_list = rules.get("중복방지", [])
    final_ignore_list = list(set(DEFAULT_IGNORE_KEYWORDS + user_ignore_list))

    if not os.path.exists(workspaces_dir):
        return pd.DataFrame(), load_status

    all_files = glob.glob(os.path.join(workspaces_dir, "**", "*.xlsx"), recursive=True)
    all_files += glob.glob(os.path.join(workspaces_dir, "**", "*.xls"), recursive=True)
    all_files += glob.glob(os.path.join(workspaces_dir, "**", "*.csv"), recursive=True)

    all_tx = []

    for file in all_files:
        filename = os.path.basename(file)
        load_status[filename] = {"status": "Ready", "msg": "대기 중"}

        filename_lower = filename.lower()
        blacklist = [
            "contact", "project", "address", "phone", "member",
            "주소록", "연락처", "명부", "현황",
            "contract", "계약", "proposal", "제안", "schedule", "일정"
        ]

        if any(k in filename_lower for k in blacklist):
            load_status[filename] = {"status": "Ignore", "msg": "재무 데이터 아님 (제외됨)"}
            continue

        # A. 파일 읽기
        candidate_dfs, read_msg = _read_raw_dataframes(file)
        if not candidate_dfs:
            load_status[filename] = {"status": "Fail", "msg": read_msg}
            continue

        # A-2. KIS빌링 포맷 감지 및 처리
        kis_processed = False
        for raw_df in candidate_dfs:
            if raw_df.shape[1] < 6:
                continue
            # 상위 5행에서 "대리점명" + "승인건수" 패턴 탐색
            is_kis = False
            for i in range(min(5, len(raw_df))):
                row_str = "".join(raw_df.iloc[i].astype(str))
                if "대리점명" in row_str and "승인건수" in row_str:
                    is_kis = True
                    break
            if not is_kis:
                continue

            # KIS빌링 확인 — 데이터 행 추출
            # 헤더 이후 첫 데이터 행 찾기 (col 0이 실제 대리점명인 행)
            data_start = None
            for i in range(len(raw_df)):
                val = raw_df.iloc[i, 0]
                if pd.notna(val):
                    val_str = str(val).strip()
                    if val_str and val_str != "대리점명" and not val_str.startswith("nan"):
                        data_start = i
                        break
            if data_start is None:
                continue

            # 날짜: 파일명에서 추출 → 못 찾으면 파일 수정일
            date_str = _extract_date_from_filename(filename)
            if not date_str:
                try:
                    from datetime import datetime as _dt
                    mtime = os.path.getmtime(file)
                    date_str = _dt.fromtimestamp(mtime).strftime('%Y-%m')
                except:
                    from datetime import datetime as _dt
                    date_str = _dt.now().strftime('%Y-%m')

            kis_rows = []
            for i in range(data_start, len(raw_df)):
                name = raw_df.iloc[i, 0]
                amount = raw_df.iloc[i, 5]  # F열 (index 5)

                if pd.isna(name) or str(name).strip() == "":
                    continue
                name_str = str(name).strip()

                # 합계/인센티브/수수료 행 제외
                if any(kw in name_str for kw in ["합계", "인센티브", "수수료"]):
                    continue

                # 금액 변환
                try:
                    amt_val = float(str(amount).replace(",", ""))
                except:
                    amt_val = 0
                if pd.isna(amount) or amt_val == 0:
                    continue

                # 매출 규칙으로 소분류 결정 (긴 키워드 우선)
                sub_cat = name_str  # 기본값: 대리점명 전체
                for k, v in sorted(rules.get("매출", {}).items(), key=lambda x: len(x[0]), reverse=True):
                    if k in name_str:
                        sub_cat = v
                        break

                kis_rows.append({
                    '날짜': f"{date_str}-01",
                    '적요': name_str,
                    '입금': amt_val,
                    '출금': 0,
                    '파일명': filename,
                    '대분류': '매출',
                    '소분류': sub_cat,
                    '__row_idx': i
                })

            if kis_rows:
                temp = pd.DataFrame(kis_rows)
                temp['날짜'] = pd.to_datetime(temp['날짜'], errors='coerce').dt.strftime('%Y-%m-%d')
                all_tx.append(temp)
                load_status[filename] = {"status": "Success", "msg": f"KIS빌링 {len(kis_rows)}건 로드"}
                kis_processed = True
            else:
                load_status[filename] = {"status": "Warn", "msg": "KIS빌링 형식이나 유효 데이터 0건"}
                kis_processed = True
            break  # 첫 번째 매칭 시트만 처리

        if kis_processed:
            continue

        # B. 표 찾기
        final_df = _find_header_and_build_df(candidate_dfs)

        if final_df is None:
            load_status[filename] = {"status": "Skip", "msg": "헤더 미발견"}
            continue

        # C. 정제
        try:
            df = final_df.copy()
            df.columns = [str(c).strip().replace(" ", "") for c in df.columns]
            row_idx_col = next((c for c in df.columns if "__row_idx" in str(c)), None)

            col_map = {"date": None, "main_desc": None, "sub_desc": None, "in": None, "out": None, "amt": None}

            sangho_cols = [c for c in df.columns if "상호" in c]
            if sangho_cols:
                if "매출" in filename:
                    receiver_col = next((c for c in sangho_cols if "받는" in c), None)
                    col_map["main_desc"] = receiver_col if receiver_col else sangho_cols[-1]
                elif "매입" in filename:
                    supplier_col = next((c for c in sangho_cols if "받는" not in c), None)
                    col_map["main_desc"] = supplier_col if supplier_col else sangho_cols[0]
                else:
                    col_map["main_desc"] = sangho_cols[0]

            col_map["sub_desc"] = next((c for c in df.columns if "적요" in c), None)
            if col_map["main_desc"] is None:
                primary_keywords = ["의뢰인", "수취인", "기재내용", "내용", "받는분", "보낸분", "성명"]
                for kw in primary_keywords:
                    found = next((c for c in df.columns if kw in c and c != col_map["sub_desc"]), None)
                    if found:
                        col_map["main_desc"] = found
                        break
                if col_map["main_desc"] is None and col_map["sub_desc"] is not None:
                    col_map["main_desc"] = col_map["sub_desc"]
                    col_map["sub_desc"] = None

            # [수정 #7] 컬럼 매핑 — 첫 번째 매칭 우선 (덮어쓰기 방지)
            for c in df.columns:
                if col_map["date"] is None and any(k in c for k in ["작성일자", "일자", "날짜", "거래일"]):
                    col_map["date"] = c
                if col_map["in"] is None and any(k in c for k in ["입금", "맡기신"]):
                    col_map["in"] = c
                if col_map["out"] is None and any(k in c for k in ["출금", "찾으신", "지급"]):
                    col_map["out"] = c

            # 금액 컬럼: 키워드 우선순위대로 탐색 (공급가액 > 합계금액)
            # 컬럼 순회가 아닌 키워드 순회로, 엑셀 컬럼 순서와 무관하게 공급가액 우선
            for amt_keyword in ["공급가액", "합계금액"]:
                if col_map["amt"] is not None:
                    break
                for c in df.columns:
                    if amt_keyword in c:
                        col_map["amt"] = c
                        break

            if not col_map["date"]:
                load_status[filename] = {"status": "Skip", "msg": "날짜 컬럼 없음"}
                continue

            trash_keywords = ["합계", "총계", "소계", "누계", "평잔", "거래내역", "조회기간"]
            check_cols = [col_map["date"]]
            if col_map["main_desc"]:
                check_cols.append(col_map["main_desc"])
            for col in check_cols:
                for kw in trash_keywords:
                    df = df[~df[col].astype(str).str.contains(kw, na=False)]

            df['__parsed_date'] = pd.to_datetime(df[col_map["date"]], errors='coerce')
            df = df.dropna(subset=['__parsed_date'])

            temp = pd.DataFrame()

            def clean_money(series):
                if series is None:
                    return 0
                return pd.to_numeric(series.astype(str).str.replace(r'[^\d.-]', '', regex=True), errors='coerce').fillna(0)

            temp['날짜'] = df['__parsed_date'].dt.strftime('%Y-%m-%d')
            if row_idx_col:
                temp['__row_idx'] = df[row_idx_col]
            else:
                temp['__row_idx'] = df.index

            if col_map["main_desc"]:
                main_vals = df[col_map["main_desc"]].fillna("").astype(str).str.strip()
                temp['적요'] = main_vals
                if col_map["sub_desc"]:
                    sub_vals = df[col_map["sub_desc"]].fillna("").astype(str).str.strip()
                    mask_empty = (temp['적요'] == '') | (temp['적요'] == 'nan')
                    temp.loc[mask_empty, '적요'] = sub_vals[mask_empty]
            else:
                temp['적요'] = "내용없음"

            val_in = clean_money(df[col_map["in"]]) if col_map["in"] else 0
            val_out = clean_money(df[col_map["out"]]) if col_map["out"] else 0
            val_amt = clean_money(df[col_map["amt"]]) if col_map["amt"] else 0

            if "매출" in filename:
                temp['입금'] = val_amt if col_map["amt"] else val_in
                temp['출금'] = 0
            elif "매입" in filename:
                temp['입금'] = 0
                temp['출금'] = val_amt if col_map["amt"] else val_out
            else:
                temp['입금'] = val_in
                temp['출금'] = val_out
                if (col_map["amt"]) and (not col_map["in"]) and (not col_map["out"]):
                    temp['입금'] = val_amt

            temp['파일명'] = filename

            # -----------------------------------------------------------------
            # [수정 #5, #10] 분류 로직 — 투자 우선순위 수정 + 출금 != 0
            # -----------------------------------------------------------------
            # 규칙 매칭: 긴 키워드가 먼저 매칭되도록 정렬
            # 예) "김미정(해링턴플레이" → 해링턴임대료 가 "김미정" → 대표임금 보다 먼저 체크
            def _sorted_rules(category):
                return sorted(rules.get(category, {}).items(), key=lambda x: len(x[0]), reverse=True)

            sorted_매출 = _sorted_rules("매출")
            sorted_판관비 = _sorted_rules("판관비")
            sorted_기타비용 = _sorted_rules("기타비용")
            sorted_투자 = _sorted_rules("투자")

            def classify(row):
                desc = str(row['적요'])
                fname = str(row['파일명'])

                is_ignored = False
                for kw in final_ignore_list:
                    if kw in desc:
                        is_ignored = True
                        break

                # [입금]
                if row['입금'] != 0:
                    # 매출 파일 → 항상 분류
                    if "매출" in fname:
                        for k, v in sorted_매출:
                            if k in desc:
                                return "매출", v
                        return "매출", "세금계산서(매출)"

                    # 은행 입금 → 제외 키워드 있으면 무조건 제외
                    if is_ignored:
                        return "입금(매출제외)", "세금계산서 발행처"

                    # 은행 입금 → 규칙 매칭
                    for k, v in sorted_매출:
                        if k in desc:
                            return "입금(매출제외)", v
                    for k, v in sorted_투자:
                        if k in desc:
                            return "투자회수", v
                    return "미분류", "-"

                # [출금]
                if row['출금'] != 0:
                    # 매입 파일 → 항상 분류 (제외 영향 없음)
                    if "매입" in fname:
                        for k, v in sorted_판관비:
                            if k in desc:
                                return "판관비", v
                        for k, v in sorted_기타비용:
                            if k in desc:
                                return "기타비용", v
                        return "판관비", "세금계산서(매입)"

                    # 은행 출금 → 제외 키워드 있으면 무조건 제외
                    if is_ignored:
                        return "출금(비용제외)", "세금계산서 발행처"

                    # 은행 출금 → 규칙 매칭
                    for k, v in sorted_투자:
                        if k in desc:
                            return "투자", v
                    for k, v in sorted_판관비:
                        if k in desc:
                            return "판관비", v
                    for k, v in sorted_기타비용:
                        if k in desc:
                            return "기타비용", v
                    return "미분류", "-"

                return "미분류", "-"

            temp[['대분류', '소분류']] = temp.apply(lambda x: pd.Series(classify(x)), axis=1)
            temp = temp[(temp['입금'] != 0) | (temp['출금'] != 0)]

            mask = (temp['대분류'] == '매출') & (temp['출금'] > 0)
            if mask.any():
                temp.loc[mask, '입금'] = -temp.loc[mask, '출금']
                temp.loc[mask, '출금'] = 0

            if temp.empty:
                load_status[filename] = {"status": "Warn", "msg": "데이터 0건"}
            else:
                load_status[filename] = {"status": "Success", "msg": f"{len(temp)}건 로드"}
                all_tx.append(temp)

        except Exception as e:
            load_status[filename] = {"status": "Fail", "msg": f"처리 에러: {e}"}
            continue

    final_df = pd.concat(all_tx, ignore_index=True) if all_tx else pd.DataFrame()

    if not final_df.empty:
        final_df = final_df.drop_duplicates(subset=['날짜', '적요', '입금', '출금', '파일명', '__row_idx'], keep='first')

    return final_df, load_status


# =============================================================================
# [메인 함수 2] read_single_file — app.py (브랜드 정산) 용
# [수정 #4] file_engine.py에 read_single_file 호환 함수 복원
# =============================================================================

# 요약/합계 행 제거용 키워드
_DROP_KEYWORDS = ["요약", "합계", "소계", "누계", "총계", "월계", "이월",
                  "Total", "Subtotal", "Summary", "Sum", "Balance", "페이지", "Page"]
_DROP_PATTERN = '|'.join(_DROP_KEYWORDS)

_DATE_PATTERN = re.compile(r"(\d{4})[년\-/.](\d{1,2})")
_CURRENCY_PATTERN = re.compile(r"[^\d.-]")


def _clean_currency_val(x):
    """금액 문자열을 숫자로 변환"""
    if pd.isna(x) or x == "":
        return 0
    s = str(x).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = _CURRENCY_PATTERN.sub("", s)
    try:
        return float(s) * (-1 if neg else 1)
    except:
        return 0


def _extract_date_from_filename(name):
    """파일명에서 날짜(YYYY-MM) 추출"""
    m = _DATE_PATTERN.search(name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


def _find_col_fuzzy(columns, hint, keywords):
    """
    hint(사용자 지정 컬럼명)를 우선 매칭하고,
    없으면 keywords 리스트에서 부분 매칭.
    """
    cols = [str(c).strip() for c in columns]

    # 1. 정확 매칭
    if hint in cols:
        return hint

    # 2. 포함 매칭 (hint)
    hint_clean = hint.replace(" ", "")
    for c in cols:
        if hint_clean in c.replace(" ", ""):
            return c

    # 3. 키워드 매칭
    for kw in keywords:
        for c in cols:
            if kw in c:
                return c

    return None


def read_single_file(file_path, filename, col_info):
    """
    app.py에서 사용하는 단일 파일 읽기 함수.
    col_info = (col_type, col_client, col_item, col_amount, col_date,
                bank_date, bank_desc, bank_out, bank_in)
    반환: (DataFrame, msg) 또는 (None, error_msg)
    """
    col_type, col_client, col_item, col_amount, col_date, \
        bank_date, bank_desc, bank_out, bank_in = col_info

    SAFE_COL_AMOUNT = "금액"
    is_bank_file = any(kw in filename for kw in ["통장", "은행", "입출금"])

    # 1. 파일 읽기
    candidate_dfs, read_msg = _read_raw_dataframes(file_path)
    if not candidate_dfs:
        return None, read_msg

    # 2. 헤더 탐색
    df = _find_header_and_build_df(candidate_dfs)
    if df is None:
        return None, "헤더 미발견"

    # 컬럼명 정리
    df.columns = [str(c).strip().replace("\n", "") for c in df.columns]

    # 중복 컬럼명 처리
    seen = {}
    new_cols = []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            new_cols.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            new_cols.append(c)
    df.columns = new_cols

    df['자료원_파일명'] = filename

    # 요약/합계 행 제거
    for col in df.columns:
        try:
            mask = df[col].astype(str).str.contains(_DROP_PATTERN, na=False)
            df = df[~mask]
        except:
            pass

    df = df.dropna(how='all')

    try:
        if is_bank_file:
            # === 은행 파일 처리 ===
            t_date = _find_col_fuzzy(df.columns, bank_date, ["거래일", "거래일자", "거래일시", "일자", "전표일자"])
            t_desc = _find_col_fuzzy(df.columns, bank_desc, ["적요", "기재내용", "내용", "받는분", "보낸분", "상호", "의뢰인"])
            t_out = _find_col_fuzzy(df.columns, bank_out, ["출금", "찾으신금액", "지급"])
            t_in = _find_col_fuzzy(df.columns, bank_in, ["입금", "맡기신금액"])

            if not t_date:
                return None, f"날짜 컬럼 못찾음 (힌트: {bank_date})"

            result = pd.DataFrame()
            result['자료원_파일명'] = df['자료원_파일명']
            result[bank_date] = pd.to_datetime(df[t_date], errors='coerce')

            if t_desc:
                result[bank_desc] = df[t_desc].fillna("").astype(str).str.strip()
            else:
                result[bank_desc] = ""

            if t_out:
                result[bank_out] = df[t_out].apply(_clean_currency_val)
            else:
                result[bank_out] = 0
            if t_in:
                result[bank_in] = df[t_in].apply(_clean_currency_val)
            else:
                result[bank_in] = 0

            result = result.dropna(subset=[bank_date])

            # 출금/입금 각각 행으로 분리
            rows = []
            for _, row in result.iterrows():
                base = {
                    '자료원_파일명': row['자료원_파일명'],
                    col_client: row[bank_desc],
                    col_date: row[bank_date],
                }
                out_val = abs(row[bank_out]) if row[bank_out] != 0 else 0
                in_val = abs(row[bank_in]) if row[bank_in] != 0 else 0

                if out_val > 0:
                    r = base.copy()
                    r[SAFE_COL_AMOUNT] = out_val
                    r['거래_유형'] = '실제출금'
                    r['데이터출처'] = '은행'
                    rows.append(r)
                if in_val > 0:
                    r = base.copy()
                    r[SAFE_COL_AMOUNT] = in_val
                    r['거래_유형'] = '실제입금'
                    r['데이터출처'] = '은행'
                    rows.append(r)

            if not rows:
                return None, "은행 데이터 0건"

            final = pd.DataFrame(rows)

        else:
            # === 세금계산서 파일 처리 ===
            t_type = _find_col_fuzzy(df.columns, col_type, ["구분", "유형", "종류"])
            t_client = _find_col_fuzzy(df.columns, col_client, ["상호", "거래처", "공급자", "공급받는자"])
            t_item = _find_col_fuzzy(df.columns, col_item, ["품목", "품명", "항목", "비고"])
            # 금액 컬럼: 키워드 우선순위 탐색 (공급가액 > 합계금액)
            # hint(사용자 설정)보다 공급가액 키워드를 먼저 체크
            t_amount = None
            for amt_kw in ["공급가액", "합계금액", "합계:합계금액", "금액"]:
                for c in [str(col).strip() for col in df.columns]:
                    if amt_kw in c.replace(" ", ""):
                        t_amount = c
                        break
                if t_amount:
                    break
            # 키워드로 못 찾으면 hint로 폴백
            if not t_amount:
                t_amount = _find_col_fuzzy(df.columns, col_amount, [])
            t_date = _find_col_fuzzy(df.columns, col_date, ["작성일자", "일자", "날짜", "발행일"])

            if not t_date:
                return None, f"날짜 컬럼 못찾음 (힌트: {col_date})"
            if not t_amount:
                return None, f"금액 컬럼 못찾음 (힌트: {col_amount})"

            result = pd.DataFrame()
            result['자료원_파일명'] = df['자료원_파일명']
            result[col_date] = pd.to_datetime(df[t_date], errors='coerce')
            result[col_client] = df[t_client].fillna("").astype(str).str.strip() if t_client else ""
            result[col_item] = df[t_item].fillna("").astype(str).str.strip() if t_item else ""
            result[SAFE_COL_AMOUNT] = df[t_amount].apply(_clean_currency_val)
            result['데이터출처'] = '세금계산서'

            result = result.dropna(subset=[col_date])
            result = result[result[SAFE_COL_AMOUNT] != 0]

            # 매출/매입 판별
            if "매출" in filename:
                result['거래_유형'] = '매출(청구)'
            elif "매입" in filename:
                result['거래_유형'] = '매입(청구)'
            elif t_type:
                def detect_type(val):
                    s = str(val)
                    if "매출" in s or "발행" in s:
                        return "매출(청구)"
                    return "매입(청구)"
                result['거래_유형'] = df[t_type].apply(detect_type)
            else:
                result['거래_유형'] = '매입(청구)'

            final = result

        # 공통 후처리
        # 분석_월 추출
        date_col_name = col_date if col_date in final.columns else bank_date
        if date_col_name in final.columns:
            dates = pd.to_datetime(final[date_col_name], errors='coerce')
            final['분석_월'] = dates.dt.strftime('%Y-%m')
        else:
            extracted = _extract_date_from_filename(filename)
            final['분석_월'] = extracted if extracted else ""

        # 사업장 판별
        fn_lower = filename.lower()
        if any(k in fn_lower for k in ["가앤", "가엔", "gaen"]):
            final['사업장'] = "가앤"
        elif any(k in fn_lower for k in ["프레피", "prepisco"]):
            final['사업장'] = "프레피스코리아"
        else:
            final['사업장'] = "기타"

        # ID 생성 (중복 제거용)
        id_cols = ['자료원_파일명']
        if '분석_월' in final.columns:
            id_cols.append('분석_월')
        if col_client in final.columns:
            id_cols.append(col_client)
        if SAFE_COL_AMOUNT in final.columns:
            id_cols.append(SAFE_COL_AMOUNT)
        if '거래_유형' in final.columns:
            id_cols.append('거래_유형')

        final['id'] = final[id_cols].astype(str).agg('|'.join, axis=1)
        # 동일 id 내 순번 추가
        final['id'] = final['id'] + '|' + final.groupby('id').cumcount().astype(str)

        return final, f"{len(final)}건 로드 완료"

    except Exception as e:
        return None, f"처리 에러: {e}"
