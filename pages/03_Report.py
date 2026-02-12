import streamlit as st
import pandas as pd
import os, json, io, tempfile
from datetime import datetime

# 경로 설정
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = parent_dir
WORKSPACES_DIR = os.path.join(BASE_DIR, "workspaces")
CLOSED_DIR = os.path.join(BASE_DIR, "closed_reports")
RULES_FILE = os.path.join(WORKSPACES_DIR, "classification_rules.json")
REPORT_SETTINGS_FILE = os.path.join(WORKSPACES_DIR, "report_settings.json")
FONT_PATH = os.path.join(BASE_DIR, "assets", "NotoSansKR-VF.ttf")

import sys
sys.path.insert(0, BASE_DIR)
import file_engine
import report_generator
import excel_report

# =============================================================================
# 유틸
# =============================================================================
def load_rules():
    if os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"매출": {}, "판관비": {}, "기타비용": {}, "투자": {}, "중복방지": []}

def check_is_closed(year, month):
    path = os.path.join(CLOSED_DIR, f"{year}년_{month}월_결산보고서.xlsx")
    return os.path.exists(path), path

def load_closed_data(filepath):
    try: return pd.read_excel(filepath, sheet_name="전체내역")
    except: return pd.DataFrame()

def load_report_settings():
    if os.path.exists(REPORT_SETTINGS_FILE):
        try:
            with open(REPORT_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_report_settings(settings):
    with open(REPORT_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def get_data_for_month(year, month, rules):
    """해당 월의 분류된 데이터를 가져옴 (마감 우선, 없으면 라이브)"""
    is_closed, closed_path = check_is_closed(year, month)
    
    if is_closed:
        df = load_closed_data(closed_path)
        source = "마감"
    else:
        df, _ = file_engine.load_and_classify_data(WORKSPACES_DIR, rules)
        if not df.empty:
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
            df = df[(df['날짜'].dt.year == year) & (df['날짜'].dt.month == month)]
        source = "라이브"
    
    return df, source

def build_report_data(df, year, month, all_df=None):
    """DataFrame에서 보고서 데이터 구조 생성"""
    if df.empty:
        return None
    
    if '날짜' not in df.columns:
        return None
    
    df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce')
    
    rev_df = df[df['대분류'] == '매출']
    opex_df = df[df['대분류'] == '판관비']
    etc_df = df[df['대분류'] == '기타비용']
    invest_df = df[df['대분류'] == '투자']
    
    total_rev = rev_df['입금'].sum()
    total_opex = opex_df['출금'].sum()
    total_etc = etc_df['출금'].sum()
    net_profit = total_rev - total_opex - total_etc
    
    tax_rev = rev_df[rev_df['소분류'] == '세금계산서(매출)']['입금'].sum()
    tax_exp = opex_df[opex_df['소분류'] == '세금계산서(매입)']['출금'].sum()
    ops_cost = opex_df[opex_df['소분류'] != '세금계산서(매입)']['출금'].sum() + total_etc
    
    rev_detail = rev_df.groupby('소분류')['입금'].sum().sort_values(ascending=False).to_dict()
    exp_detail = opex_df.groupby('소분류')['출금'].sum().sort_values(ascending=False).to_dict()
    
    # 전월 데이터
    prev_rev, prev_opex, prev_etc, prev_net = 0, 0, 0, 0
    if all_df is not None and not all_df.empty:
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_df = all_df[(all_df['날짜'].dt.year == prev_year) & (all_df['날짜'].dt.month == prev_month)]
        if not prev_df.empty:
            prev_rev = prev_df[prev_df['대분류'] == '매출']['입금'].sum()
            prev_opex = prev_df[prev_df['대분류'] == '판관비']['출금'].sum()
            prev_etc = prev_df[prev_df['대분류'] == '기타비용']['출금'].sum()
            prev_net = prev_rev - prev_opex - prev_etc
    
    # 월별 추이 (all_df 기준)
    trend = {'months': [], 'revenues': [], 'expenses': []}
    if all_df is not None and not all_df.empty:
        year_df = all_df[all_df['날짜'].dt.year == year]
        for m in sorted(year_df['날짜'].dt.month.dropna().unique().astype(int)):
            mdf = year_df[year_df['날짜'].dt.month == m]
            r = mdf[mdf['대분류'] == '매출']['입금'].sum()
            e = mdf[mdf['대분류'].isin(['판관비', '기타비용'])]['출금'].sum()
            if r > 0 or e > 0:
                trend['months'].append(f"{m}월")
                trend['revenues'].append(r)
                trend['expenses'].append(e)
    
    etc_detail = etc_df.groupby('소분류')['출금'].sum().sort_values(ascending=False).to_dict() if not etc_df.empty else {}
    invest_detail = invest_df.groupby('소분류')['출금'].sum().sort_values(ascending=False).to_dict() if not invest_df.empty else {}
    
    return {
        'year': year, 'month': month,
        'total_rev': total_rev, 'total_opex': total_opex, 'total_etc': total_etc,
        'net_profit': net_profit,
        'total_invest': invest_df['출금'].sum(),
        'tax_rev': tax_rev, 'tax_exp': tax_exp, 'ops_cost': ops_cost,
        'prev_rev': prev_rev, 'prev_opex': prev_opex, 'prev_etc': prev_etc, 'prev_net': prev_net,
        'revenue_detail': rev_detail,
        'expense_detail': exp_detail,
        'etc_detail': etc_detail,
        'invest_detail': invest_detail,
        'monthly_trend': trend,
        '미분류_count': len(df[df['대분류'] == '미분류']),
    }

# =============================================================================
# 페이지 시작
# =============================================================================
st.set_page_config(page_title="경영 보고서", layout="wide") if not hasattr(st, '_is_running_with_streamlit') else None
st.title("📊 월간 경영 보고서")

rules = load_rules()
settings = load_report_settings()

# --- 연/월 선택 ---
st.sidebar.markdown("##### 보고서 기간")
sel_year = st.sidebar.selectbox("연도", range(2024, 2030), index=1, key="rpt_year")

# 마감된 월 확인
closed_months = []
for m in range(1, 13):
    is_c, _ = check_is_closed(sel_year, m)
    if is_c:
        closed_months.append(m)

if closed_months:
    st.sidebar.caption(f"🔒 마감 완료: {', '.join(f'{m}월' for m in closed_months)}")

month_options = list(range(1, 13))
sel_month = st.sidebar.selectbox("월", month_options, 
                                  index=min(datetime.now().month - 1, 11), 
                                  format_func=lambda m: f"{'🔒 ' if m in closed_months else ''}{m}월",
                                  key="rpt_month")

# --- 데이터 로드 ---
month_df, data_source = get_data_for_month(sel_year, sel_month, rules)

# 전체 데이터 (월별 추이용)
all_df = None
try:
    full_df, _ = file_engine.load_and_classify_data(WORKSPACES_DIR, rules)
    if not full_df.empty:
        full_df['날짜'] = pd.to_datetime(full_df['날짜'], errors='coerce')
        all_df = full_df[full_df['날짜'].notna()]
except:
    pass

if month_df is None or month_df.empty:
    st.warning(f"📉 {sel_year}년 {sel_month}월 데이터가 없습니다.")
    st.info("먼저 **자금 관리** 페이지에서 파일을 업로드하고 결산을 진행해주세요.")
    st.stop()

report_data = build_report_data(month_df, sel_year, sel_month, all_df)

if report_data is None:
    st.error("데이터 처리 중 오류가 발생했습니다.")
    st.stop()

# --- 데이터 소스 안내 ---
is_closed = sel_month in closed_months
if is_closed:
    st.success(f"🔒 {sel_year}년 {sel_month}월 마감 데이터 기준으로 보고서를 생성합니다.")
else:
    st.info(f"📂 {sel_year}년 {sel_month}월 실시간 데이터 기준입니다. (마감 전)")

# =============================================================================
# 보고서 설정 (편집 가능)
# =============================================================================
st.markdown("---")
setting_key = f"{sel_year}_{sel_month}"
month_settings = settings.get(setting_key, {})

with st.expander("📝 보고서 설정", expanded=True):
    sc1, sc2 = st.columns(2)
    with sc1:
        company_name = st.text_input("회사명", 
            value=month_settings.get('company_name', settings.get('default_company', '프레피스코리아')),
            key="rpt_company")
        report_title = st.text_input("보고서 제목", 
            value=month_settings.get('report_title', '월간 경영 보고서'),
            key="rpt_title")
    with sc2:
        report_date = st.date_input("보고일",
            value=datetime.now(),
            key="rpt_date")
        st.caption(f"데이터 기준: {'마감 완료' if is_closed else '실시간'}")

# --- 핵심 포인트 편집 ---
st.markdown("#### 📋 핵심 포인트")
st.caption("자동 분석된 내용을 수정하거나 직접 추가할 수 있습니다.")

# 세션 스테이트 초기화
pts_key = f"points_{setting_key}"
if pts_key not in st.session_state:
    saved_pts = month_settings.get('key_points', None)
    if saved_pts:
        st.session_state[pts_key] = saved_pts
    else:
        st.session_state[pts_key] = report_generator.auto_analyze(report_data)

points = st.session_state[pts_key]

# 포인트 목록
points_changed = False
to_delete = None

for i, pt in enumerate(points):
    pc1, pc2, pc3 = st.columns([1, 12, 2])
    
    icon_options = ['✅', '📊', '💰', '🏢', '📈', '⚠️', '🔴', '🟢', '📋', '💡']
    current_icon = pt.get('icon', '•')
    icon_idx = icon_options.index(current_icon) if current_icon in icon_options else 0
    
    new_icon = pc1.selectbox("아이콘", icon_options, index=icon_idx, 
                              key=f"icon_{setting_key}_{i}", label_visibility="collapsed")
    new_text = pc2.text_input("내용", value=pt.get('text', ''), 
                               key=f"text_{setting_key}_{i}", label_visibility="collapsed")
    
    if pc3.button("🗑️", key=f"del_pt_{setting_key}_{i}", use_container_width=True):
        to_delete = i
    
    if new_icon != pt.get('icon') or new_text != pt.get('text'):
        points[i]['icon'] = new_icon
        points[i]['text'] = new_text
        points_changed = True

if to_delete is not None:
    points.pop(to_delete)
    st.session_state[pts_key] = points
    st.rerun()

# 포인트 추가
ac1, ac2, ac3 = st.columns([1, 10, 2])
new_pt_icon = ac1.selectbox("아이콘", ['💡', '✅', '📊', '⚠️', '🔴'], key=f"new_icon_{setting_key}", label_visibility="collapsed")
new_pt_text = ac2.text_input("새 포인트 추가", placeholder="직접 입력...", key=f"new_text_{setting_key}", label_visibility="collapsed")
if ac3.button("➕ 추가", key=f"add_pt_{setting_key}", use_container_width=True):
    if new_pt_text:
        points.append({'icon': new_pt_icon, 'text': new_pt_text, 'color': '#555'})
        st.session_state[pts_key] = points
        st.rerun()

# 자동 분석으로 초기화
if st.button("🔄 자동 분석으로 초기화", key=f"reset_pts_{setting_key}"):
    st.session_state[pts_key] = report_generator.auto_analyze(report_data)
    st.rerun()

# =============================================================================
# 미리보기 + 생성
# =============================================================================
st.markdown("---")

# 요약 미리보기
st.markdown("#### 👁️ 보고서 요약 미리보기")

net = report_data['net_profit']
total_rev = report_data['total_rev']
total_exp = report_data['total_opex'] + report_data['total_etc']
is_profit = net >= 0

# KPI 카드
k1, k2, k3, k4 = st.columns(4)
k1.metric("총 매출", f"{int(total_rev):,}원", delta="입금")
k2.metric("총 지출", f"{int(total_exp):,}원", delta="-출금", delta_color="inverse")
margin = (net / total_rev * 100) if total_rev > 0 else 0
k3.metric("순수익", f"{int(net):,}원", delta=f"이익률 {margin:.1f}%")
k4.metric("투자/저축", f"{int(report_data['total_invest']):,}원")

# 매출/매입 분해
m1, m2, m3 = st.columns(3)
with m1:
    st.markdown("**🟦 매출 구성**")
    for k, v in report_data['revenue_detail'].items():
        pct = v / total_rev * 100 if total_rev > 0 else 0
        st.text(f"  {k}: {int(v):>12,}원 ({pct:.1f}%)")
with m2:
    st.markdown("**🟥 비용 구성**")
    for k, v in report_data['expense_detail'].items():
        pct = v / total_exp * 100 if total_exp > 0 else 0
        st.text(f"  {k}: {int(v):>12,}원 ({pct:.1f}%)")
with m3:
    st.markdown("**📋 핵심 포인트**")
    for pt in points[:5]:
        st.text(f"  {pt.get('icon', '•')} {pt.get('text', '')}")

# =============================================================================
# PDF 생성 및 다운로드
# =============================================================================
st.markdown("---")

gc1, gc2, gc3 = st.columns([2, 2, 1])

with gc1:
    generate_pdf = st.button("📄 PDF 보고서 생성", type="primary", use_container_width=True)

with gc2:
    generate_xlsx = st.button("📊 엑셀 보고서 생성", use_container_width=True)

with gc3:
    save_settings_btn = st.button("💾 설정 저장", use_container_width=True)

if save_settings_btn:
    settings[setting_key] = {
        'company_name': company_name,
        'report_title': report_title,
        'key_points': points,
    }
    settings['default_company'] = company_name
    save_report_settings(settings)
    st.toast("✅ 설정이 저장되었습니다!", icon="💾")

def _prepare_data():
    """공통 데이터 준비 + 설정 저장"""
    report_data['company_name'] = company_name
    report_data['report_title'] = report_title
    report_data['report_date'] = report_date.strftime('%Y.%m.%d')
    report_data['key_points'] = points
    
    settings[setting_key] = {
        'company_name': company_name,
        'report_title': report_title,
        'key_points': points,
    }
    settings['default_company'] = company_name
    save_report_settings(settings)

if generate_pdf:
    if not os.path.exists(FONT_PATH):
        st.error(f"⚠️ 폰트 파일이 없습니다: {FONT_PATH}\n\n"
                 f"assets/NotoSansKR-VF.ttf 파일을 프로젝트 폴더에 넣어주세요.")
        st.stop()
    
    _prepare_data()
    
    with st.spinner("PDF 보고서 생성 중..."):
        try:
            filename = f"{company_name}_{sel_year}년_{sel_month}월_경영보고서.pdf"
            tmp_path = os.path.join(tempfile.gettempdir(), filename)
            
            report_generator.generate_report(report_data, tmp_path, FONT_PATH)
            
            with open(tmp_path, 'rb') as f:
                pdf_bytes = f.read()
            
            st.success(f"✅ PDF 보고서 생성 완료! ({len(pdf_bytes)/1024:.0f}KB)")
            st.download_button(
                label=f"📥 다운로드: {filename}",
                data=pdf_bytes, file_name=filename,
                mime="application/pdf", type="primary", use_container_width=True
            )
            try: os.remove(tmp_path)
            except: pass
        except Exception as e:
            st.error(f"❌ PDF 생성 실패: {e}")
            import traceback
            st.code(traceback.format_exc())

if generate_xlsx:
    _prepare_data()
    
    with st.spinner("엑셀 보고서 생성 중..."):
        try:
            filename = f"{company_name}_{sel_year}년_{sel_month}월_경영보고서.xlsx"
            tmp_path = os.path.join(tempfile.gettempdir(), filename)
            
            excel_report.generate_excel_report(report_data, tmp_path)
            
            with open(tmp_path, 'rb') as f:
                xlsx_bytes = f.read()
            
            st.success(f"✅ 엑셀 보고서 생성 완료! ({len(xlsx_bytes)/1024:.0f}KB)")
            st.download_button(
                label=f"📥 다운로드: {filename}",
                data=xlsx_bytes, file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", use_container_width=True
            )
            try: os.remove(tmp_path)
            except: pass
        except Exception as e:
            st.error(f"❌ 엑셀 생성 실패: {e}")
            import traceback
            st.code(traceback.format_exc())
