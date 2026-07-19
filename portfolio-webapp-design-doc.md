# 주식/ETF 포트폴리오 관리 & 리서치 웹사이트 — 기술 설계 문서

> 작성 기준: React + VS Code 개발 환경 (Vue를 쓰더라도 상태 구조·데이터 흐름 개념은 동일하게 적용 가능)
> 최신 정보 반영: 2026년 7월 기준 금융 API 시장 현황 (IEX Cloud는 2024년 8월 서비스 종료, Yahoo Finance 공식 API는 비공식 상태라 불안정)

---

## 현재 구현 상태 (단일 HTML MVP)

현재 저장소의 `my-portfolio_5.html`은 설치나 서버 없이 브라우저에서 바로 실행되는 1차 버전입니다. 아래 기능은 실제로 구현되어 있습니다.

- 국내(KRW)·미국(USD) 자산 입력과 USD/KRW 환율 환산
- 계획/실제 보유 모드 분리와 통화·평단 이상치 검증
- 목표 투자금액, 평가금액, 손익, 목표·현재 비중 계산
- 추가 투자금, 매도 최소화, 허용오차, 수수료, 매매 단위를 반영한 스마트 리밸런싱
- 종목 추가·수정·삭제, 중복 티커 및 잘못된 숫자 검증
- 회사명·티커 검색, 주식 프로필·재무지표·실적/배당 일정 리서치
- FMP 선택 연동 ETF 구성종목·섹터·국가 비중과 포트폴리오 실질 노출 분석
- 자산배분 도넛 차트와 백테스트 라인 차트(외부 차트 라이브러리 없이 동작)
- Twelve Data 일별 종가 자동 조회, 최신 가격 갱신, 종목 간 공통 거래일 정렬
- 1·3·5·10년 조회 기간 강제 적용과 데이터 범위 검증
- 변동성, MDD, 누적수익률, CAGR, 베타, Sharpe, Sortino 계산
- 종목 간 상관관계 매트릭스와 최대 4개 종목 비교
- 종목별 투자 근거·위험·매도 조건·날짜별 일지
- 브라우저 자동 저장, JSON 백업·복원, CSV 내보내기
- 모바일 대응, 키보드 입력, 폼 라벨 등 기본 접근성

현재 단일 HTML 버전은 개인 사용을 전제로 사용자가 입력한 Twelve Data 키를 브라우저 저장소에만 보관하며, JSON 백업이나 GitHub 소스에는 키를 넣지 않습니다. 아래의 React + 백엔드 구조는 다중 사용자 서비스에서 키를 서버에 숨기고 시세·검색·뉴스·재무정보를 확장하기 위한 다음 단계 설계입니다.

## 0. 전체 아키텍처 개요

```
[Frontend: React]
   ├─ 상태관리(Zustand): 포트폴리오, 설정값
   ├─ 데이터 페칭(TanStack Query): API 캐싱/재시도
   ├─ 차트(Recharts + TradingView Lightweight Charts)
   └─ UI(Tailwind 등)
        │
        ▼  (API Key 노출 방지를 위해 프록시 경유 권장)
[Backend: Node/Express 경량 프록시] ← 선택사항이지만 강력 추천
   ├─ 외부 API 호출 대행 (키 숨김)
   ├─ 응답 캐싱 (같은 종목 반복 요청 방지 → 무료 티어 한도 절약)
   └─ 여러 API를 조합해 일관된 포맷으로 응답
        │
        ▼
[외부 금융 데이터 API]
```

**왜 백엔드 프록시가 필요한가?**
프론트엔드에서 API를 직접 호출하면 API 키가 브라우저 소스에 그대로 노출됩니다. 또한 무료 티어는 대부분 하루 500~800건 수준으로 제한적인데, 여러 사용자가 같은 종목을 조회할 때마다 API를 호출하면 금방 소진됩니다. 얇은 Express 서버 하나로 (1) 키를 숨기고 (2) 응답을 몇 분~몇 시간 캐싱하면 실사용 단계에서도 무료 티어로 버틸 수 있습니다. 지금 1인 개발 단계라면 최소 기능만 있는 프록시로 시작해도 충분합니다.

