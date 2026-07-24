#!/usr/bin/env node
/**
 * runtime_smoke_test.mjs
 * -----------------------------------------------------------------------
 * validate_app.mjs는 "문법이 맞는지 / 필수 요소가 있는지"만 확인하는 정적 검사입니다.
 * 이 스크립트는 실제 브라우저 없이 jsdom으로 my-portfolio_5.html을 그대로 구동시켜,
 * 사람이 앱을 눌러보는 것과 비슷하게 핵심 기능을 실행해보고 런타임 오류(정의되지
 * 않은 함수, 예외 발생 등)가 없는지 확인하는 회귀 테스트입니다.
 *
 * 실행: node scripts/runtime_smoke_test.mjs
 * 필요: npm install jsdom (devDependency로 관리하지 않으며, 없으면 먼저 설치해야 합니다)
 *
 * 구현 메모(중요): 앱의 최상위 let/const 전역 상태(marketCatalog, holdings, searchIndex 등)는
 * "간접 eval" 호출마다 독립된 전역 렉시컬 스코프를 가지므로, window.eval()을 여러 번 나눠
 * 부르면 이전 호출에서 선언된 let/const를 다음 호출에서 찾을 수 없습니다(ReferenceError).
 * 그래서 앱 스크립트 원문 뒤에 테스트 시나리오 전체를 이어붙여 "단 한 번의 eval 호출"로
 * 실행하고, 결과만 window.__TEST_RESULTS__ / window.__TEST_DONE__ 같은 실제 객체 프로퍼티에
 * 기록해 Node 쪽에서 폴링합니다(객체 프로퍼티는 eval 호출과 무관하게 항상 공유됩니다).
 *
 * 실제 네트워크(무료 시세 API 등)는 절대 호출하지 않고, data/ 폴더의 저장된 캐시 파일만
 * 읽어서 fetch()를 흉내 냅니다. Firebase 로그인처럼 외부 스크립트가 필요한 기능은 버튼
 * 클릭 전까지 로드되지 않으므로 이 테스트 범위에서는 다루지 않습니다.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const HTML_PATH = path.join(ROOT, 'my-portfolio_5.html');

function readLocalDataFile(pathname){
  const rel = pathname.replace(/^\//, '');
  const full = path.join(ROOT, rel);
  if(!full.startsWith(ROOT)) return null;
  if(!fs.existsSync(full)) return null;
  return fs.readFileSync(full, 'utf8');
}

// ---- 페이지 안에서 실행될 테스트 시나리오(문자열) ----
// pass()/fail()은 window.__TEST_RESULTS__ 배열에 결과를 기록한다.
const IN_PAGE_TEST_SCRIPT = `
(async () => {
  window.__TEST_RESULTS__ = [];
  const pass = (label) => window.__TEST_RESULTS__.push({ok:true, label});
  const fail = (label, error) => window.__TEST_RESULTS__.push({ok:false, label, error: (error && error.stack) || String(error)});
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, {timeout=4000, interval=50, label=''}={}) => {
    const start = Date.now();
    while(Date.now()-start < timeout){
      try{ if(await fn()) return true; }catch(e){ /* 준비 전이면 재시도 */ }
      await sleep(interval);
    }
    throw new Error('waitFor 시간 초과: ' + label);
  };
  const $ = (id) => document.getElementById(id);
  const setVal = (id, value) => { const el=$(id); if(!el) throw new Error('요소 없음: #'+id); el.value=value; };

  try{
    await waitFor(() => marketCatalog !== null, {label:'marketCatalog 로드', timeout:8000});
    pass('초기화: catalog.json 로드 완료');
    await waitFor(() => marketManifest !== null, {label:'marketManifest 로드', timeout:8000});
    pass('초기화: manifest.json 로드 완료');
    await waitFor(() => Array.isArray(searchIndex) && searchIndex.length>0, {label:'검색 인덱스 구축'});
    pass('초기화: 검색 인덱스 구축 완료 (' + searchIndex.length + '개)');
  }catch(e){ fail('초기화', e); }

  try{
    setVal('symbolSearch','AAPL');
    searchSymbols();
    await waitFor(() => lastSearchResults && lastSearchResults.length>0, {label:'AAPL 검색 결과'});
    if(lastSearchResults[0].symbol !== 'AAPL') throw new Error('1위 결과가 AAPL이 아님: '+lastSearchResults[0].symbol);
    pass('검색: "AAPL" 입력 시 1위 결과가 AAPL');
  }catch(e){ fail('검색 기능', e); }

  try{
    selectSearchResult(0);
    await waitFor(() => currentResearch?.symbol==='AAPL', {label:'리서치 패널 심볼 반영'});
    await waitFor(() => {
      const t=$('researchAiSummary').textContent;
      return t && t!=='종목을 선택하면 표시됩니다.' && t!=='생성 중…';
    }, {label:'AI 기업요약 렌더링', timeout:5000});
    const metricsText = $('researchMetrics').textContent;
    if(!metricsText || !metricsText.trim()) throw new Error('researchMetrics가 비어 있음');
    const scoreBadge = $('researchScoreBadge').textContent;
    if(!/\\d/.test(scoreBadge)) throw new Error('종합점수 배지에 숫자가 없음: '+scoreBadge);
    if(!$('researchMoat').textContent) throw new Error('경제적 해자 패널이 비어 있음');
    if(!$('researchFairValue').textContent) throw new Error('AI 적정가 패널이 비어 있음');
    pass('리서치 패널: 지표/AI요약/종합점수(' + scoreBadge.trim() + ')/해자/적정가 렌더링 성공');
  }catch(e){ fail('리서치 패널(AI요약/점수/해자/적정가)', e); }

  try{
    for(const [symbol,name,weight] of [['AAPL','Apple Inc.',60],['QQQ','Invesco QQQ',40]]){
      setVal('fSymbol',symbol); setVal('fName',name); setVal('fWeight',String(weight));
      setVal('fShares','10'); setVal('fAvgPrice','100'); setVal('fCurPrice','110');
      addHolding();
    }
    await waitFor(() => holdings?.length===2, {label:'보유종목 2개 추가'});
    pass('포트폴리오: AAPL/QQQ 2종목 추가 성공');
  }catch(e){ fail('종목 추가', e); }

  try{
    runRiskAnalysis();
    await waitFor(() => $('correlationMatrix').textContent.trim().length>0 && $('statCAGR').textContent.trim()!=='-', {label:'백테스트 결과', timeout:10000});
    pass('백테스트/위험도 분석 실행 성공');
  }catch(e){ fail('백테스트(05)', e); }

  try{
    addSymbolToCompare('AAPL'); addSymbolToCompare('QQQ');
    runComparison();
    await waitFor(() => $('comparisonResult').innerHTML.includes('PER'), {label:'펀더멘털 비교표', timeout:10000});
    pass('종목 비교(가격 성과 + 펀더멘털 비교표) 성공');
  }catch(e){ fail('종목 비교(06 업그레이드)', e); }

  try{
    runPortfolioXray();
    await waitFor(() => $('xrayResult').textContent.trim().length>0, {label:'X-ray 결과', timeout:8000});
    pass('ETF 엑스레이(분산 진단) 실행 성공');
  }catch(e){ fail('ETF 엑스레이(07)', e); }

  try{
    runPortfolioDiagnostics();
    await waitFor(() => $('themeExposureResult').textContent.trim().length>0 && $('portfolioCoachResult').textContent.trim().length>0, {label:'포트폴리오 진단', timeout:8000});
    pass('포트폴리오 진단(테마/국가/리스크시나리오/AI코치) 실행 성공');
  }catch(e){ fail('포트폴리오 진단(신규)', e); }

  try{
    runPlanningSimulation();
    await waitFor(() => $('planningResult').textContent.trim().length>0, {label:'적립식 시뮬레이션', timeout:8000});
    pass('적립식·목표자산 시뮬레이션 실행 성공');
  }catch(e){ fail('적립식 시뮬레이션(09)', e); }

  try{
    setVal('divYield','3.5'); setVal('divAmount','10000'); setVal('divGrowth','5');
    calcDividend();
    if(!$('dividendResult').textContent.includes('연 배당')) throw new Error('배당 계산 결과 미렌더링');
    pass('배당 계산기 실행 성공');
  }catch(e){ fail('배당 계산기(신규)', e); }

  try{
    toggleWatchlist();
    await waitFor(() => loadWatchlist().some(item=>item.symbol==='AAPL'), {label:'AAPL 워치리스트 추가'});
    renderWatchlist();
    if(!$('watchlistResult').textContent.includes('AAPL')) throw new Error('워치리스트에 AAPL 없음');
    pass('관심종목(Watchlist) 추가/렌더링 성공');
  }catch(e){ fail('관심종목(신규)', e); }

  try{
    runMarketDigest();
    await waitFor(() => $('marketDigestResult').textContent.trim().length>0, {label:'시장 시그널', timeout:20000});
    pass('오늘의 시장 시그널(규칙 기반) 실행 성공');
  }catch(e){ fail('오늘의 시장 시그널(신규)', e); }

  try{
    setVal('journalHolding', String(holdings[0].id));
    loadJournalForm();
    setVal('journalThesis','장기 보유');
    setVal('journalTargetPrice','200');
    setVal('journalPurchaseDate','2020-01-01');
    saveJournalThesis();
    if(!$('journalReviewAlert').textContent.includes('복기')) throw new Error('복기 알림 미표시');
    setVal('journalEntry','리서치 기준 유지');
    addJournalEntry();
    pass('투자 일지(목표가/매수일/복기 알림) 성공');
  }catch(e){ fail('투자 일지 업그레이드', e); }

  try{
    setVal('symbolSearch','QQQ');
    searchSymbols();
    await waitFor(() => lastSearchResults && lastSearchResults.some(r=>r.symbol==='QQQ'), {label:'QQQ 검색 결과'});
    const qqqIndex = lastSearchResults.findIndex(r=>r.symbol==='QQQ');
    selectSearchResult(qqqIndex);
    await waitFor(() => currentResearch?.symbol==='QQQ', {label:'QQQ 리서치 패널 반영'});
    await waitFor(() => {
      const t=$('researchAiSummary').textContent;
      return t && t!=='종목을 선택하면 표시됩니다.' && t!=='생성 중…';
    }, {label:'QQQ AI 기업요약 렌더링', timeout:5000});
    const moatText = $('researchMoat').textContent;
    const fvText = $('researchFairValue').textContent;
    if(!moatText.includes('ETF')) throw new Error('ETF 해자 안내 문구가 없음: '+moatText);
    if(!fvText.includes('ETF')) throw new Error('ETF 적정가 안내 문구가 없음: '+fvText);
    pass('리서치 패널(ETF=QQQ): 해자/적정가 ETF 분기 정상 동작');
  }catch(e){ fail('리서치 패널 ETF 분기(QQQ)', e); }

  try{
    const before = JSON.stringify(holdings.map(h=>h.symbol));
    persistState();
    holdings=[];
    loadFromBrowser();
    renderAll();
    const after = JSON.stringify(holdings.map(h=>h.symbol));
    if(before!==after) throw new Error('저장 전('+before+') / 복원 후('+after+') 불일치');
    pass('로컬 보관함 저장 → 복원 라운드트립 일치');
  }catch(e){ fail('저장/불러오기', e); }

  window.__TEST_DONE__ = true;
})().catch(e => { window.__TEST_DONE__ = true; window.__TEST_FATAL__ = (e && e.stack) || String(e); });
`;

async function main(){
  const html = fs.readFileSync(HTML_PATH, 'utf8');
  const dom = new JSDOM(html, { url: 'https://example.com/', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;

  const consoleErrors = [];
  window.console.error = (...args) => { consoleErrors.push(args.map(String).join(' ')); };
  window.alert = () => {};
  window.confirm = () => true;
  window.scrollTo = () => {};
  if(typeof window.HTMLElement.prototype.scrollIntoView !== 'function'){
    window.HTMLElement.prototype.scrollIntoView = () => {};
  }

  window.fetch = async (url) => {
    const u = new URL(String(url), 'https://example.com/');
    if(u.pathname.startsWith('/data/')){
      const text = readLocalDataFile(u.pathname);
      if(text===null) return { ok:false, status:404, json: async () => ({}) };
      return { ok:true, status:200, json: async () => JSON.parse(text) };
    }
    return { ok:false, status:404, json: async () => ({}) };
  };

  const windowErrors = [];
  window.addEventListener('error', (event) => { windowErrors.push((event.error && event.error.stack) || event.message); });
  window.addEventListener('unhandledrejection', (event) => { windowErrors.push((event.reason && event.reason.stack) || String(event.reason)); });

  window.eval(fs.readFileSync(path.join(ROOT, 'firebase-config.js'), 'utf8'));

  const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
  if(!scriptMatch) throw new Error('인라인 <script>를 찾지 못했습니다.');

  // 앱 스크립트 + 테스트 시나리오를 한 번의 eval로 합쳐 실행 (let/const 스코프 공유 목적)
  window.eval(scriptMatch[1] + '\n;' + IN_PAGE_TEST_SCRIPT);

  const start = Date.now();
  while(!window.__TEST_DONE__ && Date.now()-start < 60000){
    await new Promise(r => setTimeout(r, 100));
  }

  const results = window.__TEST_RESULTS__ || [];
  let failCount = 0;
  for(const r of results){
    if(r.ok) console.log(`✅ ${r.label}`);
    else{ failCount++; console.log(`❌ ${r.label}`); if(r.error) console.log('   ', r.error); }
  }
  if(!window.__TEST_DONE__){ failCount++; console.log('❌ 테스트가 60초 안에 끝나지 않았습니다(타임아웃).'); }
  if(window.__TEST_FATAL__){ failCount++; console.log('❌ 테스트 러너 자체 오류:', window.__TEST_FATAL__); }
  if(windowErrors.length){ failCount += windowErrors.length; console.log(`❌ 캐치되지 않은 window 오류 ${windowErrors.length}건:`); windowErrors.forEach(e=>console.log('   ', e)); }
  if(consoleErrors.length){ console.log(`⚠️  console.error 출력 ${consoleErrors.length}건 (참고용, 실패로 집계하지 않음):`); consoleErrors.slice(0,10).forEach(e=>console.log('   ', e)); }

  console.log('\n' + '='.repeat(60));
  if(failCount>0){ console.log(`❌ 런타임 스모크 테스트 실패: ${failCount}건`); process.exit(1); }
  console.log(`✅ 런타임 스모크 테스트 전체 통과 (${results.length}개 시나리오)`);
}

main().catch(error => { console.error('스모크 테스트 실행 자체가 실패했습니다:', error); process.exit(1); });
