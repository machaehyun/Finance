"""
샘플 데이터 생성기 - Streamlit Cloud 배포용
실제 데이터 대신 사용할 데모 데이터를 생성합니다.
"""

import pandas as pd
import os
from datetime import datetime, timedelta
import random

def create_sample_data():
    """샘플 계좌 거래내역 생성"""
    
    # 샘플 거래 데이터
    start_date = datetime(2026, 1, 1)
    transactions = []
    
    # 매출 거래
    revenue_items = [
        ("세글계산서(매출)", "㈜ABC컴퍼니", 15000000),
        ("1301임대료", "㈜XYZ테크", 8000000),
        ("SK클센터", "SK㈜", 12000000),
        ("프레피스에이", "프레피스㈜", 2500000),
        ("개발운영", "테크솔루션", 1200000),
    ]
    
    for i, (description, company, amount) in enumerate(revenue_items):
        date = start_date + timedelta(days=random.randint(0, 30))
        transactions.append({
            '날짜': date.strftime('%Y-%m-%d'),
            '적요': f"{description} {company}",
            '입금': amount,
            '출금': 0,
            '잔액': 0,
            '거래점': '본점',
            '메모': ''
        })
    
    # 지출 거래 (판관비)
    expense_items = [
        ("세금계산서(매출)", "㈜공급업체", 5000000),
        ("프레피스 직원 인건비", "급여", 3000000),
        ("기관직원 입금", "급여", 2500000),
        ("기반차량리스", "차량리스", 800000),
        ("대표님차량리스", "차량리스", 1200000),
        ("문자서비스", "통신비", 150000),
        ("법인카드", "법인카드", 500000),
    ]
    
    for description, category, amount in expense_items:
        date = start_date + timedelta(days=random.randint(0, 30))
        transactions.append({
            '날짜': date.strftime('%Y-%m-%d'),
            '적요': f"{description}",
            '입금': 0,
            '출금': amount,
            '잔액': 0,
            '거래점': '본점',
            '메모': category
        })
    
    # 기타비용
    other_costs = [
        ("세금", 2000000),
        ("추억금", 500000),
    ]
    
    for description, amount in other_costs:
        date = start_date + timedelta(days=random.randint(0, 30))
        transactions.append({
            '날짜': date.strftime('%Y-%m-%d'),
            '적요': description,
            '입금': 0,
            '출금': amount,
            '잔액': 0,
            '거래점': '본점',
            '메모': ''
        })
    
    # DataFrame 생성
    df = pd.DataFrame(transactions)
    df = df.sort_values('날짜').reset_index(drop=True)
    
    # 잔액 계산
    balance = 50000000  # 초기 잔액
    for idx in df.index:
        balance += df.loc[idx, '입금'] - df.loc[idx, '출금']
        df.loc[idx, '잔액'] = balance
    
    return df

def create_sample_classification_rules():
    """샘플 분류 규칙 생성"""
    return {
        "매출": {
            "세글계산서(매출)": ["세글계산서"],
            "1301임대료": ["1301임대", "1301"],
            "SK클센터": ["SK클", "SK센터"],
            "프레피스에이": ["프레피스에이", "프레피스A"],
            "개발운영": ["개발운영", "시스템운영"]
        },
        "판관비": {
            "세금계산서(매출)": ["세금계산서(매출)"],
            "프레피스 직원 인건비": ["직원 인건비", "인건비"],
            "기관직원 입금": ["기관직원"],
            "기반차량리스": ["기반차량"],
            "대표님차량리스": ["대표님차량"],
            "문자서비스": ["문자서비스"],
            "법인카드": ["법인카드"]
        },
        "기타비용": {
            "세금": ["세금", "부가세"],
            "추억금": ["추억금"]
        },
        "투자": {
            "예금": ["정기예금", "적금"]
        },
        "중복방지": []
    }

if __name__ == "__main__":
    # 샘플 데이터 생성
    print("샘플 데이터 생성 중...")
    
    # workspaces 폴더 생성
    os.makedirs("workspaces/2026/01", exist_ok=True)
    
    # 샘플 거래내역 저장
    df = create_sample_data()
    df.to_excel("workspaces/2026/01/샘플_계좌거래내역_2026_01.xlsx", index=False)
    print("✅ 샘플 거래내역 생성 완료: workspaces/2026/01/샘플_계좌거래내역_2026_01.xlsx")
    
    # 분류 규칙 저장
    import json
    rules = create_sample_classification_rules()
    with open("workspaces/classification_rules.json", "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=4)
    print("✅ 분류 규칙 생성 완료: workspaces/classification_rules.json")
    
    print("\n🎉 샘플 데이터 생성 완료!")
    print("이제 streamlit run main.py 로 앱을 실행할 수 있습니다.")
