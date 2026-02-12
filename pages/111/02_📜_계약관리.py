import streamlit as st
import pandas as pd
import os
import sys
import time
import re
import json
import fitz  # PyMuPDF
import glob
from datetime import datetime, date
from PIL import Image
import io

# 구글 Gemini 라이브러리
import google.generativeai as genai

# -----------------------------------------------------------------------------
# 경로 설정
# -----------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# =============================================================================
# 1. 페이지 설정 및 데이터 관리
# =============================================================================
st.set_page_config(page_title="계약 및 수납 관리", layout="wide")

BASE_DIR = parent_dir
CONTRACT_ROOT = os.path.join(BASE_DIR, "workspaces", "contracts")
FILES_DIR = os.path.join(CONTRACT_ROOT, "files")
DATA_FILE = os.path.join(CONTRACT_ROOT, "contract_list.csv")
SETTINGS_FILE = os.path.join(BASE_DIR, "workspaces", "settings.json")
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")

os.makedirs(FILES_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# 설정 관리
# -----------------------------------------------------------------------------
def load_api_key():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("google_api_key", "")
        except: return ""
    return ""

def save_api_key(key):
    try:
        data = {}
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["google_api_key"] = key
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

# -----------------------------------------------------------------------------
# 자금 데이터 연동 함수
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_all_transactions():
    """자금관리 메뉴의 엑셀 파일에서 입금 내역 로드"""
    all_files = glob.glob(os.path.join(WORKSPACES_DIR, "**", "*.xlsx"), recursive=True)
    all_tx = []
    
    for file in all_files:
        try:
            df = pd.read_excel(file)
            df.columns = [str(c).strip() for c in df.columns]
            
            deposit_col = None
            desc_col = None
            date_col = None
            
            for c in df.columns:
                if "입금" in c or "맡기신" in c: deposit_col = c
                if "내용" in c or "적요" in c or "보낸분" in c: desc_col = c
                if "일자" in c or "날짜" in c or "거래일" in c: date_col = c
            
            if deposit_col and desc_col:
                if date_col:
                    temp_df = df[[date_col, desc_col, deposit_col]].copy()
                    temp_df.columns = ['날짜', '적요', '입금액']
                    temp_df['날짜'] = temp_df['날짜'].astype(str).str[:10]
                else:
                    temp_df = df[[desc_col, deposit_col]].copy()
                    temp_df.columns = ['적요', '입금액']
                    temp_df['날짜'] = "-" 
                
                temp_df['입금액'] = pd.to_numeric(temp_df['입금액'], errors='coerce').fillna(0)
                temp_df = temp_df[temp_df['입금액'] > 0]
                temp_df['출처파일'] = os.path.basename(file)
                all_tx.append(temp_df)
        except: continue
            
    if all_tx:
        final_df = pd.concat(all_tx, ignore_index=True)
        if '날짜' not in final_df.columns: final_df['날짜'] = "-"
        return final_df
    else:
        return pd.DataFrame(columns=['날짜', '적요', '입금액', '출처파일'])

# -----------------------------------------------------------------------------
# AI 분석 함수
# -----------------------------------------------------------------------------
def get_available_vision_model(api_key):
    genai.configure(api_key=api_key)
    try: return "gemini-1.5-flash"
    except: return "gemini-1.5-flash"

def analyze_contract_with_gemini(file_bytes, file_type, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        image_data = None
        if "pdf" in file_type.lower():
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            target_page_index = 0
            if len(doc) > 1:
                text_p2 = doc[1].get_text()
                if "용역" in text_p2 or "금액" in text_p2 or "비용" in text_p2:
                    target_page_index = 1
            if len(doc) > 0:
                page = doc[target_page_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                image_data = Image.open(io.BytesIO(img_bytes))
            else: return {"error": "빈 PDF"}
        else:
            image_data = Image.open(io.BytesIO(file_bytes))

        prompt = """
        이미지에서 계약 정보를 JSON으로 추출하세요.
        1. contract_name (계약명)
        2. client_name (거래처/상대방)
        3. start_date / end_date (YYYY-MM-DD)
        4. total_amount (숫자만, 월 금액이면 월 금액 추출)
        5. is_auto_renew (true/false)
        6. special_notes (비고/특약사항 요약)
        
        { "contract_name": "", "client_name": "", "start_date": "", "end_date": "", "total_amount": 0, "is_auto_renew": false, "special_notes": "" }
        """
        response = model.generate_content([prompt, image_data])
        text_res = response.text.replace("```json", "").replace("```", "").strip()
        if "}" in text_res: text_res = text_res[:text_res.rfind("}")+1]
        return json.loads(text_res)
    except Exception as e:
        return {"error": str(e)}

# -----------------------------------------------------------------------------
# 데이터 처리 함수
# -----------------------------------------------------------------------------
def load_data():
    cols = ["ID", "계약명", "거래처", "유형", "상태", "시작일", "종료일", "금액", "담당자", "파일명", "자동갱신", "비고"]
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            for col in cols:
                if col not in df.columns: df[col] = False if col == "자동갱신" else ""
            df['시작일'] = pd.to_datetime(df['시작일'], errors='coerce').dt.date
            df['종료일'] = pd.to_datetime(df['종료일'], errors='coerce').dt.date
            df['자동갱신'] = df['자동갱신'].astype(bool)
            df['금액'] = pd.to_numeric(df['금액'], errors='coerce').fillna(0).astype(int)
            # ID는 문자열로 관리 (수정 시 매칭 오류 방지)
            df['ID'] = df['ID'].astype(str)
            return df
        except: return pd.DataFrame(columns=cols)
    else: return pd.DataFrame(columns=cols)

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def calculate_d_day(end_date):
    if pd.isna(end_date): return 999
    today = date.today()
    return (end_date - today).days

def get_status_badge(d_day, is_auto_renew):
    if d_day < 0:
        return "🔄 자동연장" if is_auto_renew else "🔴 만료됨"
    elif d_day <= 30:
        return f"🟠 1개월 임박 ({d_day}일)"
    elif d_day <= 60:
        return f"🟡 2개월 안내 ({d_day}일)"
    else:
        return f"🟢 진행중"

# =============================================================================
# 3. 메인 UI
# =============================================================================
st.title("📜 계약 및 수납 통합 관리")

saved_key = load_api_key()
with st.sidebar.expander("🔑 AI 설정", expanded=True):
    api_key_input = st.text_input("Google API Key", value=saved_key, type="password")
    if api_key_input != saved_key:
        save_api_key(api_key_input)
        st.success("저장됨!")
        time.sleep(1)
        st.rerun()

df = load_data()
tx_df = load_all_transactions()

tab1, tab2 = st.tabs(["📊 수납 현황 및 계약 수정", "➕ 신규 계약 등록"])

# -----------------------------------------------------------------------------
# TAB 1: 수납 현황 및 수정
# -----------------------------------------------------------------------------
with tab1:
    if df.empty:
        st.info("등록된 계약이 없습니다.")
    else:
        # 데이터 전처리
        df['남은기간'] = df['종료일'].apply(calculate_d_day)
        df['상태표시'] = df.apply(lambda x: get_status_badge(x['남은기간'], x['자동갱신']), axis=1)
        
        # KPI 계산
        notice_cnt = len(df[(df['남은기간'] > 30) & (df['남은기간'] <= 60)])
        imminent_cnt = len(df[(df['남은기간'] >= 0) & (df['남은기간'] <= 30)])
        
        # 매칭 로직
        received_map = {} 
        received_details = {} 
        
        for idx, row in df.iterrows():
            client_name = str(row['거래처']).replace("(주)", "").replace("주식회사", "").strip()
            if not client_name: continue
            
            if not tx_df.empty:
                matched = tx_df[tx_df['적요'].astype(str).str.contains(client_name, na=False)]
            else:
                matched = pd.DataFrame(columns=['날짜', '적요', '입금액'])

            total_in = matched['입금액'].sum() if not matched.empty else 0
            received_map[row['ID']] = total_in
            received_details[row['ID']] = matched
            
        df['누적수납액'] = df['ID'].map(received_map).fillna(0)
        total_contract = df['금액'].sum()
        total_received = df['누적수납액'].sum()
        
        # 상단 지표
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 계약 금액", f"{total_contract:,} 원")
        c2.metric("실제 입금 확인", f"{int(total_received):,} 원")
        c3.metric("🔔 2개월 안내", f"{notice_cnt} 건")
        c4.metric("⚠️ 1개월 임박", f"{imminent_cnt} 건", delta_color="inverse")
        
        st.markdown("---")
        
        # 필터
        sc1, sc2 = st.columns([1, 3])
        status_filter = sc1.selectbox(
            "상태 필터", 
            ["전체", "진행중", "2개월안내", "1개월임박", "자동연장", "만료됨"]
        )
        search_query = sc2.text_input("검색", placeholder="계약명, 거래처 검색")

        view_df = df.copy()
        
        if status_filter == "진행중": view_df = view_df[view_df['남은기간'] > 60]
        elif status_filter == "2개월안내": view_df = view_df[(view_df['남은기간'] > 30) & (view_df['남은기간'] <= 60)]
        elif status_filter == "1개월임박": view_df = view_df[(view_df['남은기간'] >= 0) & (view_df['남은기간'] <= 30)]
        elif status_filter == "만료됨": view_df = view_df[(view_df['남은기간'] < 0) & (view_df['자동갱신'] == False)]
        elif status_filter == "자동연장": view_df = view_df[(view_df['남은기간'] < 0) & (view_df['자동갱신'] == True)]
        
        if search_query:
            view_df = view_df[view_df['계약명'].str.contains(search_query, na=False) | view_df['거래처'].str.contains(search_query, na=False)]

        st.caption(f"총 {len(view_df)}건의 계약이 표시됩니다. (박스를 눌러 상세 내용을 보고 수정하세요)")
        
        for idx, row in view_df.sort_values('남은기간').iterrows():
            s_text = row['상태표시']
            s_color = ":green"
            if "만료됨" in s_text: s_color = ":red"
            elif "1개월" in s_text: s_color = ":orange"
            elif "2개월" in s_text: s_color = ":violet"
            elif "자동연장" in s_text: s_color = ":blue"
            
            with st.expander(f"{s_color}[{s_text}] {row['거래처']} - {row['계약명']}"):
                
                # [NEW] 수정 모드 스위치
                is_edit_mode = st.toggle("✏️ 정보 수정 모드 켜기", key=f"edit_toggle_{row['ID']}")
                
                col1, col2 = st.columns([1, 1])
                
                # --- 왼쪽: 계약 정보 (조회 모드 vs 수정 모드) ---
                with col1:
                    st.markdown("#### 📜 계약 정보")
                    
                    if is_edit_mode:
                        # [수정 모드] 입력창 표시
                        with st.container(border=True):
                            new_name = st.text_input("계약명", value=row['계약명'], key=f"e_name_{row['ID']}")
                            new_client = st.text_input("거래처", value=row['거래처'], key=f"e_client_{row['ID']}")
                            
                            cd1, cd2 = st.columns(2)
                            new_start = cd1.date_input("시작일", value=row['시작일'], key=f"e_start_{row['ID']}")
                            new_end = cd2.date_input("종료일", value=row['종료일'], key=f"e_end_{row['ID']}")
                            
                            new_amt = st.number_input("계약 금액", value=int(row['금액']), step=10000, key=f"e_amt_{row['ID']}")
                            new_mgr = st.text_input("담당자", value=row['담당자'], key=f"e_mgr_{row['ID']}")
                            new_note = st.text_area("비고(특이사항)", value=row['비고'], key=f"e_note_{row['ID']}")
                            new_auto = st.checkbox("자동 갱신 여부", value=bool(row['자동갱신']), key=f"e_auto_{row['ID']}")
                            
                            if st.button("💾 변경사항 저장", key=f"save_{row['ID']}", type="primary"):
                                # 원본 데이터프레임 업데이트
                                df.loc[df['ID'] == row['ID'], '계약명'] = new_name
                                df.loc[df['ID'] == row['ID'], '거래처'] = new_client
                                df.loc[df['ID'] == row['ID'], '시작일'] = new_start
                                df.loc[df['ID'] == row['ID'], '종료일'] = new_end
                                df.loc[df['ID'] == row['ID'], '금액'] = new_amt
                                df.loc[df['ID'] == row['ID'], '담당자'] = new_mgr
                                df.loc[df['ID'] == row['ID'], '비고'] = new_note
                                df.loc[df['ID'] == row['ID'], '자동갱신'] = new_auto
                                
                                save_data(df)
                                st.success("수정 완료!")
                                time.sleep(0.5)
                                st.rerun()
                    else:
                        # [조회 모드] 텍스트 표시
                        st.write(f"- **금액:** {row['금액']:,} 원")
                        st.write(f"- **기간:** {row['시작일']} ~ {row['종료일']}")
                        st.write(f"- **남은기간:** {row['남은기간']}일")
                        st.write(f"- **담당:** {row['담당자']}")
                        st.write(f"- **자동갱신:** {'✅ 예' if row['자동갱신'] else '❌ 아니오'}")
                        
                        if row['비고']:
                            st.info(f"💡 특이사항: {row['비고']}")
                        else:
                            st.caption("특이사항 없음")
                        
                        # 파일 & 삭제 버튼
                        file_path = os.path.join(FILES_DIR, str(row['파일명']))
                        if row['파일명'] and os.path.exists(file_path):
                            with open(file_path, "rb") as f:
                                st.download_button("📥 계약서 다운로드", f, file_name=row['파일명'], key=f"d_{idx}")
                        
                        if st.button("🗑️ 계약 삭제", key=f"del_{idx}"):
                            df = df[df['ID'] != row['ID']]
                            save_data(df)
                            st.rerun()

                # --- 오른쪽: 자금 내역 (항상 표시) ---
                with col2:
                    st.markdown("#### 💰 입금(수납) 내역")
                    match_data = received_details.get(row['ID'])
                    
                    if match_data is not None and not match_data.empty:
                        total_in = match_data['입금액'].sum()
                        st.metric("확인된 입금 총액", f"{int(total_in):,} 원")
                        
                        display_cols = [c for c in ['날짜', '적요', '입금액'] if c in match_data.columns]
                        st.dataframe(
                            match_data[display_cols], 
                            hide_index=True,
                            use_container_width=True
                        )
                    else:
                        st.warning("⚠️ 확인된 입금 내역 없음")
                        st.caption("입금 내역이 보이지 않는다면 자금관리 메뉴에 엑셀을 올렸는지 확인하세요.")


# -----------------------------------------------------------------------------
# TAB 2: 등록
# -----------------------------------------------------------------------------
with tab2:
    st.subheader("📝 신규 계약 등록")
    
    uploaded_file = st.file_uploader("계약서 파일 첨부", type=['png', 'jpg', 'jpeg', 'pdf'])
    
    if 'gemini_result' not in st.session_state:
        st.session_state['gemini_result'] = {}

    if uploaded_file and api_key_input:
        if st.button("🤖 AI로 내용 자동 추출하기", type="primary", use_container_width=True):
            with st.spinner("AI 분석 중..."):
                file_bytes = uploaded_file.getvalue()
                file_type = uploaded_file.name.split('.')[-1]
                result = analyze_contract_with_gemini(file_bytes, file_type, api_key_input)
                
                if "error" in result:
                    st.error(f"분석 실패: {result['error']}")
                else:
                    st.session_state['gemini_result'] = result
                    st.success("✅ 완료!")
                    time.sleep(0.5)
                    st.rerun()

    ai_data = st.session_state.get('gemini_result', {})
    
    with st.form("contract_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            input_client = st.text_input("거래처/브랜드", value=ai_data.get('client_name', ''))
            input_name = st.text_input("계약명", value=ai_data.get('contract_name', ''))
            
            type_options = ["용역계약", "매매계약", "임대차계약", "비밀유지", "기타"]
            ai_type = ai_data.get('contract_type', '용역계약')
            def_idx = type_options.index(ai_type) if ai_type in type_options else 0
            input_type = st.selectbox("계약 유형", type_options, index=def_idx)
            
            ai_auto = ai_data.get('is_auto_renew', False)
            input_auto_renew = st.checkbox("🔄 자동 갱신", value=bool(ai_auto))
            
        with col2:
            def parse_date(d):
                try: return datetime.strptime(str(d), "%Y-%m-%d").date()
                except: return date.today()
            input_start = st.date_input("시작일", value=parse_date(ai_data.get('start_date')))
            input_end = st.date_input("종료일", value=parse_date(ai_data.get('end_date')))
            input_manager = st.text_input("담당자")
            
            raw_amt = ai_data.get('total_amount', 0)
            try: clean_amt = re.sub(r'[^0-9]', '', str(raw_amt)); val_amt = int(clean_amt) if clean_amt else 0
            except: val_amt = 0
            input_amount = st.number_input("계약 금액", min_value=0, step=10000, value=val_amt)

        st.write("**특이사항 (AI 요약)**")
        input_note = st.text_area("비고", value=ai_data.get('special_notes', ''), height=80)
            
        st.markdown("---")
        if st.form_submit_button("✅ 계약 저장", use_container_width=True, type="primary"):
            if not input_name or not input_client:
                st.error("필수 입력 누락")
            else:
                saved_filename = ""
                if uploaded_file:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = re.sub(r'[^\w\.-]', '_', uploaded_file.name)
                    saved_filename = f"{ts}_{safe_name}"
                    with open(os.path.join(FILES_DIR, saved_filename), "wb") as f:
                        f.write(uploaded_file.getbuffer())
                
                new_data = {
                    "ID": datetime.now().strftime("%Y%m%d%H%M%S"),
                    "계약명": input_name, "거래처": input_client, "유형": input_type,
                    "상태": "Active", "시작일": input_start, "종료일": input_end,
                    "금액": input_amount, "담당자": input_manager, "파일명": saved_filename,
                    "자동갱신": input_auto_renew, "비고": input_note
                }
                new_df = pd.DataFrame([new_data])
                df = pd.concat([df, new_df], ignore_index=True)
                save_data(df)
                st.session_state['gemini_result'] = {} 
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()