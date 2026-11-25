let token = localStorage.getItem('hr_token');
let V = null;
let formKey = null;
let pollTimer = null;
let busy = false;

function showMsg(text, ok) {
  $('#msg').innerHTML = text ? `<div class="${ok ? 'card' : 'err'}">${esc(text)}</div>` : '';
  if (text) setTimeout(() => { if ($('#msg').textContent.includes(text)) $('#msg').innerHTML = ''; }, 5000);
}

async function act(path, body, okText) {
  if (busy) return;
  busy = true;
  try {
    await api(path, Object.assign({ token }, body));
    if (okText) showMsg(okText, true);
    await poll(true);
  } catch (e) { showMsg(e.message); }
  finally { busy = false; }
}

async function poll(force) {
  clearTimeout(pollTimer);
  if (!token) { renderJoin(); return; }
  try {
    const d = await api(`/api/me?token=${encodeURIComponent(token)}&v=${force ? 0 : (V?.version || 0)}`);
    if (d.unchanged) Clock.set(d.time_left, V?.paused);
    else { V = d; Clock.set(d.time_left, d.paused); render(); }
  } catch (e) {
    if (e.message === 'NO_PLAYER') { token = null; localStorage.removeItem('hr_token'); V = null; renderJoin(); return; }
    $('#top').innerHTML = '<span class="bad">Нет связи с сервером…</span>';
  }
  pollTimer = setTimeout(poll, 1500);
}

setInterval(() => document.querySelectorAll('[data-timer]').forEach(el => el.innerHTML = timerHtml()), 500);

// ------------------------------------------------------------ вход
function renderJoin() {
  formKey = 'join';
  $('#top').innerHTML = '<b>Кадровый кризис</b><span class="muted">деловая игра по управлению персоналом</span>';
  $('#above').innerHTML = '';
  $('#below').innerHTML = '';
  $('#form').innerHTML = `<div class="card"><h2>Вход в игру</h2>
    <label>Ваше имя</label><input id="nick" maxlength="30" placeholder="Например, Саша">
    <div class="grid" style="margin-top:12px">
      <div class="card inner"><h3>Присоединиться к команде</h3>
        <label>Код команды (спросите у капитана)</label><input id="code" maxlength="4" placeholder="ABCD" style="text-transform:uppercase">
        <button style="margin-top:10px" id="bJoin">Войти</button></div>
      <div class="card inner"><h3>Создать команду</h3>
        <label>Название команды</label><input id="tname" maxlength="40" placeholder="Например, Кодеры без границ">
        <button style="margin-top:10px" class="secondary" id="bCreate">Создать (вы — капитан)</button></div>
    </div></div>`;
  const go = async (action) => {
    try {
      const r = await api('/api/join', { action, nick: $('#nick').value, code: $('#code').value, team_name: $('#tname').value });
      token = r.token; localStorage.setItem('hr_token', token); formKey = null; poll(true);
    } catch (e) { showMsg(e.message); }
  };
  $('#bJoin').onclick = () => go('join');
  $('#bCreate').onclick = () => go('create');
}

// ------------------------------------------------------------ общее
function renderTop() {
  const t = V.team;
  $('#top').innerHTML = `<b>${esc(t.name)}</b><span class="badge">код: <b>${t.code}</b></span>
    <span class="muted small">${esc(V.nick)}${V.is_captain ? ' · капитан' : ''}</span>
    <span class="grow"></span><span class="badge">${PHASES[V.phase]}${V.round ? ' · раунд ' + V.round + '/' + V.rounds : ''}</span>
    <span data-timer>${timerHtml()}</span>`;
}

