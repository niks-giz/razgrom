let H = null;
let tab = 'control';
let formKey = null;
let pollT = null;
const logFilter = { team: '', round: '', kind: 'answer', cheat: false, star: false, sort: 'time', q: '' };

function msg(text, ok) {
  $('#msg').innerHTML = text ? `<div class="${ok ? 'card good' : 'err'}">${esc(text)}</div>` : '';
  if (text) setTimeout(() => { $('#msg').innerHTML = ''; }, ok ? 3000 : 8000);
}

async function A(action, extra = {}, okText) {
  try {
    await api('/api/host/action', Object.assign({ action }, extra));
    if (okText) msg(okText, true);
    await poll(true);
    return true;
  } catch (e) { msg(e.message); return false; }
}

async function poll(force) {
  clearTimeout(pollT);
  try {
    const d = await api('/api/host/state?v=' + (force ? 0 : (H?.version || 0)));
    if (d.unchanged) Clock.set(d.time_left, H?.paused);
    else { H = d; Clock.set(d.time_left, d.paused); render(); }
  } catch (e) { $('#phase').textContent = 'нет связи: ' + e.message; }
  pollT = setTimeout(poll, 1500);
}
setInterval(() => document.querySelectorAll('[data-timer]').forEach(el => el.innerHTML = timerHtml()), 500);

document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => {
  tab = b.dataset.tab; formKey = null;
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  render();
});

function teamName(id) { return H.teams.find(t => t.id === id)?.name || id; }
const playing = () => H.teams.filter(t => t.passport_done);

// ------------------------------------------------------------ управление
function timerControls() {
  if (H.time_left == null) return '';
  return `<div class="row"><span data-timer>${timerHtml()}</span>
    <button class="secondary small" onclick="A('extend',{seconds:-60})">−1 мин</button>
    <button class="secondary small" onclick="A('extend',{seconds:60})">+1 мин</button>
    <button class="secondary small" onclick="A('extend',{seconds:180})">+3 мин</button>
    ${H.paused ? `<button class="small" onclick="A('resume')">▶ Продолжить</button>` : `<button class="secondary small" onclick="A('pause')">⏸ Пауза</button>`}</div>`;
}

function visSelect() {
  const o = [['hidden', 'скрыт'], ['screen', 'на проекторе'], ['all', 'везде (и у команд)']];
  return `<label style="display:inline;margin:0">Рейтинг:</label> <select style="width:auto" onchange="A('settings',{settings:{visibility:this.value}})">
    ${o.map(([v, n]) => `<option value="${v}" ${H.settings.visibility === v ? 'selected' : ''}>${n}</option>`).join('')}</select>`;
}

function controlTop() {
  return `<div class="card"><div class="row"><h2 class="grow" style="margin:0">${PHASES[H.phase]}${H.round ? ` · раунд ${H.round} из ${H.rounds}` : ''}</h2>
    ${visSelect()} <a href="/screen" target="_blank"><button class="secondary small">Открыть экран проектора</button></a></div>
    <p class="small muted">Адрес для игроков: ${H.urls.map(u => `<b>${esc(u)}</b>`).join(' · ')} · Команд: ${H.teams.length}, игроков: ${H.teams.reduce((s, t) => s + t.members.length, 0)}</p>
    ${timerControls()}</div>`;
}

