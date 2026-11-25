const HOST_KEY = new URLSearchParams(location.search).get('key') || '';

async function api(path, body) {
  const opt = { method: body === undefined ? 'GET' : 'POST', headers: {} };
  if (HOST_KEY) opt.headers['X-Host-Key'] = HOST_KEY;
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data;
  try { data = await r.json(); } catch (e) { throw new Error('Сервер недоступен'); }
  if (!r.ok) throw new Error(data.error || ('Ошибка ' + r.status));
  return data;
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = v => (v == null || isNaN(v)) ? '—' : Math.round(v).toLocaleString('ru-RU') + ' BYN';
const pct = v => (v == null || isNaN(v)) ? '—' : (v * 100).toFixed(1) + '%';
const signed = v => (v > 0 ? '+' : '') + money(v);
const $ = sel => document.querySelector(sel);

function fmtTime(sec) {
  if (sec == null) return '';
  sec = Math.max(0, Math.ceil(sec));
  return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
}

const PHASES = {
  lobby: 'Сбор команд', passport: 'Паспорт организации', prep: 'Подготовка раунда',
  round: 'Раунд: решение кризиса', review: 'Оценка ответов', results: 'Итоги раунда', final: 'Финал',
};

// Локальный таймер: сервер присылает остаток, клиент досчитывает
const Clock = {
  left: null, at: 0, paused: false,
  set(left, paused) { this.left = left; this.at = performance.now(); this.paused = !!paused; },
  get() { if (this.left == null) return null; return this.paused ? this.left : Math.max(0, this.left - (performance.now() - this.at) / 1000); },
};

function timerHtml() {
  const t = Clock.get();
  if (t == null) return '';
  return `<span class="timer ${t < 60 ? 'low' : ''}">${Clock.paused ? '⏸ ' : '⏱ '}${fmtTime(t)}</span>`;
}

function bar(v, max = 10, color) {
  const w = Math.max(0, Math.min(100, v / max * 100));
  const c = color || (w > 66 ? 'var(--good)' : w > 33 ? 'var(--warn)' : 'var(--bad)');
  return `<div class="bar"><i style="width:${w}%;background:${c}"></i></div>`;
}

let META = null;
async function loadMeta() { META = await api('/api/meta'); return META; }
const roleName = r => META?.roles[r]?.name || r;
const levelName = l => META?.levels[l]?.name || l;

function empCard(e, opts = {}) {
  const salCls = e.market ? (e.salary < e.market * 0.92 ? 'bad' : e.salary > e.market * 1.08 ? 'good' : '') : '';
  return `<div class="emp ${opts.sel ? 'sel' : ''}">
    <div class="row"><div class="grow"><div class="nm">${esc(e.name)} <span class="muted small">#${e.id}</span></div>
    <div class="lv"><span class="lv-${e.level}">${levelName(e.level)}</span> · ${esc(roleName(e.role))}</div></div></div>
    <div class="row small" style="margin:4px 0"><b>${money(e.salary)}</b><span class="muted">/мес</span>
      ${e.market ? `<span class="muted ${salCls}">рынок ≈ ${money(e.market)}</span>` : ''}</div>
    <div class="trait">«${esc(e.trait)}»</div>
    <div class="bars">
      <span>Профессионализм</span>${bar(e.prof)}<span>${(+e.prof).toFixed(1)}</span>
      <span>Лояльность</span>${bar(e.loyalty)}<span>${e.loyalty}</span>
      <span>Стрессоуст.</span>${bar(e.stress)}<span>${e.stress}</span>
      ${opts.morale ? `<span>Мораль</span>${bar(e.morale, 100)}<span>${Math.round(e.morale)}</span>` : ''}
    </div>
    ${opts.button || ''}
  </div>`;
}

function reportHtml(r) {
  if (!r) return '';
  const ex = r.expenses || {};
  const items = (r.one_time_items || []).map(i => `<tr><td class="muted">&nbsp;&nbsp;${esc(i.reason)}</td><td class="num">${money(i.amount)}</td></tr>`).join('');
  return `<div class="stats">
      <div class="stat"><span>Оценка плана</span><b>${r.score}/10</b></div>
      <div class="stat"><span>Выручка</span><b>${money(r.revenue)}</b></div>
      <div class="stat"><span>Расходы</span><b>${money(r.total_expenses)}</b></div>
      <div class="stat"><span>Прибыль</span><b class="${r.profit >= 0 ? 'good' : 'bad'}">${signed(r.profit)}</b></div>
      <div class="stat"><span>Рентабельность</span><b>${pct(r.margin)}</b></div>
      <div class="stat"><span>Деньги на счету</span><b>${money(r.cash)}</b></div>
      <div class="stat"><span>Репутация</span><b>${Math.round(r.reputation)}/100</b></div>
      <div class="stat"><span>Ср. мораль / штат</span><b>${Math.round(r.avg_morale)} / ${r.headcount} чел.</b></div>
    </div>
    ${r.verdict ? `<h3 style="margin-top:12px">Вердикт</h3><div class="verdict">${esc(r.verdict)}</div>` : ''}
    ${r.events?.length ? `<h3 style="margin-top:12px">События квартала</h3><ul>${r.events.map(e => `<li>${esc(e)}</li>`).join('')}</ul>` : ''}
    <details><summary>Подробно о расходах</summary><table>
      <tr><td>Зарплаты (ФОТ)</td><td class="num">${money(ex.payroll)}</td></tr>
      <tr><td>Обучение</td><td class="num">${money(ex.training)}</td></tr>
      <tr><td>Серверы</td><td class="num">${money(ex.servers)}</td></tr>
      <tr><td>Маркетинг</td><td class="num">${money(ex.marketing)}</td></tr>
      <tr><td>Офис</td><td class="num">${money(ex.office)}</td></tr>
      <tr><td>Разовые расходы</td><td class="num">${money(ex.one_time)}</td></tr>${items}
    </table>
    <p class="small muted">Мощность: ${r.metrics?.capacity} · Спрос: ${r.metrics?.demand} · Продано: ${r.metrics?.sold} ·
      Качество: ×${r.metrics?.quality} · Инфраструктура: ×${r.metrics?.infra} · Управление: ×${r.metrics?.mgmt} ·
      Ущерб от кризиса: ${Math.round((r.metrics?.crisis_damage_share || 0) * 100)}%</p></details>`;
}

function leaderboardHtml(lb) {
  if (!lb || !lb.length) return '<p class="muted">Пока нет данных</p>';
  return `<table><tr><th>#</th><th>Команда</th><th class="num">Деньги</th><th class="num">Рентаб.</th><th class="num">Балл</th></tr>
    ${lb.map(r => `<tr><td>${r.rank}</td><td><b>${esc(r.name)}</b><div class="small muted">${esc(r.company)}</div></td>
      <td class="num">${money(r.cash)}</td><td class="num">${pct(r.margin)}</td><td class="num"><b>${r.score}</b></td></tr>`).join('')}</table>`;
}