---

## 1. 추천 API 및 라이브러리

### 1.1 금융 데이터 API 비교

| API | 무료 티어 | 강점 | 약점 | 추천 용도 |
|---|---|---|---|---|
| **Twelve Data** | 800 req/일, 8 req/분 | 주식+ETF+forex+crypto, 문서 깔끔, 프론트엔드 친화적 JSON | 히스토리 깊이 제한 | **메인 시세/차트 데이터** |
| **Alpha Vantage** | 25 req/일 (매우 제한적) | 베타·변동성 등 fundamental 지표, 기술적 지표(SMA/RSI 등) 내장 | 호출 한도가 너무 낮아 실서비스엔 부적합 | 개발 초기 프로토타입, 지표 검증용 |
| **Financial Modeling Prep (FMP)** | 250 req/일 | 재무제표, 기업 개요, 배당 이력 풍부 | 무료 티어 히스토리 제한 | 종목 설명/펀더멘털 리서치 화면 |
| **Finnhub** | 60 req/분 | 호출 한도는 넉넉함 | 실시간 데이터 20분 지연, 히스토리 데이터 제한 | 뉴스/기업정보 보조용 |
| **Yahoo Finance (비공식)** | - | 데이터 범위 넓음 | 공식 API 아님, 스크래핑 기반이라 예고 없이 끊길 수 있음 | 프로토타입 단계 외 비권장 |

**국내 종목까지 다루신다면**: 한국투자증권 Open API(KIS Developers)가 실시간 시세·잔고 연동까지 가능해서 국내 주식/ETF를 다룰 때 가장 현실적인 선택입니다. 무료이고 계좌 연동 기반이라 인증 절차가 있지만, 국내 종목은 해외 API들이 거의 커버하지 못하기 때문에 국내 종목 계획이 있다면 이쪽을 별도 트랙으로 붙이는 걸 추천합니다.

**실전 조합 제안**: Twelve Data(시세/차트) + FMP(펀더멘털/기업 설명) + 자체 계산(베타·변동성·MDD는 API에 의존하지 말고 받아온 과거 가격으로 직접 계산 — 이렇게 하면 API마다 계산 방식이 달라 생기는 오차도 없고, 무료 티어에 있는 지표 전용 엔드포인트를 아낄 수 있습니다).

### 1.2 차트 라이브러리

| 라이브러리 | 용도 | 이유 |
|---|---|---|
| **TradingView Lightweight Charts** | 종목 상세 캔들스틱/라인 차트 | 무료, 매우 가볍고(45KB) 실제 트레이딩 뷰 수준의 완성도. 캔들스틱이 필요하면 사실상 최선의 선택 |
| **Recharts** | 도넛(자산배분), 백테스팅 누적수익률 라인 | React 선언적 컴포넌트 방식이라 상태와 자연스럽게 연동됨. 도넛차트 구현이 특히 쉬움 |
| **Chart.js + react-chartjs-2** | 범용 보조 차트 (막대, 비교 차트 등) | 커스터마이징 자유도가 높아 위 두 개로 안 되는 부분 보완 |

캔들스틱은 TradingView Lightweight Charts, 나머지(도넛·라인·막대)는 Recharts로 역할을 나누면 각 라이브러리의 강점만 쓰게 되어 관리가 편합니다.

### 1.3 상태관리 & 데이터 페칭

- **Zustand**: 포트폴리오 데이터처럼 여러 컴포넌트가 공유하는 상태를 다루기에 Redux보다 훨씬 가볍고 보일러플레이트가 적습니다. MVP~중규모 프로젝트에 적합.
- **TanStack Query (React Query)**: API 호출 결과를 자동 캐싱하고, 같은 종목을 여러 화면에서 조회해도 중복 호출을 막아줍니다. 무료 API 한도가 빠듯한 이 프로젝트에는 사실상 필수급으로 유용합니다.
- **Zod**: API 응답이나 사용자 입력값(비중 합계 100% 검증 등)의 유효성 검사에 사용하면 런타임 에러를 줄일 수 있습니다.