function crisisFormHtml() {
  const c = H.crisis_draft || { title: '', text: '', impact: { revenue_mult: 0.85, morale: -10, reputation: -5, cash_frac: 0 }, target: null, target_text: '' };
  const used = new Set(H.crisis_history.map(x => x.title));
  return `<div class="card"><h2>Кризис для раунда ${H.round + 1}</h2>
    <div class="row"><select id="preset" class="grow" style="flex:1">${H.presets.map(p => `<option value="${p.id}">${used.has(p.title) ? '✓ ' : ''}${esc(p.title)}</option>`).join('')}</select>
      <button class="secondary" onclick="A('pick_preset',{id:$('#preset').value})">Взять из заготовок</button>
      <button class="secondary" onclick="A('pick_preset',{id:H.presets[Math.floor(Math.random()*H.presets.length)].id})">🎲 Случайный</button></div>
    <div class="row" style="margin-top:8px"><input id="wish" class="grow" style="flex:1" placeholder="Пожелание для нейросети (необязательно): например, «про конфликт поколений»">
      <button onclick="A('generate_crisis',{wish:$('#wish').value})">🤖 Сгенерировать нейросетью</button></div>
    <div id="genStatus" class="small" style="margin-top:6px"></div>
    <hr style="border-color:var(--line)">
    <label>Название</label><input id="cTitle" value="${esc(c.title)}">
    <label>Описание (одинаковое для всех команд)</label><textarea id="cText" class="big" style="min-height:140px">${esc(c.text)}</textarea>
    <p class="small muted">Ущерб при полностью провальном ответе. Хороший ответ (балл 9–10) снимает ущерб полностью.</p>
    <div class="grid">
      <div><label>Множитель выручки (0.3–1.2)</label><input id="iRev" type="number" step="0.01" value="${c.impact.revenue_mult}"></div>
      <div><label>Мораль каждого сотрудника</label><input id="iMor" type="number" step="1" value="${c.impact.morale}"></div>
      <div><label>Репутация</label><input id="iRep" type="number" step="1" value="${c.impact.reputation}"></div>
      <div><label>Прямые потери (доля капитала, напр. −0.05)</label><input id="iCash" type="number" step="0.01" value="${c.impact.cash_frac}"></div>
    </div>
    <label><input type="checkbox" id="cTarget" style="width:auto" ${c.target === 'top' ? 'checked' : ''}> Кризис касается лучшего специалиста каждой команды</label>
    <label>Персональный текст (плейсхолдеры {name} {role} {level} {salary} {trait})</label><input id="cTT" value="${esc(c.target_text || '')}">
    <button class="good" style="margin-top:12px" onclick="startRound()">▶ Начать раунд ${H.round + 1} (${H.settings.round_minutes} мин)</button>
  </div>`;
}

function startRound() {
  const crisis = {
    id: H.crisis_draft?.id || 'custom', title: $('#cTitle').value, text: $('#cText').value,
    impact: { revenue_mult: +$('#iRev').value, morale: +$('#iMor').value, reputation: +$('#iRep').value, cash_frac: +$('#iCash').value },
    target: $('#cTarget').checked ? 'top' : null, target_text: $('#cTT').value,
  };
  A('start_round', { crisis });
}

function teamStatusTable(cols) {
  return `<table><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr>${H.teams.map(t => `<tr>${cols.map(c => `<td>${c[1](t)}</td>`).join('')}</tr>`).join('')}</table>`;
}

