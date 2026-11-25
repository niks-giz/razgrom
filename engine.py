"""Экономическая модель игры: кандидаты, расчёт квартала, рейтинг."""
import copy
import math
import random

BASE_CAPITAL = 500_000  # все денежные константы заданы для этого капитала и масштабируются

ROLES = {
    "dev":     {"name": "Разработчик",          "salary": 5000, "kind": "tech",  "w": 1.0, "freq": 3.0},
    "qa":      {"name": "Тестировщик (QA)",     "salary": 3500, "kind": "tech",  "w": 0.7, "freq": 1.3},
    "devops":  {"name": "DevOps-инженер",       "salary": 5500, "kind": "tech",  "w": 0.8, "freq": 1.0},
    "design":  {"name": "UI/UX-дизайнер",       "salary": 3800, "kind": "tech",  "w": 0.6, "freq": 1.0},
    "analyst": {"name": "Бизнес-аналитик",      "salary": 4000, "kind": "tech",  "w": 0.6, "freq": 0.8},
    "pm":      {"name": "Менеджер проекта",     "salary": 4800, "kind": "mgmt",  "w": 0.0, "freq": 1.0},
    "sales":   {"name": "Менеджер по продажам", "salary": 3000, "kind": "sales", "w": 0.0, "freq": 1.2},
    "hr":      {"name": "HR-менеджер",          "salary": 2800, "kind": "hr",    "w": 0.0, "freq": 0.8},
}

LEVELS = {
    "junior": {"name": "Junior", "mult": 0.45, "prof": (2.0, 4.0)},
    "middle": {"name": "Middle", "mult": 1.0,  "prof": (4.0, 7.0)},
    "senior": {"name": "Senior", "mult": 1.8,  "prof": (7.0, 10.0)},
}

BUDGET_KEYS = ["recruiting", "payroll", "training", "servers", "marketing", "office", "reserve"]
QUARTERLY_KEYS = ["training", "servers", "marketing", "office"]
BUDGET_NAMES = {
    "recruiting": "Рекрутинг (найм)",
    "payroll": "ФОТ (зарплаты за квартал)",
    "training": "Обучение и развитие",
    "servers": "Серверы и инфраструктура",
    "marketing": "Маркетинг",
    "office": "Офис",
    "reserve": "Резервный фонд",
}

DIRECTIONS = [
    "Веб-разработка на заказ", "Мобильные приложения", "SaaS-продукт", "Геймдев",
    "IT-аутсорсинг", "Кибербезопасность", "Финтех", "E-commerce платформа",
]

# Нормативы (при базовом капитале)
OFFICE_NORM = 2000      # офис на сотрудника за квартал
TRAINING_NORM = 1000    # обучение на сотрудника за квартал
SERVER_PER_POINT = 700  # серверы на единицу производственной мощности
REV_PER_POINT = 7500    # выручка за единицу проданного продукта
MKT_REF = 25000
MKT_K = 15
SALES_K = 3
DEMAND_BASE = 5

MALE_FIRST = ["Александр", "Дмитрий", "Максим", "Артём", "Иван", "Никита", "Павел", "Андрей", "Егор",
              "Кирилл", "Владислав", "Сергей", "Алексей", "Михаил", "Денис", "Евгений", "Илья",
              "Роман", "Антон", "Глеб", "Тимофей", "Ярослав", "Вадим", "Олег", "Станислав"]
FEMALE_FIRST = ["Анастасия", "Мария", "Дарья", "Екатерина", "Алина", "Полина", "Виктория", "Ольга",
                "Юлия", "Анна", "Елизавета", "Ксения", "Татьяна", "Валерия", "Вероника", "Алеся",
                "Светлана", "Наталья", "Ирина", "Яна", "Кристина", "Диана"]
