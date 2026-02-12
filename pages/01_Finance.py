import streamlit as st
import pandas as pd
import os
import sys
import time
import json
import glob
import re
import altair as alt
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. 파일 엔진 로드
# -----------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

try:
    import file_engine
    default_ignores = getattr(file_engine, 'DEFAULT_IGNORE_KEYWORDS', [])
except ImportError:
    st.error("🚨 프로젝트 폴더에 'file_engine.py' 파일이 없습니다.")
    st.stop()

st.set_page_config(page_title="자금 관리", layout="wide")

# 경로 설정
BASE_DIR = parent_dir
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")
CLOSED_DIR = os.path.join(BASE_DIR, "closed_reports")
RULES_FILE = os.path.join(WORKSPACES_DIR, "classification_rules.json")

if not os.path.exists(WORKSPACES_DIR): os.makedirs(WORKSPACES_DIR)
if not os.path.exists(CLOSED_DIR): os.makedirs(CLOSED_DIR)

MANUAL_FILE = os.path.join(WORKSPACES_DIR, "manual_entries.json")

# -----------------------------------------------------------------------------
# 2. 규칙 관리
# -----------------------------------------------------------------------------
def load_rules():
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in ["매출", "판관비", "기타비용", "투자"]:
                    if k not in data: data[k] = {}
                if "중복방지" not in data: data["중복방지"] = []
                return data
        except: pass
    return {"매출": {}, "판관비": {}, "기타비용": {}, "투자": {}, "중복방지": []}

def save_rules(rules):
    with open(RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=4)

# -----------------------------------------------------------------------------
# 3. 데이터 로드 (Live Data)
# -----------------------------------------------------------------------------
rules = load_rules()
live_df, load_log = file_engine.load_and_classify_data(WORKSPACES_DIR, rules)