function evalCard(t) {
  const ev = H.evals[t.id];
  const st = { queued: ['warn', 'в очереди'], running: ['warn', 'нейросеть думает…'], done: ['good', 'оценено'], error: ['bad', 'ошибка'] };
  if (!ev) return `<div class="card"><h3>${esc(t.name)}</h3><span class="badge">не оценено</span></div>`;
  const r = ev.result, p = ev.preview, s = st[ev.status] || ['', ev.status];
  const busy = ev.status === 'queued' || ev.status === 'running';
  return `<div class="card"><div class="row"><h3 class="grow" style="margin:0">${esc(t.name)}</h3>
      <span class="badge ${s[0]}">${s[1]}</span>${ev.edited ? '<span class="badge warn">изменено ведущим</span>' : ''}
      ${r ? `<span class="badge">балл ${r.score}/10</span>${r.cheat ? '<span class="badge bad">⚠ подозрение на чит</span>' : ''}<span class="badge">😂 ${r.funny}/10</span>` : ''}</div>
    ${ev.error ? `<div class="err small">${esc(ev.error)}</div>` : ''}
    <details><summary>Ответ команды</summary><pre class="card inner">${esc(t.answer?.text || '(нет ответа)')}</pre></details>
    ${t.target_text ? `<p class="small personal">${esc(t.target_text)}</p>` : ''}
    ${r ? `<p class="verdict">${esc(r.verdict)}</p>
      ${r.cheat ? `<p class="bad small">Чит: ${esc(r.cheat_reason)}</p>` : ''}
      ${r.funny_comment ? `<p class="small">😂 ${esc(r.funny_comment)}</p>` : ''}
      ${r.host_comment ? `<p class="small muted">Для ведущего: ${esc(r.host_comment)}</p>` : ''}` : ''}
    ${p ? `<div class="stats"><div class="stat"><span>Выручка</span><b>${money(p.revenue)}</b></div><div class="stat"><span>Расходы</span><b>${money(p.total_expenses)}</b></div>
      <div class="stat"><span>Прибыль</span><b class="${p.profit >= 0 ? 'good' : 'bad'}">${signed(p.profit)}</b></div><div class="stat"><span>Деньги после</span><b>${money(p.cash)}</b></div>
      <div class="stat"><span>Мораль / штат</span><b>${Math.round(p.avg_morale)} / ${p.headcount}</b></div></div>
      ${p.events.length ? `<ul class="small">${p.events.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}` : ''}
    <div class="row" style="margin-top:8px">
      <button class="secondary small" ${busy ? 'disabled' : ''} onclick="A('evaluate',{ids:['${t.id}']})">🔄 Переоценить нейросетью</button>
      <button class="secondary small" ${busy || !r ? 'disabled' : ''} onclick="quickScore('${t.id}')">Изменить балл</button>
      <button class="secondary small" ${busy || !r ? 'disabled' : ''} onclick="editEval('${t.id}')">Редактировать всё (JSON)</button>
    </div></div>`;
}

function quickScore(tid) {
  const r = H.evals[tid].result;
  const v = prompt('Новый балл 1–10 для команды ' + teamName(tid), r.score);
  if (v === null) return;
  A('edit_eval', { team_id: tid, result: Object.assign({}, r, { score: +v }) });
}

function editEval(tid) {
  const ev = H.evals[tid];
  $('#modal').innerHTML = `<div class="modal-bg"><div class="modal"><h2>Оценка: ${esc(teamName(tid))}</h2>
    <p class="small muted">Поля: score (1–10), verdict, fire [id], target_retained, salary_changes [{id,new_salary}], hire_from_pool [id], hire_new [{role,level,count}],
    budget_changes {training,servers,marketing,office}, one_time_costs [{reason,amount}], employee_effects [{id,morale_delta,prof_delta}], morale_delta_all, reputation_delta, revenue_mult, cheat…</p>
    <textarea id="evJson" style="min-height:360px;font-family:monospace;font-size:13px">${esc(JSON.stringify(ev.result, null, 2))}</textarea>
    ${ev.raw ? `<details><summary>Сырой ответ нейросети</summary><pre class="small card inner">${esc(ev.raw)}</pre></details>` : ''}
    <div class="row" style="margin-top:10px"><button onclick="saveEval('${tid}')">Сохранить и пересчитать</button><button class="secondary" onclick="$('#modal').innerHTML=''">Отмена</button></div>
  </div></div>`;
}
async function saveEval(tid) { if (await A('edit_eval', { team_id: tid, result: $('#evJson').value }, 'Сохранено')) $('#modal').innerHTML = ''; }

function controlBody() {
  const ph = H.phase;
  if (ph === 'lobby') {
    return `<div class="card"><h2>Ожидание команд</h2>
      ${teamStatusTable([['Команда', t => `<b>${esc(t.name)}</b>`], ['Код', t => t.code], ['Участники', t => t.members.map(esc).join(', ')]])}
      <p class="muted small">Капитал: ${money(H.settings.capital)} · паспорт ${H.settings.passport_minutes} мин · ${H.settings.rounds} раундов по ${H.settings.round_minutes} мин (меняется в «Настройках»)</p>
      <button class="good" onclick="if(confirm('Начать этап паспорта?'))A('start_passport')">▶ Начать паспорт организации (${H.settings.passport_minutes} мин)</button></div>`;
  }
  if (ph === 'passport') {
    return `<div class="card"><h2>Паспорт организации</h2>
      ${teamStatusTable([['Команда', t => `<b>${esc(t.name)}</b><div class="small muted">${esc(t.company.name)}</div>`],
      ['Статус', t => t.passport_done ? '<span class="badge good">готово</span>' : t.budget_confirmed ? '<span class="badge warn">набор штата</span>' : '<span class="badge">бюджет</span>'],
      ['Штат', t => t.employees.length], ['ФОТ/кв', t => money(t.payroll_q)]])}
      <p class="small muted">Когда время выйдет, команды, не утвердившие бюджет, получат черновик (или стандартное распределение) и тех сотрудников, которых успели выбрать.</p>
      <button onclick="if(confirm('Завершить этап паспорта для всех команд?'))A('end_passport')">Завершить паспорт сейчас</button></div>`;
  }
  if (ph === 'prep') {
    return `<div class="card"><h2>Текущий рейтинг</h2>${leaderboardHtml(H.leaderboard)}
      ${H.round ? `<button class="secondary" style="margin-top:10px" onclick="if(confirm('Закончить игру досрочно и подвести итоги?'))A('finish')">Подвести итоги досрочно</button>` : ''}</div>`;
  }
  if (ph === 'round') {
    const c = H.crisis;
    return `<div class="card crisis"><h2>${esc(c.title)}</h2><pre>${esc(c.text)}</pre></div>
      <div class="card"><h2>Ответы (${playing().filter(t => t.answer).length} из ${playing().length})</h2>
      ${teamStatusTable([['Команда', t => `<b>${esc(t.name)}</b>${t.target_text ? `<div class="small warn">${esc(t.target_text)}</div>` : ''}`],
      ['Статус', t => !t.passport_done ? '<span class="badge">не играет</span>' : t.answer ? `<span class="badge good">отправлен ${new Date(t.answer.ts * 1000).toLocaleTimeString('ru-RU')}</span>` : (t.draft.text ? '<span class="badge warn">пишут черновик</span>' : '<span class="badge">нет</span>')],
      ['Текст', t => t.answer || t.draft.text ? `<details><summary>${(t.answer?.text || t.draft.text).length} симв.</summary><pre class="small">${esc(t.answer?.text || t.draft.text)}</pre></details>` : '']])}
      <button style="margin-top:10px" onclick="if(confirm('Завершить приём ответов? Черновики будут отправлены автоматически.'))A('end_round')">⏹ Завершить раунд сейчас</button></div>`;
  }
  if (ph === 'review') {
    const evs = playing().map(t => H.evals[t.id]);
    const ready = evs.every(e => e && (e.status === 'done' || e.status === 'error') && e.result);
    const running = evs.some(e => e && (e.status === 'queued' || e.status === 'running'));
    return `<div class="card"><div class="row"><h2 class="grow" style="margin:0">Оценка ответов</h2>
        <button class="secondary" ${running ? 'disabled' : ''} onclick="A('evaluate',{ids:playing().filter(t=>!H.evals[t.id]||H.evals[t.id].status==='error').map(t=>t.id)})">Оценить неоценённые</button>
        <button class="secondary" ${running ? 'disabled' : ''} onclick="if(confirm('Переоценить все ответы заново?'))A('evaluate',{ids:playing().map(t=>t.id)})">Переоценить всех</button>
        <button class="good" ${ready ? '' : 'disabled'} onclick="if(confirm('Применить результаты и показать командам?'))A('apply_round',{},'Результаты применены')">✔ Применить результаты</button></div>
      <p class="small muted">Цифры ниже — предварительный расчёт. Проверьте ответы на жульничество, при необходимости поправьте балл и примените результаты.</p></div>
      ${playing().map(evalCard).join('')}`;
  }
  if (ph === 'results') {
    return `<div class="card"><h2>Результаты раунда ${H.round}</h2>${leaderboardHtml(H.leaderboard)}
      <div class="row" style="margin-top:10px">${H.last_round ? '' : `<button class="good" onclick="A('next_round')">▶ К следующему раунду</button>`}
      <button class="${H.last_round ? 'good' : 'secondary'}" onclick="if(${H.last_round} || confirm('Закончить игру досрочно?'))A('finish')">🏁 Подвести итоги игры</button></div></div>
      ${H.teams.filter(t => t.history.length).map(t => { const r = t.history[t.history.length - 1]; return `<div class="card"><details><summary>${esc(t.name)}: балл ${r.score}, прибыль ${signed(r.profit)}</summary>${reportHtml(r)}</details></div>`; }).join('')}`;
  }
  if (ph === 'final') {
    return `<div class="card"><h2>🏆 Итоговый рейтинг</h2>${leaderboardHtml(H.leaderboard)}
      <p class="small muted">Балл = ${H.settings.w_cash}% × деньги на счету + ${H.settings.w_margin}% × рентабельность за всю игру (нормировано между командами).</p>
      <div class="row"><a href="/api/host/export?key=${HOST_KEY}"><button class="secondary">Скачать журнал игры (HTML)</button></a>
      <button class="danger" onclick="resetGame()">Новая игра</button></div></div>`;
  }
  return '';
}

function updGen() {
  const el = $('#genStatus');
  if (el) el.innerHTML = H.gen_status === 'running' ? '<span class="warn">🤖 Нейросеть придумывает кризис…</span>' : H.gen_status ? `<span class="bad">${esc(H.gen_status)}</span>` : '';
}

// ------------------------------------------------------------ команды
function teamsTab() {
  return H.teams.map(t => `<div class="card"><div class="row"><h2 class="grow" style="margin:0">${esc(t.name)} <span class="badge">код ${t.code}</span></h2>
      <button class="secondary small" onclick="const n=prompt('Новое название',teamName('${t.id}'));if(n)A('rename_team',{team_id:'${t.id}',name:n})">Переименовать</button>
      <button class="secondary small" onclick="adjustCash('${t.id}')">Скорректировать деньги</button>
      <button class="danger small" onclick="if(confirm('Удалить эту команду?'))A('delete_team',{team_id:'${t.id}'})">Удалить</button></div>
    <table><tr><th>Участник</th><th>IP</th><th></th></tr>${t.members_full.map(m => `<tr><td>${esc(m.nick)} ${m.captain ? '<span class="badge good">капитан</span>' : ''}</td><td class="small muted">${esc(m.ip)}</td>
      <td>${m.captain ? '' : `<button class="secondary small" onclick="A('set_captain',{team_id:'${t.id}',idx:${m.idx}})">Сделать капитаном</button>`}
      <button class="secondary small" onclick="if(confirm('Исключить участника?'))A('kick_member',{team_id:'${t.id}',idx:${m.idx}})">Исключить</button></td></tr>`).join('')}</table>
    ${t.passport_done ? `<div class="stats" style="margin-top:10px"><div class="stat"><span>Компания</span><b>${esc(t.company.name)}</b></div><div class="stat"><span>Деньги</span><b>${money(t.cash)}</b></div>
      <div class="stat"><span>Штат</span><b>${t.employees.length}</b></div><div class="stat"><span>Репутация</span><b>${Math.round(t.reputation)}</b></div></div>
      <details><summary>Сотрудники и бюджеты</summary><div class="grid">${t.employees.map(e => empCard(e, { morale: true })).join('')}</div>
      <table>${Object.entries(t.quarterly).map(([k, v]) => `<tr><td>${META.budget_names[k]}</td><td class="num">${money(v)}</td></tr>`).join('')}</table></details>` : ''}
  </div>`).join('') || '<div class="card muted">Команд пока нет</div>';
}

function adjustCash(tid) {
  const d = prompt('Изменение денег команды ' + teamName(tid) + ' (например −20000 или 15000):');
  if (!d) return;
  const reason = prompt('Причина (попадёт в журнал):') || '';
  A('adjust_cash', { team_id: tid, delta: +d.replace(/[^\d.-]/g, ''), reason });
}

// ------------------------------------------------------------ журнал
function logFormHtml() {
  const rounds = [...new Set(H.log.map(e => e.round))].sort((a, b) => a - b);
  return `<div class="card"><div class="row">
    <select id="fTeam" style="width:auto"><option value="">Все команды</option>${H.teams.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select>
    <select id="fRound" style="width:auto"><option value="">Все раунды</option>${rounds.map(r => `<option value="${r}">Раунд ${r}</option>`).join('')}</select>
    <select id="fKind" style="width:auto"><option value="answer">Ответы на кризисы</option><option value="passport">Паспорта</option><option value="">Всё (вкл. системные)</option></select>
    <select id="fSort" style="width:auto"><option value="time">По времени</option><option value="funny">Самые смешные</option><option value="score">По баллу</option></select>
    <label style="display:inline"><input type="checkbox" id="fCheat" style="width:auto"> только подозрительные</label>
    <label style="display:inline"><input type="checkbox" id="fStar" style="width:auto"> только ★</label>
    <input id="fQ" placeholder="Поиск по тексту" style="width:200px">
    <a href="/api/host/export?key=${HOST_KEY}"><button class="secondary small">Экспорт HTML</button></a></div></div>
    <div id="logList"></div>`;
}
function initLogForm() {
  const m = { fTeam: 'team', fRound: 'round', fKind: 'kind', fSort: 'sort', fQ: 'q' };
  Object.entries(m).forEach(([id, k]) => { $('#' + id).value = logFilter[k]; $('#' + id).oninput = () => { logFilter[k] = $('#' + id).value; renderLog(); }; });
  $('#fCheat').checked = logFilter.cheat; $('#fCheat').onchange = () => { logFilter.cheat = $('#fCheat').checked; renderLog(); };
  $('#fStar').checked = logFilter.star; $('#fStar').onchange = () => { logFilter.star = $('#fStar').checked; renderLog(); };
}
function renderLog() {
  const f = logFilter;
  let L = H.log.filter(e => (!f.team || e.team_id === f.team) && (f.round === '' || String(e.round) === f.round) && (!f.kind || e.kind === f.kind)
    && (!f.cheat || e.cheat) && (!f.star || e.starred) && (!f.q || (e.text + ' ' + e.nick + ' ' + e.team_name).toLowerCase().includes(f.q.toLowerCase())));
  if (f.sort === 'funny') L.sort((a, b) => (b.funny || 0) - (a.funny || 0));
  else if (f.sort === 'score') L.sort((a, b) => (b.score || 0) - (a.score || 0));
  else L = L.slice().reverse();
  $('#logList').innerHTML = `<div class="card"><p class="small muted">Записей: ${L.length}. Каждая отправка ответа сохраняется отдельно; полный журнал с сырыми ответами нейросети — в папке data.</p>
    ${L.map(e => `<div class="logentry ${e.cheat ? 'cheat' : ''}"><div class="row">
      <button class="star ${e.starred ? 'on' : ''}" title="Отметить" onclick="A('star',{id:${e.id}})">★</button>
      <b>${esc(e.team_name || 'Система')}</b><span class="muted small">${esc(e.nick)} · ${esc(e.ip || '')} · раунд ${e.round} · ${new Date(e.ts * 1000).toLocaleTimeString('ru-RU')} · ${e.kind}${e.auto ? ' (авто-отправка черновика)' : ''}</span>
      ${e.score != null ? `<span class="badge">балл ${e.score}</span>` : ''}${e.cheat ? '<span class="badge bad">⚠ чит?</span>' : ''}${e.funny ? `<span class="badge">😂 ${e.funny}</span>` : ''}</div>
      <pre style="margin:6px 0 0 34px">${esc(e.text)}</pre>
      ${e.cheat ? `<p class="bad small" style="margin-left:34px">${esc(e.cheat_reason)}</p>` : ''}
      ${e.funny_comment ? `<p class="small" style="margin-left:34px">😂 ${esc(e.funny_comment)}</p>` : ''}
      ${e.verdict ? `<details style="margin-left:34px"><summary>Вердикт</summary><p class="small">${esc(e.verdict)}</p></details>` : ''}</div>`).join('')}</div>`;
}

// ------------------------------------------------------------ настройки
const LLM_PRESETS = [
  ['Ollama (локально)', 'http://localhost:11434/v1', 'qwen2.5:7b'],
  ['LM Studio (локально)', 'http://localhost:1234/v1', 'local-model'],
  ['OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini'],
  ['OpenRouter', 'https://openrouter.ai/api/v1', 'deepseek/deepseek-chat'],
  ['DeepSeek', 'https://api.deepseek.com/v1', 'deepseek-chat'],
];
function settingsHtml() {
  const s = H.settings, l = H.llm;
  return `<div class="card"><h2>Параметры игры</h2><div class="grid">
      <div><label>Стартовый капитал, BYN ${H.phase !== 'lobby' ? '(только до начала)' : ''}</label><input id="sCap" type="number" value="${s.capital}" ${H.phase !== 'lobby' ? 'disabled' : ''}></div>
      <div><label>Время на паспорт, мин</label><input id="sPass" type="number" step="0.5" value="${s.passport_minutes}"></div>
      <div><label>Время на раунд, мин</label><input id="sRound" type="number" step="0.5" value="${s.round_minutes}"></div>
      <div><label>Количество раундов</label><input id="sRounds" type="number" min="1" value="${s.rounds}"></div>
      <div><label>Вес денег в итоговом балле, %</label><input id="sWc" type="number" value="${s.w_cash}"></div>
      <div><label>Вес рентабельности, %</label><input id="sWm" type="number" value="${s.w_margin}"></div>
      <div><label>Одновременных запросов к нейросети</label><input id="sPar" type="number" min="1" max="10" value="${s.parallel}"></div>
      <div><label>Автооценка после раунда</label><select id="sAuto"><option value="1" ${s.auto_eval ? 'selected' : ''}>Да</option><option value="0" ${s.auto_eval ? '' : 'selected'}>Нет, запускаю вручную</option></select></div>
    </div><button style="margin-top:10px" onclick="saveSettings()">Сохранить</button></div>
  <div class="card"><h2>Нейросеть (любой OpenAI-совместимый API)</h2>
    <div class="row">${LLM_PRESETS.map((p, i) => `<button class="secondary small" onclick="llmPreset(${i})">${p[0]}</button>`).join('')}</div>
    <div class="grid">
      <div><label>Base URL</label><input id="lUrl" value="${esc(l.base_url)}"></div>
      <div><label>Модель</label><input id="lModel" value="${esc(l.model)}"></div>
      <div><label>API-ключ ${l.has_key ? '(сохранён — оставьте пустым, чтобы не менять)' : ''}</label><input id="lKey" type="password" placeholder="${l.has_key ? '••••••••' : 'не нужен для Ollama/LM Studio'}"></div>
      <div><label>Температура</label><input id="lTemp" type="number" step="0.1" value="${l.temperature}"></div>
      <div><label>Таймаут, сек</label><input id="lTo" type="number" value="${l.timeout}"></div>
      <div><label>JSON-режим (response_format)</label><select id="lJson"><option value="1" ${l.json_mode ? 'selected' : ''}>Включён</option><option value="0" ${l.json_mode ? '' : 'selected'}>Выключен</option></select></div>
    </div>
    <div class="row" style="margin-top:10px"><button onclick="saveLlm()">Сохранить</button><button class="secondary" onclick="testLlm()">Проверить связь</button>
      ${l.has_key ? `<button class="secondary small" onclick="A('llm',{llm:{clear_key:true}},'Ключ удалён')">Удалить ключ</button>` : ''}</div>
    <div id="llmOut" class="small" style="margin-top:8px"></div></div>
  <div class="card"><h2>Опасная зона</h2><p class="small muted">Сброс удалит все команды и результаты текущей игры (журнал в папке data сохранится).</p>
    <button class="danger" onclick="resetGame()">Сбросить игру</button></div>`;
}
function llmPreset(i) { const p = LLM_PRESETS[i]; $('#lUrl').value = p[1]; $('#lModel').value = p[2]; }
function saveSettings() {
  const settings = { passport_minutes: +$('#sPass').value, round_minutes: +$('#sRound').value, rounds: +$('#sRounds').value,
    w_cash: +$('#sWc').value, w_margin: +$('#sWm').value, parallel: +$('#sPar').value, auto_eval: $('#sAuto').value === '1' };
  if (!$('#sCap').disabled) settings.capital = +$('#sCap').value;
  A('settings', { settings }, 'Настройки сохранены');
}
function llmCfg() {
  const c = { base_url: $('#lUrl').value, model: $('#lModel').value, temperature: +$('#lTemp').value, timeout: +$('#lTo').value, json_mode: $('#lJson').value === '1' };
  if ($('#lKey').value) c.api_key = $('#lKey').value;
  return c;
}
async function saveLlm() { await A('llm', { llm: llmCfg() }, 'Настройки нейросети сохранены'); }
async function testLlm() {
  await A('llm', { llm: llmCfg() });
  $('#llmOut').innerHTML = '<span class="warn">Проверяю…</span>';
  try {
    const r = await api('/api/host/llm_test', {});
    $('#llmOut').innerHTML = r.ok ? `<span class="good">✔ Работает (${r.seconds} с):</span> <pre>${esc(r.reply)}</pre>` : `<span class="bad">✖ ${esc(r.error)}</span>`;
  } catch (e) { $('#llmOut').innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
}
function resetGame() {
  if (prompt('Чтобы сбросить игру, введите RESET') === 'RESET') { formKey = null; A('reset', { confirm: 'RESET' }, 'Новая игра создана'); }
}

// ------------------------------------------------------------ рендер
function render() {
  $('#phase').textContent = PHASES[H.phase] + (H.round ? ` · раунд ${H.round}/${H.rounds}` : '');
  let key = null, top = '', form = '', body = '', init = null, after = null;
  if (tab === 'control') {
    top = controlTop();
    if (H.phase === 'prep') { key = 'prep' + H.round + '-' + H.draft_stamp; form = crisisFormHtml(); after = updGen; }
    body = controlBody();
  } else if (tab === 'teams') body = teamsTab();
  else if (tab === 'log') { key = 'log' + H.teams.length + '-' + new Set(H.log.map(e => e.round)).size; form = logFormHtml(); init = initLogForm; after = renderLog; }
  else if (tab === 'settings') { key = 'settings'; form = settingsHtml(); }
  $('#pTop').innerHTML = top;
  if (key === null || key !== formKey) { $('#pForm').innerHTML = form; formKey = key; if (init) init(); }
  $('#pBody').innerHTML = body;
  if (after) after();
}

(async () => { await loadMeta(); poll(true); })();
