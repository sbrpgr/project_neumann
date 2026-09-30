/* Offline WAIT-UX adapter: recorded progress only; no timers imply live work. */
(() => {
  'use strict';
  let root, progress = 0;
  const labels = ['계획서 확인', '심사 기록 연결', '권고 정리', '원문 대조'];
  function create(host) {
    root = host; progress = 0; root.replaceChildren();
    const list = document.createElement('ol'); list.className = 'wait-list';
    labels.forEach(label => { const item = document.createElement('li'); item.textContent = label + ' · 대기합니다'; list.append(item); });
    const bar = document.createElement('progress'); bar.max = labels.length; bar.value = 0; bar.setAttribute('aria-label', '저장 결과를 불러오는 진행');
    const note = document.createElement('p'); note.className = 'meta'; note.textContent = '사전 계산 결과를 재생합니다. 모델을 실행하지 않습니다.';
    root.append(list, bar, note); return root;
  }
  function update(value) {
    if (!root) return; progress = Math.max(progress, Math.min(labels.length, value));
    [...root.querySelectorAll('li')].forEach((li, i) => { li.textContent = labels[i] + (i < progress ? ' · 확인했습니다' : ' · 대기합니다'); li.classList.toggle('done', i < progress); });
    root.querySelector('progress').value = progress;
  }
  function done() { update(labels.length); }
  function fail(message) { if (root) root.querySelector('p').textContent = message; }
  window.NeumannWait = {create, update, done, fail};
})();