# 3-1. 수기 입력 데이터 로드 및 병합
def load_manual_entries():
    if os.path.exists(MANUAL_FILE):
        try:
            with open(MANUAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return []

def save_manual_entries(entries):
    with open(MANUAL_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

manual_entries = load_manual_entries()

if manual_entries:
    manual_rows = []
    for e in manual_entries:
        manual_rows.append({
            '날짜': e['날짜'],
            '적요': e['적요'],
            '입금': e.get('입금', 0),
            '출금': e.get('출금', 0),
            '대분류': e['대분류'],
            '소분류': e['소분류'],
            '파일명': '✍️ 수기입력',
            '__row_idx': 0,
        })
    manual_df = pd.DataFrame(manual_rows)
    if live_df.empty:
        live_df = manual_df
    else:
        live_df = pd.concat([live_df, manual_df], ignore_index=True)

# -----------------------------------------------------------------------------
# 4. 사이드바
# -----------------------------------------------------------------------------
st.sidebar.title("📅 기간 설정")

selected_year = datetime.now().year
selected_month = datetime.now().month

if 'finance_selected_year' not in st.session_state:
    st.session_state['finance_selected_year'] = selected_year
if 'finance_selected_month' not in st.session_state:
    st.session_state['finance_selected_month'] = selected_month

def check_is_closed(year, month):
    path = os.path.join(CLOSED_DIR, f"{year}년_{month}월_결산보고서.xlsx")
    return os.path.exists(path), path

@st.cache_data(ttl=60) 
def load_closed_data(filepath):
    try: return pd.read_excel(filepath, sheet_name="전체내역")
    except: return pd.DataFrame()

live_view_df = pd.DataFrame()
if not live_df.empty:
    live_df['날짜'] = pd.to_datetime(live_df['날짜'], errors='coerce')
    valid_live_df = live_df[live_df['날짜'].notna()]
    
    if not valid_live_df.empty:
        data_years = set(valid_live_df['날짜'].dt.year.unique())
        base_years = sorted(list(data_years | {datetime.now().year, 2024, 2025}), reverse=True)
        
        st.sidebar.markdown("##### 연도 (Year)")
        cols_y = st.sidebar.columns(3)
        for i, y in enumerate(base_years):
            is_sel = (st.session_state['finance_selected_year'] == y)
            label = f"✔ {y}" if y in data_years else f"{y}"
            if cols_y[i%3].button(label, key=f"y_{y}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state['finance_selected_year'] = y
                st.rerun()
        
        selected_year = st.session_state['finance_selected_year']
        st.sidebar.markdown(f"##### {selected_year}년 월 (Month)")
        
        cols_m = st.sidebar.columns(3)
        for m in range(1, 13):
            is_sel = (st.session_state['finance_selected_month'] == m)
            is_closed, _ = check_is_closed(selected_year, m)
            icon = "🔒" if is_closed else "✔"
            has_data = not valid_live_df[(valid_live_df['날짜'].dt.year == selected_year) & (valid_live_df['날짜'].dt.month == m)].empty
            label = f"{icon} {m}월" if (has_data or is_closed) else f"{m}월"
            if cols_m[(m-1)%3].button(label, key=f"m_{m}", type="primary" if is_sel else "secondary", use_container_width=True):
                st.session_state['finance_selected_month'] = m
                st.rerun()

        selected_month = st.session_state['finance_selected_month']
        
        start = pd.Timestamp(f"{selected_year}-{selected_month:02d}-01")
        end = start + pd.DateOffset(months=1)
        live_view_df = valid_live_df[(valid_live_df['날짜'] >= start) & (valid_live_df['날짜'] < end)].copy()

is_closed, closed_file_path = check_is_closed(selected_year, selected_month)
final_df = pd.DataFrame()
mode = "LIVE" 

if is_closed:
    final_df = load_closed_data(closed_file_path)
    mode = "CLOSED"
    st.sidebar.success(f"🔒 {selected_year}년 {selected_month}월은 **마감된 달**입니다.")
else:
    final_df = live_view_df.copy()
    mode = "LIVE"

# [수정 #1] 데이터 초기화 — JSON 설정 파일 보호
st.sidebar.markdown("---")
if st.sidebar.button("🗑️ 데이터 초기화", use_container_width=True):
    PROTECT_EXTENSIONS = {'.json'}
    for root, dirs, files in os.walk(WORKSPACES_DIR):
        for fname in files:
            fpath = os.path.join(root, fname)
            if os.path.splitext(fname)[1].lower() not in PROTECT_EXTENSIONS:
                try: os.remove(fpath) 
                except: pass
        # 빈 하위 폴더 정리
        for d in dirs:
            dpath = os.path.join(root, d)
            try:
                if not os.listdir(dpath):
                    os.rmdir(dpath)
            except: pass
    # 빈 연도 폴더 정리
    for d in os.listdir(WORKSPACES_DIR):
        dpath = os.path.join(WORKSPACES_DIR, d)
        if os.path.isdir(dpath):
            try:
                if not os.listdir(dpath):
                    os.rmdir(dpath)
            except: pass
    st.toast("엑셀/CSV 파일이 초기화되었습니다! (분류 규칙은 유지)", icon="🧹")
    time.sleep(1)
    st.rerun()

# -----------------------------------------------------------------------------
# 마감 보고서 저장 헬퍼 함수
# [수정 #6] 투자상세 + 요약 시트 포함
# -----------------------------------------------------------------------------
def _save_closing_report(filepath, data_df, total_rev, total_opex, total_etc, total_invest, net_profit):
    """마감 보고서를 엑셀로 저장 (요약 + 전체내역 + 매출상세 + 지출상세 + 투자상세)"""
    with pd.ExcelWriter(filepath) as writer:
        # 요약 시트
        summary = pd.DataFrame({
            "항목": ["총 매출", "판관비", "기타비용", "순수익", "투자/저축"],
            "금액": [int(total_rev), int(total_opex), int(total_etc), int(net_profit), int(total_invest)]
        })
        summary.to_excel(writer, sheet_name="요약", index=False)
        
        # 전체내역
        data_df.to_excel(writer, sheet_name="전체내역", index=False)
        
        # 매출상세
        rev = data_df[data_df['대분류'] == '매출']
        if not rev.empty:
            rev.to_excel(writer, sheet_name="매출상세", index=False)
        
        # 판관비상세
        opex = data_df[data_df['대분류'] == '판관비']
        if not opex.empty:
            opex.to_excel(writer, sheet_name="판관비상세", index=False)
        
        # 기타비용상세
        etc = data_df[data_df['대분류'] == '기타비용']
        if not etc.empty:
            etc.to_excel(writer, sheet_name="기타비용상세", index=False)
        
        # 투자상세
        invest = data_df[data_df['대분류'] == '투자']
        if not invest.empty:
            invest.to_excel(writer, sheet_name="투자상세", index=False)

# -----------------------------------------------------------------------------
# 메인 탭
# -----------------------------------------------------------------------------
st.title("💰 자금 관리 시스템")
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 1. 월간 결산", "⚙️ 2. 규칙 설정", "📂 3. 파일 업로드", "🔍 4. 데이터 검증", "✍️ 5. 수기 입력"])

# ==================== TAB 1: 월간 결산 ====================
with tab1:
    if final_df.empty:
        st.warning(f"📉 {selected_year}년 {selected_month}월 데이터가 없습니다.")
    else:
        if mode == "CLOSED":
            live_cnt = len(live_view_df)
            close_cnt = len(final_df)
            live_sum = int(live_view_df['입금'].sum() + live_view_df['출금'].sum()) if not live_view_df.empty else 0
            close_sum = int(final_df['입금'].sum() + final_df['출금'].sum())
            
            if (live_cnt != close_cnt) or (live_sum != close_sum):
                st.warning(f"🚨 **주의: 마감 이후 새로운 데이터가 감지되었습니다!** (기존: {close_cnt}건 vs 현재: {live_cnt}건)")
                
                with st.expander("🔍 변경 사항 확인 및 업데이트 (클릭)", expanded=True):
                    c_diff1, c_diff2 = st.columns(2)
                    c_diff1.info(f"📂 **저장된 마감 데이터**\n\n건수: {close_cnt}건\n총액: {close_sum:,}원")
                    c_diff2.error(f"⚡ **현재 업로드된 데이터**\n\n건수: {live_cnt}건\n총액: {live_sum:,}원")
                    
                    st.markdown("---")
                    b1, b2 = st.columns(2)
                    
                    # [수정 #2] 빈 데이터로 마감 덮어쓰기 방지
                    if b1.button("✅ 마감 업데이트 (현재 데이터로 덮어쓰기)", type="primary", use_container_width=True):
                        if live_view_df.empty:
                            st.error("⛔ 현재 업로드된 데이터가 없습니다. 빈 데이터로 덮어쓸 수 없습니다. 파일을 먼저 업로드해주세요.")
                        else:
                            _rev = live_view_df[live_view_df['대분류'] == '매출']['입금'].sum()
                            _opex = live_view_df[live_view_df['대분류'] == '판관비']['출금'].sum()
                            _etc = live_view_df[live_view_df['대분류'] == '기타비용']['출금'].sum()
                            _invest = live_view_df[live_view_df['대분류'] == '투자']['출금'].sum()
                            _net = _rev - _opex - _etc
                            _save_closing_report(closed_file_path, live_view_df, _rev, _opex, _etc, _invest, _net)
                            st.toast("마감 데이터가 최신으로 업데이트되었습니다!", icon="💾")
                            time.sleep(1.5)
                            st.rerun()
                        
                    if b2.button("❌ 변경 무시 (기존 마감 유지)", use_container_width=True):
                        st.toast("현재 화면은 기존 마감 데이터를 유지합니다.", icon="🛡️")

        st.subheader(f"📈 {selected_year}년 {selected_month}월 손익 결산")
        
        # '투자'는 손익 계산에서 제외
        total_rev = final_df[final_df['대분류'] == '매출']['입금'].sum()
        total_opex = final_df[final_df['대분류'] == '판관비']['출금'].sum()
        total_etc = final_df[final_df['대분류'] == '기타비용']['출금'].sum()
        
        # 투자금 집계
        total_invest = final_df[final_df['대분류'] == '투자']['출금'].sum()
        
        net_profit = total_rev - total_opex - total_etc
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("1. 총 매출", f"{int(total_rev):,} 원", delta="입금")
        c2.metric("2. 판관비", f"{int(total_opex):,} 원", delta="-출금", delta_color="inverse")
        c3.metric("3. 기타비용", f"{int(total_etc):,} 원", delta="-출금", delta_color="inverse")
        c4.metric("💰 순수익 (투자제외)", f"{int(net_profit):,} 원", delta=f"{int(net_profit):,} 원")
        
        # 투자 현황
        if total_invest > 0:
            invest_data = final_df[final_df['대분류'] == '투자']
            with st.expander(f"💎 **이번 달 저축/투자 금액: {int(total_invest):,} 원** (클릭하여 상세 보기)", expanded=False):
                st.caption("ℹ️ 투자는 비용이 아닌 '자산'으로 분류되어 순수익 계산에 영향을 주지 않습니다.")
                st.dataframe(
                    invest_data[['날짜', '적요', '출금', '소분류']].sort_values('날짜')
                    .style.format({"출금": "{:,.0f}"}), 
                    use_container_width=True,
                    hide_index=True
                )

        st.divider()
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.markdown("### 🟦 매출 상세")
            rev_data = final_df[final_df['대분류'] == '매출']
            if not rev_data.empty:
                grouped_rev = rev_data.groupby('소분류')['입금'].sum().sort_values(ascending=False)
                chart_data = grouped_rev[grouped_rev > 0].reset_index()
                chart_data.columns = ['브랜드', '매출']
                chart_data = chart_data.dropna(subset=['매출'])
                if not chart_data.empty and chart_data['매출'].sum() > 0:
                    c = alt.Chart(chart_data).mark_bar(color="#3498db").encode(
                        x=alt.X('브랜드', sort='-y', axis=alt.Axis(labelAngle=0)), 
                        y='매출', tooltip=['브랜드', alt.Tooltip('매출', format=',')]
                    ).properties(height=200)
                    st.altair_chart(c, use_container_width=True)
                
                for cat, val in grouped_rev.items():
                    with st.expander(f"🔹 {cat} : {int(val):,} 원"):
                        cat_data = rev_data[rev_data['소분류']==cat]
                        st.dataframe(cat_data.style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}, na_rep=""), hide_index=True)
            else: st.caption("내역 없음")

        with col_right:
            st.markdown("### 🟥 지출 상세")
            
            # 판관비
            st.markdown("#### 📊 판관비")
            opex_data = final_df[final_df['대분류'] == '판관비']
            if not opex_data.empty:
                grouped_opex = opex_data.groupby('소분류')['출금'].sum().sort_values(ascending=False)
                for cat, val in grouped_opex.items():
                    with st.expander(f"🔴 {cat} : {int(val):,} 원"):
                        cat_data = opex_data[opex_data['소분류']==cat]
                        st.dataframe(cat_data.style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}, na_rep=""), hide_index=True)
            else:
                st.caption("내역 없음")
            
            # 기타비용
            st.markdown("#### 💸 기타비용")
            etc_data = final_df[final_df['대분류'] == '기타비용']
            if not etc_data.empty:
                grouped_etc = etc_data.groupby('소분류')['출금'].sum().sort_values(ascending=False)
                for cat, val in grouped_etc.items():
                    with st.expander(f"🔴 {cat} : {int(val):,} 원"):
                        cat_data = etc_data[etc_data['소분류']==cat]
                        st.dataframe(cat_data.style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}, na_rep=""), hide_index=True)
            else:
                st.caption("내역 없음")

        # [수정 #8] 기타 입출금 (손익에 미포함) — 보이지 않던 카테고리 가시화
        other_categories = ['입금(매출제외)', '출금(비용제외)', '투자회수']
        other_data = final_df[final_df['대분류'].isin(other_categories)]
        if not other_data.empty:
            st.divider()
            with st.expander(f"ℹ️ 기타 입출금 ({len(other_data)}건) — 손익에 미포함", expanded=False):
                st.caption("세금계산서 발행처 입출금 등 손익 계산에서 제외된 내역입니다.")
                st.dataframe(
                    other_data[['날짜', '대분류', '소분류', '적요', '입금', '출금', '파일명']].sort_values('날짜')
                    .style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}),
                    hide_index=True, use_container_width=True
                )

        if mode == "LIVE":
            unclassified = final_df[final_df['대분류'] == '미분류']
            if not unclassified.empty:
                st.divider()
                st.error(f"⚠️ **미분류 {len(unclassified)}건**")
                
                # 1. 일괄 처리 도구
                with st.container(border=True):
                    st.markdown("#### ⚡ 미분류 일괄 처리")
                    unique_desc = sorted(unclassified['적요'].astype(str).unique())
                    target_descs = st.multiselect("키워드 선택", unique_desc)
                    c1, c2, c3 = st.columns([1, 1, 1])
                    cat = c1.selectbox("대분류", ["판관비", "매출", "기타비용", "투자"])
                    sub = c2.text_input("소분류 입력")
                    if c3.button("적용", type="primary", use_container_width=True):
                        if target_descs and sub:
                            for d in target_descs:
                                rules[cat][d] = sub
                            save_rules(rules)
                            st.rerun()
                
                # 2. 미분류 내역 테이블
                st.markdown("##### 📋 미분류 내역 상세")
                st.dataframe(unclassified[['날짜', '적요', '입금', '출금', '파일명']].sort_values('날짜').style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}), hide_index=True, use_container_width=True)

        st.divider()
        if mode == "LIVE":
            if st.button("💾 이 달의 결산 마감하기 (확정)", type="primary", use_container_width=True):
                if final_df[final_df['대분류'] == '미분류'].empty:
                    save_path = os.path.join(CLOSED_DIR, f"{selected_year}년_{selected_month}월_결산보고서.xlsx")
                    # [수정 #6] 투자상세 + 요약 시트 포함
                    _save_closing_report(save_path, final_df, total_rev, total_opex, total_etc, total_invest, net_profit)
                    st.success("✅ 마감 완료!")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("미분류 항목이 있어 마감 불가")
        else:
            st.info(f"🔒 {selected_year}년 {selected_month}월은 이미 마감되었습니다.")

