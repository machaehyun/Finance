#!/usr/bin/env python3
"""
report_generator.py — 월간 경영 보고서 PDF 생성 모듈
Finance 페이지의 마감 데이터를 기반으로 보고용 PDF를 생성합니다.
"""

import os, io
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# === 색상 팔레트 ===
C_NAVY = '#1B3A5C'
C_BLUE = '#2E6DB4'
C_ORANGE = '#E8832A'
C_GREEN = '#2B8C5A'
C_RED = '#D94040'
C_BG = '#F4F6F9'
PIE_BLUE = ['#1B3A5C', '#2E6DB4', '#5B8EC9', '#8BB4DB', '#B8D4ED', '#D6E4F0']
PIE_RED  = ['#D94040', '#E86B4A', '#F09060', '#F5B080', '#FADCB0', '#FFF0E0']

W, H = A4

_font_initialized = False
_font_prop = None

def _init_fonts(font_path):
    """폰트를 한 번만 초기화"""
    global _font_initialized, _font_prop
    if _font_initialized:
        return _font_prop
    
    if not os.path.exists(font_path):
        raise FileNotFoundError(f"폰트 파일이 없습니다: {font_path}")
    
    pdfmetrics.registerFont(TTFont('NotoR', font_path))
    pdfmetrics.registerFont(TTFont('NotoB', font_path))
    pdfmetrics.registerFont(TTFont('NotoM', font_path))
    
    fm.fontManager.addfont(font_path)
    _font_prop = fm.FontProperties(fname=font_path)
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = [_font_prop.get_name()] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False
    
    _font_initialized = True
    return _font_prop

# === 포맷 유틸 ===
def fmt(val, short=False):
    if abs(val) >= 1e8:
        return f"{val/1e8:,.1f}억"
    elif abs(val) >= 1e4:
        return f"{val/1e4:,.0f}만" + ("" if short else "원")
    return f"{val:,.0f}원"

def pct_str(val, total):
    if total == 0: return "-"
    return f"{val/total*100:.1f}%"

def _change_str(cur, prev):
    if prev == 0: return ""
    change = (cur - prev) / abs(prev) * 100
    sign = "▲" if change >= 0 else "▼"
    return f"{sign} {abs(change):.1f}%"

# === PDF 그리기 유틸 ===
def _draw_section(c, y, num, title):
    c.saveState()
    c.setFillColor(HexColor(C_NAVY))
    c.setFont('NotoB', 12)
    c.drawString(25*mm, y, f"{num}. {title}")
    c.setStrokeColor(HexColor(C_NAVY))
    c.setLineWidth(1.2)
    c.line(25*mm, y - 2.5, W - 20*mm, y - 2.5)
    c.restoreState()
    return y - 8*mm

def _draw_box(c, x, y, w, h, fill=None, stroke='#D0D8E0', r=4):
    c.saveState()
    if fill:
        c.setFillColor(HexColor(fill))
    if stroke:
        c.setStrokeColor(HexColor(stroke))
        c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, r, fill=1 if fill else 0, stroke=1 if stroke else 0)
    c.restoreState()

# === 차트 생성 ===
def _create_waterfall(data, font_prop):
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    fig.patch.set_facecolor('white')
    
    labels = data['labels']
    values = data['values']
    colors = data['colors']
    
    cumulative = [0]
    for v in values[:-1]:
        cumulative.append(cumulative[-1] + v)
    
    bottoms, heights = [], []
    for i, val in enumerate(values):
        if i == 0 or i == len(labels) - 1:
            bottoms.append(0)
            heights.append(val)
        elif val < 0:
            bottoms.append(cumulative[i] + val)
            heights.append(abs(val))
        else:
            bottoms.append(cumulative[i])
            heights.append(val)
    
    bars = ax.bar(range(len(labels)), heights, bottom=bottoms, color=colors,
                  width=0.6, edgecolor='white', linewidth=0.5, zorder=3)
    
    for i, (bar, val) in enumerate(zip(bars, values)):
        top = bar.get_y() + bar.get_height()
        txt = fmt(abs(val), short=True)
        if val < 0: txt = f"-{txt}"
        ax.text(bar.get_x() + bar.get_width()/2, top + max(max(values), 1) * 0.02,
               txt, ha='center', va='bottom', fontproperties=font_prop, fontsize=8.5,
               fontweight='bold', color=colors[i])
    
    for i in range(len(labels) - 2):
        y_line = cumulative[i+1]
        ax.plot([i + 0.3, i + 0.7], [y_line, y_line], color='#999', linewidth=0.8, linestyle='--', zorder=2)
    
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontproperties=font_prop, fontsize=9)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v/1e4:,.0f}만'))
    ax.tick_params(axis='y', labelsize=7, colors='#999')
    for s in ['top', 'right']: ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']: ax.spines[s].set_color('#ddd')
    ax.grid(axis='y', alpha=0.2, linestyle='--')
    ax.set_axisbelow(True)
    plt.tight_layout(pad=0.5)
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf

