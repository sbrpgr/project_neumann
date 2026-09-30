/* WAIT-UX: 분석 대기 화면을 "에이전트가 실제로 하는 일"을 따라가는 인터랙티브 화면으로 바꾼다.
   - 컨셉: 흩어진 거절 기록 조각들이 모여 위험카드로 뭉쳐진다(유사 연구 찾기 → 심사평 문장 읽기 → 반복 지적 묶기 → 근거 대조 → 위험카드).
   - 정직성: 카운터·미리보기는 작업 API(GET /premortem/jobs/{id})의 실제 진행 보고(stage·stages_done·stage_summary·
     stage_elapsed_s·eta_s)로만 움직인다. 보고가 없으면 "—"와 "진행 중"만 보인다. 조각 시각화는 장식이며 수치가 아니다(캡션에 표시).
     mock provider·목업 재생은 화면에 표시한다.
   - 연결: index.html은 window.NeumannWait.mount(job)(대기 화면 그릴 때)·update(body)(폴링 응답마다)만 부른다.
     FIN-UI 목업(?mock=final&at=job)은 update({mock:true, state, stage, label, index, total, elapsed})를 준다.
     이 모듈이 없어도 기존 타임라인이 그대로 나온다. 외부 요청 0 · 순수 JS/Canvas · textContent만(innerHTML 없음).
   - prefers-reduced-motion: 시각화를 정지 그림(단계마다 한 장)으로, 펄스·전환 애니메이션은 끈다. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = String(text); return e; }
  function add(p) { for (var i = 1; i < arguments.length; i++) { var c = arguments[i]; if (c == null || c === false) continue; p.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); } return p; }
  function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; }
  var RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  function reduced() { return !!(RM && RM.matches); }
  function U() { return window.NeumannUI || null; }
  function fmtN(n) { return n == null || isNaN(n) ? '—' : String(Math.round(n)); }

  /* 에이전트가 하는 일(컨셉 단계) ← 파이프라인 단계 이름(jobs.STAGE_LABELS) */
  var STEPS = [
    { id: 'read', en: 'READ', name: '계획서 읽기', stages: ['plan_normalize', 'fitness', 'query_axes'],
      why: '계획서에서 분야·방법·주장을 뽑아 검색 질의를 만듭니다. 무엇을 찾을지 정하는 단계입니다.' },
    { id: 'search', en: 'SEARCH', name: '유사 연구 찾기', stages: ['search'],
      why: '같은 방법·주제로 심사받은 연구를 찾습니다. 그 연구들이 받은 심사평(거절·수정 요구 기록)이 위험의 근거가 됩니다.' },
    { id: 'extract', en: 'EXTRACT', name: '심사평 문장 읽기', stages: ['extract_issues'],
      why: '찾은 연구의 심사평을 문장 단위로 읽고 지적만 뽑습니다. LLM이 묶음마다 읽어서 가장 오래 걸리는 단계입니다.' },
    { id: 'group', en: 'SYNTHESIZE', name: '반복 지적 묶기', stages: ['synthesize_cards'],
      why: '여러 심사평에서 반복되는 지적을 위험 유형으로 묶고, 이 계획서의 어느 줄에 해당하는지 붙입니다.' },
    { id: 'verify', en: 'VERIFY', name: '근거 대조', stages: ['verify_evidence'],
      why: '카드가 인용한 심사평 문장이 원문과 글자 단위로 같은지 확인합니다. 확인되지 않은 근거와 카드는 버립니다.' },
    { id: 'finish', en: 'FINISH', name: '위험카드 마무리', stages: ['expected_review', 'checklist', 'semantic_validate', 'assemble'],
      why: '예상 심사평과 예방 체크리스트를 만들고 2차 검증을 거쳐 리포트로 정리합니다.' }
  ];
  var STAGE_STEP = {}; STEPS.forEach(function (s, i) { s.stages.forEach(function (st) { STAGE_STEP[st] = i; }); });
  var STAGE_LABEL = { plan_normalize: '계획서 정리', fitness: '적합성 판정', query_axes: '검색 질의 만들기', search: '유사 연구 검색', extract_issues: '지적 추출', synthesize_cards: '위험카드 합성', verify_evidence: '원문 대조', expected_review: '예상 심사평', checklist: '체크리스트', semantic_validate: '2차 검증', assemble: '결과 정리' };
  /* 카운터: 어느 단계의 어느 수치를 보이나(모두 서버 stage_summary.counts에서만) */
  var COUNTS = [
    { id: 'works', step: 1, stage: 'search', label: '유사 연구', unit: '편', pick: function (c) { return c.kept != null ? c.kept : c.hits; } },
    { id: 'excerpts', step: 2, stage: 'extract_issues', label: '심사평 문장', unit: '개', pick: function (c) { return c.excerpts; } },
    { id: 'findings', step: 2, stage: 'extract_issues', label: '추출한 지적', unit: '건', pick: function (c) { return c.findings_kept != null ? c.findings_kept + (c.findings_rule || 0) : null; }, of: function (c) { return c.findings_total; } },
    { id: 'cards', step: 3, stage: 'synthesize_cards', label: '카드 후보', unit: '장', pick: function (c) { return c.cards; } },
    { id: 'verified', step: 4, stage: 'verify_evidence', label: '원문 일치', unit: '', pick: function (c) { return c.quotes_verified; }, of: function (c) { return c.quotes_total; } }
  ];

  var W = null;       /* 화면 상태 */
  var VIZ = null;     /* 캔버스 상태 */
  var HEALTH = { asked: false, mock: false };

  function fresh() {
    return { status: 'queued', stage: '', label: '', position: 0, eta: null, stageElapsed: null, done: {}, summary: {}, cur: -1, mock: false,
             mockNote: '', failed: false, finished: false, open: {}, openItem: {}, t0: Date.now(), sig: '', waitText: '' };
  }
  function stepOf(stage) { return Object.prototype.hasOwnProperty.call(STAGE_STEP, stage) ? STAGE_STEP[stage] : -1; }

  /* ---------- 진행 보고 → 상태 ---------- */
  function fromBody(b) {
    var w = W || (W = fresh());
    if (b && b.mock) {  /* FIN-UI 목업 훅 모양 {mock, state, stage, label, index, total, elapsed} */
      w.mock = true; w.mockNote = '목업 재생 · 서버 호출 없음 · 가짜 데이터';
      w.status = b.state === 'done' ? 'done' : (b.state === 'queued' ? 'queued' : 'running');
      w.finished = b.state === 'done'; w.failed = b.state === 'failed';
      if (b.stage) { w.stage = String(b.stage); w.label = String(b.label || STAGE_LABEL[w.stage] || w.stage); var i = stepOf(w.stage); if (i >= 0) w.cur = i; }
      if (b.summary && b.stage) w.summary[b.stage] = b.summary;
      if (typeof b.index === 'number' && typeof b.total === 'number') {
        var seen = ['plan_normalize', 'query_axes', 'search', 'extract_issues', 'synthesize_cards', 'verify_evidence'];
        for (var k = 0; k < Math.min(b.index, seen.length); k++) if (!w.done[seen[k]]) w.done[seen[k]] = { status: 'ok', s: null };
      }
      if (w.finished) w.cur = STEPS.length;
      return w;
    }
    b = b || {};
    w.status = b.status === 'queued' ? 'queued' : (b.status === 'done' ? 'done' : 'running');
    w.position = +b.position || 0;
    w.eta = b.eta_s == null ? null : +b.eta_s;
    w.stageElapsed = b.stage_elapsed_s == null ? null : +b.stage_elapsed_s;
    (b.stages_done || []).forEach(function (d) { if (!d || !d.stage) return; w.done[d.stage] = { status: String(d.status || ''), s: d.elapsed_s == null ? null : +d.elapsed_s }; if (d.summary) w.summary[d.stage] = d.summary; });
    if (b.stage_summary && typeof b.stage_summary === 'object') Object.keys(b.stage_summary).forEach(function (k) { w.summary[k] = b.stage_summary[k]; });
    var st = b.stage && b.stage !== 'running' && b.stage !== 'queued' ? String(b.stage) : '';
    if (st) { w.stage = st; w.label = String(b.stage_label || STAGE_LABEL[st] || st); var si = stepOf(st); if (si >= 0) w.cur = Math.max(w.cur, si); }
    else if (w.status === 'running' && !w.stage) { w.label = ''; }
    /* 끝난 단계로도 현재 단계를 추정한다(다음 단계 시작 보고가 아직 없을 때) */
    Object.keys(w.done).forEach(function (n) { var i = stepOf(n); if (i >= 0 && i > w.cur && !w.stage) w.cur = i; });
    if (w.status === 'done') { w.finished = true; w.cur = STEPS.length; }
    return w;
  }
  function stepState(i) {
    var w = W;
    if (w.finished) return 'done';
    if (w.failed) return i === w.cur ? 'fail' : (i < w.cur ? 'done' : 'todo');
    if (i < w.cur) return 'done';
    if (i === w.cur) return w.status === 'queued' ? 'todo' : 'run';
    return 'todo';
  }
  function stepElapsed(i) {
    var s = STEPS[i], sum = 0, any = false;
    s.stages.forEach(function (st) { var d = W.done[st]; if (d && d.s != null) { sum += d.s; any = true; } });
    if (!any && stepState(i) === 'run' && W.stageElapsed != null) return W.stageElapsed;
    return any ? sum : null;
  }
  function counts(stage) { var s = W.summary[stage]; return s && s.counts ? s.counts : null; }
  function works() { var s = W.summary.search; return s && s.works ? s.works : []; }
  function cardsPrev() { var s = W.summary.synthesize_cards; return s && s.cards ? s.cards : []; }

  /* ---------- DOM ---------- */
  function build() {
    var root = el('div', 'wx'); root.id = 'waitux';
    var now = el('div', 'wx-now'); now.setAttribute('role', 'status'); now.setAttribute('aria-live', 'polite');
    var nowL = el('div'); add(nowL, el('div', 'k', 'now'), el('h2')); nowL.lastChild.id = 'wxNow';
    var eta = el('div', 'wx-eta'); eta.id = 'wxEta';
    var why = el('p', 'wx-why'); why.id = 'wxWhy';
    add(now, nowL, eta, why);
    var viz = el('div', 'wx-viz'); var cv = el('canvas'); cv.id = 'wxCanvas'; cv.setAttribute('aria-hidden', 'true');
    var cap = el('div', 'wx-cap'); add(cap, el('span', null, '흩어진 거절 기록 조각 → 반복 지적 → 위험카드'), el('span', 'r', '장식 · 수치 아님'));
    var badge = el('span', 'wx-badge'); badge.id = 'wxBadge'; badge.hidden = true;
    add(viz, cv, cap, badge);
    var cts = el('div', 'wx-counts'); cts.id = 'wxCounts';
    COUNTS.forEach(function (c) { var t = el('div', 'wx-ct todo'); t.dataset.ct = c.id; add(t, el('div', 'l', c.label), el('div', 'v', '—'), el('div', 's', '대기')); add(cts, t); });
    var feedW = el('div', 'wx-feed'); feedW.id = 'wxFeedWorks'; feedW.hidden = true;
    var hw = el('h3'); add(hw, '찾은 유사 연구', el('span', 'n', ''), el('span', 'note', '눌러서 연도·학회·유사도 보기 · 서버가 보고한 순서')); add(feedW, hw, el('ul', 'wx-list'));
    var feedC = el('div', 'wx-feed'); feedC.id = 'wxFeedCards'; feedC.hidden = true;
    var hc = el('h3'); add(hc, '위험카드 후보', el('span', 'n', ''), el('span', 'note', '원문 대조 전 · 대조에서 탈락할 수 있음')); add(feedC, hc, el('ul', 'wx-list'));
    var steps = el('ol', 'wx-steps'); steps.id = 'wxSteps';
    STEPS.forEach(function (s, i) {
      var li = el('li', 'wx-step todo'); li.dataset.step = String(i);
      var b = el('button'); b.type = 'button'; b.setAttribute('aria-expanded', 'false'); b.dataset.wxstep = String(i);
      var tm = el('span', 'tm'); add(tm, el('span', 'sec', ''), el('span', 'car', '›'));
      var ttl = el('span', 'ttl'); add(ttl, el('span', 'n', s.name), el('span', 'st', ''));
      add(b, el('span', 'nm', s.en), ttl, tm);
      var body = el('div', 'wx-body'); body.id = 'wxBody' + i; body.hidden = true;
      add(body, el('p', null, s.why), el('div', 'kv'));
      add(li, b, body); add(steps, li);
    });
    var foot = el('div', 'wx-foot'); foot.id = 'wxFoot';
    add(root, now, viz, cts, feedW, feedC, steps, foot);
    root.addEventListener('click', onClick);
    return root;
  }
  function onClick(ev) {
    var t = ev.target.closest ? ev.target.closest('button') : null; if (!t || !W) return;
    if (t.dataset.wxstep != null) { var i = +t.dataset.wxstep; W.open[i] = !W.open[i]; W.openAuto = false; paintSteps(); return; }
    if (t.dataset.wxitem != null) { var k = t.dataset.wxitem; W.openItem[k] = !W.openItem[k]; paintFeed(true); }
  }

  function paint() {
    if (!W || !$('waitux')) return;
    var w = W, U_ = U();
    var st = w.finished ? 'done' : (w.failed ? 'fail' : (w.status === 'queued' ? 'queued' : 'running'));
    var nowH = $('wxNow'); clear(nowH);
    var name = w.finished ? '분석 완료' : (w.failed ? '분석 중단' : (w.status === 'queued' ? '대기열' : (w.cur >= 0 && w.cur < STEPS.length ? STEPS[w.cur].name : '분석 시작')));
    var sub = w.finished ? '리포트로 이동합니다' : (w.failed ? '아래 오류 안내 확인' : (w.status === 'queued' ? (w.position > 0 ? '앞에 ' + w.position + '건' : '곧 시작') : (w.label ? w.label : (w.stage ? w.stage : '진행 단계 보고 없음'))));
    add(nowH, el('span', null, name), el('span', 'st', sub));
    var why = $('wxWhy'); clear(why);
    if (w.finished) add(why, '모든 단계가 끝났습니다.');
    else if (w.failed) add(why, '분석이 끝까지 가지 못했습니다. 아래 오류 안내를 확인하세요.');
    else if (w.status === 'queued') add(why, el('b', null, '왜 기다리나요? '), '동시에 돌릴 수 있는 분석 수가 정해져 있어 앞 분석이 끝나면 시작합니다.');
    else if (w.cur >= 0 && w.cur < STEPS.length) add(why, el('b', null, '왜 이걸 하나요? '), STEPS[w.cur].why);
    else add(why, '서버가 첫 단계를 보고하면 여기에 단계 설명이 보입니다.');
    var eta = $('wxEta'); clear(eta);
    if (w.finished) add(eta, el('b', null, '완료'));
    else if (w.failed) add(eta, el('b', null, '중단'));
    else if (w.status === 'queued') { add(eta, w.eta != null ? el('b', null, '약 ' + fmtN(Math.max(w.eta, 1)) + '초 뒤 시작') : el('b', null, '시작 대기'), el('span', 'sub', '최근 분석 평균 기준')); }
    else {
      if (w.eta == null) add(eta, el('b', null, '남은 시간 미상'));
      else if (w.eta <= 1.5) add(eta, el('b', null, '곧 끝남'), el('span', 'sub', '평균보다 오래 걸리는 중'));
      else add(eta, el('b', null, '약 ' + fmtN(w.eta) + '초 남음'), el('span', 'sub', '최근 분석 평균 기준 · 실제와 다를 수 있음'));
      if (w.stageElapsed != null) add(eta, el('span', 'sub', '이 단계 ' + fmtN(w.stageElapsed) + '초째'));
    }
    var badge = $('wxBadge'); var mock = w.mock || HEALTH.mock;
    badge.hidden = !mock; badge.textContent = w.mock ? '목업 재생' : 'mock provider';
    paintCounts(); paintFeed(false); paintSteps();
    var foot = $('wxFoot'); clear(foot);
    add(foot, el('span', null, '수치와 제목은 서버 진행 보고(jobs API)에서 온 것만 표시합니다. 보고가 없으면 "—"로 둡니다.'));
    if (mock) add(foot, el('span', 'mock', w.mock ? w.mockNote : '모의(mock) provider · 실제 LLM 분석이 아닙니다'));
    /* 기존 머리(상태 글자·진행 막대·대기 문구)도 단계 기준으로 맞춘다(시간으로 지어내지 않는다) */
    var js = $('jobState'); if (js) { js.textContent = st === 'done' ? 'complete' : (st === 'fail' ? 'failed' : st); js.style.color = st === 'done' ? 'var(--green)' : 'var(--red)'; }
    var pb = $('pbar'); if (pb) { var doneN = 0; for (var i = 0; i < STEPS.length; i++) if (stepState(i) === 'done') doneN++; var pct = w.finished ? 100 : Math.round((doneN + (st === 'running' && w.cur >= 0 ? 0.5 : 0)) / STEPS.length * 100); pb.style.width = Math.max(st === 'queued' ? 3 : 6, pct) + '%'; }
    var jw = $('jobWait'); if (jw && U_ && U_.S.job && U_.S.job.waitText) jw.textContent = U_.S.job.waitText;
    vizMode();
  }
  function paintCounts() {
    COUNTS.forEach(function (c) {
      var t = document.querySelector('#wxCounts [data-ct="' + c.id + '"]'); if (!t) return;
      var cs = counts(c.stage), v = cs ? c.pick(cs) : null, of = cs && c.of ? c.of(cs) : null, ss = stepState(c.step);
      var vEl = t.querySelector('.v'), sEl = t.querySelector('.s'); clear(vEl);
      if (v != null) { add(vEl, fmtN(v)); if (of != null) add(vEl, el('small', null, '/ ' + fmtN(of))); else if (c.unit) add(vEl, el('small', null, c.unit)); }
      else add(vEl, '—');
      t.className = 'wx-ct ' + (ss === 'run' ? 'run' : (ss === 'done' ? 'done' : 'todo'));
      sEl.textContent = v != null ? (ss === 'run' ? '집계 중 · 지금까지' : '서버 보고') : (ss === 'run' ? '진행 중 · 아직 보고 없음' : (ss === 'done' ? '보고 없음' : (ss === 'fail' ? '중단' : '대기')));
    });
  }
  function paintFeed(force) {
    var ws = works(), cs = cardsPrev();
    var sig = JSON.stringify([ws, cs, W.openItem]);
    if (!force && sig === W.sig) return;
    var grew = W.sig && ws.length + cs.length > (W.nItems || 0); W.sig = sig; W.nItems = ws.length + cs.length;
    var fw = $('wxFeedWorks'), fc = $('wxFeedCards');
    fw.hidden = !ws.length; fc.hidden = !cs.length;
    fw.querySelector('.n').textContent = ws.length ? ws.length + '편' : '';
    fc.querySelector('.n').textContent = cs.length ? cs.length + '장' : '';
    var ul = fw.querySelector('ul'); clear(ul); ul.className = 'wx-list' + (grew ? ' new' : '');
    ws.forEach(function (x, i) {
      var key = 'w' + i, li = el('li'), b = el('button'); b.type = 'button'; b.dataset.wxitem = key; b.setAttribute('aria-expanded', W.openItem[key] ? 'true' : 'false');
      var meta = [x.year != null ? String(x.year) : null, x.score != null ? '유사도 ' + (+x.score).toFixed(2) : null].filter(Boolean).join(' · ');
      add(b, el('span', 'n', String(i + 1)), el('span', 't', x.title || '(제목 없음)'), el('span', 'm', meta)); add(li, b);
      if (W.openItem[key]) { var d = el('div', 'd'); add(d, kv('연도', x.year != null ? x.year : '—'), kv('학회·저널', x.venue || '—'), kv('유사도', x.score != null ? (+x.score).toFixed(3) : '—'), el('span', 'mono', '심사평 원문은 리포트의 근거 패널에서 대조된 인용만 보입니다')); add(li, d); }
      add(ul, li);
    });
    var uc = fc.querySelector('ul'); clear(uc); uc.className = 'wx-list' + (grew ? ' new' : '');
    cs.forEach(function (x, i) {
      var key = 'c' + i, li = el('li'), b = el('button'); b.type = 'button'; b.dataset.wxitem = key; b.setAttribute('aria-expanded', W.openItem[key] ? 'true' : 'false');
      add(b, el('span', 'n', String(i + 1)), el('span', 't', x.title || '(제목 없음)'), el('span', 'm', x.code || '')); add(li, b);
      if (W.openItem[key]) { var d2 = el('div', 'd'); add(d2, kv('위험 코드', x.code || '—'), el('span', 'mono', '근거 대조를 통과해야 리포트의 위험카드가 됩니다')); add(li, d2); }
      add(uc, li);
    });
  }
  function kv(l, v) { var s = el('span'); add(s, el('span', 'lab', l), el('span', 'mono', String(v))); return s; }
  function paintSteps() {
    var w = W, showCur = w.cur >= 0 && w.cur < STEPS.length;
    STEPS.forEach(function (s, i) {
      var li = document.querySelector('#wxSteps [data-step="' + i + '"]'); if (!li) return;
      var ss = stepState(i); li.className = 'wx-step ' + ss;
      var open = w.open[i] != null ? !!w.open[i] : (showCur && i === w.cur && !w.finished);
      var b = li.querySelector('button'), body = $('wxBody' + i); b.setAttribute('aria-expanded', open ? 'true' : 'false'); body.hidden = !open;
      var stTxt = ss === 'run' ? (w.label && stepOf(w.stage) === i ? w.label : '진행 중') : (ss === 'done' ? '완료' : (ss === 'fail' ? '중단' : '대기'));
      var subs = s.stages.filter(function (st) { return w.done[st] && w.done[st].status && w.done[st].status !== 'ok'; }).map(function (st) { return (STAGE_LABEL[st] || st) + ' ' + w.done[st].status; });
      b.querySelector('.st').textContent = stTxt + (subs.length ? ' · ' + subs.join(', ') : '');
      var e = stepElapsed(i); b.querySelector('.sec').textContent = e != null ? (Math.round(e * 10) / 10).toFixed(1) + 's' : '';
      var kvEl = body.querySelector('.kv'); clear(kvEl);
      s.stages.forEach(function (st) { var d = w.done[st], c = counts(st); var parts = []; if (d) parts.push(d.status + (d.s != null ? ' ' + d.s.toFixed(1) + 's' : '')); else if (w.stage === st) parts.push('진행 중'); if (c) Object.keys(c).slice(0, 8).forEach(function (k) { parts.push(k + ' ' + c[k]); }); if (parts.length) { var sp = el('span'); add(sp, el('b', null, STAGE_LABEL[st] || st), ' ' + parts.join(' · ')); add(kvEl, sp); } });
      if (!kvEl.childNodes.length) add(kvEl, el('span', null, ss === 'todo' ? '아직 시작 전' : '서버 단계 보고 없음'));
    });
  }

  /* ---------- 조각 시각화(장식) ---------- */
  function seeded(seed) { var s = seed >>> 0; return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  function vizInit(canvas) {
    var rnd = seeded(20261001), N = 64, parts = [];
    for (var i = 0; i < N; i++) parts.push({ x: rnd(), y: rnd(), tx: rnd(), ty: rnd(), w: 10 + rnd() * 14, h: 6 + rnd() * 6, rot: (rnd() - .5) * 1.2, trot: (rnd() - .5) * 1.2, a: .18, ta: .18, tint: 0, ttint: 0, k: 0, seed: rnd() });
    VIZ = { c: canvas, parts: parts, mode: -1, raf: 0, t: 0, scan: 0, clusters: 1, groups: [], last: 0 };
    vizResize();
    if (window.ResizeObserver) { VIZ.ro = new ResizeObserver(function () { vizResize(); if (reduced()) vizDraw(); }); VIZ.ro.observe(canvas.parentNode); }
  }
  function vizResize() { var c = VIZ.c, r = c.parentNode.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2); var h = parseFloat(getComputedStyle(c).height) || 190; c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(h * dpr)); VIZ.W = r.width; VIZ.H = h; VIZ.dpr = dpr; }
  function vizMode() {
    if (!VIZ || !$('wxCanvas')) return;
    var w = W, mode = w.finished ? 6 : (w.failed ? -2 : (w.status === 'queued' ? -1 : Math.max(0, w.cur)));
    var cc = counts('synthesize_cards'), k = cc && cc.cards != null ? Math.max(1, Math.min(8, cc.cards)) : (mode >= 3 ? 1 : 0);
    var ws = counts('search'); var nWorks = ws && ws.kept != null ? ws.kept : null;
    if (mode !== VIZ.mode || k !== VIZ.clusters || nWorks !== VIZ.nWorks) { VIZ.mode = mode; VIZ.clusters = k; VIZ.nWorks = nWorks; vizTargets(); }
    if (reduced()) { vizSnap(); vizDraw(); if (VIZ.raf) { cancelAnimationFrame(VIZ.raf); VIZ.raf = 0; } return; }
    if (!VIZ.raf) VIZ.raf = requestAnimationFrame(vizTick);
  }
  function vizTargets() {
    var m = VIZ.mode, ps = VIZ.parts, rnd = seeded(7 + m * 13 + VIZ.clusters), k = VIZ.clusters;
    var cx = [], cy = [];
    for (var g = 0; g < Math.max(k, 1); g++) { cx.push(k === 1 ? .5 : .14 + .72 * (g + .5) / k); cy.push(.5 + (k > 4 && g % 2 ? .18 : (k > 4 ? -.18 : 0))); }
    VIZ.groups = cx.map(function (x, i) { return { x: x, y: cy[i] }; });
    ps.forEach(function (p, i) {
      p.k = i % Math.max(k, 1);
      if (m <= -1 || m === 0) { p.tx = (rnd() < .5 ? -.15 + rnd() * .12 : 1.03 + rnd() * .12); p.ty = rnd(); p.ta = m === 0 ? .22 : .12; p.ttint = 0; p.trot = (rnd() - .5) * 1.4; }
      else if (m === 1) { p.tx = .06 + rnd() * .88; p.ty = .12 + rnd() * .7; p.ta = .55; p.ttint = 0; p.trot = (rnd() - .5) * 1.0; }
      else if (m === 2) { p.tx = .06 + rnd() * .88; p.ty = .12 + rnd() * .7; p.ta = .7; p.ttint = p.seed < .45 ? 1 : 0; p.trot = (rnd() - .5) * .6; }
      else if (m === 3) { var gx = cx[p.k], gy = cy[p.k], r = .06 + rnd() * .12, a = rnd() * 6.283; p.tx = gx + Math.cos(a) * r * (k > 1 ? .55 : 1.4); p.ty = gy + Math.sin(a) * r; p.ta = .75; p.ttint = p.seed < .45 ? 1 : .3; p.trot = (rnd() - .5) * .35; }
      else if (m === 4 || m === 5) { var gx2 = cx[p.k], gy2 = cy[p.k], r2 = .03 + rnd() * .07, a2 = rnd() * 6.283; p.tx = gx2 + Math.cos(a2) * r2 * (k > 1 ? .55 : 1.3); p.ty = gy2 + Math.sin(a2) * r2; p.ta = .85; p.ttint = p.seed < .45 ? 1 : .2; p.trot = (rnd() - .5) * .15; }
      else { var gx3 = cx[p.k], gy3 = cy[p.k]; p.tx = gx3 + (rnd() - .5) * .05 * (k > 1 ? 1 : 2.2); p.ty = gy3 + (rnd() - .5) * .18; p.ta = .9; p.ttint = p.seed < .45 ? 1 : .15; p.trot = 0; }
    });
  }
  function vizSnap() { VIZ.parts.forEach(function (p) { p.x = p.tx; p.y = p.ty; p.a = p.ta; p.tint = p.ttint; p.rot = p.trot; }); }
  function vizTick(ts) {
    VIZ.raf = 0; if (!$('wxCanvas')) return;
    var dt = Math.min(0.05, (ts - (VIZ.last || ts)) / 1000); VIZ.last = ts; VIZ.t += dt;
    var m = VIZ.mode, ease = 1 - Math.pow(0.02, dt);
    VIZ.parts.forEach(function (p, i) {
      var wob = m >= 1 && m <= 2 ? .006 : (m <= 0 ? .012 : .002);
      var ox = Math.sin(VIZ.t * (0.6 + p.seed) + i) * wob, oy = Math.cos(VIZ.t * (0.5 + p.seed * .7) + i * 1.7) * wob;
      p.x += (p.tx + ox - p.x) * ease; p.y += (p.ty + oy - p.y) * ease; p.a += (p.ta - p.a) * ease; p.rot += (p.trot - p.rot) * ease;
      var tt = p.ttint; if (m === 2) { var sx = (VIZ.t * .28) % 1.2; tt = Math.abs(p.x - sx) < .06 ? 1 : p.ttint * .6; }
      p.tint += (tt - p.tint) * (m === 2 ? .25 : ease);
    });
    vizDraw();
    VIZ.raf = requestAnimationFrame(vizTick);
  }
  function css(name, fb) { var v = getComputedStyle(document.documentElement).getPropertyValue(name); return v ? v.trim() : fb; }
  function vizDraw() {
    var c = VIZ.c, ctx = c.getContext('2d'); if (!ctx) return;
    var Wd = VIZ.W, Hd = VIZ.H, dpr = VIZ.dpr, m = VIZ.mode;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, Wd, Hd);
    var ink = css('--ink', '#14161a'), red = css('--red', '#b5171f'), line = css('--line2', '#c6c9c3'), redT = css('--red-t', '#fbe9e9');
    if (m === 2 && !reduced()) { var sx = ((VIZ.t * .28) % 1.2) * Wd; ctx.strokeStyle = red; ctx.globalAlpha = .35; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx, 8); ctx.lineTo(sx, Hd - 26); ctx.stroke(); ctx.globalAlpha = 1; }
    if (m >= 4) VIZ.groups.forEach(function (g) { var gw = (VIZ.groups.length > 1 ? Math.min(150, Wd / VIZ.groups.length * .72) : Math.min(260, Wd * .5)), gh = Hd * .52; ctx.save(); ctx.globalAlpha = m >= 6 ? .95 : .55; ctx.strokeStyle = m >= 6 ? ink : line; ctx.fillStyle = m >= 6 ? '#fff' : 'transparent'; ctx.lineWidth = m >= 6 ? 1.2 : 1; ctx.setLineDash(m >= 6 ? [] : [3, 3]); ctx.beginPath(); ctx.rect(g.x * Wd - gw / 2, g.y * Hd - gh / 2, gw, gh); if (m >= 6) ctx.fill(); ctx.stroke(); if (m >= 6) { ctx.setLineDash([]); ctx.strokeStyle = red; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(g.x * Wd - gw / 2, g.y * Hd - gh / 2); ctx.lineTo(g.x * Wd + gw / 2, g.y * Hd - gh / 2); ctx.stroke(); } ctx.restore(); });
    VIZ.parts.forEach(function (p) {
      ctx.save(); ctx.translate(p.x * Wd, p.y * Hd); ctx.rotate(p.rot); ctx.globalAlpha = Math.max(0, Math.min(1, p.a));
      ctx.fillStyle = p.tint > .5 ? redT : '#fff'; ctx.strokeStyle = p.tint > .5 ? red : ink; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.rect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.fill(); ctx.stroke();
      ctx.globalAlpha *= .8; ctx.strokeStyle = p.tint > .5 ? red : line; ctx.beginPath(); ctx.moveTo(-p.w / 2 + 2, 0); ctx.lineTo(p.w / 2 - 2, 0); ctx.stroke();
      ctx.restore();
    });
    if (m >= 5 && m < 6) VIZ.groups.forEach(function (g) { ctx.save(); ctx.strokeStyle = red; ctx.lineWidth = 2; ctx.lineCap = 'round'; ctx.beginPath(); var x = g.x * Wd, y = g.y * Hd - Hd * .3; ctx.moveTo(x - 6, y); ctx.lineTo(x - 2, y + 4); ctx.lineTo(x + 6, y - 4); ctx.stroke(); ctx.restore(); });
  }

  /* ---------- 연결 API ---------- */
  function mount(job) {
    var app = $('app'); if (!app || document.body.dataset.view !== 'job') return false;
    var tl = app.querySelector('.tl'); if (!tl) return false;
    if (!W) W = fresh();
    var j = job || {};
    if (j.state === 'failed') { W.failed = true; W.finished = false; }
    else if (j.state === 'done') { W.finished = true; W.status = 'done'; W.cur = STEPS.length; }
    if (j.raw) fromBody(j.raw);
    var old = $('waitux'); if (old) old.parentNode.removeChild(old);
    var root = build(); tl.parentNode.insertBefore(root, tl); tl.hidden = true;
    var log = app.querySelector('.log'); if (log && !W.finished) log.hidden = true;
    vizInit($('wxCanvas'));
    if (!HEALTH.asked) { HEALTH.asked = true; try { fetch('health', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (h) { var eff = h && h.llm && (h.llm.effective || h.llm.provider); if (eff === 'mock') { HEALTH.mock = true; if (W && $('waitux')) paint(); } }).catch(function () {}); } catch (e) { /* 정적 판 */ } }
    paint();
    return true;
  }
  function update(body) {
    fromBody(body);
    if (!$('waitux') || document.body.dataset.view !== 'job') { var u = U(); if (!u || !mount(u.S.job)) return false; }
    if (!body || !body.mock) { var u2 = U(); if (u2 && u2.S.job) u2.S.job.raw = body; }
    paint();
    return true;
  }
  function reset() { W = null; if (VIZ && VIZ.raf) cancelAnimationFrame(VIZ.raf); if (VIZ && VIZ.ro) VIZ.ro.disconnect(); VIZ = null; }

  /* ---------- 목업 재생(?mock=final&at=job, FIN-UI 블록이 없을 때만): 가짜 데이터로 단계 이벤트를 타이머로 흘린다 ---------- */
  var MOCK_SCRIPT = [['plan_normalize', 500], ['query_axes', 900], ['search', 1400], ['extract_issues', 2600], ['synthesize_cards', 1500], ['verify_evidence', 900], ['expected_review', 700], ['checklist', 500], ['semantic_validate', 500]];
  function mockPlay(view, onDone) {
    var u = U(); if (!u || !view) return false;
    reset(); var run = {}; u.S.job = { state: 'running', run: run, waitText: '목업 · 작업 등록 · 서버 호출 없음' }; u.S.elapsed = 0; u.go(1);
    var t0 = Date.now(), tick = setInterval(function () { if (u.S.job && u.S.job.run === run && u.S.step === 1) { u.S.elapsed = (Date.now() - t0) / 1000; var e = $('elapsed'); if (e) e.textContent = u.S.elapsed.toFixed(1); } else clearInterval(tick); }, 100);
    var wl = (view.works || []).slice(0, 8).map(function (x) { return { title: x.t, year: null, venue: null, score: typeof x.s === 'number' ? x.s : null }; });
    var cl = (view.cards || []).slice(0, 8).map(function (c) { var f = view.fams && view.fams[c.fam]; return { title: f ? f.n : '위험카드', code: f ? f.k : '' }; });
    var sums = { search: { counts: { hits: wl.length, kept: wl.length }, works: wl }, extract_issues: { counts: { excerpts: Object.keys(view.ev || {}).length, findings_kept: Object.keys(view.ev || {}).length, findings_total: Object.keys(view.ev || {}).length } }, synthesize_cards: { counts: { cards: cl.length }, cards: cl }, verify_evidence: { counts: { quotes_total: Object.keys(view.ev || {}).length, quotes_verified: Object.keys(view.ev || {}).length } } };
    update({ mock: true, state: 'queued', stage: '', label: '작업 등록', index: -1, total: MOCK_SCRIPT.length, elapsed: 0 });
    var at = 300;
    MOCK_SCRIPT.forEach(function (s, i) {
      setTimeout(function () { if (!u.S.job || u.S.job.run !== run) return; u.S.job.waitText = '목업 분석 중 · ' + (STAGE_LABEL[s[0]] || s[0]) + ' · 서버 호출 없음'; update({ mock: true, state: 'running', stage: s[0], label: STAGE_LABEL[s[0]] || s[0], index: i, total: MOCK_SCRIPT.length, elapsed: (Date.now() - t0) / 1000 }); }, at);
      at += s[1];
      setTimeout(function () { if (!u.S.job || u.S.job.run !== run) return; if (sums[s[0]]) { W.done[s[0]] = { status: 'ok', s: s[1] / 1000 }; update({ mock: true, state: 'running', stage: s[0], label: STAGE_LABEL[s[0]] || s[0], index: i, total: MOCK_SCRIPT.length, elapsed: (Date.now() - t0) / 1000, summary: sums[s[0]] }); } }, at - 60);
    });
    setTimeout(function () { if (!u.S.job || u.S.job.run !== run) return; clearInterval(tick); u.S.job = { state: 'done', run: run, view: view }; update({ mock: true, state: 'done', stage: '', label: '완료', index: MOCK_SCRIPT.length, total: MOCK_SCRIPT.length, elapsed: (Date.now() - t0) / 1000 }); setTimeout(function () { if (typeof onDone === 'function') onDone(); else if (u.S.step === 1) u.go(2); }, 900); }, at + 200);
    return true;
  }
  function bootMockHook() {
    if (!/[?&]mock=final(?:&|$)/.test(location.search) || window.NeumannFinal) return;  /* FIN-UI 블록이 있으면 그쪽 mockAnalysis가 update()를 부른다 */
    var u = U(); if (!u) return;
    var bar = $('rvMockBar');
    if (bar && !$('wxMockPlay')) { var b = el('button', 'btn sm', '대기 화면 재생'); b.id = 'wxMockPlay'; b.type = 'button'; b.addEventListener('click', function () { var d = u.D(); if (d) mockPlay(d); }); bar.insertBefore(b, bar.lastChild); }
    var at = (/[?&]at=([a-z]+)/.exec(location.search) || [])[1];
    if (at === 'job') { var d = u.D(); if (d) mockPlay(d); }
  }
  setTimeout(bootMockHook, 0);

  window.NeumannWait = { mount: mount, update: update, reset: reset, mockPlay: mockPlay, steps: STEPS, state: function () { return W; } };
})();
