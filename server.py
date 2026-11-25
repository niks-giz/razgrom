"""Сервер игры «Кадровый кризис». Запуск: python server.py [порт]"""
import copy
import html
import json
import os
import random
import secrets
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ai
import crises
import engine

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")
STATE_FILE = os.path.join(DATA, "state.json")
CONFIG_FILE = os.path.join(DATA, "config.json")
os.makedirs(DATA, exist_ok=True)

DEFAULT_SETTINGS = {
    "capital": 500000,
    "passport_minutes": 10,
    "round_minutes": 7,
    "rounds": 5,
    "w_cash": 60,
    "w_margin": 40,
    "visibility": "screen",  # hidden | screen | all
    "auto_eval": True,
    "parallel": 2,
}

LOCK = threading.RLock()
STATE = {}
CONFIG = {}
SEM = threading.Semaphore(2)
PORT = 8000


class ApiError(Exception):
    pass


# ---------------------------------------------------------------- состояние

def new_state(settings=None):
    return {
        "version": 1, "game_id": secrets.token_hex(4), "settings": settings or dict(DEFAULT_SETTINGS),
        "phase": "lobby", "round": 0, "deadline": None, "paused_left": None,
        "crisis": None, "crisis_draft": None, "draft_stamp": 0, "gen_status": None, "crisis_history": [],
        "teams": {}, "players": {}, "evals": {}, "next_emp_id": 1, "log": [], "log_seq": 0,
    }


def load():
    global STATE, CONFIG, SEM
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            CONFIG = json.load(f)
    CONFIG.setdefault("llm", dict(ai.DEFAULT_CONFIG))
    for k, v in ai.DEFAULT_CONFIG.items():
        CONFIG["llm"].setdefault(k, v)
    CONFIG.setdefault("host_key", secrets.token_urlsafe(6))
    save_config()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                STATE = json.load(f)
            for k, v in DEFAULT_SETTINGS.items():
                STATE["settings"].setdefault(k, v)
            for ev in STATE["evals"].values():
                if ev.get("status") in ("queued", "running"):
                    ev["status"] = "error"
                    ev["error"] = "Оценка прервана перезапуском сервера"
            if STATE.get("gen_status") == "running":
                STATE["gen_status"] = None
            print("Загружена сохранённая игра (фаза: %s, раунд %s)" % (STATE["phase"], STATE["round"]))
        except Exception:
            traceback.print_exc()
            STATE = new_state()
    else:
        STATE = new_state()
    SEM = threading.Semaphore(max(1, int(STATE["settings"].get("parallel", 2))))


def save_config():
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CONFIG_FILE)


def save():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def bump():
    STATE["version"] += 1
    save()