function dashboard(opts = {}) {
  const t = V.team;
  if (!t.passport_done) return '';
  const q = t.quarterly;
  const qcost = t.payroll_q + q.training + q.servers + q.marketing + q.office;
  const last = t.history[t.history.length - 1];
  const morale = t.employees.length ? t.employees.reduce((s, e) => s + e.morale, 0) / t.employees.length : 0;
  return `<div class="card"><h2>${esc(t.company.name)} <span class="muted small">${esc(t.company.direction)}</span></h2>
    <div class="stats">
      <div class="stat"><span>Деньги на счету</span><b class="${t.cash < 0 ? 'bad' : ''}">${money(t.cash)}</b></div>
      <div class="stat"><span>Расходы в квартал (план)</span><b>${money(qcost)}</b></div>
      <div class="stat"><span>Прибыль прошлого кв.</span><b class="${last ? (last.profit >= 0 ? 'good' : 'bad') : ''}">${last ? signed(last.profit) : '—'}</b></div>
      <div class="stat"><span>Репутация</span><b>${Math.round(t.reputation)}/100</b></div>
      <div class="stat"><span>Штат</span><b>${t.employees.length} чел.</b></div>
      <div class="stat"><span>Средняя мораль</span><b>${Math.round(morale)}/100</b></div>
    </div>
    <h3 style="margin-top:12px">Квартальные бюджеты</h3>
    <table>
      <tr><td>ФОТ (зарплаты сотрудников × 3 мес.)</td><td class="num">${money(t.payroll_q)}</td></tr>
      ${META.quarterly_keys.map(k => `<tr><td>${META.budget_names[k]}</td><td class="num">${money(q[k])}</td></tr>`).join('')}
    </table>
    ${t.company.mission ? `<details><summary>Миссия и кадровая политика</summary><pre>${esc(t.company.mission)}</pre></details>` : ''}
  </div>
  <div class="card"><h2>Сотрудники (${t.employees.length})</h2>
    <div class="grid">${t.employees.map(e => empCard(e, { morale: true })).join('') || '<p class="muted">Никого нет</p>'}</div>
  </div>
  ${t.pool.length ? `<div class="card"><details ${opts.openPool ? 'open' : ''}><summary>Кандидаты в резерве (${t.pool.length}) — можно нанять, упомянув в ответе имя или #номер</summary>
    <div class="grid" style="margin-top:8px">${t.pool.map(e => empCard(e)).join('')}</div></details></div>` : ''}
  ${t.departed?.length ? `<div class="card"><details><summary>Ушедшие сотрудники (${t.departed.length})</summary><ul>
    ${t.departed.map(e => `<li>${esc(e.name)} (${roleName(e.role)}) — ${esc(e.left_reason)}, раунд ${e.left_round}</li>`).join('')}</ul></details></div>` : ''}
  ${t.history.length ? `<div class="card"><h2>История кварталов</h2><table>
    <tr><th>Кв.</th><th>Кризис</th><th class="num">Балл</th><th class="num">Выручка</th><th class="num">Прибыль</th><th class="num hide-mobile">Деньги</th></tr>
    ${t.history.map(h => `<tr><td>${h.round}</td><td>${esc(h.crisis_title)}</td><td class="num">${h.score}</td><td class="num">${money(h.revenue)}</td>
      <td class="num ${h.profit >= 0 ? 'good' : 'bad'}">${signed(h.profit)}</td><td class="num hide-mobile">${money(h.cash)}</td></tr>`).join('')}
  </table></div>` : ''}`;
}

function crisisCard() {
  const c = V.crisis;
  if (!c) return '';
  return `<div class="card crisis"><div class="muted small">Кризис раунда ${V.round}</div><h2>${esc(c.title)}</h2>
    <pre>${esc(c.text)}</pre>${c.personal ? `<div class="personal">${esc(c.personal)}</div>` : ''}</div>`;
}

function lbCard() {
  return V.leaderboard ? `<div class="card"><h2>Рейтинг команд</h2>${leaderboardHtml(V.leaderboard)}</div>` : '';
}

// ------------------------------------------------------------ паспорт: бюджет
const HINTS = {
  recruiting: 'Тратится сразу. Чем больше, тем больше и сильнее кандидатов. Ориентир ≈ 5% капитала.',
  payroll: 'Лимит найма: сумма окладов × 3 месяца. Неиспользованное остаётся на счету.',
  training: 'Ежеквартально. Рост профессионализма и морали. Норма ≈ {training} BYN на человека.',
  servers: 'Ежеквартально. Нехватка серверов снижает производство продукта.',
  marketing: 'Ежеквартально. Формирует спрос (с убывающей отдачей).',
  office: 'Ежеквартально. Влияет на мораль. Норма ≈ {office} BYN на человека.',
};