# ==================== TAB 2: 규칙 설정 ====================
with tab2:
    st.subheader("분류 규칙 및 중복 방지 설정")
    rt1, rt2, rt3, rt4, rt5 = st.tabs(["🔵 매출(브랜드)", "🔴 판관비", "🟣 기타비용", "🟢 투자/저축", "🚫 중복 방지"])

    # [수정 #9] 체크박스 무한 save 제거 — 변경 감지 후 저장
    def rule_ui(category):
        if category == "매출": label = "브랜드명"
        elif category == "투자": label = "투자항목(예: S&P500)"
        else: label = "계정과목"
        
        st.markdown(f"**{category}** 규칙 관리")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            k = c1.text_input("키워드", key=f"k_{category}")
            v = c2.text_input(label, key=f"v_{category}")
            
            is_dup = False
            if category == "매출": st.caption("자동 중복 제외됨")
            else: is_dup = st.checkbox("은행 내역 중복 제외", key=f"chk_{category}")

            if c3.button("추가", key=f"add_{category}", use_container_width=True):
                if k and v:
                    rules[category][k] = v
                    if is_dup and k not in rules["중복방지"]: rules["중복방지"].append(k)
                    save_rules(rules)
                    st.rerun()
        
        if rules.get(category):
            rules_changed = False
            for rk, rv in list(rules[category].items()):
                rc1, rc2, rc3 = st.columns([3, 1, 1])
                rc1.text(f"{rk} ➡ {rv}")
                if category != "매출":
                    is_chk = rk in rules["중복방지"]
                    new_chk = rc2.checkbox("제외", value=is_chk, key=f"dup_{category}_{rk}")
                    if new_chk != is_chk:
                        if new_chk:
                            rules["중복방지"].append(rk)
                        else:
                            rules["중복방지"].remove(rk)
                        rules_changed = True
                if rc3.button("삭제", key=f"del_{category}_{rk}"):
                    del rules[category][rk]
                    if rk in rules["중복방지"]:
                        rules["중복방지"].remove(rk)
                    save_rules(rules)
                    st.rerun()
            
            if rules_changed:
                save_rules(rules)
                st.rerun()

    def ignore_ui():
        st.markdown("**중복 방지 목록**")
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            new_ig = c1.text_input("거래처명 입력", key="new_ignore")
            if c2.button("등록", key="btn_ignore", use_container_width=True):
                if new_ig and new_ig not in rules["중복방지"]:
                    rules["중복방지"].append(new_ig)
                    save_rules(rules)
                    st.rerun()
        if rules["중복방지"]:
            for i, ig in enumerate(rules["중복방지"]):
                ic1, ic2 = st.columns([4, 1])
                ic1.text(ig)
                if ic2.button("삭제", key=f"del_ig_{i}"):
                    rules["중복방지"].remove(ig)
                    save_rules(rules)
                    st.rerun()

    with rt1: rule_ui("매출")
    with rt2: rule_ui("판관비")
    with rt3: rule_ui("기타비용")
    with rt4: rule_ui("투자")
    with rt5: ignore_ui()

