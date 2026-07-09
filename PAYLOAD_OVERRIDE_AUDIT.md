# PAYLOAD_OVERRIDE_AUDIT

## 1. 요약
- flat_overrides 전체 개수: 227
- API_DATA 개수: 71
- AI_TEXT 개수: 90
- STATIC_TEXT 개수: 63
- REVIEW 개수: 3

## 2. 분류표

| Key | 현재 값 요약 | 분류 | 이유 | 향후 처리 |
|---|---|---|---|---|
| ANATOMY_KEYLINE | 헤드라인 좋고 세부도 좋아야 진짜다. 이번엔 둘 다 같은 방향 — 발표 직후 반응이 뒤집힐 위험은 낮다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| BREADTH_ADVANCERS | 69% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| BREADTH_ADVANCERS_LABEL | 상승 종목 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| BREADTH_HIGHS | 311 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| BREADTH_HIGHS_LABEL | 52주 신고가 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| BREADTH_LOWS | 24 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| BREADTH_LOWS_LABEL | 52주 신저가 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| BREADTH_SUMMARY | 소수 대형주가 아니라 시장 전체가 오른 날 — 랠리의 질은 양호 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_1_NOTE | 물가 둔화 재확인 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_1_STAGE | 지표 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CHAIN_1_TITLE | CPI 2.6%, 예상 −0.2%p 하회 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_2_NOTE | FedWatch, 발표 30분 내 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_2_STAGE | 금리 기대 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CHAIN_2_TITLE | 9월 인하 확률 68% → 84% | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_3_NOTE | 정책 기대에 민감한 단기물이 먼저 반응 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_3_STAGE | 채권·달러 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CHAIN_3_TITLE | 2년물 −11bp · 10년물 −9bp · 달러 −0.7% | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_4_NOTE | 금리↓ = 미래 이익의 현재가치↑ | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_4_STAGE | 할인율 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CHAIN_4_TITLE | 성장주 밸류에이션 부담 완화 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_5_NOTE | 금리에 눌려있던 중소형주가 가장 크게 반등 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_5_STAGE | 주식·코인 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CHAIN_5_TITLE | 나스닥 +1.1% · 러셀2000 +1.6% · BTC +2.4% | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHAIN_KEYLINE | 발표 → 주가 사이엔 5개의 연결고리가 있다. 이번엔 다섯 개가 전부 교과서대로 작동했다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| CHECKPOINT_1_DATE | 7/16 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_1_IMPORTANCE | ★★★☆☆ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_1_TEXT | 6월 PPI — 근원 상회 시 오늘 해석 약화 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_2_DATE | 7/17 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_2_IMPORTANCE | ★★★★☆ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_2_TEXT | 소매판매 + 옵션만기 — 강세/약세 갈림길 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_3_DATE | 7/21 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_3_IMPORTANCE | ★★★☆☆ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_3_TEXT | 20년물 입찰 — 수요 부진 시 금리 반등 리스크 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_4_DATE | 7/25 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_4_IMPORTANCE | ★★★★★ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_4_TEXT | 6월 PCE — 연준 선호 지표, 인하 확정력 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_5_DATE | 7/29 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_5_IMPORTANCE | ★★★★★ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| CHECKPOINT_5_TEXT | FOMC — "인플레 진전" 문구 변화 주시 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 calendar/checkpoints로 이동 |
| COMPONENT_1_DIRECTION | ▼ 3개월 연속 둔화 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_1_NAME | 주거 (집세·월세) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| COMPONENT_1_PREVIOUS | (전월 +0.35%) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_1_SHARE | CPI의 36% · 최대 항목 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_1_VALUE | +0.22% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_1_VERDICT | 우호 · 뚜렷한 둔화 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_2_DIRECTION | ▼ 둔화 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_2_NAME | 근원 서비스 (주거 제외) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| COMPONENT_2_PREVIOUS | (전월 +0.31%) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_2_SHARE | 일명 "슈퍼코어" | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_2_VALUE | +0.18% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_2_VERDICT | 우호 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_3_DIRECTION | ▼ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_3_NAME | 근원 CPI (에너지·식품 제외) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| COMPONENT_3_PREVIOUS | (예상 3.0% · 전월 3.1%) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_3_SHARE | 연준의 기준 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_3_VERDICT | 우호 · 예상 하회 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_4_DIRECTION | ▼ | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_4_NAME | 상품 (중고차 등) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| COMPONENT_4_PREVIOUS | (하락 지속) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_4_SHARE | 19% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_4_VALUE | −0.6% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_4_VERDICT | 우호 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_5_DIRECTION | ▲ 소폭 상승 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_5_NAME | 식품 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| COMPONENT_5_PREVIOUS | (전월 +0.2%) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_5_SHARE | 13% · 체감물가 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_5_VALUE | +0.3% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_5_VERDICT | 소폭 비우호 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_LEGEND_NOTE | 주거 하나가 3분의 1 — 그래서 주거가 안 꺾이면 CPI는 못 내려온다 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| COMPONENT_STACK_1 | 주거 36% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_STACK_2 | 서비스 25% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_STACK_3 | 상품 19% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_STACK_4 | 식품 13% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| COMPONENT_STACK_5 | 7% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.components로 이동 |
| CONFIDENCE_TITLE | 왜 72점이고 신뢰도는 "보통"인가 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONF_1_LABEL | 지표–시장반응 일치도 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONF_2_LABEL | 유동성 뒷받침 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONF_3_LABEL | 포지셔닝 여유 (롱 과밀) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONF_4_LABEL | 정책 확인 대기 (PCE·FOMC 전) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONF_5_LABEL | 데이터 완결성 (감마 등 미제공 2건) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CONTRARIAN_BOLD_1 | 2년물이 11bp 급락하며 할인율이 순간적으로 낮아진 것 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_BOLD_2 | 금리에 빌린 랠리 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_BOLD_3 | 2년물 3.81%의 유지 여부 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_EASY_TEXT | 오늘 주가는 "물가 뉴스"가 아니라 "금리가 내려갔다는 사실"에 반응해 오른 것이다. 뉴스(CPI)는 한 번 나오고 끝나지만 금… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_MIDDLE | 이다. 즉 이 랠리는 물가가 아니라 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_PREFIX | 대부분은 "CPI가 낮아졌으니 강세"로 읽는다. 하지만 오늘 랠리의 진짜 엔진은 CPI 숫자가 아니라 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_SUFFIX | 다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CONTRARIAN_SUFFIX_PREFIX | 다. 이틀 뒤 PPI가 예상을 웃돌아 2년물이 되돌아가면, CPI 호재는 그대로인데 주가만 반납하는 그림이 나온다. 봐야 할 것… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.contrarian_view로 이동 |
| CURRENT_BAND_TEXT_BOLD | 분할·조건 확인 후 진입이 어울리는 구간 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CURRENT_BAND_TEXT_PREFIX | 방향은 위쪽 우위. 단 한 번에 올라타기보다 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CURRENT_BAND_TEXT_SUFFIX | 특히 지금처럼 포지셔닝 과열 동반 시 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| CURRENT_BAND_TITLE | 강세 우위 (현재 68) | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| DASHBOARD_KEYLINE | 유동성과 시장 폭은 건강한데, 포지셔닝만 과열 — "체력은 좋은데 이미 많이 뛴 몸". | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| DELTA_LABEL | 판단의 변화: | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| DELTA_REASON_BOLD | 2주 전엔 "지켜보자"였다면, 오늘부터는 "긍정 쪽으로 기울었다"로 판단이 이동 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| DELTA_REASON_LINE | 움직인 이유: 인플레 둔화 확인(+10) · 유동성 8주 최고(+6) · 포지셔닝 과열 심화(−2) | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| DELTA_REASON_SUFFIX | 했다는 뜻. 점수 자체보다 이 방향 전환이 더 중요한 정보다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| DISCLAIMER_BOLD | 샘플이며 모든 수치는 가상의 예시 데이터 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| DISCLAIMER_PREFIX | 본 페이지는 서비스 시안용 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| DISCLAIMER_SUFFIX | 입니다. 실제 서비스는 투자 조언이 아닌 시장 해석·학습 자료로 제공됩니다. 데이터 출처(실서비스 기준): BLS · FRED … | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| EASY_SUMMARY_BOLD_1 | 연준이 금리를 내릴 가능성이 커졌고, 금리가 내려가면 주식(특히 기술주)에 유리 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EASY_SUMMARY_BOLD_2 | 50(중립)보다 오를 쪽에 무게가 실리지만, 확신 구간(85+)은 아니라는 뜻 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EASY_SUMMARY_MIDDLE | 합니다. 다만 이미 많은 투자자가 주식을 사둔 상태라 "다들 좋은 줄 아는 호재"가 됐어요. 점수 72는 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EASY_SUMMARY_PREFIX | 물가가 식어서 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EASY_SUMMARY_SUFFIX | 입니다. ※ bp = 0.01%p. −11bp는 금리가 0.11%p 내렸다는 의미. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| ENERGY_LEGEND | 맨 오른쪽 7% = 에너지 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| EXPECTATION_24H | 2.9% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.expectations로 이동 |
| EXPECTATION_24H_LABEL | 24시간 전 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.expectations로 이동 |
| EXPECTATION_48H | 3.0% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event.expectations로 이동 |
| EXPECTATION_PATH_COMMENT | 기대가 이미 내려오는 중이었는데도 그보다 더 낮았다. 순수 서프라이즈는 유효하다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EXPECTATION_PATH_PREFIX | 시장 기대의 이동 경로: 48시간 전 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| EXPECTATION_SOURCE_LABEL | 기대치 출처: | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| EXPECTATION_SOURCE_TEXT | 이코노미스트 설문 컨센서스(블룸버그·로이터 집계) + 인플레이션 스왑 시장 가격. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| EXPECTATION_WHY_LABEL | 왜 내려왔나: | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| EXPECTATION_WHY_TEXT | 발표 전 주 유가 하락과 민간 임대료 지표(Zillow 등) 둔화가 확인되며 전문가들이 전망을 낮췄다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FED_KEYLINE | 지금 연준의 눈은 물가보다 고용에 45% 쏠려 있다. 이번 CPI는 "인하해도 된다"는 안전판을 깔아준 것. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FED_WEIGHT_1_NAME | 고용 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| FED_WEIGHT_1_VALUE | 45% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event 또는 market_data로 이동 |
| FED_WEIGHT_2_NAME | 물가 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| FED_WEIGHT_2_VALUE | 35% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event 또는 market_data로 이동 |
| FED_WEIGHT_3_NAME | 금융안정 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| FED_WEIGHT_3_VALUE | 20% | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 event 또는 market_data로 이동 |
| FED_WEIGHT_NOTE | 추정 근거: 6월 FOMC 성명서가 "인플레 진전"에서 "고용 하방 리스크"로 무게를 옮겼고, 최근 위원 발언 5건 중 4건이 … | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FLOW_EASY_TEXT | 기관의 질문은 "오를까?"가 아니라 "어디가 아직 싸게 남았고, 남들이 덜 샀나?"다. 대형 기술주는 좋아도 이미 만원 버스라,… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_1_NAME | 장기 국채 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_1_NOTE | 인하 사이클 초입의 전형적 매수처 — 금리가 내리면 채권 가격은 오른다 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_2_NAME | 중소형주 (러셀2000) | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_2_NOTE | 빚(변동금리) 부담이 큰 기업들이라 금리 인하의 직접 수혜 + 아직 포지션이 가볍다 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_3_NAME | 금 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_IN_3_NOTE | 실질금리 하락 + 달러 약세의 동시 수혜 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_KEYLINE | 기관은 "좋다/나쁘다"가 아니라 "어디가 아직 덜 샀나"로 움직인다. 유인이 커진 방향: 장기채 + 중소형주. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_OUT_1_NAME | 현금·MMF | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_OUT_1_NOTE | 금리 인하가 시작되면 예금·단기채 이자 매력이 줄어든다 — 6조 달러 MMF 자금의 이동 압력 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_OUT_2_NAME | 대형 기술주 (추가 매수 관점) | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FLOW_OUT_2_NOTE | 이미 포지션 백분위 78% — 나빠서가 아니라 "더 살 여력"이 작아서 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 assets/flows로 이동 |
| FOCUS_1_NAME | 금리 · 연준 피벗 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_focus로 이동 |
| FOCUS_1_NOTE | 이번 CPI가 정확히 여기에 꽂힘 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FOCUS_2_NAME | AI 실적 · CAPEX | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_focus로 이동 |
| FOCUS_2_NOTE | 다음 주 빅테크 실적 개막 — 실적 시즌엔 1순위로 교체될 수 있음 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FOCUS_3_NAME | 재정적자 · 국채 수급 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_focus로 이동 |
| FOCUS_3_NOTE | 7/21 20년물 입찰 대기 — 부진 시 순위 급등 주의 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FOCUS_4_NAME | 지정학 리스크 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_focus로 이동 |
| FOCUS_4_NOTE | 유가 안정으로 후순위 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| FUTURES_POSITIONING | 74% | REVIEW | 키 이름만으로 API/AI/고정문구 경계를 확정하기 어려워 사람 검토가 필요함. | 사람이 검토 필요 |
| LESSON_FORMULA | 재료의 힘 = 서프라이즈 크기 × (1 − 선반영 비율) × 포지셔닝 여유. | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| LESSON_TEXT | 서프라이즈가 커도(z −1.8) 부분 선반영과 롱 쏠림이 곱해지면 실제 연료는 절반으로 준다. 숫자만 보지 말고 이 세 항을 곱… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| LIQUIDITY_LABEL | 유동성 점수 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| LIQUIDITY_SCORE | 82 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| LIQUIDITY_STATUS | ↑↑ 최근 8주 최고 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| MARKET_FOCUS_KEYLINE | 시장의 1순위 관심사가 "금리"였기 때문에 이번 CPI에 크게 반응했다. 관심사가 다른 곳에 있었다면 같은 숫자에도 조용했을 것. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| MYTH_1_ANSWER_BOLD | 발표 다음 날이 단기 고점 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_1_ANSWER_PREFIX | 부분 선반영 + 롱 쏠림 상태의 호재는 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_1_ANSWER_SUFFIX | 이 된 사례가 유사 7건 중 4건. 재료의 힘은 이미 절반 소비됐다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_1_CASE | 2024년 7월 CPI가 예상을 하회했을 때, 나스닥은 호재에도 당일 −2% 가까이 하락했다 — 이미 대형 기술주에 쏠려 있던 … | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_1_QUESTION | "CPI가 좋았으니 내일 사도 늦지 않다" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_2_ANSWER_BOLD | 왜 내리는지 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_2_ANSWER_PREFIX | 금리가 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_2_ANSWER_SUFFIX | 가 중요하다. 물가 둔화 때문이면 호재, 경기 침체 때문이면 악재. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_2_CASE | 같은 "인하 시작"인데 결과는 정반대였다 — 1995년과 2019년의 보험성 인하(경기가 버티는데 미리 내림) 뒤엔 강한 랠리가… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_2_QUESTION | "금리 내리면 무조건 주가는 오른다" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_3_ANSWER_BOLD | 방향과 기대 대비 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_3_ANSWER_PREFIX | 시장은 수준이 아니라 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_3_ANSWER_SUFFIX | 를 산다. 2.9%도 예상(3.0%)을 밑돌았고 3개월 연속 둔화 — 시장에겐 충분한 진전이다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_3_CASE | 2023년 내내 근원 CPI는 4~5%대로 목표(2%)의 두 배가 넘었지만, "정점을 지나 내려온다"는 방향이 확인되자 나스닥은… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| MYTH_3_QUESTION | "근원 CPI 2.9%면 아직 높은 거 아닌가" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.myths로 이동 |
| NET_LIQUIDITY_NOTE | ▲ 26주 중 최고 · 최근 8주 가속 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| NET_LIQUIDITY_VALUE | $6.27T | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| OPTION_OPTIMISM | 68% | REVIEW | 키 이름만으로 API/AI/고정문구 경계를 확정하기 어려워 사람 검토가 필요함. | 사람이 검토 필요 |
| POSITIONING_1_LABEL | 선물 투기포지션 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| POSITIONING_2_LABEL | 옵션 낙관도 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| POSITIONING_3_LABEL | 개인 낙관도 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| POSITIONING_TITLE | 포지셔닝 — 얼마나 쏠렸나 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| POSITION_1_TEXT_BOLD | "어디서 틀렸다고 인정할까" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_1_TEXT_PREFIX | 질문은 "더 살까"가 아니라 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_1_TEXT_SUFFIX | 다. 2년물 3.81% 상향 이탈, S&P500 발표일 종가 하회 — 이 두 개가 이 리포트 기준의 무효화 라인. 수익 중이라면… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_1_TITLE | 이미 보유 중이라면 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_2_TEXT_BOLD | "약세 시나리오(20%)의 되돌림이 오면 나는 살 수 있는 계획이 있는가?" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_2_TEXT_PREFIX | 롱 과밀 국면의 추격 진입은 유사 사례에서 승률이 낮았다. 질문: | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_2_TEXT_SUFFIX | 진입 트리거를 가격이 아니라 조건(2년물 유지 + 되돌림 −2% 이내)으로 미리 적어둘 것. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_2_TITLE | 현금 비중이 크다면 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_3_TEXT_BOLD | 확인 후 진입은 약세 시나리오 하나를 통째로 소거 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_3_TEXT_PREFIX | 오늘 밤 갭에 올라타는 것과 7/16 PPI 확인 후 들어가는 것의 차이는 하루지만, | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_3_TEXT_SUFFIX | 한다. 급할 이유가 있는지 자문할 것. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_3_TITLE | 신규 진입을 고민 중이라면 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_4_TEXT_BOLD_1 | 미장 주가에는 호재지만 원화 환산 수익률은 깎는 방향 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_4_TEXT_BOLD_2 | "내 미장 계좌는 환노출인가, 환헤지인가?" | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_4_TEXT_MIDDLE | 이다. 달러 약세 국면의 미장 수익은 환차손이 일부 상쇄한다 — 지수 +1.1%여도 원화로는 +0.4%일 수 있다. 반대로 원화… | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_4_TEXT_PREFIX | 이번 재료(달러 −0.7%)는 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_4_TITLE | 한국 투자자라면 — 환율 한 겹 더 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| POSITION_GUIDE_KEYLINE | 같은 리포트라도 지금 내 포지션이 무엇이냐에 따라 해야 할 질문이 다르다. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis.position_guides로 이동 |
| REINTERPRETATION_RISK | ✓ 재해석 리스크: 낮음 — 헤드라인·근원·주거·슈퍼코어가 모두 같은 방향 | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| RETAIL_OPTIMISM | 61% | REVIEW | 키 이름만으로 API/AI/고정문구 경계를 확정하기 어려워 사람 검토가 필요함. | 사람이 검토 필요 |
| RISKS_KEYLINE | 맞을 이유보다 틀릴 이유가 중요하다. Bullish 72점을 무너뜨릴 수 있는 4가지. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 risks로 이동 |
| RRP_NOTE | ▼ 26주 최저 = 돈이 시장으로 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| RRP_VALUE | $2,620억 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| SECTION_10_TITLE | 개인이 여기서 착각하는 것 3가지 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_11_TITLE | 역사상 가장 비슷했던 순간 Top 5 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_12_TITLE | 앞으로 3가지 길 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_13_TITLE | 이 해석이 틀릴 수 있는 이유 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_14_TAG | 조언 아님 · 스스로에게 던질 질문 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_14_TITLE_PREFIX | 그래서 나는 — 상태별 점검 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_15_TITLE | 오늘 배울 원리 한 가지 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_16_TITLE | AI 예측 성적표 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_17_TITLE | 다음 체크포인트 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_1_TITLE | 30초 결론 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_2_TITLE | 지금 시장이 보고 있는 것 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_3_TITLE | 시장 체력 대시보드 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_4_TITLE | 지표 해부 — 헤드라인 뒤에 숨은 것 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_5_TITLE | CPI 하락이 어떻게 주가 상승이 됐나 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_6_TITLE | 자산별 반응과 이유 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_7_TITLE | 연준은 이걸 어떻게 볼까 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_8_TITLE | 기관은 어디로 움직일까 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| SECTION_9_TITLE | 시장이 놓치고 있는 핵심 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| STRIP_NOTE_BOLD | "이전" = 한 달 전에 발표된 5월 수치 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| STRIP_NOTE_PREFIX | 모두 전년동월비(1년 전 같은 달 대비 상승률). | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| STRIP_NOTE_SUFFIX | 예상과의 차이는 "놀라움", 이전과의 차이는 "추세"를 본다. 이번엔 둘 다 예상 하회 + 추세 하락 — 이중으로 우호적. | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TGA_NOTE | — 26주 중 45% 위치 · 완만 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| TGA_VALUE | $7,350억 | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 market_data로 이동 |
| TRACK_1_STATUS | 검증 대기 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_1_TEXT | 이번 콜 — 1일 후 S&P500 ↑ · 1주 후 10년물 ↓ | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_2_STATUS | 적중 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_2_TEXT | 7/2 고용보고서 — 1주 후 S&P500 ↑ | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_3_STATUS | 빗나감 · 국채입찰 부진 누락 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_3_TEXT | 6/25 PCE — 1일 후 10년물 ↓ | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_NOTE | 이번 콜이 틀린다면 가장 유력한 이유: 7/17 옵션만기 청산이 지표 방향을 일시적으로 덮는 경우. | AI_TEXT | 데이터를 해석해 문장으로 설명하거나 리포트별 판단을 서술하는 영역. | canonical의 analysis 또는 market_view로 이동 |
| TRACK_RATE_LABEL | 누적 적중률 | STATIC_TEXT | 섹션명, 라벨, UI 안내, 고지처럼 리포트마다 거의 고정되는 문구. | flat_overrides에 유지 또는 constants/static_text로 분리 |
| TRACK_RATE_VALUE | 1일 64% · 1주 58% (n=31) | API_DATA | 숫자, 일정, 시장 상태, 지표 구성, 성과처럼 외부 데이터 수집 또는 계산으로 채워질 가능성이 높음. | canonical의 prediction_track_record로 이동 |