def _create_dual_pie(rev_detail, exp_detail, font_prop):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.5, 3.0))
    fig.patch.set_facecolor('white')
    
    for ax, detail, title, colors in [
        (ax1, rev_detail, '매출 구성', PIE_BLUE),
        (ax2, exp_detail, '비용 구성', PIE_RED)
    ]:
        labels = list(detail.keys())[:6]
        vals = list(detail.values())[:6]
        if len(detail) > 6:
            labels.append('기타')
            vals.append(sum(list(detail.values())[6:]))
        total = sum(vals) if sum(vals) > 0 else 1
        
        legend_labels = [f'{l}  {v/total*100:.0f}%' for l, v in zip(labels, vals)]
        
        ax.pie(vals, labels=None, autopct='', startangle=90,
               colors=colors[:len(labels)],
               wedgeprops=dict(width=0.42, edgecolor='white', linewidth=1.5))
        
        ax.text(0, 0, fmt(total, short=True), ha='center', va='center',
               fontproperties=font_prop, fontsize=10, fontweight='bold', color='#333')
        ax.set_title(title, fontproperties=font_prop, fontsize=10, pad=8, color='#333')
        ax.legend(legend_labels, loc='center left', bbox_to_anchor=(0.95, 0.5),
                 prop=font_prop, fontsize=7.5, frameon=False)
    
    plt.tight_layout(pad=1.0)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf

def _create_trend(monthly_data, font_prop):
    fig, ax = plt.subplots(figsize=(7.5, 2.5))
    fig.patch.set_facecolor('white')
    
    months = monthly_data['months']
    revenues = monthly_data['revenues']
    expenses = monthly_data['expenses']
    profits = [r - e for r, e in zip(revenues, expenses)]
    
    x = np.arange(len(months))
    bw = 0.28
    ax.bar(x - bw, revenues, bw, color=C_BLUE, alpha=0.85, label='매출', zorder=3)
    ax.bar(x, expenses, bw, color=C_RED, alpha=0.7, label='지출', zorder=3)
    ax.bar(x + bw, profits, bw, color=C_GREEN, alpha=0.8, label='순수익', zorder=3)
    
    ax.set_xticks(x)
    ax.set_xticklabels(months, fontproperties=font_prop, fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'{v/1e4:,.0f}만'))
    ax.tick_params(axis='y', labelsize=7, colors='#999')
    ax.legend(prop=font_prop, fontsize=8, framealpha=0.9, edgecolor='#ddd', loc='upper left')
    for s in ['top', 'right']: ax.spines[s].set_visible(False)
    for s in ['left', 'bottom']: ax.spines[s].set_color('#ddd')
    ax.grid(axis='y', alpha=0.2, linestyle='--')
    ax.set_axisbelow(True)
    plt.tight_layout(pad=0.5)
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf

# === 자동 분석 포인트 ===
def auto_analyze(data):
    """데이터 기반 핵심 포인트 자동 생성"""
    points = []
    net = data['net_profit']
    total_rev = data['total_rev']
    total_exp = data['total_opex'] + data['total_etc']
    tax_rev = data.get('tax_rev', 0)
    tax_exp = data.get('tax_exp', 0)
    ops = data.get('ops_cost', 0)
    gross = tax_rev - tax_exp
    
    margin = (net / total_rev * 100) if total_rev > 0 else 0
    gross_margin = (gross / tax_rev * 100) if tax_rev > 0 else 0
    
    if net >= 0:
        points.append({'icon': '✅', 'text': f'당월 순이익 {fmt(net)} 달성 (이익률 {margin:.1f}%)', 'color': C_GREEN})
    else:
        points.append({'icon': '🔴', 'text': f'당월 순손실 {fmt(abs(net))} 발생', 'color': C_RED})
    
    points.append({'icon': '📊', 'text': f'매출총이익률 {gross_margin:.1f}% (매출 {fmt(tax_rev)} - 매입 {fmt(tax_exp)})', 'color': C_BLUE})
    
    exp_detail = data.get('expense_detail', {})
    if exp_detail:
        top_name, top_val = list(exp_detail.items())[0]
        points.append({'icon': '💰', 'text': f'최대 비용: {top_name} ({fmt(top_val)}, 전체 지출의 {pct_str(top_val, total_exp)})', 'color': C_ORANGE})
    
    if ops > 0:
        points.append({'icon': '🏢', 'text': f'운영비 합계 {fmt(ops)} (매입 외 인건비/임대료/서비스 등)', 'color': '#555'})
    
    invest = data.get('total_invest', 0)
    if invest > 0:
        points.append({'icon': '📈', 'text': f'투자/저축 {fmt(invest)} 집행 (비용 아닌 자산 이동)', 'color': C_GREEN})
    
    unc = data.get('미분류_count', 0)
    if unc > 0:
        points.append({'icon': '⚠️', 'text': f'미분류 거래 {unc}건 — 규칙 추가 필요', 'color': C_ORANGE})
    
    return points


