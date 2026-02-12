# 💰 Prepisco Korea 재무관리 시스템

## 📊 개요

Streamlit 기반의 종합 업무 관리 시스템으로, 재무 자동화부터 프로젝트 관리까지 통합 솔루션을 제공합니다.

## ✨ 주요 기능

### 1. 재무 관리
- 📈 계좌 거래내역 자동 파싱 (엑셀/HTML)
- 🤖 매출/지출 자동 분류
- 📊 월간 결산 대시보드
- 📄 엑셀/PDF 보고서 자동 생성
- 🔒 월별 마감 및 데이터 보호

### 2. 계약 관리
- 📝 계약서 등록 및 추적
- 💰 수납 현황 관리
- ⏰ 계약 만료 알림

### 3. 프로젝트 관리 (PMS)
- 📋 칸반 보드 (대기/진행중/완료)
- 📊 진행률 트래킹
- 🔗 계약 연동

### 4. 인사 관리
- 👥 직원 명부 (개발 예정)
- 💼 급여 관리 (개발 예정)

## 🚀 로컬 실행 방법

```bash
# 의존성 설치
pip install -r requirements.txt

# 앱 실행
streamlit run main.py
```

## 📂 프로젝트 구조

```
.
├── main.py                 # 메인 대시보드
├── file_engine.py          # 데이터 파싱 엔진
├── report_generator.py     # PDF 보고서 생성
├── excel_report.py         # 엑셀 보고서 생성
├── pages/
│   ├── 01_Finance.py      # 재무 관리
│   ├── 02_Contracts.py    # 계약 관리
│   ├── 04_HR.py           # 인사 관리
│   └── 05_PMS.py          # 프로젝트 관리
└── workspaces/            # 데이터 저장소 (gitignore)
```

## 🔧 기술 스택

- **Frontend**: Streamlit
- **Data Processing**: Pandas, OpenPyXL
- **Visualization**: Altair
- **Report Generation**: ReportLab

## 📝 라이선스

Private - Prepisco Korea

## 👤 개발자

마채현 (realkoul@prephis.co.kr)

## 📅 버전

- v1.0.0 (2026-02-12): 초기 릴리즈
  - 재무 관리 기능 완성
  - 계약 관리 기능 추가
  - 프로젝트 관리 칸반보드 구현