### 설치 방법

```bash
# 프론트엔드
npm install zustand @tanstack/react-query recharts lightweight-charts zod

# 백엔드(프록시 서버, 선택이지만 권장)
npm install express axios node-cache cors dotenv
```

---

## 2. 핵심 기능 설계 (State 구조 & 로직 흐름)

### 2.1 위험도 분석 (변동성·베타)

**핵심 수식**

```
일별 수익률:  r_t = (P_t - P_(t-1)) / P_(t-1)

연율화 변동성:  σ_annual = stdev(r_1, r_2, ..., r_n) × √252
  (252 = 미국 시장 연간 거래일 수. 국내는 약 245일 사용)

베타:  β = Cov(r_stock, r_market) / Var(r_market)
  (r_market은 보통 S&P500(SPY) 또는 QQQ 등 비교 지수의 수익률)
```

**로직 흐름**
1. 사용자가 종목 검색 → 백엔드 프록시에서 최근 1~3년치 일별 종가(OHLC) 조회
2. 프론트엔드에서 일별 수익률 배열 계산
3. 표준편차 → 연율화 변동성 계산
4. 비교 지수(SPY 등)의 동일 기간 수익률과 공분산 계산 → 베타 산출
5. 결과를 `riskMetrics` 상태에 저장하고, 게이지 차트나 색상 뱃지(저위험/중위험/고위험)로 시각화

**상태 구조 예시 (Zustand)**

```javascript
// store/riskStore.js
// 종목별 위험 지표를 캐싱하는 스토어
// 같은 종목을 다시 계산하지 않도록 symbol을 key로 저장
const useRiskStore = create((set) => ({
  riskMetrics: {}, // { [symbol]: { volatility, beta, updatedAt } }

  setRiskMetric: (symbol, metric) =>
    set((state) => ({
      riskMetrics: {
        ...state.riskMetrics,
        [symbol]: { ...metric, updatedAt: Date.now() },
      },
    })),
}));
```

### 2.2 포트폴리오 비중 입력

**로직 흐름**
1. 사용자가 종목을 추가하면 `holdings` 배열에 `{ symbol, targetWeight: 0 }` 추가
2. 슬라이더 또는 숫자 입력으로 비중 조정
3. **합계 100% 검증**: 실시간으로 합계를 계산해 100%를 초과/미달하면 경고 표시 (전량 100%를 강제하기보다 "잔여 현금 비중"을 자동 계산해 보여주는 방식이 UX상 자연스럽습니다)

```javascript
// store/portfolioStore.js
const usePortfolioStore = create((set, get) => ({
  holdings: [], // [{ symbol, name, targetWeight, currentShares, avgBuyPrice }]

  addHolding: (holding) =>
    set((state) => ({ holdings: [...state.holdings, holding] })),

  updateWeight: (symbol, weight) =>
    set((state) => ({
      holdings: state.holdings.map((h) =>
        h.symbol === symbol ? { ...h, targetWeight: weight } : h
      ),
    })),

  // 파생값: 합계 비중 (렌더링 시 계산해서 사용, 별도 상태로 두지 않는 것이 원칙)
  getTotalWeight: () =>
    get().holdings.reduce((sum, h) => sum + h.targetWeight, 0),
}));
```

> **왜 합계 비중을 별도 상태로 저장하지 않는가**: `holdings` 배열이 바뀔 때마다 합계도 같이 업데이트해줘야 하는데, 이걸 잊으면 값이 어긋나는 버그가 생깁니다. 합계처럼 다른 상태로부터 계산 가능한 값은 함수(selector)로 매번 계산하는 것이 안전합니다.

### 2.3 투자 금액 설정