# =============================================================================
# 메인 생성 함수
# =============================================================================
def generate_report(data, output_path, font_path):
    """
    월간 경영 보고서 PDF를 생성합니다.
    
    data 구조:
        year, month, report_title, company_name, report_date,
        total_rev, total_opex, total_etc, net_profit, total_invest,
        tax_rev, tax_exp, ops_cost,
        prev_rev, prev_opex, prev_etc, prev_net,
        revenue_detail: {소분류: 금액},
        expense_detail: {소분류: 금액},
        monthly_trend: {months: [], revenues: [], expenses: []},
        key_points: [{'icon': str, 'text': str, 'color': str}, ...],
        미분류_count: int
    """
    font_prop = _init_fonts(font_path)
    
    year = data['year']
    month = data['month']
    company = data.get('company_name', '')
    title = data.get('report_title', '월간 경영 보고서')
    report_date = data.get('report_date', '')
    
    total_rev = data['total_rev']
    total_opex = data['total_opex']
    total_etc = data['total_etc']
    total_exp = total_opex + total_etc
    net = data['net_profit']
    tax_rev = data.get('tax_rev', 0)
    tax_exp = data.get('tax_exp', 0)
    ops_cost = data.get('ops_cost', 0)
    gross = tax_rev - tax_exp
    is_profit = net >= 0
    
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle(f"{company} {year}년 {month}월 경영보고서")
    
    # =====================================================================
    # 헤더
    # =====================================================================
    c.setFillColor(HexColor(C_NAVY))
    c.rect(0, H - 55*mm, W, 55*mm, fill=1, stroke=0)
    c.setFillColor(HexColor(C_ORANGE))
    c.rect(0, H - 56*mm, W, 1.2*mm, fill=1, stroke=0)
    
    c.setFillColor(white)
    c.setFont('NotoB', 24)
    c.drawCentredString(W/2, H - 25*mm, title)
    c.setFont('NotoR', 12)
    c.drawCentredString(W/2, H - 36*mm, f"{year}년 {month}월  |  {company}")
    
    c.setFont('NotoR', 8)
    c.setFillColor(HexColor('#8BB4DB'))
    c.drawCentredString(W/2, H - 46*mm, f"보고일: {report_date}")
    
    y = H - 66*mm
    
    # =====================================================================
    # 1. 이번 달 한눈에 보기
    # =====================================================================
    y = _draw_section(c, y, 1, "이번 달 한눈에 보기")
    
    # 큰 손익 카드
    card_w = W - 50*mm
    card_h = 30*mm
    card_x = 25*mm
    card_y = y - card_h
    
    profit_color = C_GREEN if is_profit else C_RED
    profit_bg = '#E8F5E9' if is_profit else '#FFEBEE'
    profit_label = "이익" if is_profit else "손실"
    
    _draw_box(c, card_x, card_y, card_w, card_h, fill=profit_bg, stroke=profit_color)
    
    c.setFillColor(HexColor(profit_color))
    c.setFont('NotoB', 11)
    c.drawString(card_x + 6*mm, card_y + card_h - 10*mm, f"이번 달 순{profit_label}")
    c.setFont('NotoB', 22)
    c.drawString(card_x + 6*mm, card_y + 5*mm, fmt(abs(net)))
    
    rx = card_x + card_w/2 + 10*mm
    c.setFont('NotoR', 9)
    c.setFillColor(HexColor('#555'))
    margin = (net / total_rev * 100) if total_rev > 0 else 0
    c.drawString(rx, card_y + card_h - 10*mm, f"매출  {fmt(total_rev)}")
    c.drawString(rx, card_y + card_h - 17*mm, f"지출  {fmt(total_exp)}")
    c.setFillColor(HexColor(profit_color))
    c.setFont('NotoB', 9)
    c.drawString(rx, card_y + 4*mm, f"이익률  {margin:.1f}%")
    
    y = card_y - 5*mm
    
    # 3개 미니 카드
    mini_w = (card_w - 8*mm) / 3
    mini_h = 22*mm
    mini_y = y - mini_h
    
    mini_items = [
        ("매출총이익", "매출 - 매입", gross, C_BLUE, '#E3F2FD'),
        ("운영비", "인건비/임대/서비스 등", ops_cost, C_ORANGE, '#FFF3E0'),
        ("투자/저축", "자산 이동 (비용 아님)", data['total_invest'], C_GREEN, '#E8F5E9'),
    ]
    
    for i, (label, desc, val, color, bg) in enumerate(mini_items):
        mx = card_x + i * (mini_w + 4*mm)
        _draw_box(c, mx, mini_y, mini_w, mini_h, fill=bg, stroke=color)
        c.setFillColor(HexColor(color))
        c.setFont('NotoB', 8.5)
        c.drawString(mx + 4*mm, mini_y + mini_h - 7*mm, label)
        c.setFont('NotoB', 13)
        c.drawString(mx + 4*mm, mini_y + mini_h - 17*mm, fmt(val))
        c.setFillColor(HexColor('#888'))
        c.setFont('NotoR', 6.5)
        c.drawString(mx + 4*mm, mini_y + 2*mm, desc)
    
    y = mini_y - 8*mm
    
    # =====================================================================
    # 2. 손익 흐름 (워터폴)
    # =====================================================================
    y = _draw_section(c, y, 2, "손익 흐름 — 돈이 어떻게 남았나?")
    
    wf_data = {
        'labels': ['매출', '매입(원가)', '운영비', '순수익'],
        'values': [total_rev, -tax_exp, -ops_cost, net],
        'colors': [C_BLUE, C_RED, C_ORANGE, C_GREEN if is_profit else C_RED],
    }
    
    chart_buf = _create_waterfall(wf_data, font_prop)
    chart_h = 48*mm
    c.drawImage(ImageReader(chart_buf), 25*mm, y - chart_h, width=W - 45*mm, height=chart_h, mask='auto')
    y = y - chart_h - 8*mm
    
    # =====================================================================
    # 3. 매출 vs 비용 구성
    # =====================================================================
    y = _draw_section(c, y, 3, "매출 vs 비용 — 어디서 벌고 어디에 썼나?")
    
    pie_buf = _create_dual_pie(data['revenue_detail'], data['expense_detail'], font_prop)
    pie_h = 48*mm
    c.drawImage(ImageReader(pie_buf), 20*mm, y - pie_h, width=W - 40*mm, height=pie_h, mask='auto')
    y = y - pie_h - 8*mm
    
    # =====================================================================
    # 4. 핵심 포인트
    # =====================================================================
    if y < 100*mm:
        c.showPage()
        y = H - 25*mm
    
    y = _draw_section(c, y, 4, "핵심 포인트")
    
    points = data.get('key_points', [])
    if not points:
        points = auto_analyze(data)
    
    for pt in points[:6]:
        icon = pt.get('icon', '•')
        text = pt.get('text', '')
        color = pt.get('color', '#333')
        
        c.setFillColor(HexColor(color))
        c.setFont('NotoB', 9)
        c.drawString(28*mm, y, icon)
        c.setFont('NotoR', 9)
        c.setFillColor(HexColor('#333'))
        c.drawString(35*mm, y, text)
        y -= 6*mm
    
    y -= 6*mm
    
    # =====================================================================
    # 5. 손익 현황 상세
    # =====================================================================
    y = _draw_section(c, y, 5, "손익 현황 상세")
    
    table_x = 25*mm
    table_w = W - 50*mm
    row_h = 7.5*mm
    col_w = [table_w * 0.35, table_w * 0.25, table_w * 0.2, table_w * 0.2]
    
    prev_rev = data.get('prev_rev', 0)
    prev_opex = data.get('prev_opex', 0)
    prev_etc = data.get('prev_etc', 0)
    prev_net = data.get('prev_net', 0)
    
    rows = [
        ("항목", f"당월 ({month}월)", "전월", "증감", True),
        ("매출 (세금계산서)", fmt(tax_rev), "-", "", False),
        ("매출 (브랜드별)", fmt(total_rev - tax_rev), "-", "", False),
        ("총 매출", fmt(total_rev), fmt(prev_rev) if prev_rev else "-", "", True),
        ("매입 (세금계산서)", fmt(tax_exp), "-", "", False),
        ("운영비 (인건비 등)", fmt(ops_cost), "-", "", False),
        ("총 지출", fmt(total_exp), fmt(prev_opex + prev_etc) if prev_opex else "-", "", True),
        ("순수익", fmt(net), fmt(prev_net) if prev_net else "-",
         _change_str(net, prev_net) if prev_net else "", True),
    ]
    
    for i, (col1, col2, col3, col4, is_bold) in enumerate(rows):
        ry = y - (i + 1) * row_h
        
        if i == 0:
            c.setFillColor(HexColor(C_NAVY))
            c.rect(table_x, ry, table_w, row_h, fill=1, stroke=0)
            c.setFillColor(white)
            c.setFont('NotoB', 8.5)
        elif is_bold:
            c.setFillColor(HexColor('#E8EFF6'))
            c.rect(table_x, ry, table_w, row_h, fill=1, stroke=0)
            c.setFillColor(HexColor(C_NAVY))
            c.setFont('NotoB', 8.5)
        else:
            bg = '#FFFFFF' if i % 2 == 0 else '#F8FAFC'
            c.setFillColor(HexColor(bg))
            c.rect(table_x, ry, table_w, row_h, fill=1, stroke=0)
            c.setFillColor(HexColor('#444'))
            c.setFont('NotoR', 8.5)
        
        c.setStrokeColor(HexColor('#DEE2E6'))
        c.setLineWidth(0.3)
        c.rect(table_x, ry, table_w, row_h, fill=0, stroke=1)
        
        ty = ry + 2*mm
        c.drawString(table_x + 4*mm, ty, col1)
        c.drawRightString(table_x + col_w[0] + col_w[1] - 4*mm, ty, col2)
        c.drawRightString(table_x + col_w[0] + col_w[1] + col_w[2] - 4*mm, ty, col3)
        
        if col4:
            if '▲' in col4:
                c.setFillColor(HexColor(C_GREEN))
            elif '▼' in col4:
                c.setFillColor(HexColor(C_RED))
            c.drawRightString(table_x + table_w - 4*mm, ty, col4)
    
    y = y - (len(rows) + 1) * row_h - 8*mm
    
    # =====================================================================
    # 6. 월별 추이 (2개월 이상 데이터일 때)
    # =====================================================================
    if len(data.get('monthly_trend', {}).get('months', [])) > 1:
        if y < 60*mm:
            c.showPage()
            y = H - 25*mm
        
        y = _draw_section(c, y, 6, "월별 추이")
        trend_buf = _create_trend(data['monthly_trend'], font_prop)
        trend_h = 42*mm
        c.drawImage(ImageReader(trend_buf), 25*mm, y - trend_h, width=W - 45*mm, height=trend_h, mask='auto')
    
    # =====================================================================
    # 푸터
    # =====================================================================
    c.setFillColor(HexColor('#AAA'))
    c.setFont('NotoR', 7)
    c.drawCentredString(W/2, 8*mm, f"© {year} {company}  |  본 보고서는 자동 생성된 재무 분석 자료입니다.")
    
    c.save()
    return output_path