function budgetFormHtml() {
  const t = V.team, b = t.budget_draft, s = V.capital / 500000;
  const hint = k => (HINTS[k] || '').replace('{training}', Math.round(META.norms.training * s)).replace('{office}', Math.round(META.norms.office * s));
  return `<div class="card"><h2>Шаг 1. Паспорт организации</h2>
    <label>Название компании</label><input id="cName" maxlength="60" value="${esc(t.company.name)}">
    <label>Направление деятельности</label><select id="cDir">${META.directions.map(d => `<option ${d === t.company.direction ? 'selected' : ''}>${esc(d)}</option>`).join('')}</select>
    <label>Миссия и кадровая политика (как вы мотивируете и удерживаете людей)</label>
    <textarea id="cMission" maxlength="1500" placeholder="Например: ценим людей больше процессов, гибкий график, прозрачная система премий...">${esc(t.company.mission)}</textarea>
  </div>
  <div class="card"><h2>Распределение капитала: ${money(V.capital)}</h2>
    <p class="small muted">После утверждения рекрутинг списывается сразу, остальные статьи — ваш план расходов на каждый квартал. Всё, что не потрачено, остаётся на счету.</p>
    ${META.budget_keys.filter(k => k !== 'reserve').map(k => `<div class="budget-row"><div>${META.budget_names[k]}</div>
      <input type="number" min="0" step="1000" data-b="${k}" value="${b[k] || 0}"><div class="hint">${hint(k)}</div></div>`).join('')}
    <div class="budget-row"><div><b>Резервный фонд (остаток)</b></div><div id="reserve" class="num"></div>
      <div class="hint">Подушка безопасности: деньги, которые остаются на счету.</div></div>
    <button id="bBudget" style="margin-top:10px">Утвердить бюджет и получить кандидатов</button>
  </div>`;
}

function readBudget() {
  const b = {};
  document.querySelectorAll('[data-b]').forEach(i => b[i.dataset.b] = Math.max(0, Math.round(+i.value || 0)));
  return b;
}
function readCompany() { return { name: $('#cName').value, direction: $('#cDir').value, mission: $('#cMission').value }; }

function updReserve() {
  const b = readBudget();
  const rest = V.capital - Object.values(b).reduce((a, x) => a + x, 0);
  $('#reserve').innerHTML = `<b class="${rest < 0 ? 'bad' : 'good'}">${money(rest)}</b>`;
}

let draftT = null;
function sendDraft() {
  clearTimeout(draftT);
  draftT = setTimeout(() => api('/api/passport/draft', { token, company: readCompany(), budget: readBudget() }).catch(e => showMsg(e.message)), 700);
}

function initBudgetForm() {
  document.querySelectorAll('[data-b], #cName, #cDir, #cMission').forEach(i => i.addEventListener('input', () => { updReserve(); sendDraft(); }));
  updReserve();
  $('#bBudget').onclick = async () => {
    clearTimeout(draftT);
    try { await api('/api/passport/draft', { token, company: readCompany(), budget: readBudget() }); } catch (e) { }
    act('/api/passport/budget', { budget: readBudget() });
  };
}

function budgetReadonly() {
  const t = V.team, b = t.budget || t.budget_draft;
  return `<div class="card"><h2>${t.budget_confirmed ? 'Бюджет утверждён' : 'Капитан заполняет паспорт…'}</h2>
    <p><b>${esc(t.company.name || '—')}</b> · ${esc(t.company.direction)}</p>${t.company.mission ? `<pre class="muted">${esc(t.company.mission)}</pre>` : ''}
    <table>${META.budget_keys.map(k => `<tr><td>${META.budget_names[k]}</td><td class="num">${money(k === 'reserve' && !t.budget_confirmed ? V.capital - META.budget_keys.filter(x => x !== 'reserve').reduce((a, x) => a + (b[x] || 0), 0) : b[k])}</td></tr>`).join('')}</table></div>`;
}