**로직 흐름**
1. `totalInvestment` 상태에 총 투자금액 저장
2. 각 종목의 배분 금액 = `totalInvestment × (targetWeight / 100)`
3. 배분 금액 ÷ 현재가 = 매수 가능 수량(소수점 처리 여부는 ETF 소수점 매매 지원 여부에 따라 다름)

```javascript
// derived 값 — 별도 store가 아니라 컴포넌트나 selector에서 계산
function getAllocatedAmount(totalInvestment, targetWeight) {
  return totalInvestment * (targetWeight / 100);
}
```

### 2.4 리서치 & 차트 기능

**로직 흐름**
1. 검색창 입력 → debounce(300ms) 처리 후 종목 검색 API 호출 (매 키입력마다 호출하면 API 한도 순삭됩니다)
2. 종목 선택 시 TanStack Query로 `/api/stock/:symbol` 호출 → 백엔드가 캐시 확인 후 없으면 외부 API 호출
3. 응답 데이터를 기업 설명 카드 + 현재가 + TradingView Lightweight Charts로 렌더링
4. 기간 선택 탭(1개월/6개월/1년/5년)에 따라 재조회

```javascript
// hooks/useStockData.js
import { useQuery } from '@tanstack/react-query';

function useStockData(symbol, range = '1y') {
  return useQuery({
    queryKey: ['stock', symbol, range], // 캐시 키: 종목+기간별로 구분
    queryFn: () => fetch(`/api/stock/${symbol}?range=${range}`).then(r => r.json()),
    staleTime: 1000 * 60 * 15, // 15분간은 재요청하지 않음 (API 한도 절약)
    enabled: !!symbol, // symbol이 있을 때만 실행
  });
}
```

---

## 3. 추가 기능 설계 (공식 & UI 팁)

### 3.1 자산 배분 도넛 차트

Recharts의 `PieChart` + `innerRadius`를 주면 바로 도넛 형태가 됩니다.

```jsx
import { PieChart, Pie, Cell, Tooltip, Legend } from 'recharts';

function AllocationDonut({ holdings }) {
  const data = holdings.map(h => ({ name: h.symbol, value: h.targetWeight }));
  const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981'];

  return (
    <PieChart width={320} height={320}>
      <Pie
        data={data}
        dataKey="value"
        innerRadius={70}   // 이 값이 있어야 '도넛' 모양이 됨 (0이면 완전한 파이차트)
        outerRadius={120}
        paddingAngle={2}
      >
        {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
      </Pie>
      <Tooltip formatter={(v) => `${v}%`} />
      <Legend />
    </PieChart>
  );
}
```

**UI 팁**: 도넛 중앙에 총 투자금액을 텍스트로 겹쳐 보여주면(absolute positioning) 대시보드 느낌이 훨씬 살아납니다.

### 3.2 과거 데이터 백테스팅

**핵심 수식** (정규화 가격 지수 방식 — 리밸런싱 없이 매수 후 보유 가정 시 가장 단순)

```
각 종목 정규화 지수:  Index_i(t) = P_i(t) / P_i(0) × 100

포트폴리오 가치:  V(t) = Σ [ 초기투자금 × 비중_i × Index_i(t) / 100 ]

누적 수익률:  CumReturn(t) = (V(t) - V(0)) / V(0) × 100
```

**정기 리밸런싱을 가정한 백테스팅(더 정교한 버전)**은 매월/매분기 시작 시점마다 비중을 목표 비중으로 재조정한다고 가정하고 위 계산을 구간별로 반복 적용합니다. 처음에는 리밸런싱 없는 단순 buy-and-hold 버전으로 MVP를 만들고, 이후 옵션으로 "리밸런싱 주기"를 추가하는 순서를 추천합니다.

**로직 흐름**
1. 각 보유 종목의 과거 종가 시계열을 API로 조회 (기간 통일 필수 — 상장일이 다르면 짧은 쪽에 맞춤)
2. 종목별 정규화 지수 계산
3. 비중 가중합으로 포트폴리오 가치 시계열 산출
4. Recharts LineChart로 누적 수익률 곡선 표시