## 3. API_DATA 후보

- BREADTH_ADVANCERS
- BREADTH_HIGHS
- BREADTH_LOWS
- CHECKPOINT_1_DATE
- CHECKPOINT_1_IMPORTANCE
- CHECKPOINT_1_TEXT
- CHECKPOINT_2_DATE
- CHECKPOINT_2_IMPORTANCE
- CHECKPOINT_2_TEXT
- CHECKPOINT_3_DATE
- CHECKPOINT_3_IMPORTANCE
- CHECKPOINT_3_TEXT
- CHECKPOINT_4_DATE
- CHECKPOINT_4_IMPORTANCE
- CHECKPOINT_4_TEXT
- CHECKPOINT_5_DATE
- CHECKPOINT_5_IMPORTANCE
- CHECKPOINT_5_TEXT
- COMPONENT_1_DIRECTION
- COMPONENT_1_PREVIOUS
- COMPONENT_1_SHARE
- COMPONENT_1_VALUE
- COMPONENT_1_VERDICT
- COMPONENT_2_DIRECTION
- COMPONENT_2_PREVIOUS
- COMPONENT_2_SHARE
- COMPONENT_2_VALUE
- COMPONENT_2_VERDICT
- COMPONENT_3_DIRECTION
- COMPONENT_3_PREVIOUS
- COMPONENT_3_SHARE
- COMPONENT_3_VERDICT
- COMPONENT_4_DIRECTION
- COMPONENT_4_PREVIOUS
- COMPONENT_4_SHARE
- COMPONENT_4_VALUE
- COMPONENT_4_VERDICT
- COMPONENT_5_DIRECTION
- COMPONENT_5_PREVIOUS
- COMPONENT_5_SHARE
- COMPONENT_5_VALUE
- COMPONENT_5_VERDICT
- COMPONENT_STACK_1
- COMPONENT_STACK_2
- COMPONENT_STACK_3
- COMPONENT_STACK_4
- COMPONENT_STACK_5
- EXPECTATION_24H
- EXPECTATION_24H_LABEL
- EXPECTATION_48H
- FED_WEIGHT_1_VALUE
- FED_WEIGHT_2_VALUE
- FED_WEIGHT_3_VALUE
- FOCUS_1_NAME
- FOCUS_2_NAME
- FOCUS_3_NAME
- FOCUS_4_NAME
- LIQUIDITY_LABEL
- LIQUIDITY_SCORE
- LIQUIDITY_STATUS
- NET_LIQUIDITY_NOTE
- NET_LIQUIDITY_VALUE
- POSITIONING_1_LABEL
- POSITIONING_2_LABEL
- POSITIONING_3_LABEL
- POSITIONING_TITLE
- RRP_NOTE
- RRP_VALUE
- TGA_NOTE
- TGA_VALUE
- TRACK_RATE_VALUE

