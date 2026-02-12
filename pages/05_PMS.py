import streamlit as st
import pandas as pd
import os
import sys
import time
from datetime import datetime, date

# -----------------------------------------------------------------------------
# 경로 설정 (중요: 계약 데이터도 불러와야 함)
# -----------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

st.set_page_config(page_title="프로젝트 관리 | PMS", layout="wide")

BASE_DIR = parent_dir
CONTRACT_ROOT = os.path.join(BASE_DIR, "workspaces", "contracts")
DATA_FILE = os.path.join(CONTRACT_ROOT, "contract_list.csv")
PROJECT_FILE = os.path.join(CONTRACT_ROOT, "project_list.csv")

# -----------------------------------------------------------------------------
# 데이터 로드/저장
# -----------------------------------------------------------------------------
def load_contracts():
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            df['ID'] = df['ID'].astype(str)
            return df
        except: return pd.DataFrame()
    return pd.DataFrame()

def load_projects():
    cols = ["P_ID", "프로젝트명", "관련계약ID", "진행상태", "진행률", "담당자", "메모", "마감일"]
    if os.path.exists(PROJECT_FILE):
        try:
            df = pd.read_csv(PROJECT_FILE)
            for col in cols:
                if col not in df.columns: df[col] = 0 if col == "진행률" else ""
            df['마감일'] = pd.to_datetime(df['마감일'], errors='coerce').dt.date
            df['관련계약ID'] = df['관련계약ID'].astype(str) # 비교를 위해 문자열 변환
            return df
        except: return pd.DataFrame(columns=cols)
    else: return pd.DataFrame(columns=cols)

def save_projects(df):
    df.to_csv(PROJECT_FILE, index=False)

# =============================================================================
# 메인 UI
# =============================================================================
st.title("🚀 프로젝트 진행 관리 (PMS)")

# 데이터 로드
contract_df = load_contracts()
proj_df = load_projects()

# 1. 신규 프로젝트 등록 (상단)
with st.expander("➕ 새 프로젝트 만들기", expanded=False):
    with st.form("new_project_form"):
        c1, c2 = st.columns(2)
        p_name = c1.text_input("프로젝트명 (예: 홈페이지 구축)")
        
        # 계약 목록 연동 (거래처 - 계약명)
        contract_map = {}
        if not contract_df.empty:
            for _, row in contract_df.iterrows():
                label = f"{row['거래처']} - {row['계약명']}"
                contract_map[label] = str(row['ID'])
        
        selected_contract = c2.selectbox("관련 계약 연결", ["(연결 안 함)"] + list(contract_map.keys()))
        
        c3, c4 = st.columns(2)
        p_manager = c3.text_input("담당자")
        p_deadline = c4.date_input("목표 마감일")
        p_memo = st.text_area("업무 메모")
        
        if st.form_submit_button("프로젝트 생성", type="primary"):
            if not p_name:
                st.error("프로젝트명은 필수입니다.")
            else:
                rel_id = contract_map.get(selected_contract, "")
                new_p = {
                    "P_ID": datetime.now().strftime("%Y%m%d%H%M%S"),
                    "프로젝트명": p_name,
                    "관련계약ID": rel_id,
                    "진행상태": "대기",
                    "진행률": 0,
                    "담당자": p_manager,
                    "메모": p_memo,
                    "마감일": p_deadline
                }
                proj_df = pd.concat([proj_df, pd.DataFrame([new_p])], ignore_index=True)
                save_projects(proj_df)
                st.success("프로젝트가 생성되었습니다!")
                time.sleep(0.5)
                st.rerun()

st.markdown("---")

# 2. 칸반 보드 (대기 / 진행중 / 완료)
col_todo, col_doing, col_done = st.columns(3, gap="medium")

# 필터링
todos = proj_df[proj_df['진행상태'] == "대기"]
doings = proj_df[proj_df['진행상태'] == "진행중"]
dones = proj_df[proj_df['진행상태'] == "완료"]

def render_card(row, col_type):
    # 카드 스타일링
    with st.container(border=True):
        # 헤더
        st.markdown(f"#### {row['프로젝트명']}")
        
        # 관련 계약 정보 (있으면 표시)
        if str(row['관련계약ID']) and not contract_df.empty:
            rel = contract_df[contract_df['ID'] == str(row['관련계약ID'])]
            if not rel.empty:
                client = rel.iloc[0]['거래처']
                st.caption(f"🏢 **{client}** 관련")
        
        # 진행률 & 마감일
        st.progress(int(row['진행률']))
        
        info_col1, info_col2 = st.columns(2)
        info_col1.caption(f"📅 ~{row['마감일']}")
        info_col2.caption(f"👤 {row['담당자']}")
        
        # 이동 버튼
        b1, b2, b3 = st.columns([1, 1, 1])
        
        # [이전 단계]
        if col_type != "todo":
            if b1.button("⬅️", key=f"prev_{row['P_ID']}"):
                new_status = "대기" if col_type == "doing" else "진행중"
                proj_df.loc[proj_df['P_ID'] == row['P_ID'], '진행상태'] = new_status
                save_projects(proj_df)
                st.rerun()
        
        # [삭제]
        if b2.button("🗑️", key=f"del_{row['P_ID']}"):
            proj_df.drop(proj_df[proj_df['P_ID'] == row['P_ID']].index, inplace=True)
            save_projects(proj_df)
            st.rerun()
            
        # [다음 단계]
        if col_type != "done":
            if b3.button("➡️", key=f"next_{row['P_ID']}"):
                new_status = "진행중" if col_type == "todo" else "완료"
                if new_status == "완료": proj_df.loc[proj_df['P_ID'] == row['P_ID'], '진행률'] = 100
                elif new_status == "진행중" and row['진행률'] == 0: proj_df.loc[proj_df['P_ID'] == row['P_ID'], '진행률'] = 50
                proj_df.loc[proj_df['P_ID'] == row['P_ID'], '진행상태'] = new_status
                save_projects(proj_df)
                st.rerun()

        # [상세 수정]
        with st.popover("📝 상세 / 수정"):
            u_prog = st.slider("진행률", 0, 100, int(row['진행률']), key=f"sl_{row['P_ID']}")
            u_memo = st.text_area("메모", row['메모'], key=f"ta_{row['P_ID']}")
            if st.button("적용", key=f"up_{row['P_ID']}"):
                proj_df.loc[proj_df['P_ID'] == row['P_ID'], '진행률'] = u_prog
                proj_df.loc[proj_df['P_ID'] == row['P_ID'], '메모'] = u_memo
                save_projects(proj_df)
                st.rerun()

# 화면 그리기
with col_todo:
    st.header("📌 대기")
    st.caption(f"{len(todos)}건")
    for _, row in todos.iterrows(): render_card(row, "todo")

with col_doing:
    st.header("🏃 진행중")
    st.caption(f"{len(doings)}건")
    for _, row in doings.iterrows(): render_card(row, "doing")

with col_done:
    st.header("✅ 완료")
    st.caption(f"{len(dones)}건")
    for _, row in dones.iterrows(): render_card(row, "done")