def add_log(kind, team=None, nick="", ip="", text="", **extra):
    STATE["log_seq"] += 1
    e = {"id": STATE["log_seq"], "ts": time.time(), "round": STATE["round"], "phase": STATE["phase"], "kind": kind,
         "team_id": team["id"] if team else None, "team_name": team["name"] if team else "",
         "nick": nick, "ip": ip, "text": text, "starred": False}
    e.update(extra)
    STATE["log"].append(e)
    with open(os.path.join(DATA, f"log_{STATE['game_id']}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def file_log(record):
    with open(os.path.join(DATA, f"log_{STATE['game_id']}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- помощники

CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gen_code():
    used = {t["code"] for t in STATE["teams"].values()}
    while True:
        c = "".join(random.choice(CODE_CHARS) for _ in range(4))
        if c not in used:
            return c


def time_left():
    if STATE["paused_left"] is not None:
        return STATE["paused_left"]
    if STATE["deadline"] is None:
        return None
    return max(0.0, STATE["deadline"] - time.time())


def player(token):
    p = STATE["players"].get(token or "")
    if not p or p["team"] not in STATE["teams"]:
        raise ApiError("NO_PLAYER")
    return p, STATE["teams"][p["team"]]


def require_captain(token):
    p, t = player(token)
    if t["captain"] != token:
        raise ApiError("Это может делать только капитан команды")
    return p, t


def teams_list():
    return sorted(STATE["teams"].values(), key=lambda t: int(t["id"][1:]))


def target_employee(t):
    if not t["employees"]:
        return None
    return max(t["employees"], key=lambda e: (e["prof"], e["salary"]))


def target_text_for(t, crisis):
    if not crisis or crisis.get("target") != "top" or t.get("crisis_target") is None:
        return ""
    e = next((x for x in t["employees"] if x["id"] == t["crisis_target"]), None)
    if not e:
        return ""
    tpl = crisis.get("target_text") or "Речь о вашем сотруднике: {name} ({role}, {level})."
    try:
        return tpl.format(name=e["name"], role=engine.ROLES[e["role"]]["name"], level=engine.LEVELS[e["level"]]["name"],
                          salary=engine.fmt(e["salary"]), trait=e["trait"])
    except (KeyError, IndexError, ValueError):
        return f"Речь о вашем сотруднике: {e['name']} ({engine.ROLES[e['role']]['name']})."


def new_team(name, token, nick, ip):
    n = 1
    while f"t{n}" in STATE["teams"]:
        n += 1
    cap = STATE["settings"]["capital"]
    return {
        "id": f"t{n}", "name": name, "code": gen_code(), "captain": token,
        "members": [{"token": token, "nick": nick, "ip": ip, "joined": time.time()}],
        "company": {"name": "", "direction": engine.DIRECTIONS[0], "mission": ""},
        "budget_draft": engine.default_budget(cap), "budget": None, "budget_confirmed": False,
        "pool": [], "employees": [], "departed": [], "passport_done": False,
        "quarterly": {k: 0 for k in engine.QUARTERLY_KEYS}, "cash": cap, "reputation": 50.0,
        "history": [], "answers": {}, "draft": {"text": "", "ts": 0, "by": ""},
        "crisis_target": None, "total_revenue": 0.0, "total_profit": 0.0,
    }


def check_budget(b):
    cap = STATE["settings"]["capital"]
    out = {}
    for k in engine.BUDGET_KEYS:
        if k == "reserve":
            continue
        try:
            v = int(float(b.get(k, 0) or 0))
        except (TypeError, ValueError):
            raise ApiError(f"Некорректная сумма: {engine.BUDGET_NAMES[k]}")
        if v < 0:
            raise ApiError("Суммы не могут быть отрицательными")
        out[k] = v
    total = sum(out.values())
    if total > cap:
        raise ApiError(f"Превышен капитал: распределено {engine.fmt(total)} из {engine.fmt(cap)}")
    out["reserve"] = cap - total
    return out


def confirm_budget(t, b):
    t["budget"] = b
    t["budget_confirmed"] = True
    rng = random.Random(f"{STATE['game_id']}-pool-{t['id']}")
    pool, STATE["next_emp_id"] = engine.generate_pool(rng, b["recruiting"], STATE["settings"]["capital"], STATE["next_emp_id"])
    t["pool"] = pool


def finish_passport(t, nick="", ip=""):
    if t["passport_done"]:
        return
    if not t["budget_confirmed"]:
        try:
            b = check_budget(t["budget_draft"])
        except ApiError:
            b = engine.default_budget(STATE["settings"]["capital"])
        confirm_budget(t, b)
    b = t["budget"]
    t["passport_done"] = True
    t["quarterly"] = {k: b[k] for k in engine.QUARTERLY_KEYS}
    t["cash"] = STATE["settings"]["capital"] - b["recruiting"]
    if not t["company"]["name"]:
        t["company"]["name"] = t["name"]
    staff = "; ".join(f"{e['name']} ({engine.LEVELS[e['level']]['name']} {engine.ROLES[e['role']]['name']}, {e['salary']})"
                      for e in t["employees"])
    add_log("passport", t, nick, ip,
            f"Компания: {t['company']['name']}\nНаправление: {t['company']['direction']}\nМиссия: {t['company']['mission']}\n"
            f"Бюджет: " + ", ".join(f"{engine.BUDGET_NAMES[k]} — {b[k]}" for k in engine.BUDGET_KEYS) +
            f"\nШтат ({len(t['employees'])}): {staff}")


# ---------------------------------------------------------------- фазы

def start_passport():
    if STATE["phase"] != "lobby":
        raise ApiError("Паспорт можно начать только из лобби")
    STATE["phase"] = "passport"
    STATE["deadline"] = time.time() + STATE["settings"]["passport_minutes"] * 60
    STATE["paused_left"] = None
    add_log("system", text="Начат этап паспорта организации")


def end_passport():
    for t in teams_list():
        finish_passport(t)
    STATE["phase"] = "prep"
    STATE["deadline"] = None
    STATE["paused_left"] = None
    add_log("system", text="Этап паспорта завершён")


def start_round(c):
    if STATE["phase"] != "prep":
        raise ApiError("Раунд можно начать только на этапе подготовки")
    if not c or not str(c.get("title", "")).strip() or not str(c.get("text", "")).strip():
        raise ApiError("Укажите название и описание кризиса")
    imp = c.get("impact") or {}
    crisis = {
        "id": c.get("id") or "custom",
        "title": str(c["title"]).strip()[:200], "text": str(c["text"]).strip()[:4000],
        "impact": {"revenue_mult": engine.clamp(imp.get("revenue_mult", 0.85), 0.3, 1.2),
                   "morale": engine.clamp(imp.get("morale", -10), -40, 20),
                   "reputation": engine.clamp(imp.get("reputation", 0), -30, 20),
                   "cash_frac": engine.clamp(imp.get("cash_frac", 0), -0.3, 0.1)},
        "target": "top" if c.get("target") == "top" else None,
        "target_text": str(c.get("target_text") or "")[:500],
    }
    STATE["round"] += 1
    STATE["crisis"] = crisis
    STATE["evals"] = {}
    for t in teams_list():
        t["draft"] = {"text": "", "ts": 0, "by": ""}
        e = target_employee(t) if crisis["target"] == "top" else None
        t["crisis_target"] = e["id"] if e else None
    STATE["phase"] = "round"
    STATE["deadline"] = time.time() + STATE["settings"]["round_minutes"] * 60
    STATE["paused_left"] = None
    add_log("system", text=f"Раунд {STATE['round']}: {crisis['title']}\n{crisis['text']}")


def end_round():
    if STATE["phase"] != "round":
        raise ApiError("Сейчас не идёт раунд")
    rk = str(STATE["round"])
    for t in teams_list():
        if not t["passport_done"]:
            continue
        if rk not in t["answers"] and t["draft"]["text"].strip():
            t["answers"][rk] = {"text": t["draft"]["text"], "ts": time.time(), "by": t["draft"]["by"], "auto": True}
            add_log("answer", t, t["draft"]["by"], "", t["draft"]["text"], auto=True)
    STATE["phase"] = "review"
    STATE["deadline"] = None
    STATE["paused_left"] = None
    if STATE["settings"].get("auto_eval", True):
        start_eval([t["id"] for t in teams_list() if t["passport_done"]])


NO_ANSWER = {"score": 1, "verdict": "Команда не дала ответа. Пока руководство молчало, кризис развивался сам по себе.",
             "host_comment": "Нет ответа"}


def start_eval(ids):
    for tid in ids:
        if tid not in STATE["teams"]:
            continue
        cur = STATE["evals"].get(tid)
        if cur and cur.get("status") in ("queued", "running"):
            continue
        stamp = (cur or {}).get("stamp", 0) + 1
        STATE["evals"][tid] = {"status": "queued", "result": None, "raw": "", "error": "", "preview": None,
                               "stamp": stamp, "edited": False}
        threading.Thread(target=eval_worker, args=(tid, stamp), daemon=True).start()


def eval_worker(tid, stamp):
    with LOCK:
        t = copy.deepcopy(STATE["teams"][tid])
        settings = dict(STATE["settings"])
        crisis = copy.deepcopy(STATE["crisis"])
        rnd = STATE["round"]
        ans = t["answers"].get(str(rnd))
        cfg = dict(CONFIG["llm"])
        ttext = target_text_for(t, crisis)
    result, raw, err = None, "", ""
    if not ans or not ans["text"].strip():
        result = dict(NO_ANSWER)
    else:
        with SEM:
            with LOCK:
                ev = STATE["evals"].get(tid)
                if not ev or ev["stamp"] != stamp:
                    return
                ev["status"] = "running"
                ev["started"] = time.time()
                bump()
            try:
                result, raw = ai.evaluate(cfg, t, settings, crisis, rnd, ans["text"], ttext)
            except Exception as e:
                err = str(e)
                result = {"score": 5, "verdict": "Нейросеть не смогла оценить ответ, оценку выставит ведущий.",
                          "host_comment": "Ошибка нейросети: " + err[:300]}
    with LOCK:
        ev = STATE["evals"].get(tid)
        if not ev or ev["stamp"] != stamp:
            return
        ev["result"] = engine.normalize_eval(result, t, settings)
        ev["raw"] = raw
        ev["error"] = err
        ev["status"] = "error" if err else "done"
        compute_preview(tid)
        attach_eval_to_log(tid)
        file_log({"kind": "ai_eval", "ts": time.time(), "round": rnd, "team_id": tid, "raw": raw, "error": err,
                  "result": ev["result"]})
        bump()


def seed_for(tid):
    return f"{STATE['game_id']}-{STATE['round']}-{tid}"


def compute_preview(tid):
    ev = STATE["evals"][tid]
    t = STATE["teams"][tid]
    try:
        _, report, _ = engine.simulate(t, STATE["settings"], STATE["crisis"], ev["result"], STATE["round"],
                                       seed_for(tid), STATE["next_emp_id"])
        ev["preview"] = report
    except Exception as e:
        traceback.print_exc()
        ev["preview"] = None
        ev["error"] = "Ошибка расчёта: " + str(e)


def attach_eval_to_log(tid):
    r = STATE["evals"][tid]["result"]
    for e in reversed(STATE["log"]):
        if e["kind"] == "answer" and e["team_id"] == tid and e["round"] == STATE["round"]:
            e["score"] = r["score"]
            e["cheat"] = r["cheat"]
            e["cheat_reason"] = r["cheat_reason"]
            e["funny"] = r["funny"]
            e["funny_comment"] = r["funny_comment"]
            e["verdict"] = r["verdict"]
            break


def apply_round():
    if STATE["phase"] != "review":
        raise ApiError("Сейчас не этап оценки")
    ids = [t["id"] for t in teams_list() if t["passport_done"]]
    missing = [STATE["teams"][i]["name"] for i in ids
               if STATE["evals"].get(i, {}).get("status") not in ("done", "error") or not STATE["evals"][i].get("result")]
    if missing:
        raise ApiError("Ещё не оценены: " + ", ".join(missing))
    for i in ids:
        t = STATE["teams"][i]
        new_t, report, STATE["next_emp_id"] = engine.simulate(t, STATE["settings"], STATE["crisis"],
                                                              STATE["evals"][i]["result"], STATE["round"],
                                                              seed_for(i), STATE["next_emp_id"])
        STATE["teams"][i] = new_t
        file_log({"kind": "round_result", "ts": time.time(), "round": STATE["round"], "team_id": i, "report": report})
    STATE["crisis_history"].append({"round": STATE["round"], "title": STATE["crisis"]["title"]})
    STATE["phase"] = "results"
    add_log("system", text=f"Результаты раунда {STATE['round']} применены")


def is_last_round():
    return STATE["round"] >= STATE["settings"]["rounds"]


# ---------------------------------------------------------------- представления

def leaderboard():
    return engine.leaderboard(teams_list(), STATE["settings"])


def public_team(t, full=True):
    s = engine.scale(STATE["settings"])
    d = {k: v for k, v in t.items() if k not in ("captain", "members", "answers")}
    d["members"] = [m["nick"] for m in t["members"]]
    d["captain_nick"] = next((m["nick"] for m in t["members"] if m["token"] == t["captain"]), "")
    for key in ("employees", "pool"):
        d[key] = [dict(e, market=round(engine.market_salary(e["role"], e["level"], s))) for e in t[key]]
    d["payroll_q"] = engine.quarterly_payroll(t)
    return d


def common_view():
    return {"version": STATE["version"], "now": time.time(), "phase": STATE["phase"], "round": STATE["round"],
            "rounds": STATE["settings"]["rounds"], "time_left": time_left(), "paused": STATE["paused_left"] is not None,
            "capital": STATE["settings"]["capital"], "visibility": STATE["settings"]["visibility"],
            "last_round": is_last_round()}


def player_view(token):
    p, t = player(token)
    v = common_view()
    rk = str(STATE["round"])
    v["nick"] = p["nick"]
    v["is_captain"] = t["captain"] == token
    v["team"] = public_team(t)
    if STATE["phase"] in ("round", "review", "results") and STATE["crisis"]:
        c = STATE["crisis"]
        v["crisis"] = {"title": c["title"], "text": c["text"], "personal": target_text_for(t, c)}
    v["answer"] = t["answers"].get(rk) if STATE["phase"] in ("round", "review", "results") else None
    v["draft"] = t["draft"]
    v["leaderboard"] = leaderboard() if (STATE["settings"]["visibility"] == "all" or STATE["phase"] == "final") else None
    return v


def screen_view():
    v = common_view()
    rk = str(STATE["round"])
    if STATE["crisis"] and STATE["phase"] in ("round", "review", "results"):
        v["crisis"] = {"title": STATE["crisis"]["title"], "text": STATE["crisis"]["text"]}
    v["teams"] = [{"name": t["name"], "company": t["company"].get("name") or "", "members": len(t["members"]),
                   "budget_confirmed": t["budget_confirmed"], "passport_done": t["passport_done"],
                   "submitted": rk in t["answers"], "eval": STATE["evals"].get(t["id"], {}).get("status")}
                  for t in teams_list()]
    show = STATE["settings"]["visibility"] in ("screen", "all") or STATE["phase"] == "final"
    v["leaderboard"] = leaderboard() if show else None
    v["urls"] = [f"http://{ip}:{PORT}" for ip in lan_ips()]
    return v


def host_view():
    v = common_view()
    v["settings"] = STATE["settings"]
    v["game_id"] = STATE["game_id"]
    v["crisis"] = STATE["crisis"]
    v["crisis_draft"] = STATE["crisis_draft"]
    v["draft_stamp"] = STATE["draft_stamp"]
    v["gen_status"] = STATE["gen_status"]
    v["crisis_history"] = STATE["crisis_history"]
    rk = str(STATE["round"])
    teams = []
    for t in teams_list():
        d = public_team(t)
        d["members_full"] = [{"nick": m["nick"], "ip": m["ip"], "captain": m["token"] == t["captain"], "idx": i}
                             for i, m in enumerate(t["members"])]
        d["answer"] = t["answers"].get(rk)
        d["target_text"] = target_text_for(t, STATE["crisis"]) if STATE["phase"] in ("round", "review") else ""
        teams.append(d)
    v["teams"] = teams
    v["evals"] = STATE["evals"]
    v["leaderboard"] = leaderboard()
    v["log"] = STATE["log"]
    v["presets"] = crises.PRESETS
    v["llm"] = {k: v2 for k, v2 in CONFIG["llm"].items() if k != "api_key"}
    v["llm"]["has_key"] = bool(CONFIG["llm"].get("api_key"))
    v["urls"] = [f"http://{ip}:{PORT}" for ip in lan_ips()]
    return v


def meta():
    return {"roles": engine.ROLES, "levels": engine.LEVELS, "budget_keys": engine.BUDGET_KEYS,
            "budget_names": engine.BUDGET_NAMES, "directions": engine.DIRECTIONS,
            "quarterly_keys": engine.QUARTERLY_KEYS,
            "norms": {"office": engine.OFFICE_NORM, "training": engine.TRAINING_NORM}}


# ---------------------------------------------------------------- API игроков

def api_join(body, ip):
    nick = str(body.get("nick", "")).strip()[:30]
    if not nick:
        raise ApiError("Введите имя")
    token = secrets.token_urlsafe(16)
    if body.get("action") == "create":
        if STATE["phase"] not in ("lobby", "passport"):
            raise ApiError("Игра уже идёт — новые команды создавать нельзя, присоединяйтесь по коду")
        name = str(body.get("team_name", "")).strip()[:40]
        if not name:
            raise ApiError("Введите название команды")
        if any(t["name"].lower() == name.lower() for t in STATE["teams"].values()):
            raise ApiError("Команда с таким названием уже есть")
        t = new_team(name, token, nick, ip)
        STATE["teams"][t["id"]] = t
    else:
        code = str(body.get("code", "")).strip().upper()
        t = next((x for x in STATE["teams"].values() if x["code"] == code), None)
        if not t:
            raise ApiError("Команда с таким кодом не найдена")
        t["members"].append({"token": token, "nick": nick, "ip": ip, "joined": time.time()})
    STATE["players"][token] = {"team": t["id"], "nick": nick, "ip": ip}
    add_log("join", t, nick, ip, f"{nick} вошёл(ла) в команду")
    bump()
    return {"token": token}


def api_passport_draft(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "passport" or t["passport_done"]:
        raise ApiError("Паспорт сейчас нельзя менять")
    c = body.get("company") or {}
    t["company"]["name"] = str(c.get("name", t["company"]["name"]))[:60]
    d = str(c.get("direction", t["company"]["direction"]))
    t["company"]["direction"] = d[:60]
    t["company"]["mission"] = str(c.get("mission", t["company"]["mission"]))[:1500]
    if not t["budget_confirmed"] and isinstance(body.get("budget"), dict):
        b = {}
        for k in engine.BUDGET_KEYS:
            try:
                b[k] = max(0, int(float(body["budget"].get(k, 0) or 0)))
            except (TypeError, ValueError):
                b[k] = 0
        t["budget_draft"] = b
    bump()
    return {"ok": True}


def api_budget_confirm(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "passport" or t["budget_confirmed"]:
        raise ApiError("Бюджет уже утверждён или этап закончился")
    b = check_budget(body.get("budget") or {})
    t["budget_draft"] = b
    confirm_budget(t, b)
    bump()
    return {"ok": True}


def api_hire(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "passport" or not t["budget_confirmed"] or t["passport_done"]:
        raise ApiError("Сейчас нельзя нанимать")
    cid = int(body.get("id"))
    if body.get("hire"):
        c = next((x for x in t["pool"] if x["id"] == cid), None)
        if not c:
            raise ApiError("Кандидат не найден")
        if engine.quarterly_payroll(t) + c["salary"] * 3 > t["budget"]["payroll"]:
            raise ApiError("Не хватает ФОТ на этого кандидата")
        t["pool"].remove(c)
        t["employees"].append(c)
    else:
        c = next((x for x in t["employees"] if x["id"] == cid), None)
        if not c:
            raise ApiError("Сотрудник не найден")
        t["employees"].remove(c)
        t["pool"].append(c)
        order = {k: i for i, k in enumerate(engine.ROLES)}
        lv = {"senior": 0, "middle": 1, "junior": 2}
        t["pool"].sort(key=lambda x: (order[x["role"]], lv[x["level"]]))
    bump()
    return {"ok": True}


def api_passport_finish(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "passport" or not t["budget_confirmed"]:
        raise ApiError("Сначала утвердите бюджет")
    finish_passport(t, p["nick"], ip)
    bump()
    return {"ok": True}


def api_answer_draft(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "round":
        return {"ok": False}
    t["draft"] = {"text": str(body.get("text", ""))[:4000], "ts": time.time(), "by": p["nick"]}
    bump()
    return {"ok": True}


def api_answer_submit(body, ip):
    p, t = require_captain(body.get("token"))
    if STATE["phase"] != "round":
        raise ApiError("Время на ответ вышло")
    if not t["passport_done"]:
        raise ApiError("Ваша команда не прошла этап паспорта")
    text = str(body.get("text", "")).strip()[:4000]
    if len(text) < 5:
        raise ApiError("Ответ слишком короткий")
    rk = str(STATE["round"])
    t["answers"][rk] = {"text": text, "ts": time.time(), "by": p["nick"], "auto": False}
    t["draft"] = {"text": text, "ts": time.time(), "by": p["nick"]}
    add_log("answer", t, p["nick"], ip, text, auto=False)
    bump()
    return {"ok": True}


# ---------------------------------------------------------------- API ведущего

def host_action(body):
    global SEM
    a = body.get("action")
    s = STATE["settings"]
    if a == "settings":
        new = body.get("settings") or {}
        if "capital" in new and STATE["phase"] != "lobby" and int(new["capital"]) != s["capital"]:
            raise ApiError("Капитал можно менять только до начала игры")
        for k, typ in (("capital", int), ("passport_minutes", float), ("round_minutes", float), ("rounds", int),
                       ("w_cash", float), ("w_margin", float), ("parallel", int)):
            if k in new:
                s[k] = typ(new[k])
        s["capital"] = max(10000, s["capital"])
        s["rounds"] = max(1, s["rounds"])
        if "visibility" in new and new["visibility"] in ("hidden", "screen", "all"):
            s["visibility"] = new["visibility"]
        if "auto_eval" in new:
            s["auto_eval"] = bool(new["auto_eval"])
        if STATE["phase"] == "lobby":
            for t in STATE["teams"].values():
                t["cash"] = s["capital"]
                t["budget_draft"] = engine.default_budget(s["capital"])
        SEM = threading.Semaphore(max(1, s["parallel"]))
    elif a == "start_passport":
        start_passport()
    elif a == "end_passport":
        if STATE["phase"] != "passport":
            raise ApiError("Сейчас не этап паспорта")
        end_passport()
    elif a == "extend":
        sec = float(body.get("seconds", 60))
        if STATE["paused_left"] is not None:
            STATE["paused_left"] = max(0, STATE["paused_left"] + sec)
        elif STATE["deadline"] is not None:
            STATE["deadline"] = max(time.time(), STATE["deadline"] + sec)
    elif a == "pause":
        if STATE["deadline"] is not None and STATE["paused_left"] is None:
            STATE["paused_left"] = time_left()
            STATE["deadline"] = None
    elif a == "resume":
        if STATE["paused_left"] is not None:
            STATE["deadline"] = time.time() + STATE["paused_left"]
            STATE["paused_left"] = None
    elif a == "pick_preset":
        c = crises.get(body.get("id"))
        if not c:
            raise ApiError("Нет такого кризиса")
        STATE["crisis_draft"] = c
        STATE["draft_stamp"] += 1
    elif a == "generate_crisis":
        if STATE["gen_status"] == "running":
            raise ApiError("Генерация уже идёт")
        STATE["gen_status"] = "running"
        threading.Thread(target=gen_worker, args=(str(body.get("wish", ""))[:500],), daemon=True).start()
    elif a == "start_round":
        start_round(body.get("crisis"))
    elif a == "end_round":
        end_round()
    elif a == "evaluate":
        if STATE["phase"] != "review":
            raise ApiError("Оценка возможна только после окончания раунда")
        ids = body.get("ids") or [t["id"] for t in teams_list() if t["passport_done"]]
        start_eval(ids)
    elif a == "edit_eval":
        tid = body.get("team_id")
        ev = STATE["evals"].get(tid)
        if STATE["phase"] != "review" or not ev or ev["status"] in ("queued", "running"):
            raise ApiError("Сейчас нельзя редактировать эту оценку")
        res = body.get("result")
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except json.JSONDecodeError as e:
                raise ApiError(f"Некорректный JSON: {e}")
        ev["result"] = engine.normalize_eval(res, STATE["teams"][tid], s)
        ev["edited"] = True
        ev["status"] = "done"
        ev["error"] = ""
        compute_preview(tid)
        attach_eval_to_log(tid)
        file_log({"kind": "host_edit_eval", "ts": time.time(), "round": STATE["round"], "team_id": tid, "result": ev["result"]})
    elif a == "apply_round":
        apply_round()
    elif a == "next_round":
        if STATE["phase"] != "results":
            raise ApiError("Сейчас нельзя")
        if is_last_round():
            raise ApiError("Это был последний раунд — подведите итоги (или увеличьте число раундов в настройках)")
        STATE["phase"] = "prep"
        STATE["crisis_draft"] = None
        STATE["draft_stamp"] += 1
    elif a == "finish":
        if STATE["phase"] not in ("results", "prep"):
            raise ApiError("Итоги можно подвести после применения результатов раунда")
        STATE["phase"] = "final"
        lb = leaderboard()
        add_log("system", text="Итоги: " + "; ".join(f"{r['rank']}. {r['name']} — {r['score']}" for r in lb))
        file_log({"kind": "final", "ts": time.time(), "leaderboard": lb})
    elif a == "star":
        for e in STATE["log"]:
            if e["id"] == body.get("id"):
                e["starred"] = not e.get("starred")
    elif a == "set_captain":
        t = STATE["teams"].get(body.get("team_id"))
        if not t:
            raise ApiError("Нет команды")
        t["captain"] = t["members"][int(body.get("idx"))]["token"]
    elif a == "kick_member":
        t = STATE["teams"].get(body.get("team_id"))
        m = t["members"][int(body.get("idx"))]
        if m["token"] == t["captain"] and len(t["members"]) > 1:
            raise ApiError("Сначала назначьте другого капитана")
        t["members"].remove(m)
        STATE["players"].pop(m["token"], None)
        if not t["members"]:
            del STATE["teams"][t["id"]]
    elif a == "delete_team":
        t = STATE["teams"].pop(body.get("team_id"), None)
        if t:
            for m in t["members"]:
                STATE["players"].pop(m["token"], None)
            STATE["evals"].pop(t["id"], None)
    elif a == "rename_team":
        t = STATE["teams"].get(body.get("team_id"))
        if t:
            t["name"] = str(body.get("name", t["name"]))[:40]
    elif a == "adjust_cash":
        t = STATE["teams"].get(body.get("team_id"))
        if t:
            delta = float(body.get("delta", 0))
            t["cash"] += delta
            add_log("system", t, text=f"Ведущий скорректировал деньги: {delta:+.0f} BYN. Причина: {body.get('reason', '')}")
    elif a == "reset":
        if body.get("confirm") != "RESET":
            raise ApiError("Нужно подтверждение")
        old = STATE["game_id"]
        STATE.clear()
        STATE.update(new_state(dict(s)))
        print(f"Игра {old} сброшена, новая игра {STATE['game_id']}")
    elif a == "llm":
        cfg = body.get("llm") or {}
        for k in ("base_url", "model"):
            if k in cfg:
                CONFIG["llm"][k] = str(cfg[k]).strip()
        if cfg.get("api_key"):
            CONFIG["llm"]["api_key"] = str(cfg["api_key"]).strip()
        if cfg.get("clear_key"):
            CONFIG["llm"]["api_key"] = ""
        for k, typ in (("temperature", float), ("timeout", float)):
            if k in cfg:
                CONFIG["llm"][k] = typ(cfg[k])
        if "json_mode" in cfg:
            CONFIG["llm"]["json_mode"] = bool(cfg["json_mode"])
        save_config()
    else:
        raise ApiError("Неизвестное действие")
    bump()
    return {"ok": True}


def gen_worker(wish):
    with LOCK:
        cfg = dict(CONFIG["llm"])
        rnd = STATE["round"] + 1
        total = STATE["settings"]["rounds"]
        prev = [c["title"] for c in STATE["crisis_history"]]
    try:
        c, raw = ai.generate_crisis(cfg, rnd, total, prev, wish)
        with LOCK:
            STATE["crisis_draft"] = c
            STATE["draft_stamp"] += 1
            STATE["gen_status"] = None
            file_log({"kind": "ai_crisis", "ts": time.time(), "raw": raw})
            bump()
    except Exception as e:
        with LOCK:
            STATE["gen_status"] = "Ошибка: " + str(e)[:400]
            bump()


def export_html():
    rows = []
    for e in STATE["log"]:
        if e["kind"] not in ("answer", "passport"):
            continue
        ts = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
        extra = ""
        if e.get("score") is not None:
            extra = (f"<p><b>Балл:</b> {e['score']} &nbsp; <b>Смешно:</b> {e.get('funny', 0)}/10 "
                     f"{'&nbsp; <b style=color:red>ПОДОЗРЕНИЕ НА ЧИТ:</b> ' + html.escape(e.get('cheat_reason', '')) if e.get('cheat') else ''}</p>"
                     f"<p><i>{html.escape(e.get('verdict', ''))}</i></p>")
        rows.append(f"<div class=e><h3>{'★ ' if e.get('starred') else ''}Раунд {e['round']} · {html.escape(e['team_name'])} · "
                    f"{html.escape(e['nick'])} · {ts} · {e['kind']}{' (авто)' if e.get('auto') else ''}</h3>"
                    f"<pre>{html.escape(e['text'])}</pre>{extra}</div>")
    lb = leaderboard()
    lbh = "".join(f"<tr><td>{r['rank']}</td><td>{html.escape(r['name'])}</td><td>{engine.fmt(r['cash'])}</td>"
                  f"<td>{r['margin'] * 100:.1f}%</td><td>{r['score']}</td></tr>" for r in lb)
    return (f"<!doctype html><meta charset=utf-8><title>Журнал игры {STATE['game_id']}</title>"
            "<style>body{font-family:sans-serif;max-width:900px;margin:auto}pre{white-space:pre-wrap;background:#f4f4f4;padding:8px}"
            ".e{border-bottom:1px solid #ccc;padding:6px 0}td,th{padding:4px 10px;border:1px solid #ccc}</style>"
            f"<h1>Журнал игры {STATE['game_id']}</h1><table><tr><th>#</th><th>Команда</th><th>Деньги</th>"
            f"<th>Рентабельность</th><th>Балл</th></tr>{lbh}</table>" + "".join(rows))


# ---------------------------------------------------------------- HTTP

def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    ips = [ip for ip in ips if not ip.startswith("127.")]
    return sorted(ips) or ["127.0.0.1"]


LOCAL_CACHE = {"ips": set(), "ts": 0}


def is_local(ip):
    if ip.startswith("127.") or ip in ("::1", "localhost"):
        return True
    if time.time() - LOCAL_CACHE["ts"] > 30:
        LOCAL_CACHE["ips"] = set(lan_ips())
        LOCAL_CACHE["ts"] = time.time()
    return ip in LOCAL_CACHE["ips"]


MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}

PLAYER_POST = {
    "/api/join": api_join,
    "/api/passport/draft": api_passport_draft,
    "/api/passport/budget": api_budget_confirm,
    "/api/passport/hire": api_hire,
    "/api/passport/finish": api_passport_finish,
    "/api/answer/draft": api_answer_draft,
    "/api/answer/submit": api_answer_submit,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def ip(self):
        return self.client_address[0]

    def host_ok(self, qs):
        key = self.headers.get("X-Host-Key") or (qs.get("key") or [""])[0]
        return is_local(self.ip()) or key == CONFIG.get("host_key")

    def send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(data, (bytes, bytearray)):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def static(self, name):
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self.send(404, {"error": "not found"})
        with open(path, "rb") as f:
            self.send(200, f.read(), MIME.get(os.path.splitext(path)[1], "application/octet-stream"))

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path == "/":
                return self.static("index.html")
            if u.path == "/screen":
                return self.static("screen.html")
            if u.path == "/host":
                if not self.host_ok(qs):
                    return self.send(403, "Панель ведущего доступна только на компьютере хоста".encode("utf-8"),
                                     "text/plain; charset=utf-8")
                return self.static("host.html")
            if u.path.startswith("/static/"):
                return self.static(u.path[len("/static/"):])
            if u.path == "/api/meta":
                return self.send(200, meta())
            since = int((qs.get("v") or ["0"])[0] or 0)
            if u.path == "/api/me":
                with LOCK:
                    if since == STATE["version"]:
                        return self.send(200, {"unchanged": True, "now": time.time(), "time_left": time_left()})
                    return self.send(200, player_view((qs.get("token") or [""])[0]))
            if u.path == "/api/screen":
                with LOCK:
                    if since == STATE["version"]:
                        return self.send(200, {"unchanged": True, "now": time.time(), "time_left": time_left()})
                    return self.send(200, screen_view())
            if u.path.startswith("/api/host/"):
                if not self.host_ok(qs):
                    return self.send(403, {"error": "Доступ только для ведущего"})
                with LOCK:
                    if u.path == "/api/host/state":
                        if since == STATE["version"]:
                            return self.send(200, {"unchanged": True, "now": time.time(), "time_left": time_left()})
                        return self.send(200, host_view())
                    if u.path == "/api/host/export":
                        return self.send(200, export_html().encode("utf-8"), "text/html; charset=utf-8",
                                         {"Content-Disposition": f"attachment; filename=log_{STATE['game_id']}.html"})
            self.send(404, {"error": "not found"})
        except ApiError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": "Ошибка сервера: " + str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
            if u.path in PLAYER_POST:
                with LOCK:
                    return self.send(200, PLAYER_POST[u.path](body, self.ip()))
            if u.path == "/api/host/action":
                if not self.host_ok(qs):
                    return self.send(403, {"error": "Доступ только для ведущего"})
                with LOCK:
                    return self.send(200, host_action(body))
            if u.path == "/api/host/llm_test":
                if not self.host_ok(qs):
                    return self.send(403, {"error": "Доступ только для ведущего"})
                with LOCK:
                    cfg = dict(CONFIG["llm"])
                t0 = time.time()
                try:
                    out = ai.test(cfg)
                    return self.send(200, {"ok": True, "reply": out[:1000], "seconds": round(time.time() - t0, 1)})
                except Exception as e:
                    return self.send(200, {"ok": False, "error": str(e)})
            self.send(404, {"error": "not found"})
        except ApiError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": "Ошибка сервера: " + str(e)})


def ticker():
    while True:
        time.sleep(0.5)
        try:
            with LOCK:
                if STATE["deadline"] is not None and STATE["paused_left"] is None and time.time() >= STATE["deadline"]:
                    if STATE["phase"] == "passport":
                        end_passport()
                    elif STATE["phase"] == "round":
                        end_round()
                    else:
                        STATE["deadline"] = None
                    bump()
        except Exception:
            traceback.print_exc()


def main():
    global PORT
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    load()
    threading.Thread(target=ticker, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    print("=" * 60)
    print(" Игра «Кадровый кризис» запущена")
    print(f" Панель ведущего:  http://localhost:{PORT}/host")
    print(f" Экран проектора:  http://localhost:{PORT}/screen")
    print(" Адрес для игроков (телефоны/ноутбуки в той же сети):")
    for ip in lan_ips():
        print(f"     http://{ip}:{PORT}")
    print(f" Ключ ведущего для входа с другого устройства: /host?key={CONFIG['host_key']}")
    print(" Остановить: Ctrl+C")
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Остановлено")


if __name__ == "__main__":
    main()