### 3.3 위험 지표(MDD) 제공

**핵심 수식**

```
Peak(t) = max(V(0), V(1), ..., V(t))   // t 시점까지의 역사적 최고점

Drawdown(t) = (V(t) - Peak(t)) / Peak(t)   // 항상 0 이하 값

MDD = min(Drawdown(0), Drawdown(1), ..., Drawdown(n))   // 가장 깊었던 낙폭
```

```javascript
// utils/calculateMDD.js
// values: 시간순으로 정렬된 포트폴리오 가치 배열
function calculateMDD(values) {
  let peak = values[0];
  let maxDrawdown = 0;

  for (const v of values) {
    if (v > peak) peak = v; // 신고점 갱신
    const drawdown = (v - peak) / peak; // 현재 낙폭 (음수)
    if (drawdown < maxDrawdown) maxDrawdown = drawdown; // 더 깊은 낙폭이면 갱신
  }

  return maxDrawdown * 100; // % 단위로 반환 (예: -28.4)
}
```

**UI 팁**: MDD는 숫자만 보여주기보다, 백테스팅 라인 차트 위에 가장 깊었던 낙폭 구간을 음영으로 표시하면 "이 정도까지 손실을 견딜 수 있는가"를 훨씬 직관적으로 전달합니다.

### 3.4 리밸런싱 계산기

**핵심 수식**

```
목표금액_i = 총평가금액 × 목표비중_i

현재금액_i = 현재보유수량_i × 현재가격_i

차이금액_i = 목표금액_i - 현재금액_i

필요매매수량_i = 차이금액_i / 현재가격_i
  → 양수면 매수, 음수면 매도
```

```javascript
// utils/calculateRebalance.js
function calculateRebalance(holdings) {
  // 1. 총평가금액 계산
  const totalValue = holdings.reduce(
    (sum, h) => sum + h.currentShares * h.currentPrice, 0
  );

  // 2. 종목별 매매 수량 계산
  return holdings.map((h) => {
    const targetAmount = totalValue * (h.targetWeight / 100);
    const currentAmount = h.currentShares * h.currentPrice;
    const diffAmount = targetAmount - currentAmount;
    const diffShares = diffAmount / h.currentPrice;

    return {
      symbol: h.symbol,
      action: diffShares > 0 ? 'BUY' : 'SELL',
      shares: Math.abs(Math.round(diffShares * 100) / 100), // 소수점 2자리
      amount: Math.abs(Math.round(diffAmount)),
    };
  });
}
```

**UI 팁**: 매수/매도를 색상(빨강/파랑 또는 초록)으로 구분한 테이블로 보여주고, "적용" 버튼을 누르면 `currentShares`를 자동 업데이트하도록 하면 실제로 리밸런싱을 실행한 것처럼 상태가 반영되어 사용성이 좋아집니다.

---

## 4. 개발 로드맵 (MVP 기준)

| 단계 | 목표 | 주요 작업 |
|---|---|---|
| **Phase 1** | 리서치 화면 뼈대 | 종목 검색 → 백엔드 프록시 → 현재가 + 라인차트 표시. API 캐싱 구조부터 잡기 |
| **Phase 2** | 포트폴리오 입력 | holdings 상태 설계, 비중 입력 UI, 투자금액 설정, 도넛 차트 연결 |
| **Phase 3** | 위험도 분석 | 변동성·베타 계산 로직, 게이지/뱃지 UI |
| **Phase 4** | 백테스팅 엔진 | 정규화 지수 계산, 누적수익률 라인차트, MDD 계산 및 표시 |
| **Phase 5** | 리밸런싱 계산기 | 매매 수량 계산, 매수/매도 테이블 UI, 적용 시 상태 반영 |
| **Phase 6** | 완성도 작업 | 로딩/에러 상태 처리, 반응형 UI, localStorage 대체용 백엔드 저장(DB) 연동, 배포 |

