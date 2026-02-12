import streamlit as st
import pandas as pd
import os
import sys
import altair as alt
from datetime import datetime

# -----------------------------------------------------------------------------
# [중요] file_engine 로드
# -----------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
try:
    import file_engine
except ImportError:
    sys.path.append(current_dir)
    try:
        import file_engine
    except:
        st.error("file_engine.py를 찾을 수 없습니다.")
        st.stop()

st.set_page_config(
    page_title="재무 대시보드", 
    page_icon="💰", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# 데이터 로드
# -----------------------------------------------------------------------------
WORKSPACES_DIR = os.path.join(current_dir, "workspaces")
RULES_FILE = os.path.join(WORKSPACES_DIR, "classification_rules.json")

# [수정 #3] 규칙 로드 — 투자 + 중복방지 카테고리 포함
import json
def load_rules():
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 누락된 키가 있으면 기본값 추가
                for k in ["매출", "판관비", "기타비용", "투자"]:
                    if k not in data: data[k] = {}
                if "중복방지" not in data: data["중복방지"] = []
                return data
        except: pass
    return {"매출": {}, "판관비": {}, "기타비용": {}, "투자": {}, "중복방지": []}

rules = load_rules()
df, _ = file_engine.load_and_classify_data(WORKSPACES_DIR, rules)

# -----------------------------------------------------------------------------
# 메인 화면 UI
# -----------------------------------------------------------------------------
st.title("📊 재무 현황 대시보드")
st.markdown("회사의 자금 흐름과 주요 지표를 한눈에 확인하세요.")
st.divider()

if df.empty:
    st.info("아직 데이터가 없습니다. 좌측 메뉴의 **'자금 관리'** 페이지에서 엑셀 파일을 업로드해주세요.")
else:
    # 날짜 처리
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    df = df.sort_values('날짜')
    
    # [사이드바 필터] 연도/월 선택
    st.sidebar.header("대시보드 필터")
    valid_df = df[df['날짜'].notna()]
    if not valid_df.empty:
        years = sorted(valid_df['날짜'].dt.year.unique(), reverse=True)
        selected_year = st.sidebar.selectbox("연도 선택", years)
        
        # 월 선택 (전체 보기 옵션 추가)
        months = sorted(valid_df[valid_df['날짜'].dt.year == selected_year]['날짜'].dt.month.unique())
        selected_month = st.sidebar.selectbox("월 선택 (0=전체)", [0] + months, format_func=lambda x: "전체" if x==0 else f"{x}월")
        
        # 데이터 필터링
        if selected_month == 0:
            current_df = valid_df[valid_df['날짜'].dt.year == selected_year]
            period_title = f"{selected_year}년 전체"
        else:
            current_df = valid_df[
                (valid_df['날짜'].dt.year == selected_year) & 
                (valid_df['날짜'].dt.month == selected_month)
            ]
            period_title = f"{selected_year}년 {selected_month}월"
    else:
        current_df = pd.DataFrame()
        period_title = "-"

    # -------------------------------------------------------------------------
    # 1. 핵심 지표 (KPI Metrics)
    # [수정 #3] 투자 KPI 추가
    # -------------------------------------------------------------------------
    if not current_df.empty:
        total_rev = current_df[current_df['대분류'] == '매출']['입금'].sum()
        total_exp = current_df[current_df['대분류'].isin(['판관비', '기타비용'])]['출금'].sum()
        total_invest = current_df[current_df['대분류'] == '투자']['출금'].sum()
        net_profit = total_rev - total_exp
        margin = (net_profit / total_rev * 100) if total_rev > 0 else 0

        st.subheader(f"📅 {period_title} 요약")
        
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("총 매출", f"{int(total_rev):,}원", border=True)
        k2.metric("총 지출", f"{int(total_exp):,}원", border=True)
        k3.metric("순수익", f"{int(net_profit):,}원", delta=f"{margin:.1f}% (이익률)", border=True)
        k4.metric("투자/저축", f"{int(total_invest):,}원", border=True)
        
        # 미분류 건수 확인
        unclassified_count = len(current_df[current_df['대분류'] == '미분류'])
        k5.metric("미분류 건수", f"{unclassified_count}건", delta_color="inverse", 
                  delta="확인 필요" if unclassified_count > 0 else "완벽")

        st.markdown("---")

        # ---------------------------------------------------------------------
        # 2. 차트 영역 (좌: 추이, 우: 구성)
        # [수정 #3] 월별 투자 추이도 차트에 포함
        # ---------------------------------------------------------------------
        c_left, c_right = st.columns([2, 1])

        with c_left:
            st.markdown("#### 📈 월별 매출/지출/투자 추이")
            # 월별 집계 (전체 데이터 기준, 연도 필터만 적용)
            trend_df = valid_df[valid_df['날짜'].dt.year == selected_year].copy()
            trend_df['월'] = trend_df['날짜'].dt.month
            
            monthly_rev = trend_df[trend_df['대분류']=='매출'].groupby('월')['입금'].sum().reset_index()
            monthly_rev['유형'] = '매출'
            monthly_rev.rename(columns={'입금':'금액'}, inplace=True)
            
            monthly_exp = trend_df[trend_df['대분류'].isin(['판관비', '기타비용'])].groupby('월')['출금'].sum().reset_index()
            monthly_exp['유형'] = '지출'
            monthly_exp.rename(columns={'출금':'금액'}, inplace=True)
            
            monthly_invest = trend_df[trend_df['대분류']=='투자'].groupby('월')['출금'].sum().reset_index()
            monthly_invest['유형'] = '투자'
            monthly_invest.rename(columns={'출금':'금액'}, inplace=True)
            
            chart_df = pd.concat([monthly_rev, monthly_exp, monthly_invest])
            chart_df = chart_df.dropna(subset=['금액'])
            chart_df = chart_df[chart_df['금액'] > 0]
            
            if not chart_df.empty:
                # Altair 라인 차트
                chart = alt.Chart(chart_df).mark_line(point=True).encode(
                    x=alt.X('월:O', title='월'),
                    y=alt.Y('금액:Q', title='금액(원)'),
                    color=alt.Color('유형', scale=alt.Scale(
                        domain=['매출', '지출', '투자'], 
                        range=['#3b82f6', '#ef4444', '#10b981']
                    )),
                    tooltip=['월', '유형', alt.Tooltip('금액', format=',')]
                ).properties(height=350)
                
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("해당 연도에 데이터가 없습니다.")

        with c_right:
            st.markdown("#### 🍩 지출 구성 (Top 5)")
            # 소분류별 지출 합계
            exp_breakdown = current_df[current_df['대분류'].isin(['판관비', '기타비용'])]
            if not exp_breakdown.empty:
                pie_df = exp_breakdown.groupby('소분류')['출금'].sum().reset_index()
                pie_df = pie_df[pie_df['출금'] > 0]
                pie_df = pie_df.sort_values('출금', ascending=False).head(5) # Top 5만
                
                if not pie_df.empty:
                    # 도넛 차트
                    base = alt.Chart(pie_df).encode(theta=alt.Theta("출금", stack=True))
                    pie = base.mark_arc(innerRadius=50).encode(
                        color=alt.Color("소분류"),
                        order=alt.Order("출금", sort="descending"),
                        tooltip=["소분류", alt.Tooltip("출금", format=",")]
                    )
                    text = base.mark_text(radius=140).encode(
                        text="소분류",
                        order=alt.Order("출금", sort="descending"),
                        color=alt.value("black")  
                    )
                    st.altair_chart(pie + text, use_container_width=True)
                else:
                    st.caption("지출 내역이 없습니다.")
            else:
                st.caption("지출 내역이 없습니다.")

        # ---------------------------------------------------------------------
        # 3. 최근 거래 내역
        # ---------------------------------------------------------------------
        st.markdown("#### 🕒 최근 입출금 내역 (최근 5건)")
        recent_tx = current_df.sort_values('날짜', ascending=False).head(5)
        st.dataframe(
            recent_tx[['날짜', '대분류', '소분류', '적요', '입금', '출금']]
            .style.format({"입금": "{:,.0f}", "출금": "{:,.0f}"}),
            use_container_width=True,
            hide_index=True
        )

    else:
        st.warning("선택하신 기간에 데이터가 없습니다.")