// ------------------------------------------------------------ паспорт: найм
function hiringHtml() {
  const t = V.team, limit = t.budget.payroll, used = t.payroll_q;
  const cap = V.is_captain && !t.passport_done;
  const btn = (e, hired) => cap ? `<button class="small ${hired ? 'secondary' : ''}" style="margin-top:8px;width:100%" onclick="act('/api/passport/hire',{id:${e.id},hire:${!hired}})">${hired ? 'Убрать' : 'Нанять'}</button>` : '';
  return `<div class="card"><h2>Шаг 2. Формирование штата</h2>
    <div class="stats"><div class="stat"><span>ФОТ использован (за квартал)</span><b class="${used > limit ? 'bad' : ''}">${money(used)} из ${money(limit)}</b>${bar(used, limit || 1, 'var(--accent)')}</div>
      <div class="stat"><span>Нанято</span><b>${t.employees.length} чел.</b></div>
      <div class="stat"><span>Кандидатов в пуле</span><b>${t.pool.length}</b></div></div>
    <p class="small muted">Сравнивайте оклад с рыночным: недоплата снижает мораль, переплата — повышает. Учтите баланс ролей: без тестировщиков падает качество, без DevOps нужны дорогие серверы, без менеджера проекта большая команда работает хуже, без продажника и маркетинга продукт никто не купит.</p>
    ${cap ? `<button class="good" onclick="if(confirm('Завершить найм? Изменить штат можно будет только через ответы на кризисы.'))act('/api/passport/finish',{})">Завершить формирование штата</button>` : ''}
  </div>
  <div class="card"><h2>Нанятые (${t.employees.length})</h2><div class="grid">${t.employees.map(e => empCard(e, { sel: true, button: btn(e, true) })).join('') || '<p class="muted">Пока никого</p>'}</div></div>
  <div class="card"><h2>Кандидаты</h2><div class="grid">${t.pool.map(e => empCard(e, { button: btn(e, false) })).join('')}</div></div>`;
}

// ------------------------------------------------------------ раунд
function answerFormHtml() {
  return `<div class="card"><h2>Ваш план действий</h2>
    <p class="small muted">Пишите конкретно: кого и почему увольняете/нанимаете (имя или #номер), какие зарплаты и премии (суммы в BYN), что меняете в бюджетах, как общаетесь с людьми.
    Нейросеть применит только то, что явно написано. Отправить можно несколько раз — засчитывается последний вариант. Когда время выйдет, черновик отправится автоматически.</p>
    <textarea id="ans" class="big" maxlength="4000" placeholder="1. ...&#10;2. ...&#10;3. ..."></textarea>
    <div class="row" style="margin-top:8px"><span id="cnt" class="small muted"></span><span class="grow"></span>
      <button id="bSend">Отправить ответ</button></div>
    <div id="ansStatus" class="small" style="margin-top:6px"></div></div>`;
}

let ansT = null;
function initAnswerForm() {
  const ta = $('#ans');
  ta.value = V.answer?.text || V.draft?.text || '';
  const upd = () => $('#cnt').textContent = ta.value.length + ' / 4000';
  upd();
  ta.addEventListener('input', () => {
    upd(); clearTimeout(ansT);
    ansT = setTimeout(() => api('/api/answer/draft', { token, text: ta.value }).catch(() => { }), 1200);
  });
  $('#bSend').onclick = () => { clearTimeout(ansT); act('/api/answer/submit', { text: ta.value }, 'Ответ отправлен!'); };
}

function updAnswerStatus() {
  const el = $('#ansStatus');
  if (!el) return;
  const a = V.answer;
  el.innerHTML = a ? `<span class="good">✔ Отправлено в ${new Date(a.ts * 1000).toLocaleTimeString('ru-RU')}</span>${$('#ans').value.trim() !== a.text ? ' <span class="warn">— есть неотправленные изменения</span>' : ''}`
    : '<span class="warn">Ответ ещё не отправлен</span>';
}