## 4. AI_TEXT 후보

- ANATOMY_KEYLINE
- BREADTH_SUMMARY
- CHAIN_1_NOTE
- CHAIN_1_TITLE
- CHAIN_2_NOTE
- CHAIN_2_TITLE
- CHAIN_3_NOTE
- CHAIN_3_TITLE
- CHAIN_4_NOTE
- CHAIN_4_TITLE
- CHAIN_5_NOTE
- CHAIN_5_TITLE
- CHAIN_KEYLINE
- COMPONENT_LEGEND_NOTE
- CONTRARIAN_BOLD_1
- CONTRARIAN_BOLD_2
- CONTRARIAN_BOLD_3
- CONTRARIAN_EASY_TEXT
- CONTRARIAN_MIDDLE
- CONTRARIAN_PREFIX
- CONTRARIAN_SUFFIX
- CONTRARIAN_SUFFIX_PREFIX
- DASHBOARD_KEYLINE
- DELTA_REASON_BOLD
- DELTA_REASON_LINE
- DELTA_REASON_SUFFIX
- EASY_SUMMARY_BOLD_1
- EASY_SUMMARY_BOLD_2
- EASY_SUMMARY_MIDDLE
- EASY_SUMMARY_PREFIX
- EASY_SUMMARY_SUFFIX
- EXPECTATION_PATH_COMMENT
- EXPECTATION_SOURCE_TEXT
- EXPECTATION_WHY_TEXT
- FED_KEYLINE
- FED_WEIGHT_NOTE
- FLOW_EASY_TEXT
- FLOW_IN_1_NAME
- FLOW_IN_1_NOTE
- FLOW_IN_2_NAME
- FLOW_IN_2_NOTE
- FLOW_IN_3_NAME
- FLOW_IN_3_NOTE
- FLOW_KEYLINE
- FLOW_OUT_1_NAME
- FLOW_OUT_1_NOTE
- FLOW_OUT_2_NAME
- FLOW_OUT_2_NOTE
- FOCUS_1_NOTE
- FOCUS_2_NOTE
- FOCUS_3_NOTE
- FOCUS_4_NOTE
- LESSON_TEXT
- MARKET_FOCUS_KEYLINE
- MYTH_1_ANSWER_BOLD
- MYTH_1_ANSWER_PREFIX
- MYTH_1_ANSWER_SUFFIX
- MYTH_1_CASE
- MYTH_1_QUESTION
- MYTH_2_ANSWER_BOLD
- MYTH_2_ANSWER_PREFIX
- MYTH_2_ANSWER_SUFFIX
- MYTH_2_CASE
- MYTH_2_QUESTION
- MYTH_3_ANSWER_BOLD
- MYTH_3_ANSWER_PREFIX
- MYTH_3_ANSWER_SUFFIX
- MYTH_3_CASE
- MYTH_3_QUESTION
- POSITION_1_TEXT_BOLD
- POSITION_1_TEXT_PREFIX
- POSITION_1_TEXT_SUFFIX
- POSITION_1_TITLE
- POSITION_2_TEXT_BOLD
- POSITION_2_TEXT_PREFIX
- POSITION_2_TEXT_SUFFIX
- POSITION_2_TITLE
- POSITION_3_TEXT_BOLD
- POSITION_3_TEXT_PREFIX
- POSITION_3_TEXT_SUFFIX
- POSITION_3_TITLE
- POSITION_4_TEXT_BOLD_1
- POSITION_4_TEXT_BOLD_2
- POSITION_4_TEXT_MIDDLE
- POSITION_4_TEXT_PREFIX
- POSITION_4_TITLE
- POSITION_GUIDE_KEYLINE
- REINTERPRETATION_RISK
- RISKS_KEYLINE
- TRACK_NOTE