SURNAMES = [("Ковалёв", "Ковалёва"), ("Новик", "Новик"), ("Мельник", "Мельник"), ("Шевчук", "Шевчук"),
            ("Козлов", "Козлова"), ("Жук", "Жук"), ("Савицкий", "Савицкая"), ("Климович", "Климович"),
            ("Бондаренко", "Бондаренко"), ("Морозов", "Морозова"), ("Лукашевич", "Лукашевич"),
            ("Петров", "Петрова"), ("Соколов", "Соколова"), ("Ткачук", "Ткачук"), ("Ярошевич", "Ярошевич"),
            ("Кравченко", "Кравченко"), ("Волков", "Волкова"), ("Зайцев", "Зайцева"), ("Гончаров", "Гончарова"),
            ("Михалевич", "Михалевич"), ("Карпович", "Карпович"), ("Лебедев", "Лебедева"),
            ("Романовский", "Романовская"), ("Сидоренко", "Сидоренко"), ("Белов", "Белова"),
            ("Кузьмич", "Кузьмич"), ("Дубовский", "Дубовская"), ("Орлов", "Орлова")]

TRAITS = [
    "Любит спорить с начальством", "Трудоголик, рискует выгореть", "Душа компании",
    "Работает только под дедлайн", "Постоянно ищет новые вакансии", "Наставник для новичков",
    "Не переносит переработки", "Мечтает о собственном стартапе", "Перфекционист, всё переделывает",
    "Знает всех в индустрии", "Тихий, но очень надёжный", "Часто опаздывает, но гениален",
    "Ценит стабильность больше денег", "Хочет расти в тимлиды", "Обижается на критику",
    "Обожает новые технологии", "Работает только удалённо", "Конфликтует с дизайнерами",
    "Генерирует идеи пачками", "Мотивирован только деньгами", "Командный игрок",
    "Пишет документацию (редкость!)", "Ненавидит митинги", "Просит повышения каждый месяц",
    "Бывший фрилансер, любит свободу", "Студент, совмещает с учёбой", "Сильный переговорщик",
    "Лоялен к компании, где его ценят", "Медленный, но без ошибок", "Нестабилен под давлением",
    "Готов к релокации в любой момент", "Отличный коммуникатор с клиентами",
]