function answerReadonly() {
  const a = V.answer, d = V.draft;
  return `<div class="card"><h2>План команды</h2>
    ${a ? `<p class="good small">✔ Отправлен капитаном в ${new Date(a.ts * 1000).toLocaleTimeString('ru-RU')}</p>` : `<p class="muted small">Капитан (${esc(V.team.captain_nick)}) пишет ответ — текст обновляется автоматически</p>`}
    <div class="card inner"><pre>${esc((a && (!d || d.ts <= a.ts) ? a.text : d?.text) || '…')}</pre></div></div>`;
}

// ------------------------------------------------------------ рендер
function render() {
  renderTop();
  const t = V.team, ph = V.phase;
  let key = null, above = '', form = '', below = '', init = null, upd = null;

  if (ph === 'lobby') {
    above = `<div class="card center"><h2>Команда «${esc(t.name)}»</h2>
      <p>Код для входа товарищей по команде:</p><div style="font-size:2.6em;font-weight:800;letter-spacing:.15em">${t.code}</div>
      <p class="muted">Участники: ${t.members.map(esc).join(', ')}</p>
      <p>Ждём, пока ведущий начнёт игру. Первый этап — паспорт организации (капитан распределяет капитал ${money(V.capital)} и нанимает сотрудников).</p></div>`;
  } else if (ph === 'passport') {
    if (!t.budget_confirmed) {
      if (V.is_captain) { key = 'budget'; form = budgetFormHtml(); init = initBudgetForm; }
      else above = budgetReadonly();
    } else if (!t.passport_done) {
      above = hiringHtml();
    } else {
      above = `<div class="card center"><h2>✔ Паспорт готов</h2><p class="muted">Ждём остальные команды и начала первого раунда.</p></div>`;
      below = dashboard();
    }
  } else if (!t.passport_done) {
    above = `<div class="card"><h2>Ваша команда не участвует в раундах</h2><p class="muted">Паспорт организации не был заполнен вовремя. Обратитесь к ведущему.</p></div>`;
  } else if (ph === 'prep') {
    const last = t.history[t.history.length - 1];
    above = `<div class="card center"><h2>Ведущий готовит ${V.round ? 'следующий' : 'первый'} кризис…</h2><p class="muted">Изучите своих сотрудников — от этого будет зависеть ваш ответ.</p></div>`;
    below = (last ? `<div class="card"><h2>Итоги квартала ${last.round}</h2>${reportHtml(last)}</div>` : '') + lbCard() + dashboard();
  } else if (ph === 'round') {
    above = crisisCard();
    if (V.is_captain) { key = 'answer' + V.round; form = answerFormHtml(); init = initAnswerForm; upd = updAnswerStatus; }
    else form = answerReadonly();
    below = dashboard({ openPool: false });
  } else if (ph === 'review') {
    above = crisisCard() + `<div class="card center"><h2>🤖 Нейросеть анализирует ответы…</h2><p class="muted">Скоро ведущий объявит результаты.</p></div>`;
    form = V.answer ? `<div class="card"><h3>Ваш ответ</h3><pre>${esc(V.answer.text)}</pre></div>` : '<div class="card"><p class="bad">Ваша команда не отправила ответ.</p></div>';
    below = dashboard();
  } else if (ph === 'results') {
    const last = t.history[t.history.length - 1];
    above = crisisCard() + (last && last.round === V.round ? `<div class="card"><h2>Результаты квартала ${last.round}</h2>${reportHtml(last)}</div>` : '');
    below = lbCard() + dashboard();
  } else if (ph === 'final') {
    const me = (V.leaderboard || []).find(r => r.id === t.id);
    above = `<div class="card center"><h1>🏁 Игра окончена</h1>${me ? `<h2>Ваше место: ${me.rank} из ${V.leaderboard.length}</h2><p>Итоговый балл: <b>${me.score}</b> · Деньги: <b>${money(me.cash)}</b> · Рентабельность: <b>${pct(me.margin)}</b></p>` : ''}</div>` + lbCard();
    below = dashboard();
  }

  $('#above').innerHTML = above;
  if (key === null || key !== formKey) {
    $('#form').innerHTML = form;
    formKey = key;
    if (init) init();
  }
  $('#below').innerHTML = below;
  if (upd) upd();
}

(async () => {
  try { await loadMeta(); } catch (e) { }
  poll(true);
})();
