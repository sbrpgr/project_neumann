(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const samples = JSON.parse($('sample-data').textContent);
  const labels = ['입력', '분석', '채택', '수정 계획서', '최종 점검', '완성'];
  const sections = [...document.querySelectorAll('section[data-step]')];
  const tick = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 10 4 4 8-8"/></svg>';
  const alertIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3 18 17H2Z"/><path d="M10 7v4m0 3h.01"/></svg>';
  let sample = samples[0], selected = new Set(), items = [], checks = [], step = 0, unlocked = 0;
  let generation = 0, directEdits = false, currentChange = null;
  const changes = new Map();
  const pause = () => new Promise(resolve => setTimeout(resolve, 220));
  const el = (tag, cls, text) => {
    const node = document.createElement(tag); if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text; return node;
  };
  const textOf = () => items.map(item => (item.heading ? '## ' : '') + item.text).join('\n\n') + '\n';

  labels.forEach((label, i) => {
    const li = el('li'); const button = el('button'); button.type = 'button';
    const number = el('span', 'step-number', i + 1); number.setAttribute('aria-hidden', 'true');
    button.append(number, el('span', 'step-label', label));
    button.addEventListener('click', () => { if (i <= unlocked) go(i); }); li.append(button); $('steps').append(li);
  });
  function syncSteps() {
    [...$('steps').children].forEach((li, i) => {
      li.className = i === step ? 'current' : i < unlocked ? 'complete' : '';
      const button = li.querySelector('button'); button.disabled = i > unlocked;
      if (i === step) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
      const number = li.querySelector('.step-number');
      if (i < unlocked && i !== step) number.innerHTML = tick; else number.textContent = i + 1;
    });
  }
  function go(next) {
    step = next; sections.forEach((section, i) => { section.hidden = i !== next; }); syncSteps();
    if (next === 2) renderCards();
    if (next === 3) renderPaper($('revision'), true);
    if (next === 5) renderFinal();
    window.scrollTo({top: 0, behavior: 'instant'});
    sections[next].querySelector('h1').focus({preventScroll: true});
  }
  function invalidate() {
    generation++; unlocked = 0; checks = []; items = []; changes.clear(); directEdits = false;
    selected = new Set(sample.edits.map(edit => edit.id));
  }
  function choose(index) {
    sample = samples[index]; invalidate(); $('plan-input').value = sample.original;
    $('file-input').value = '';
    [...$('samples').children].forEach((button, i) => button.setAttribute('aria-pressed', i === index ? 'true' : 'false'));
    validateInput(); go(0);
  }
  samples.forEach((entry, i) => {
    const button = el('button', 'sample'); button.type = 'button'; button.dataset.sample = String(i);
    button.append(el('span', 'chip', entry.field), el('p', '', entry.intro));
    button.addEventListener('click', () => choose(i)); $('samples').append(button);
  });
  function validateInput() {
    const value = $('plan-input').value.trim(); $('char-count').textContent = value.length + '자';
    const message = $('input-message'); message.className = 'meta';
    const match = samples.find(entry => entry.original.trim() === value);
    const outOfScope = /조리|레시피|여행 일정|투자 추천/.test(value) && !match;
    if (outOfScope) { message.textContent = '범위 밖 입력입니다. 연구계획서 샘플을 선택합니다.'; message.classList.add('error'); }
    else if (value.length < 300) { message.textContent = '연구계획서를 300자 이상 입력합니다.'; message.classList.add('error'); }
    else if (!match) { message.textContent = (value.length < 600 ? '600자 미만으로 정보가 부족합니다. ' : '') + '사전 계산 결과가 없는 문안입니다. 샘플을 선택하면 끝까지 볼 수 있습니다.'; message.classList.add('warning'); }
    else { if (sample !== match) { sample = match; selected = new Set(sample.edits.map(edit => edit.id)); } message.textContent = value.length < 600 ? '600자 미만으로 정보가 부족할 수 있습니다.' : '선택한 샘플의 저장된 분석 결과를 볼 수 있습니다.'; }
    if (message.classList.contains('error') || message.classList.contains('warning')) {
      const icon = el('span'); icon.innerHTML = alertIcon; message.prepend(icon, document.createTextNode(' '));
    }
    [...$('samples').children].forEach((button, i) => button.setAttribute('aria-pressed', match === samples[i] ? 'true' : 'false'));
    $('start').disabled = !match || value.length < 300 || outOfScope;
    return !!match && value.length >= 300;
  }
  $('plan-input').addEventListener('input', () => { invalidate(); validateInput(); syncSteps(); });
  $('file-input').addEventListener('change', () => {
    if (!$('file-input').files.length) return;
    invalidate(); $('plan-input').value = ''; validateInput();
    $('input-message').textContent = '정적판에서는 새 파일을 읽거나 분석하지 않습니다. 사전 계산된 샘플을 선택합니다.';
    $('input-message').className = 'meta warning';
    const icon = el('span'); icon.innerHTML = alertIcon; $('input-message').prepend(icon, document.createTextNode(' ')); go(0);
  });
  $('start').addEventListener('click', async () => {
    if (!validateInput()) return; invalidate(); const run = generation;
    unlocked = 1; $('show-cards').disabled = true; go(1); NeumannWait.create($('wait-root'));
    for (let i = 1; i <= 4; i++) { await pause(); if (run !== generation) return; NeumannWait.update(i); }
    NeumannWait.done(); renderCards(); unlocked = 2; $('show-cards').disabled = false; go(step);
  });
  $('show-cards').addEventListener('click', () => go(2));
  function updateAdoption() { $('make-plan').textContent = `채택 ${selected.size}건으로 수정 계획서 받기`; }
  function renderCards() {
    $('cards').replaceChildren(); $('sample-context').textContent = sample.field + ' · ' + sample.title;
    sample.edits.forEach(edit => {
      const card = el('article', 'card'); const heading = el('div', 'card-heading');
      const toggle = el('label', 'toggle'); const input = el('input'); input.type = 'checkbox'; input.checked = selected.has(edit.id);
      input.setAttribute('aria-label', edit.title + ' 채택'); input.dataset.edit = edit.id;
      input.addEventListener('change', () => {
        if (input.checked) selected.add(edit.id); else selected.delete(edit.id);
        unlocked = 2; updateAdoption(); go(2);
      }); toggle.append(input, document.createTextNode('채택')); heading.append(el('h3', '', edit.title), toggle);
      const details = el('details'); const summary = el('summary'); summary.append(el('span', 'chip', edit.paper));
      details.append(summary, el('p', 'quote', edit.evidence.quote), el('p', 'meta', `${edit.reference} · 원문 문자 ${edit.evidence.start}–${edit.evidence.end}에서 발췌했습니다.`));
      card.append(heading, details, el('p', 'preview', edit.after), el('p', 'meta', '제안 출처: ' + edit.origin + ' · ' + edit.reference));
      $('cards').append(card);
    }); updateAdoption();
  }
  function makePlan() {
    items = []; checks = []; changes.clear(); directEdits = false;
    const original = sample.original.split('\n');
    for (let i = 0; i < original.length; i++) {
      const edit = sample.edits.find(entry => entry.lines[0] === i + 1 && selected.has(entry.id));
      if (edit) {
        const item = {text: edit.after, change: edit.id}; items.push(item);
        changes.set(edit.id, {...edit, item, kind: 'adoption'}); i = edit.lines.at(-1) - 1;
      } else if (original[i].trim()) {
        const heading = original[i].startsWith('#');
        items.push({text: original[i].replace(/^#+\s*/, '').replace(/^연구계획서 \(예시\) — /, ''), heading});
      }
    }
    items.push({text: '실행 조건', heading: true}); items.push({text: sample.condition_note, note: true});
    sample.conditions.forEach(text => items.push({text, condition: true}));
    renderPaper($('revision'), true); $('edit-note').textContent = '직접 편집한 문안에는 새로운 분석을 수행하지 않습니다.';
    unlocked = 3; go(3);
  }
  $('make-plan').addEventListener('click', makePlan);
  function renderPaper(host, editable) {
    host.replaceChildren();
    items.forEach(item => {
      if (item.heading) { host.append(el('h2', '', item.text)); return; }
      if (item.note) { host.append(el('p', 'condition-note', item.text)); return; }
      const row = el('div', 'paragraph' + (item.change ? ' changed' : ''));
      const paragraph = el('p', 'paragraph-text', item.text); paragraph.style.whiteSpace = 'pre-wrap';
      if (editable) {
        paragraph.contentEditable = 'true'; paragraph.setAttribute('role', 'textbox'); paragraph.setAttribute('aria-label', '계획서 문단 편집');
        paragraph.addEventListener('input', () => {
          item.text = paragraph.innerText; directEdits = true; unlocked = 3;
          $('edit-note').textContent = '문안을 직접 편집했습니다. 변경한 문장은 사전 계산된 분석 범위에 포함되지 않습니다.';
          // Keep focus and caret while updating future-step locks.
          [...$('steps').children].forEach((li, i) => { li.querySelector('button').disabled = i > unlocked; });
        });
        paragraph.addEventListener('paste', event => {
          event.preventDefault(); const plain = event.clipboardData.getData('text/plain');
          const selection = window.getSelection(); if (!selection.rangeCount) return;
          const range = selection.getRangeAt(0); if (!paragraph.contains(range.commonAncestorContainer)) return;
          range.deleteContents(); const node = document.createTextNode(plain); range.insertNode(node); range.setStartAfter(node); range.collapse(true);
          selection.removeAllRanges(); selection.addRange(range); paragraph.dispatchEvent(new Event('input', {bubbles: true}));
        });
      }
      if (item.change && changes.has(item.change)) {
        const change = changes.get(item.change); const index = [...changes.keys()].indexOf(item.change) + 1;
        const number = el('button', 'change-number', index); number.type = 'button'; number.setAttribute('aria-label', `수정 ${index}의 원문과 근거`);
        number.addEventListener('click', () => openChange(change)); row.append(number);
      }
      row.append(paragraph); host.append(row);
    });
  }
  function openChange(change) {
    currentChange = change; $('change-before').textContent = change.before;
    $('change-after').textContent = change.item.text;
    $('change-evidence').textContent = change.evidence ? change.evidence.quote + '\n출처: ' + change.origin + ' · ' + change.reference : change.reason + '\n출처: 로컬 도구 실행 결과';
    $('undo-change').hidden = step !== 3; $('change-dialog').showModal();
  }
  $('close-dialog').addEventListener('click', () => $('change-dialog').close());
  $('undo-change').addEventListener('click', () => {
    if (!currentChange || step !== 3) return;
    currentChange.item.text = currentChange.before; delete currentChange.item.change;
    selected.delete(currentChange.id); changes.delete(currentChange.id); directEdits = true; unlocked = 3;
    $('change-dialog').close(); renderPaper($('revision'), true); go(3);
  });
  function toolSourcesIntact(index) {
    const sources = sample.before_checks[index].sources;
    const sourceItems = items.filter(item => item.condition).map(item => item.text);
    return sources.every(source => sourceItems.filter(value => value === source).length === 1);
  }
  function renderChecks() {
    $('checks').replaceChildren();
    const categories = ['논리', '물리', '구조'];
    for (let i = 0; i < 3; i++) {
      const result = checks[i]; const card = el('article', 'card check-card' + (!result ? ' pending' : ''));
      card.dataset.check = String(i); const heading = el('div', 'card-heading'); heading.append(el('h3', '', categories[i]));
      const status = el('span', 'status ' + (result?.status || '')); status.innerHTML = result ? (result.status === 'passed' ? tick : alertIcon) : '';
      status.append(document.createTextNode(`${sample.after_checks[i].tool} · ${!result ? '대기합니다' : result.status === 'passed' ? '통과 1' : result.status === 'failed' ? '실패 1' : '미점검 1'}`)); heading.append(status); card.append(heading);
      if (result) {
        card.append(el('p', '', result.message), el('p', 'meta', sample.after_checks[i].scope));
        if (result.status !== 'unchecked') {
          card.append(el('p', 'meta', (result.undone ? '자동 수정을 되돌렸습니다.' : sample.corrections[i].reason) + ' 출처: 로컬 도구 실행 결과.'));
          const details = el('details'); details.append(el('summary', '', '원문과 점검한 조건을 확인합니다'));
          details.append(el('p', 'quote', sample.corrections[i].before + '\n→ ' + (result.undone ? sample.corrections[i].before : sample.corrections[i].after)));
          const sources = result.undone ? sample.before_checks[i].sources : sample.after_checks[i].sources;
          details.append(el('p', 'quote', sources.join('\n'))); card.append(details);
          const undo = el('button', 'text-button', result.undone ? '자동 수정을 다시 적용합니다' : '되돌리기'); undo.type = 'button';
          undo.addEventListener('click', () => toggleCorrection(i)); card.append(undo);
        }
      }
      $('checks').append(card);
    }
  }
  function checkNote() {
    const remaining = checks.filter(result => result.status !== 'passed').length;
    $('check-note').textContent = `사전 계산 조건 ${checks.length}건 중 ${checks.length - remaining}건 통과 · ${remaining}건 확인 필요` + (directEdits ? ' · 직접 편집한 문장은 별도 검토가 필요합니다.' : ' · 문서 전체의 타당성은 별도 검토가 필요합니다.');
  }
  $('finalize').addEventListener('click', async () => {
    // A second explicit confirmation begins a new playback; earlier tool marks
    // are restored first so that their recorded sources can be compared again.
    checks.forEach((result, i) => {
      if (result.item) {
        if (result.item.text === sample.corrections[i].after) result.item.text = sample.corrections[i].before;
        delete result.item.change; changes.delete('tool-' + i);
      }
    });
    checks = []; unlocked = 4; const run = ++generation; $('finish').disabled = true; go(4); renderChecks();
    for (let i = 0; i < 3; i++) {
      await pause(); if (run !== generation) return;
      if (!toolSourcesIntact(i)) {
        checks.push({status: 'unchecked', message: '점검 조건이 편집되어 저장된 결과를 적용할 수 없습니다. 새 점검은 수행하지 않았습니다.'});
      } else {
        const correction = sample.corrections[i]; const item = items.find(entry => entry.condition && entry.text === correction.before);
        item.text = correction.after; item.change = 'tool-' + i;
        changes.set(item.change, {...correction, item, kind: 'tool', id: item.change});
        checks.push({status: 'passed', message: sample.after_checks[i].message, item, undone: false});
      }
      renderChecks(); checkNote();
    }
    unlocked = 5; $('finish').disabled = false; go(step);
  });
  function toggleCorrection(index) {
    const result = checks[index]; if (!result || result.status === 'unchecked') return;
    result.undone = !result.undone; const correction = sample.corrections[index];
    result.item.text = result.undone ? correction.before : correction.after;
    result.status = result.undone ? 'failed' : 'passed';
    result.message = (result.undone ? sample.before_checks : sample.after_checks)[index].message;
    if (result.undone) { delete result.item.change; changes.delete('tool-' + index); }
    else { result.item.change = 'tool-' + index; changes.set(result.item.change, {...correction, item: result.item, kind: 'tool', id: result.item.change}); }
    renderChecks(); checkNote();
  }
  $('finish').addEventListener('click', () => go(5));
  function renderFinal() {
    renderPaper($('final-document'), false);
    const remaining = checks.filter(result => result.status !== 'passed').length;
    $('final-summary').textContent = `권고 반영 ${[...changes.values()].filter(change => change.kind === 'adoption').length}건 · 자동 수정 ${checks.filter(result => result.status === 'passed').length}건 · 확인 필요 ${remaining + (directEdits ? 1 : 0)}건`;
  }
  function download(data, filename, type) {
    const url = URL.createObjectURL(new Blob([data], {type})); const link = el('a');
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function exportNote() {
    const remaining = checks.filter(result => result.status !== 'passed').length;
    return '\n---\n사전 계산 결과 · 실시간 분석 아님\n제안 출처: Claude/Codex 오프라인 · 가상 심사 기록\n점검 출처: 로컬 도구 실행 결과 (명시한 실행 조건만 확인)\n' +
      `확인 필요: ${remaining}건` + (directEdits ? ' · 직접 편집한 문장은 별도 검토가 필요합니다.' : '') + '\n실제 실험과 추가 검토가 필요합니다.\n';
  }
  $('download-md').addEventListener('click', () => download(textOf() + exportNote(), `neumann-${sample.id}-final.md`, 'text/markdown;charset=utf-8'));
  // Minimal standard OOXML, ZIP "stored" entries. Entirely local; no library/CDN.
  function crc32(bytes) {
    let crc = 0xffffffff; for (const byte of bytes) { crc ^= byte; for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); } return (crc ^ 0xffffffff) >>> 0;
  }
  function zip(files) {
    const encoder = new TextEncoder(), chunks = [], central = []; let offset = 0;
    const header = (size, signature) => { const data = new Uint8Array(size); const view = new DataView(data.buffer); view.setUint32(0, signature, true); return [data, view]; };
    for (const [filename, text] of files) {
      const name = encoder.encode(filename), bytes = encoder.encode(text), crc = crc32(bytes);
      const [local, l] = header(30, 0x04034b50); l.setUint16(4, 20, true); l.setUint16(12, 33, true); l.setUint32(14, crc, true); l.setUint32(18, bytes.length, true); l.setUint32(22, bytes.length, true); l.setUint16(26, name.length, true);
      const [entry, c] = header(46, 0x02014b50); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(14, 33, true); c.setUint32(16, crc, true); c.setUint32(20, bytes.length, true); c.setUint32(24, bytes.length, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
      chunks.push(local, name, bytes); central.push(entry, name); offset += local.length + name.length + bytes.length;
    }
    const centralSize = central.reduce((sum, chunk) => sum + chunk.length, 0);
    const [end, e] = header(22, 0x06054b50); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, centralSize, true); e.setUint32(16, offset, true);
    const result = new Uint8Array(offset + centralSize + end.length); let position = 0;
    [...chunks, ...central, end].forEach(chunk => { result.set(chunk, position); position += chunk.length; }); return result;
  }
  $('download-docx').addEventListener('click', () => {
    const xml = value => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const paragraphs = (textOf() + exportNote()).split('\n').map(line => `<w:p><w:r><w:rPr><w:rFonts w:ascii="Pretendard" w:eastAsia="Pretendard"/><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">${xml(line)}</w:t></w:r></w:p>`).join('');
    const doc = '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + paragraphs + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>';
    const content = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>';
    const rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>';
    download(zip([['[Content_Types].xml', content], ['_rels/.rels', rels], ['word/document.xml', doc]]), `neumann-${sample.id}-final.docx`, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
  });
  $('reset').addEventListener('click', () => choose(0));
  choose(0);
})();