# ==================== TAB 3, 4 (기존 유지) ====================
with tab3:
    st.subheader("엑셀 파일 업로드")
    c1, c2 = st.columns(2)
    with c1:
        u_year = st.selectbox("연도", range(2024, 2030), index=1)
    with c2:
        u_month = st.selectbox("월", range(1, 13), index=datetime.now().month-1)
    
    uploaded_files = st.file_uploader(f"{u_year}년 {u_month}월 파일 업로드", accept_multiple_files=True)
    if uploaded_files:
        # 연/월 하위 폴더 생성
        month_dir = os.path.join(WORKSPACES_DIR, f"{u_year}년", f"{u_month}월")
        os.makedirs(month_dir, exist_ok=True)
        
        failed = []
        for f in uploaded_files:
            # 파일명에 날짜가 없으면 선택한 연/월을 앞에 붙여서 저장
            original_name = f.name
            date_prefix = f"{u_year}-{u_month:02d}"
            if not re.search(r'\d{4}[-년.]?\d{1,2}', original_name):
                save_name = f"{date_prefix}_{original_name}"
            else:
                save_name = original_name
            
            dest = os.path.join(month_dir, save_name)
            try:
                if os.path.exists(dest):
                    try:
                        os.remove(dest)
                    except PermissionError:
                        base, ext = os.path.splitext(save_name)
                        dest = os.path.join(month_dir, f"{base}_{int(time.time())}{ext}")
                with open(dest, "wb") as w:
                    w.write(f.getbuffer())
            except PermissionError:
                failed.append(original_name)
        
        if failed:
            st.error(f"⚠️ 파일이 잠겨있어 저장 실패: {', '.join(failed)}\n\n"
                     f"해당 파일을 엑셀에서 닫거나, OneDrive 동기화 완료 후 다시 시도해주세요.")
        else:
            st.success(f"업로드 완료! → {u_year}년/{u_month}월/")
            time.sleep(1)
            st.rerun()

    # --- 기존 루트 파일 자동 정리 안내 ---
    PROTECT_EXT = {'.json'}
    root_files = [f for f in os.listdir(WORKSPACES_DIR) 
                  if os.path.isfile(os.path.join(WORKSPACES_DIR, f)) 
                  and os.path.splitext(f)[1].lower() not in PROTECT_EXT]
    if root_files:
        st.warning(f"⚠️ 정리되지 않은 파일 {len(root_files)}개가 루트에 있습니다.")
        if st.button("📂 기존 파일 자동 정리 (연/월 폴더로 이동)", use_container_width=True):
            moved = 0
            for fname in root_files:
                src = os.path.join(WORKSPACES_DIR, fname)
                # 파일명에서 날짜 추출
                m = re.search(r'(\d{4})[-년.]?\s*(\d{1,2})', fname)
                if m:
                    yr, mo = int(m.group(1)), int(m.group(2))
                else:
                    # 파일 수정일 기준
                    mt = datetime.fromtimestamp(os.path.getmtime(src))
                    yr, mo = mt.year, mt.month
                target_dir = os.path.join(WORKSPACES_DIR, f"{yr}년", f"{mo}월")
                os.makedirs(target_dir, exist_ok=True)
                try:
                    import shutil
                    shutil.move(src, os.path.join(target_dir, fname))
                    moved += 1
                except: pass
            st.success(f"✅ {moved}개 파일 정리 완료!")
            time.sleep(1)
            st.rerun()

    # --- 폴더 구조 표시 ---
    st.markdown("---")
    st.markdown("**📁 저장된 파일 목록**")
    has_files = False
    for year_dir in sorted(glob.glob(os.path.join(WORKSPACES_DIR, "*년"))):
        year_name = os.path.basename(year_dir)
        for month_dir in sorted(glob.glob(os.path.join(year_dir, "*월"))):
            month_name = os.path.basename(month_dir)
            files_in = [f for f in os.listdir(month_dir) 
                        if os.path.isfile(os.path.join(month_dir, f))]
            if files_in:
                has_files = True
                with st.expander(f"📂 {year_name} / {month_name} ({len(files_in)}개)", expanded=False):
                    for fname in sorted(files_in):
                        fc1, fc2 = st.columns([5, 1])
                        fc1.text(f"  📄 {fname}")
                        if fc2.button("🗑️", key=f"fdel_{year_name}_{month_name}_{fname}"):
                            try:
                                os.remove(os.path.join(month_dir, fname))
                                st.toast(f"삭제: {fname}")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"삭제 실패: {e}")
    if not has_files:
        st.info("업로드된 파일이 없습니다.")