def clamp(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = lo
    if math.isnan(v):
        v = lo
    return max(lo, min(hi, v))


def scale(settings):
    return settings["capital"] / BASE_CAPITAL


def market_salary(role, level, s):
    return ROLES[role]["salary"] * LEVELS[level]["mult"] * s


def make_candidate(rng, emp_id, role, level, s, quality=0.0):
    lo, hi = LEVELS[level]["prof"]
    prof = rng.uniform(lo, hi) + quality * 0.5
    prof = round(clamp(prof, 1, 10), 1)
    pos = (prof - lo) / (hi - lo) if hi > lo else 0.5
    salary = market_salary(role, level, s) * rng.uniform(0.85, 1.15) * (0.93 + 0.14 * pos)
    salary = max(50, int(round(salary / 50.0)) * 50)
    female = rng.random() < 0.4
    sn = rng.choice(SURNAMES)
    name = f"{rng.choice(FEMALE_FIRST if female else MALE_FIRST)} {sn[1] if female else sn[0]}"
    loyalty = int(round(clamp(rng.triangular(1, 10, 6.5), 1, 10)))
    if level == "senior":
        loyalty = max(1, loyalty - 1)
    return {
        "id": emp_id,
        "name": name,
        "role": role,
        "level": level,
        "salary": salary,
        "prof": prof,
        "loyalty": loyalty,
        "stress": rng.randint(1, 10),
        "morale": 70.0,
        "trait": rng.choice(TRAITS),
        "hired_round": 0,
    }


def generate_pool(rng, recruiting, capital, next_id):
    """Чем больше бюджет рекрутинга, тем больше и сильнее пул. Возвращает (пул, следующий id)."""
    s = capital / BASE_CAPITAL
    ratio = recruiting / (capital * 0.05) if capital > 0 else 0
    r = clamp(ratio, 0, 2)
    size = int(round(6 + 7 * r))
    p_senior = 0.08 + 0.17 * r
    p_junior = max(0.15, 0.5 - 0.17 * r)
    roles = list(ROLES.keys())
    picks = []
    if size >= len(roles):
        picks = roles[:]
        rng.shuffle(picks)
    weights = [ROLES[k]["freq"] for k in roles]
    while len(picks) < size:
        picks.append(rng.choices(roles, weights)[0])
    pool = []
    for role in picks:
        x = rng.random()
        level = "senior" if x < p_senior else ("junior" if x < p_senior + p_junior else "middle")
        pool.append(make_candidate(rng, next_id, role, level, s, quality=r * 0.5))
        next_id += 1
    order = {k: i for i, k in enumerate(roles)}
    lv = {"senior": 0, "middle": 1, "junior": 2}
    pool.sort(key=lambda c: (order[c["role"]], lv[c["level"]]))
    return pool, next_id


def default_budget(capital):
    shares = {"recruiting": 0.05, "payroll": 0.25, "training": 0.02, "servers": 0.04,
              "marketing": 0.06, "office": 0.04}
    b = {k: int(capital * v) for k, v in shares.items()}
    b["reserve"] = capital - sum(b.values())
    return b


def eff(e):
    return e["prof"] * (0.6 + 0.4 * e["morale"] / 100.0)


def quarterly_payroll(team):
    return sum(e["salary"] * 3 for e in team["employees"])


def normalize_eval(ev, team, settings):
    """Приводит ответ нейросети к допустимым диапазонам."""
    cap = settings["capital"]
    ev = dict(ev or {})
    out = {}
    out["score"] = int(round(clamp(ev.get("score", 5), 1, 10)))
    out["verdict"] = str(ev.get("verdict") or "")[:3000]

    def ids(v):
        res = []
        for x in (v if isinstance(v, list) else []):
            try:
                res.append(int(x))
            except (TypeError, ValueError):
                pass
        return res

    out["fire"] = ids(ev.get("fire"))
    tr = ev.get("target_retained")
    out["target_retained"] = tr if isinstance(tr, bool) else None
    out["salary_changes"] = []
    for sc in ev.get("salary_changes") or []:
        try:
            out["salary_changes"].append({"id": int(sc["id"]), "new_salary": float(sc["new_salary"])})
        except (TypeError, ValueError, KeyError):
            pass
    out["hire_from_pool"] = ids(ev.get("hire_from_pool"))
    out["hire_new"] = []
    for h in ev.get("hire_new") or []:
        try:
            role, level = h.get("role"), h.get("level", "middle")
            if role in ROLES and level in LEVELS:
                out["hire_new"].append({"role": role, "level": level,
                                        "count": int(clamp(h.get("count", 1), 1, 5))})
        except AttributeError:
            pass
    out["budget_changes"] = {}
    bc = ev.get("budget_changes") or {}
    if isinstance(bc, dict):
        for k in QUARTERLY_KEYS:
            if k in bc and bc[k] is not None:
                out["budget_changes"][k] = int(clamp(bc[k], 0, cap * 0.6))
    out["one_time_costs"] = []
    for c in ev.get("one_time_costs") or []:
        try:
            out["one_time_costs"].append({"reason": str(c.get("reason", "Разовый расход"))[:200],
                                          "amount": int(clamp(c.get("amount", 0), 0, cap * 0.5))})
        except AttributeError:
            pass
    out["employee_effects"] = []
    for x in ev.get("employee_effects") or []:
        try:
            out["employee_effects"].append({"id": int(x["id"]),
                                            "morale_delta": clamp(x.get("morale_delta", 0), -30, 30),
                                            "prof_delta": clamp(x.get("prof_delta", 0), -1.5, 1.5)})
        except (TypeError, ValueError, KeyError, AttributeError):
            pass
    out["morale_delta_all"] = clamp(ev.get("morale_delta_all", 0), -15, 15)
    out["reputation_delta"] = clamp(ev.get("reputation_delta", 0), -10, 10)
    out["revenue_mult"] = clamp(ev.get("revenue_mult", 1.0), 0.85, 1.15)
    out["cheat"] = bool(ev.get("cheat", False))
    out["cheat_reason"] = str(ev.get("cheat_reason") or "")[:500]
    out["funny"] = int(clamp(ev.get("funny", 0), 0, 10))
    out["funny_comment"] = str(ev.get("funny_comment") or "")[:500]
    out["host_comment"] = str(ev.get("host_comment") or "")[:1000]
    return out


def fmt(v):
    return f"{int(round(v)):,}".replace(",", " ") + " BYN"


def _depart(t, e, reason, round_no):
    t["employees"] = [x for x in t["employees"] if x["id"] != e["id"]]
    d = dict(e)
    d["left_round"] = round_no
    d["left_reason"] = reason
    t.setdefault("departed", []).append(d)


def simulate(team, settings, crisis, ev_raw, round_no, seed, next_id):
    """Чистая функция: считает квартал. Возвращает (новое состояние команды, отчёт, next_id)."""
    t = copy.deepcopy(team)
    cap = settings["capital"]
    s = scale(settings)
    rng = random.Random(seed)
    ev = normalize_eval(ev_raw, t, settings)
    score = ev["score"]
    f = clamp(1 - 1.1 * (score - 1) / 9, -0.1, 1.0)  # доля ущерба от кризиса
    imp = (crisis or {}).get("impact", {}) or {}
    events = []
    one_time = []

    def emp(i):
        for e in t["employees"]:
            if e["id"] == i:
                return e
        return None

    # 1. Увольнения
    fired = 0
    for fid in ev["fire"]:
        e = emp(fid)
        if not e:
            continue
        fired += 1
        one_time.append({"reason": f"Выходное пособие: {e['name']}", "amount": e["salary"]})
        events.append(f"Уволен(а) {e['name']} ({ROLES[e['role']]['name']}), выходное пособие {fmt(e['salary'])}.")
        _depart(t, e, "уволен(а) компанией", round_no)

    # 2. Персональная цель кризиса
    tid = t.get("crisis_target")
    if crisis and crisis.get("target") == "top" and tid is not None:
        e = emp(tid)
        if e:
            if ev["target_retained"] is False:
                events.append(f"{e['name']} покидает компанию — удержать не удалось.")
                _depart(t, e, "ушёл(ла) из-за кризиса", round_no)
            elif ev["target_retained"] is True:
                events.append(f"{e['name']} остаётся в компании.")

    # 3. Изменения зарплат
    sal_morale = {}
    for sc in ev["salary_changes"]:
        e = emp(sc["id"])
        if not e:
            continue
        old = e["salary"]
        new = int(round(clamp(sc["new_salary"], old * 0.7, old * 2.0) / 50.0)) * 50
        if new == old:
            continue
        e["salary"] = new
        k = new / old - 1
        sal_morale[e["id"]] = min(20, k * 60) if k > 0 else k * 80
        events.append(f"Зарплата {e['name']}: {fmt(old)} → {fmt(new)} в месяц.")

    # 4. Найм
    hired_now = set()
    for pid in ev["hire_from_pool"]:
        c = next((x for x in t.get("pool", []) if x["id"] == pid), None)
        if not c:
            continue
        t["pool"] = [x for x in t["pool"] if x["id"] != pid]
        c = dict(c)
        c["hired_round"] = round_no
        t["employees"].append(c)
        hired_now.add(c["id"])
        fee = c["salary"] * 0.5
        one_time.append({"reason": f"Найм: {c['name']}", "amount": fee})
        events.append(f"Нанят(а) {c['name']} ({LEVELS[c['level']]['name']} {ROLES[c['role']]['name']}), {fmt(c['salary'])}/мес.")
    new_count = 0
    for h in ev["hire_new"]:
        for _ in range(h["count"]):
            if new_count >= 6:
                break
            c = make_candidate(rng, next_id, h["role"], h["level"], s)
            next_id += 1
            c["hired_round"] = round_no
            t["employees"].append(c)
            hired_now.add(c["id"])
            new_count += 1
            fee = c["salary"] * 0.7
            one_time.append({"reason": f"Срочный найм: {c['name']}", "amount": fee})
            events.append(f"Срочно нанят(а) {c['name']} ({LEVELS[c['level']]['name']} {ROLES[c['role']]['name']}), {fmt(c['salary'])}/мес.")

    # 5. Бюджеты
    q = t["quarterly"]
    for k, v in ev["budget_changes"].items():
        if q.get(k) != v:
            events.append(f"Бюджет «{BUDGET_NAMES[k]}»: {fmt(q.get(k, 0))} → {fmt(v)} в квартал.")
            q[k] = v

    active = t["employees"]
    n = max(1, len(active))

    # 6. Мораль и рост
    office_ratio = q["office"] / (n * OFFICE_NORM * s)
    train_ratio = q["training"] / (n * TRAINING_NORM * s)
    hr_eff = sum(eff(e) for e in active if e["role"] == "hr")
    hr_cov = min(1.0, hr_eff * 3 / n)
    target_base = 58 + (min(office_ratio, 1.5) - 1) * 20 + min(train_ratio, 2) * 5 + hr_cov * 10
    eff_map = {x["id"]: x for x in ev["employee_effects"]}
    for e in active:
        m = e["morale"]
        stress_factor = 1.3 - e["stress"] * 0.06
        m += imp.get("morale", 0) * f * stress_factor
        m += ev["morale_delta_all"]
        m += sal_morale.get(e["id"], 0)
        x = eff_map.get(e["id"])
        if x:
            m += x["morale_delta"]
        ratio = e["salary"] / market_salary(e["role"], e["level"], s)
        sal_eff = (ratio - 1) * 50 if ratio < 1 else min(15, (ratio - 1) * 30)
        target = target_base + sal_eff + (e["loyalty"] - 5) * 1.5
        m += (target - m) * 0.35
        m -= min(10, fired * 2)
        e["morale"] = round(clamp(m, 0, 100), 1)
        gain = 0.25 * min(train_ratio, 2) * (0.5 if e["level"] == "senior" else 1)
        if x:
            gain += x["prof_delta"]
        e["prof"] = round(clamp(e["prof"] + gain, 1, 10), 2)

    # 7. Текучесть
    quitting = set()
    for e in active:
        if e["morale"] < 40:
            p = (40 - e["morale"]) / 40 * (1.2 - e["loyalty"] / 10) * (1 - 0.5 * hr_cov)
            if rng.random() < clamp(p, 0, 0.8):
                quitting.add(e["id"])
                events.append(f"{e['name']} увольняется по собственному желанию (мораль {e['morale']:.0f}).")

    # 8. Производство и спрос
    def part(e):
        if e["id"] in quitting:
            return 0.5
        if e["id"] in hired_now:
            return 0.7
        return 1.0

    by = {k: 0.0 for k in ROLES}
    for e in active:
        by[e["role"]] += eff(e) * part(e)
    tech = sum(by[k] * ROLES[k]["w"] for k in ROLES if ROLES[k]["kind"] == "tech")
    quality = 0.8 + 0.2 * min(1.0, by["qa"] / (by["dev"] * 0.25)) if by["dev"] > 0 else 1.0
    value = 1 + min(0.15, (by["design"] + by["analyst"]) * 0.02)
    need = tech * SERVER_PER_POINT * s * (1 - min(0.3, by["devops"] * 0.06))
    infra = 1.0 if need <= 0 else clamp(q["servers"] / need, 0.3, 1.0) ** 0.6
    mgmt = 1 + min(0.25, by["pm"] * 0.04) - (0.15 if by["pm"] == 0 and len(active) > 5 else 0)
    capacity = tech * quality * value * infra * mgmt
    rep_factor = 0.5 + t["reputation"] / 100.0
    demand = (DEMAND_BASE + MKT_K * math.sqrt(max(0, q["marketing"]) / (MKT_REF * s)) + SALES_K * by["sales"]) * rep_factor
    lo, hi = min(capacity, demand), max(capacity, demand)
    sold = (lo + 0.15 * (hi - lo)) if capacity > 0 else 0
    crisis_rev = 1 - (1 - clamp(imp.get("revenue_mult", 1.0), 0.3, 1.2)) * f
    revenue = sold * REV_PER_POINT * s * crisis_rev * ev["revenue_mult"]

    # 9. Расходы
    payroll = sum(e["salary"] * 3 * (0.5 if e["id"] in quitting else 1.0) for e in active)
    crisis_cash = -clamp(imp.get("cash_frac", 0), -0.3, 0.1) * cap * f
    if abs(crisis_cash) > 0.5:
        one_time.append({"reason": "Прямые потери от кризиса" if crisis_cash > 0 else "Выгода от кризиса",
                         "amount": crisis_cash})
    one_time.extend(ev["one_time_costs"])
    one_time_total = sum(c["amount"] for c in one_time)
    expenses = {
        "payroll": payroll,
        "training": q["training"],
        "servers": q["servers"],
        "marketing": q["marketing"],
        "office": q["office"],
        "one_time": one_time_total,
    }
    total_exp = sum(expenses.values())
    profit = revenue - total_exp

    for e in list(active):
        if e["id"] in quitting:
            _depart(t, e, "уволился(лась) сам(а) — низкая мораль", round_no)

    t["reputation"] = round(clamp(t["reputation"] + imp.get("reputation", 0) * f + ev["reputation_delta"], 0, 100), 1)
    cash_before = t["cash"]
    t["cash"] = round(cash_before + profit, 2)
    t["total_revenue"] = t.get("total_revenue", 0) + revenue
    t["total_profit"] = t.get("total_profit", 0) + profit
    t["crisis_target"] = None

    staff = t["employees"]
    report = {
        "round": round_no,
        "crisis_title": (crisis or {}).get("title", ""),
        "score": score,
        "verdict": ev["verdict"],
        "revenue": round(revenue, 2),
        "expenses": {k: round(v, 2) for k, v in expenses.items()},
        "one_time_items": [{"reason": c["reason"], "amount": round(c["amount"], 2)} for c in one_time],
        "total_expenses": round(total_exp, 2),
        "profit": round(profit, 2),
        "margin": round(profit / revenue, 4) if revenue > 0 else None,
        "cash_before": round(cash_before, 2),
        "cash": t["cash"],
        "reputation": t["reputation"],
        "headcount": len(staff),
        "avg_morale": round(sum(e["morale"] for e in staff) / len(staff), 1) if staff else 0,
        "events": events,
        "metrics": {
            "capacity": round(capacity, 2), "demand": round(demand, 2), "sold": round(sold, 2),
            "quality": round(quality, 3), "infra": round(infra, 3), "mgmt": round(mgmt, 3),
            "value": round(value, 3), "crisis_damage_share": round(f, 3),
            "crisis_revenue_mult": round(crisis_rev, 3), "ai_revenue_mult": ev["revenue_mult"],
            "hr_coverage": round(hr_cov, 2), "office_ratio": round(office_ratio, 2),
            "training_ratio": round(train_ratio, 2), "servers_needed": round(need, 2),
        },
    }
    t.setdefault("history", []).append(report)
    return t, report, next_id


def leaderboard(teams, settings):
    rows = []
    for t in teams:
        if not t.get("passport_done"):
            continue
        rev = t.get("total_revenue", 0)
        prof = t.get("total_profit", 0)
        rows.append({"id": t["id"], "name": t["name"], "company": t["company"].get("name") or t["name"],
                     "cash": round(t["cash"], 2), "margin": round(prof / rev, 4) if rev > 0 else (-1.0 if prof < 0 else 0.0),
                     "total_profit": round(prof, 2), "headcount": len(t["employees"]),
                     "reputation": t["reputation"]})
    if not rows:
        return rows

    def norm(vals):
        lo, hi = min(vals), max(vals)
        return [1.0 if hi == lo else (v - lo) / (hi - lo) for v in vals]

    nc = norm([r["cash"] for r in rows])
    nm = norm([r["margin"] for r in rows])
    wc, wm = settings.get("w_cash", 60), settings.get("w_margin", 40)
    tot = (wc + wm) or 1
    for r, a, b in zip(rows, nc, nm):
        r["score"] = round(100 * (wc * a + wm * b) / tot, 1)
    rows.sort(key=lambda r: (-r["score"], -r["cash"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows
