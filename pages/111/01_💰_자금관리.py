import streamlit as st
import pandas as pd
import os
import io
import json
import time
import re
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# -----------------------------------------------------------------------------
# [중요] 경로 설정 (pages 폴더 안에 있으므로 부모 디렉토리 참조)
# -----------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# 부모 폴더에 있는 file_engine 모듈 가져오기
import file_engine as engine

# =============================================================================
# 1. 페이지 설정 및 기본 경로 정의
# =============================================================================
st.set_page_config(page_title="자금 관리 | 회사 통합 시스템", layout="wide")

# 작업 공간은 루트 디렉토리(parent_dir) 아래의 workspaces 폴더
BASE_DIR = parent_dir
UPLOAD_ROOT = os.path.join(BASE_DIR, "workspaces")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

SAFE_COL_AMOUNT = "금액"

# =============================================================================
# 2. 유틸리티 함수 (캐시, 브랜드 맵, 자동 추출)
# =============================================================================
def get_file_hash(filepath):
    """파일 변경 감지를 위한 해시 생성"""
    try:
        stat = os.stat(filepath)
        return f"{filepath}_{stat.st_mtime}_{stat.st_size}"
    except: return filepath

@st.cache_data(ttl=3600)
def get_cached_brand_map(work_dir, _cache_key):
    """브랜드 매핑 JSON 파일 로드 (캐시 적용)"""
    p = os.path.join(work_dir, "brands.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def load_brand_map(work_dir):
    """브랜드 매핑 로드 래퍼"""
    p = os.path.join(work_dir, "brands.json")
    cache_key = get_file_hash(p) if os.path.exists(p) else "empty"
    return get_cached_brand_map(work_dir, cache_key)

def save_brand_map(work_dir, data):
    """브랜드 매핑 저장"""
    p = os.path.join(work_dir, "brands.json")
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        get_cached_brand_map.clear() # 저장 후 캐시 초기화
    except: pass

def extract_brand_auto(client_name):
    """거래처명에서 브랜드명 자동 추출 (정규식)"""
    if pd.isna(client_name) or str(client_name).strip() == "": return None
    name = str(client_name).strip()
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    remove_words = ['주식회사', '(주)', '㈜', '유한회사', '(유)', 'Corp', 'Corporation', 'Co', 'Ltd', 'LLC', 'Inc', '코리아', 'Korea', '재팬', 'Japan', '차이나', 'China', '지점', '본사', '본점', '영업소']
    for word in remove_words: name = name.replace(word, '')
    name = re.sub(r'[^\w가-힣\s]', '', name)
    name = name.strip()
    if len(name) < 2 or name.isdigit(): return None
    return name

# =============================================================================
# 3. 데이터 로더 (병렬 처리 + 정렬 보장)
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def read_file_cached(filepath, filename, col_info, file_hash):
    return engine.read_single_file(filepath, filename, col_info)

def load_folder_parallel(path, col_info, max_workers=4):
    files = sorted([f for f in os.listdir(path) if f.endswith((".xlsx", ".xls", ".csv")) and not f.startswith("~$") and not f.startswith("month_") and not f.endswith("brands.json")])
    if not files: return [], []
    
    results = []
    status = []
    total = len(files)
    progress_bar = st.progress(0)
    status_text = st.empty()
    completed = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        for f in files:
            filepath = os.path.join(path, f)
            file_hash = get_file_hash(filepath)
            future = executor.submit(read_file_cached, filepath, f, col_info, file_hash)
            future_to_file[future] = f
            
        for future in as_completed(future_to_file):
            f = future_to_file[future]
            completed += 1
            status_text.text(f"📂 읽는 중 ({completed}/{total}): {f}")
            progress_bar.progress(completed / total)
            try:
                df, msg = future.result()
                status.append({"file": f, "ok": df is not None, "msg": msg, "data": df})
                if df is not None: results.append((f, df))
            except Exception as e:
                status.append({"file": f, "ok": False, "msg": f"오류: {str(e)}", "data": None})
    
    # [중요] 파일명 순으로 정렬하여 리스트 순서 섞임 방지
    results.sort(key=lambda x: x[0])
    dfs = [r[1] for r in results]
                
    time.sleep(0.3); status_text.empty(); progress_bar.empty()
    return dfs, status

@st.cache_data(ttl=3600)
def aggregate_brand_data(df, amount_col):
    """브랜드별 집계 (제외/미지정 항목 자동 필터링)"""
    # '제외' 및 '미지정' 브랜드는 분석에서 뺌
    df = df[~df['브랜드'].isin(['제외', '미지정'])]
    
    brand_agg = df.groupby(['브랜드', '거래_유형'])[amount_col].sum().unstack(fill_value=0)
    for c in ['매출(청구)', '매입(청구)', '실제출금']:
        if c not in brand_agg.columns: brand_agg[c] = 0
            
    brand_agg['순이익'] = brand_agg['매출(청구)'] - brand_agg['매입(청구)'] - brand_agg['실제출금']
    return brand_agg.sort_values('순이익', ascending=False)

# =============================================================================
# 4. 콜백 함수 (체크박스 상태 유지용)
# =============================================================================
def update_manual_selection():
    """수동 관리 탭 체크박스 콜백"""
    edited_rows = st.session_state["manual_editor"]["edited_rows"]
    current_ids = st.session_state.get('manual_view_ids', [])
    for idx_str, change in edited_rows.items():
        idx = int(idx_str)
        if idx < len(current_ids) and "선택" in change:
            target_id = current_ids[idx]
            if change["선택"]: st.session_state.manual_selected_ids.add(target_id)
            else: st.session_state.manual_selected_ids.discard(target_id)

def update_bank_selection():
    """은행 비용 탭 체크박스 콜백"""
    edited_rows = st.session_state["bank_editor"]["edited_rows"]
    current_ids = st.session_state.get('bank_view_ids', [])
    for idx_str, change in edited_rows.items():
        idx = int(idx_str)
        if idx < len(current_ids) and "선택" in change:
            target_id = current_ids[idx]
            if change["선택"]: st.session_state.bank_selected_ids.add(target_id)
            else: st.session_state.bank_selected_ids.discard(target_id)

# =============================================================================
# 5. UI 메인 (사이드바)
# =============================================================================
st.sidebar.title("🗂 작업 월 선택")
months = sorted([d.name for d in os.scandir(UPLOAD_ROOT) if d.is_dir()], reverse=True)
choice = st.sidebar.selectbox("선택", months + ["➕ 새 작업 월"])

if choice == "➕ 새 작업 월":
    nm = st.sidebar.text_input("월 입력 (YYYY-MM)", datetime.now().strftime("%Y-%m"))
    if st.sidebar.button("생성"):
        os.makedirs(os.path.join(UPLOAD_ROOT, nm), exist_ok=True)
        st.rerun()
    st.stop()

WORK_DIR = os.path.join(UPLOAD_ROOT, choice)

st.sidebar.markdown("---")
if st.sidebar.button("🗑️ 초기화 (파일 삭제)", type="primary"):
    try:
        for f in os.listdir(WORK_DIR):
            file_path = os.path.join(WORK_DIR, f)
            if os.path.isfile(file_path): os.remove(file_path)
        st.cache_data.clear()
        st.success("초기화 완료!"); time.sleep(1); st.rerun()
    except Exception as e: st.error(f"오류: {e}")

uploaded = st.sidebar.file_uploader("엑셀/CSV 파일 업로드", accept_multiple_files=True)
if uploaded:
    for f in uploaded:
        with open(os.path.join(WORK_DIR, f.name), "wb") as w: w.write(f.getbuffer())
    st.cache_data.clear()
    st.success("업로드 완료!"); st.rerun()

st.sidebar.markdown("---")
with st.sidebar.expander("⚙️ 컬럼 매핑 설정"):
    col_type = st.text_input("구분", "구분")
    col_client = st.text_input("거래처", "상호")
    col_item = st.text_input("품목", "품목")
    col_amount = st.text_input("금액", "합계 : 합계금액")
    col_date = st.text_input("날짜", "작성일자")
    st.caption("은행 파일 설정")
    bank_date = st.text_input("은행 날짜", "거래일시")
    bank_desc = st.text_input("은행 내용", "적요")
    bank_out = st.text_input("은행 출금", "출금")
    bank_in = st.text_input("은행 입금", "입금")

col_info = (col_type, col_client, col_item, col_amount, col_date, bank_date, bank_desc, bank_out, bank_in)

# 데이터 로딩 시작
with st.spinner("📊 데이터를 분석하고 있습니다..."):
    dfs, status_list = load_folder_parallel(WORK_DIR, col_info, max_workers=4)

st.sidebar.markdown("---")
with st.sidebar.expander("📋 파일 처리 상태", expanded=False):
    for s in status_list:
        if s["ok"]: st.success(f"✅ {s['file']}")
        else: st.error(f"❌ {s['file']}")

if not dfs:
    st.info("데이터가 없습니다. 파일을 업로드해주세요.")
    st.stop()

# 데이터 병합 및 초기 브랜드 매핑
merged = pd.concat(dfs, ignore_index=True)
brand_map = load_brand_map(WORK_DIR)
merged['브랜드'] = merged['id'].map(brand_map).fillna("미지정")

# =============================================================================
# 6. 메인 탭 구성
# =============================================================================
tab1, tab2, tab3 = st.tabs(["💰 월별 정산 리포트", "📊 데이터 통합 확인", "🔍 파일별 검증"])

# -----------------------------------------------------------------------------
# TAB 1: 정산 리포트 (메인 기능)
# -----------------------------------------------------------------------------
with tab1:
    st.header(f"💰 {choice} 자금 관리 리포트")
    
    if merged.empty:
        st.info("데이터 없음")
    else:
        # 사업장 필터
        if '사업장' in merged.columns:
            unique_companies = merged['사업장'].dropna().unique()
            company_list = sorted([x for x in unique_companies if str(x).strip() != ""])
            company_options = ["전체"] + company_list
            selected_company = st.radio("🏢 사업장 선택", company_options, horizontal=True)
            view_df = merged.copy() if selected_company == "전체" else merged[merged['사업장'] == selected_company].copy()
        else:
            view_df = merged.copy()
            selected_company = "전체"

        # [계산용 데이터] '제외' 및 '미지정' 브랜드를 뺀 유효 데이터
        active_view_df = view_df[~view_df['브랜드'].isin(['제외', '미지정'])].copy()
        
        # 기본 매출/매입 DF 생성 (순서 보장)
        sales_df = active_view_df[active_view_df['거래_유형'] == '매출(청구)'].copy()
        purchase_df = active_view_df[active_view_df['거래_유형'] == '매입(청구)'].copy()

        st.markdown("---")
        
        # ----------------------------------------
        # 브랜드 관리 섹션
        # ----------------------------------------
        st.subheader("🏷️ 브랜드 분류 관리 (세금계산서)")
        
        # 관리용 DF (미지정도 포함해서 보여줘야 함)
        brand_manage_df = view_df[view_df['데이터출처'] == '세금계산서'].copy()
        if '브랜드_AI추천' not in brand_manage_df.columns:
            brand_manage_df['브랜드_AI추천'] = brand_manage_df[col_client].apply(extract_brand_auto)
        
        existing_brands = sorted([b for b in brand_manage_df['브랜드'].unique() if b != '미지정'])
        
        t_ai, t_manual, t_bulk = st.tabs(["🤖 AI 추천", "✏️ 수동 선택", "📦 거래처 일괄"])
        
        # [AI 추천 탭]
        with t_ai:
            auto_df = brand_manage_df[(brand_manage_df['브랜드'] == '미지정') & (brand_manage_df['브랜드_AI추천'].notna())].copy()
            if auto_df.empty: st.info("자동 추천할 항목이 없습니다.")
            else:
                grouped = auto_df.groupby('브랜드_AI추천').agg({col_client: lambda x: ', '.join(x.unique()[:3]), 'id': 'count', SAFE_COL_AMOUNT: 'sum'}).reset_index()
                grouped.columns = ['브랜드', '거래처', '건수', '금액']
                grouped.insert(0, '적용', True)
                edited_auto = st.data_editor(grouped, hide_index=True, use_container_width=True)
                if st.button("✅ AI 추천 적용", type="primary"):
                    applied = 0
                    for _, row in edited_auto[edited_auto['적용']].iterrows():
                        target_ids = auto_df[auto_df['브랜드_AI추천'] == row['브랜드']]['id'].tolist()
                        for id_val in target_ids: brand_map[id_val] = row['브랜드']; applied += 1
                    save_brand_map(WORK_DIR, brand_map)
                    st.success(f"{applied}건 적용 완료!"); time.sleep(1); st.rerun()
        
        # [수동 선택 탭]
        with t_manual:
            if 'manual_selected_ids' not in st.session_state: st.session_state.manual_selected_ids = set()
            with st.expander("🔍 상세 필터 열기", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                filter_unassigned = c1.checkbox("미지정만 보기", value=False)
                brand_filter = c2.selectbox("브랜드", ["전체"] + sorted(brand_manage_df['브랜드'].unique().tolist()))
                amount_filter = c3.selectbox("금액", ["전체", "100만↑", "50만↑", "10만↑", "10만↓"])
                sort_by = c4.selectbox("정렬", ["금액↓", "금액↑", "가나다"])
                
                s1, s2, s3 = st.columns(3)
                search_text = s1.text_input("거래처 검색")
                item_search = s2.text_input("품목 검색")
                global_search = s3.text_input("전체 검색")
            
            # 필터링 로직
            manual_df = brand_manage_df.copy()
            if filter_unassigned: manual_df = manual_df[manual_df['브랜드'] == '미지정']
            if search_text: manual_df = manual_df[manual_df[col_client].astype(str).str.contains(search_text, case=False, na=False)]
            if brand_filter != "전체": manual_df = manual_df[manual_df['브랜드'] == brand_filter]
            if amount_filter == "100만↑": manual_df = manual_df[manual_df[SAFE_COL_AMOUNT] >= 1000000]
            elif amount_filter == "50만↑": manual_df = manual_df[manual_df[SAFE_COL_AMOUNT] >= 500000]
            elif amount_filter == "10만↑": manual_df = manual_df[manual_df[SAFE_COL_AMOUNT] >= 100000]
            elif amount_filter == "10만↓": manual_df = manual_df[manual_df[SAFE_COL_AMOUNT] < 100000]
            if item_search: manual_df = manual_df[manual_df[col_item].astype(str).str.contains(item_search, case=False, na=False)]
            if global_search:
                mask = pd.Series([False]*len(manual_df), index=manual_df.index)
                for col in manual_df.select_dtypes(include=['object']).columns: mask |= manual_df[col].astype(str).str.contains(global_search, case=False, na=False)
                manual_df = manual_df[mask]
            
            if sort_by == "금액↓": manual_df = manual_df.sort_values(SAFE_COL_AMOUNT, ascending=False)
            elif sort_by == "금액↑": manual_df = manual_df.sort_values(SAFE_COL_AMOUNT, ascending=True)
            elif sort_by == "가나다": manual_df = manual_df.sort_values(col_client)
            
            manual_df = manual_df.reset_index(drop=True)
            display_cols = ['브랜드', '브랜드_AI추천', col_client, col_item, SAFE_COL_AMOUNT]
            display_cols = [c for c in display_cols if c in manual_df.columns]
            manual_df_display = manual_df[display_cols + ['id']].copy()
            manual_df_display['선택'] = manual_df_display['id'].isin(st.session_state.manual_selected_ids)
            
            # 현재 뷰 ID 저장 (콜백용)
            st.session_state['manual_view_ids'] = manual_df_display['id'].tolist()
            
            b1, b2, b3, b4, b5 = st.columns([2, 1, 1, 1, 1])
            sel_count = len(st.session_state.manual_selected_ids)
            b1.info(f"✅ {sel_count}건")
            if b2.button("✅ 전체선택", use_container_width=True):
                st.session_state.manual_selected_ids.update(set(manual_df['id'].tolist())); st.rerun()
            if b3.button("❌ 선택해제", use_container_width=True):
                st.session_state.manual_selected_ids.clear(); st.rerun()
            if b4.button("🔄 새로고침", use_container_width=True): st.rerun()
            manual_height = b5.slider("목록 높이", 300, 1500, 500, 100, label_visibility="collapsed")
            
            st.data_editor(
                manual_df_display[['선택'] + display_cols],
                column_config={"선택": st.column_config.CheckboxColumn("☑", width="small"), "브랜드": st.column_config.TextColumn("브랜드", disabled=True), SAFE_COL_AMOUNT: st.column_config.NumberColumn("금액", format="%d")},
                hide_index=True, use_container_width=True, height=manual_height, key="manual_editor", on_change=update_manual_selection
            )
            
            st.markdown("---")
            x1, x2, x3, x4 = st.columns([1, 2, 1, 1])
            brand_method = x1.radio("방식", ["기존", "신규"], horizontal=True, label_visibility="collapsed")
            if brand_method == "기존": selected_brand = x2.selectbox("브랜드 선택", [""] + existing_brands) if existing_brands else ""
            else: selected_brand = x2.text_input("신규 입력")
            
            # [수정] 고유 키 적용
            if x3.button("🚀 적용", type="primary", use_container_width=True, disabled=(sel_count == 0), key="btn_manual_apply"):
                if selected_brand and selected_brand.strip():
                    for id_val in st.session_state.manual_selected_ids: brand_map[id_val] = selected_brand.strip()
                    save_brand_map(WORK_DIR, brand_map)
                    st.session_state.manual_selected_ids.clear()
                    st.success("적용 완료!"); time.sleep(1); st.rerun()
                else: st.warning("브랜드명 입력 필요")
            
            # [수정] 고유 키 적용
            if x4.button("⛔ 제외", use_container_width=True, disabled=(sel_count == 0), key="btn_manual_exclude"):
                for id_val in st.session_state.manual_selected_ids: brand_map[id_val] = "제외"
                save_brand_map(WORK_DIR, brand_map)
                st.session_state.manual_selected_ids.clear()
                st.success("선택 항목 제외 완료!"); time.sleep(1); st.rerun()

        # [일괄 적용 탭]
        with t_bulk:
            client_summary = brand_manage_df[brand_manage_df['브랜드'] == '미지정'].groupby(col_client).agg({'id': 'count', SAFE_COL_AMOUNT: 'sum', '브랜드_AI추천': 'first'}).reset_index()
            client_summary.columns = ['거래처', '건수', '금액', 'AI']
            client_summary = client_summary.sort_values('금액', ascending=False)
            if client_summary.empty: st.info("일괄 적용할 미지정 거래처가 없습니다.")
            else:
                client_summary.insert(0, '적용', False)
                client_summary['브랜드'] = client_summary['AI'].fillna('')
                edited_bulk = st.data_editor(client_summary, column_config={"적용": st.column_config.CheckboxColumn(), "금액": st.column_config.NumberColumn(format="%d")}, hide_index=True, use_container_width=True)
                if st.button("✅ 일괄 적용", type="primary"):
                    applied = 0
                    for _, row in edited_bulk[edited_bulk['적용']].iterrows():
                        if row['브랜드'].strip():
                            target_ids = brand_manage_df[(brand_manage_df[col_client] == row['거래처']) & (brand_manage_df['브랜드'] == '미지정')]['id']
                            for id_val in target_ids: brand_map[id_val] = row['브랜드'].strip(); applied += 1
                    if applied: save_brand_map(WORK_DIR, brand_map); st.success(f"{applied}건 적용 완료!"); time.sleep(1); st.rerun()

        st.markdown("---")
        # ----------------------------------------
        # 브랜드별 손익 분석
        # ----------------------------------------
        st.subheader("📊 손익 분석 (미지정/제외 항목 미포함)")
        
        analysis_type = st.radio("분석 기준", ["브랜드별", "품목별"], horizontal=True)
        if analysis_type == "브랜드별": brand_agg = aggregate_brand_data(active_view_df, SAFE_COL_AMOUNT)
        else:
            brand_agg = active_view_df.groupby([col_item, '거래_유형'])[SAFE_COL_AMOUNT].sum().unstack(fill_value=0)
            for c in ['매출(청구)', '매입(청구)', '실제출금']: 
                if c not in brand_agg.columns: brand_agg[c] = 0
            brand_agg['순이익'] = brand_agg['매출(청구)'] - brand_agg['매입(청구)'] - brand_agg['실제출금']
            brand_agg = brand_agg.sort_values('순이익', ascending=False)
        
        def color_profit(val): return f'color: {"blue" if val > 0 else "red" if val < 0 else "black"}; font-weight: bold'
        st.dataframe(brand_agg[['매출(청구)', '매입(청구)', '실제출금', '순이익']].style.format("{:,.0f}").map(color_profit, subset=['순이익']), use_container_width=True)
        
        st.markdown("---")
        # ----------------------------------------
        # 은행 비용 관리
        # ----------------------------------------
        st.subheader("🏦 은행 추가 비용 관리")
        if 'bank_selected_ids' not in st.session_state: st.session_state.bank_selected_ids = set()

        bank_out_df = view_df[view_df['거래_유형'] == '실제출금'].copy()
        
        if not bank_out_df.empty:
            bank_out_df = bank_out_df.sort_values(by=['자료원_파일명', col_client]).reset_index(drop=True)
            
            bank_cols = ['브랜드', '자료원_파일명', col_client, SAFE_COL_AMOUNT, 'id']
            bank_cols = [c for c in bank_cols if c in bank_out_df.columns]
            
            bank_display = bank_out_df[bank_cols].copy()
            bank_display['선택'] = bank_display['id'].isin(st.session_state.bank_selected_ids)
            
            st.session_state['bank_view_ids'] = bank_display['id'].tolist()
            
            bk1, bk2, bk3, bk4 = st.columns([2, 1, 1, 1])
            sel_bk_count = len(st.session_state.bank_selected_ids)
            bk1.info(f"✅ {sel_bk_count}건")
            if bk2.button("✅ 전체선택", key="bank_all"):
                st.session_state.bank_selected_ids.update(set(bank_out_df['id'].tolist())); st.rerun()
            if bk3.button("❌ 선택해제", key="bank_none"):
                st.session_state.bank_selected_ids.clear(); st.rerun()
            bank_height = bk4.slider("높이", 300, 1500, 500, 100, label_visibility="collapsed", key="bank_h")

            st.data_editor(
                bank_display[['선택'] + [c for c in bank_cols if c != 'id']],
                column_config={"선택": st.column_config.CheckboxColumn("☑", width="small"), "브랜드": st.column_config.TextColumn("현재 브랜드", disabled=True), SAFE_COL_AMOUNT: st.column_config.NumberColumn("금액", format="%d")},
                hide_index=True, use_container_width=True, height=bank_height, key="bank_editor", on_change=update_bank_selection
            )
            
            st.markdown("##### ⚙️ 선택 항목 비용/브랜드 적용")
            bk_c1, bk_c2, bk_c3, bk_c4 = st.columns([1, 2, 1, 1])
            bank_brand_method = bk_c1.radio("방식", ["공통비용", "기존", "신규"], key="bk_method", label_visibility="collapsed")
            if bank_brand_method == "공통비용": target_bank_brand = "공통비용"
            elif bank_brand_method == "기존": target_bank_brand = bk_c2.selectbox("브랜드 선택", [""] + existing_brands, key="bk_exist")
            else: target_bank_brand = bk_c2.text_input("브랜드 입력", placeholder="예: 나이키", key="bk_new")
            
            # [수정] 고유 키 적용
            if bk_c3.button("✅ 적용", type="primary", use_container_width=True, disabled=(sel_bk_count == 0), key="btn_bank_apply"):
                if target_bank_brand and target_bank_brand.strip():
                    for id_val in st.session_state.bank_selected_ids: brand_map[id_val] = target_bank_brand.strip()
                    save_brand_map(WORK_DIR, brand_map)
                    st.session_state.bank_selected_ids.clear()
                    st.success("적용 완료!"); time.sleep(1); st.rerun()
                else: st.warning("브랜드명을 입력하세요.")
            
            # [수정] 고유 키 적용
            if bk_c4.button("⛔ 제외", use_container_width=True, disabled=(sel_bk_count == 0), key="btn_bank_exclude"):
                for id_val in st.session_state.bank_selected_ids: brand_map[id_val] = "제외"
                save_brand_map(WORK_DIR, brand_map)
                st.session_state.bank_selected_ids.clear()
                st.success("제외 완료!"); time.sleep(1); st.rerun()
            
            # 비용 계산: '미지정'과 '제외'를 뺀 항목만 합산
            assigned_bank_expenses = bank_out_df[~bank_out_df['브랜드'].isin(['미지정', '제외'])][SAFE_COL_AMOUNT].sum()
            st.info(f"💰 비용 처리된 금액 (브랜드 지정된 항목만): {assigned_bank_expenses:,.0f} 원")
        else:
            assigned_bank_expenses = 0
            st.write("출금 내역 없음")
        
        st.markdown("---")
        # ----------------------------------------
        # 최종 리포트
        # ----------------------------------------
        st.subheader("💰 최종 결과 (미지정/제외 제외)")
        
        total_sales = sales_df[SAFE_COL_AMOUNT].sum()
        total_purchase = purchase_df[SAFE_COL_AMOUNT].sum()
        final_profit = total_sales - total_purchase - assigned_bank_expenses
        
        z1, z2, z3, z4 = st.columns(4)
        z1.metric("① 총 매출", f"{total_sales:,.0f}")
        z2.metric("② 총 매입", f"{total_purchase:,.0f}")
        z3.metric("③ 비용(은행)", f"{assigned_bank_expenses:,.0f}")
        z4.metric("💰 순수익", f"{final_profit:,.0f}")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            pd.DataFrame({"항목": ["총 매출", "총 매입", "비용(은행)", "최종 순수익"], "금액": [total_sales, total_purchase, assigned_bank_expenses, final_profit]}).to_excel(writer, sheet_name='요약', index=False)
            brand_agg.reset_index().to_excel(writer, sheet_name='브랜드별분석', index=False)
            if not bank_out_df.empty:
                bank_out_df[~bank_out_df['브랜드'].isin(['미지정', '제외'])].to_excel(writer, sheet_name='비용상세', index=False)
                
        st.download_button("💾 엑셀 다운로드", buffer.getvalue(), f"정산_{choice}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -----------------------------------------------------------------------------
# TAB 2: 데이터 확인
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("📊 데이터 통합 확인")
    table_height = st.slider("📏 표 높이 조절 (px)", 300, 2500, 800, 100, key="main_table_slider")
    cols = list(merged.columns)
    for c in ['브랜드', '사업장']:
        if c in cols: cols.remove(c); cols.insert(0, c)
    st.dataframe(merged[cols].style.format({SAFE_COL_AMOUNT: "{:,.0f}"}), use_container_width=True, height=table_height, hide_index=True)

# -----------------------------------------------------------------------------
# TAB 3: 파일 검증
# -----------------------------------------------------------------------------
with tab3:
    st.subheader("📋 파일 읽기 검증")
    for s in status_list:
        with st.expander(f"{'✅' if s['ok'] else '❌'} {s['file']}"):
            if s["ok"] and s["data"] is not None:
                st.dataframe(s["data"].head(10))
                st.caption(f"{len(s['data'])}행")
            else: st.error(s['msg'])