## 5. STATIC_TEXT 후보

- BREADTH_ADVANCERS_LABEL
- BREADTH_HIGHS_LABEL
- BREADTH_LOWS_LABEL
- CHAIN_1_STAGE
- CHAIN_2_STAGE
- CHAIN_3_STAGE
- CHAIN_4_STAGE
- CHAIN_5_STAGE
- COMPONENT_1_NAME
- COMPONENT_2_NAME
- COMPONENT_3_NAME
- COMPONENT_4_NAME
- COMPONENT_5_NAME
- CONFIDENCE_TITLE
- CONF_1_LABEL
- CONF_2_LABEL
- CONF_3_LABEL
- CONF_4_LABEL
- CONF_5_LABEL
- CURRENT_BAND_TEXT_BOLD
- CURRENT_BAND_TEXT_PREFIX
- CURRENT_BAND_TEXT_SUFFIX
- CURRENT_BAND_TITLE
- DELTA_LABEL
- DISCLAIMER_BOLD
- DISCLAIMER_PREFIX
- DISCLAIMER_SUFFIX
- ENERGY_LEGEND
- EXPECTATION_PATH_PREFIX
- EXPECTATION_SOURCE_LABEL
- EXPECTATION_WHY_LABEL
- FED_WEIGHT_1_NAME
- FED_WEIGHT_2_NAME
- FED_WEIGHT_3_NAME
- LESSON_FORMULA
- SECTION_10_TITLE
- SECTION_11_TITLE
- SECTION_12_TITLE
- SECTION_13_TITLE
- SECTION_14_TAG
- SECTION_14_TITLE_PREFIX
- SECTION_15_TITLE
- SECTION_16_TITLE
- SECTION_17_TITLE
- SECTION_1_TITLE
- SECTION_2_TITLE
- SECTION_3_TITLE
- SECTION_4_TITLE
- SECTION_5_TITLE
- SECTION_6_TITLE
- SECTION_7_TITLE
- SECTION_8_TITLE
- SECTION_9_TITLE
- STRIP_NOTE_BOLD
- STRIP_NOTE_PREFIX
- STRIP_NOTE_SUFFIX
- TRACK_1_STATUS
- TRACK_1_TEXT
- TRACK_2_STATUS
- TRACK_2_TEXT
- TRACK_3_STATUS
- TRACK_3_TEXT
- TRACK_RATE_LABEL