**팁**: Phase 1에서 백엔드 프록시 + 캐싱 구조를 먼저 잡아두면 이후 모든 단계에서 API 한도 걱정 없이 개발할 수 있습니다. 반대로 이 부분을 나중으로 미루면 Phase 4(백테스팅)에서 대량의 과거 데이터를 반복 조회하다가 무료 티어 한도를 순식간에 소진하게 됩니다.

---

## 5. 데이터 구조 (JSON) 예시

```json
{
  "portfolio": {
    "id": "portfolio-001",
    "totalInvestment": 10000000,
    "baseCurrency": "KRW",
    "createdAt": "2026-07-18T00:00:00Z",
    "holdings": [
      {
        "symbol": "QQQM",
        "name": "Invesco NASDAQ 100 ETF",
        "assetClass": "ETF",
        "targetWeight": 40,
        "currentShares": 12,
        "avgBuyPrice": 185.32
      },
      {
        "symbol": "SOXQ",
        "name": "Invesco PHLX Semiconductor ETF",
        "assetClass": "ETF",
        "targetWeight": 25,
        "currentShares": 30,
        "avgBuyPrice": 42.10
      },
      {
        "symbol": "CASH",
        "name": "현금성 자산",
        "assetClass": "CASH",
        "targetWeight": 35,
        "currentShares": null,
        "avgBuyPrice": null
      }
    ]
  },

  "marketData": {
    "QQQM": {
      "currentPrice": 198.45,
      "dailyChangePercent": 1.23,
      "updatedAt": "2026-07-18T05:00:00Z",
      "historicalPrices": [
        { "date": "2026-07-17", "open": 196.1, "high": 199.0, "low": 195.8, "close": 198.45, "volume": 3120000 }
      ],
      "riskMetrics": {
        "volatilityAnnualized": 22.4,
        "beta": 1.15,
        "calculatedAt": "2026-07-18T05:00:00Z"
      }
    }
  },

  "backtestResult": {
    "startDate": "2021-07-18",
    "endDate": "2026-07-18",
    "initialInvestment": 10000000,
    "cumulativeReturnSeries": [
      { "date": "2021-07-18", "value": 10000000, "cumulativeReturnPct": 0 },
      { "date": "2026-07-18", "value": 19850000, "cumulativeReturnPct": 98.5 }
    ],
    "mddPercent": -28.4,
    "cagrPercent": 14.7
  },

  "rebalanceResult": [
    { "symbol": "QQQM", "action": "SELL", "shares": 1.5, "amount": 297675 },
    { "symbol": "SOXQ", "action": "BUY", "shares": 8.2, "amount": 345220 }
  ]
}
```

**설계 이유**
- `holdings`와 `marketData`를 분리한 이유: 포트폴리오 구성(비중, 보유수량)은 사용자가 자주 바꾸는 값이고, 시세 데이터는 API에서 받아와 캐싱하는 값이라 갱신 주기가 다릅니다. 두 관심사를 분리해두면 나중에 marketData만 별도로 캐시 무효화하기 쉽습니다.
- `CASH`를 `assetClass: "CASH"`로 별도 취급: 현금성 자산은 currentShares/avgBuyPrice가 무의미하므로 null로 명시해 다른 로직에서 이 필드를 실수로 참조하지 않도록 방지합니다.

---

## 요약

1. **API**: Twelve Data(시세) + FMP(펀더멘털) 조합 + 백엔드 프록시로 캐싱 — 무료 티어로도 실서비스 초입까지 버틸 수 있는 구조
2. **차트**: 캔들스틱은 TradingView Lightweight Charts, 나머지는 Recharts
3. **상태관리**: Zustand(전역 상태) + TanStack Query(서버 데이터 캐싱) 조합이 이 규모의 프로젝트에 가장 적합
4. **위험 지표(변동성/베타/MDD)는 API가 제공하는 값에 의존하지 말고 원본 가격 데이터로 직접 계산** — 일관성 확보 + API 호출 절약

이 문서를 프로젝트 루트에 `docs/design.md`로 두고 개발하시면서 참고하시면 좋을 것 같습니다.