with tab4:
    st.subheader("데이터 검증")
    if not live_df.empty:
        f_list = live_df['파일명'].unique()
        sel_f = st.selectbox("파일 선택", f_list)
        f_data = live_df[live_df['파일명'] == sel_f].copy()
        
        filter_m = st.checkbox(f"{selected_year}년 {selected_month}월만 보기", value=True)
        if filter_m:
            s = pd.Timestamp(f"{selected_year}-{selected_month:02d}-01")
            e = s + pd.DateOffset(months=1)
            f_data = f_data[(f_data['날짜']>=s) & (f_data['날짜']<e)]
            
        if '__row_idx' in f_data.columns:
            f_data['엑셀 행 번호'] = f_data['__row_idx'] + 1
        else:
            f_data['엑셀 행 번호'] = 0

        st.dataframe(f_data.sort_values('날짜').style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}, na_rep=""), use_container_width=True, hide_index=True)
    else:
        st.info("데이터 없음")

# ==================== TAB 5: 수기 입력 ====================
with tab5:
    st.subheader("✍️ 수기 입력")
    st.caption("파일로 올릴 수 없는 거래를 직접 입력합니다. 저장 즉시 정산에 반영됩니다.")

    # --- 입력 폼 ---
    with st.container(border=True):
        st.markdown("#### 새 항목 추가")
        r1c1, r1c2, r1c3 = st.columns([1, 1, 1])
        m_date = r1c1.date_input("날짜", value=datetime(selected_year, selected_month, 1))
        m_cat = r1c2.selectbox("대분류", ["매출", "판관비", "기타비용", "투자"])
        m_sub = r1c3.text_input("소분류", placeholder="예: 현금매출, 교통비, S&P500")

        r2c1, r2c2, r2c3 = st.columns([2, 1, 1])
        m_desc = r2c1.text_input("적요 (내용)", placeholder="예: 카드단말기 현금결제분")
        m_type = r2c2.radio("입/출금", ["입금", "출금"], horizontal=True)
        m_amount = r2c3.number_input("금액", min_value=0, step=1000, format="%d")

        m_memo = st.text_input("메모 (선택)", placeholder="비고나 참고사항")

        if st.button("💾 저장", type="primary", use_container_width=True):
            if not m_sub:
                st.warning("소분류를 입력해주세요.")
            elif m_amount <= 0:
                st.warning("금액을 입력해주세요.")
            else:
                new_entry = {
                    "id": f"manual_{int(time.time()*1000)}",
                    "날짜": m_date.strftime("%Y-%m-%d"),
                    "적요": m_desc if m_desc else m_sub,
                    "대분류": m_cat,
                    "소분류": m_sub,
                    "입금": m_amount if m_type == "입금" else 0,
                    "출금": m_amount if m_type == "출금" else 0,
                    "메모": m_memo,
                }
                manual_entries.append(new_entry)
                save_manual_entries(manual_entries)
                st.success(f"저장 완료! ({m_cat}/{m_sub} {m_amount:,}원)")
                time.sleep(1)
                st.rerun()

    # --- 기존 수기 입력 내역 ---
    st.markdown("---")
    st.markdown("#### 📋 수기 입력 내역")

    # 월 필터
    filter_year = selected_year
    filter_month = selected_month
    filtered_entries = [
        e for e in manual_entries
        if e['날짜'].startswith(f"{filter_year}-{filter_month:02d}")
    ]

    if not filtered_entries:
        other_count = len(manual_entries) - len(filtered_entries)
        msg = f"{filter_year}년 {filter_month}월 수기 입력 내역이 없습니다."
        if other_count > 0:
            msg += f" (다른 월에 {other_count}건 있음)"
        st.info(msg)
    else:
        st.caption(f"{filter_year}년 {filter_month}월 — {len(filtered_entries)}건")
        
        for i, e in enumerate(filtered_entries):
            amount = e.get('입금', 0) or e.get('출금', 0)
            direction = "입금" if e.get('입금', 0) > 0 else "출금"
            memo_str = f" | {e['메모']}" if e.get('메모') else ""
            
            ec1, ec2 = st.columns([6, 1])
            ec1.markdown(
                f"**{e['날짜']}** · {e['대분류']}/{e['소분류']} · "
                f"{e['적요']} · **{direction} {amount:,}원**{memo_str}"
            )
            if ec2.button("🗑️", key=f"del_manual_{e['id']}", use_container_width=True):
                manual_entries = [x for x in manual_entries if x['id'] != e['id']]
                save_manual_entries(manual_entries)
                st.rerun()

    # 전체 보기
    if manual_entries and len(manual_entries) != len(filtered_entries):
        with st.expander(f"📁 전체 수기 입력 보기 (총 {len(manual_entries)}건)"):
            all_manual_df = pd.DataFrame(manual_entries)
            display_cols = ['날짜', '대분류', '소분류', '적요', '입금', '출금', '메모']
            display_cols = [c for c in display_cols if c in all_manual_df.columns]
            st.dataframe(
                all_manual_df[display_cols].style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}, na_rep=""),
                use_container_width=True, hide_index=True
            )