## 6. REVIEW 후보

- FUTURES_POSITIONING
- OPTION_OPTIMISM
- RETAIL_OPTIMISM

## 7. 다음 단계 제안

3단계 실제 데이터 수집 전에 우선 canonical 구조로 옮겨야 할 키는 아래와 같다. 추천 기준은 실제 API 수집, 시장 데이터 계산, 또는 AI 자동 해석에 바로 연결되는 값이다.

1. BREADTH_ADVANCERS - canonical의 market_data.breadth로 이동
2. BREADTH_HIGHS - canonical의 market_data.breadth로 이동
3. BREADTH_LOWS - canonical의 market_data.breadth로 이동
4. NET_LIQUIDITY_VALUE - canonical의 market_data.liquidity로 이동
5. RRP_VALUE - canonical의 market_data.liquidity로 이동
6. TGA_VALUE - canonical의 market_data.liquidity로 이동
7. EXPECTATION_48H - canonical의 event.expectations로 이동
8. EXPECTATION_24H - canonical의 event.expectations로 이동
9. COMPONENT_1_VALUE - canonical의 event.components로 이동
10. COMPONENT_2_VALUE - canonical의 event.components로 이동
11. COMPONENT_4_VALUE - canonical의 event.components로 이동
12. COMPONENT_5_VALUE - canonical의 event.components로 이동
13. CHECKPOINT_1_DATE - canonical의 calendar/checkpoints로 이동
14. CHECKPOINT_1_TEXT - canonical의 calendar/checkpoints로 이동
15. CHECKPOINT_1_IMPORTANCE - canonical의 calendar/checkpoints로 이동
16. CHECKPOINT_2_DATE - canonical의 calendar/checkpoints로 이동
17. CHECKPOINT_2_TEXT - canonical의 calendar/checkpoints로 이동
18. BREADTH_SUMMARY - canonical의 analysis 또는 market_view로 이동
19. ANATOMY_KEYLINE - canonical의 analysis로 이동
20. MARKET_FOCUS_KEYLINE - canonical의 market_view로 이동
