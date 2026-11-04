"""Javohir AI — Telegram kanal avtopiloti.

Har ishga tushganda (GitHub Actions har 15 daqiqada chaqiradi):
  1. Botga kelgan xabar va tugma bosishlarni o'qiydi (✅ / ❌ tasdiqlash).
  2. Jadvaldagi vaqti kelgan ishlarni bajaradi: yangilik, maslahat, reels, navbat.
     Har bir post avval adminga qoralama bo'lib boradi, ✅ bosilsa kanalga chiqadi.
  3. Holatni state.json ga yozadi (workflow uni repoga qaytarib saqlaydi).

Lokal sinov:  python bot.py --dry --force news
"""
import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys

import feedparser
import requests

ROOT = pathlib.Path(__file__).parent
CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
STATE_PATH = ROOT / "state.json"
CONTENT = ROOT / "content"
TZ = dt.timezone(dt.timedelta(hours=CONFIG.get("utc_offset", 5)))

# Nusxalashda qo'shilib qoladigan bo'sh joy, yangi qator va boshqa ortiqcha qismlarni tozalaymiz
_tok = re.search(r"\d{6,}:[\w-]{30,}", os.environ.get("BOT_TOKEN", ""))
TOKEN = _tok.group(0) if _tok else ""
ADMIN_ID = re.sub(r"[^\d-]", "", os.environ.get("ADMIN_ID", "") or str(CONFIG.get("admin_id", "")))
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", CONFIG.get("gemini_model", "gemini-2.5-flash"))

DRY = False
_dry_ids = iter(range(1000, 10**6))

KIND_LABEL = {
    "news": "📰 Yangilik",
    "tip": "💡 AI maslahat",
    "reel": "🎬 Reels video",
    "queue": "🗓 Rejalashtirilgan post",
    "manual": "✍️ Sizning postingiz",
}


# ---------------------------------------------------------------- Telegram

def tg(method, files=None, **params):
    if DRY:
        shown = {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v) for k, v in params.items()}
        print(f"[DRY] {method} {json.dumps(shown, ensure_ascii=False)}" + (f" files={list(files)}" if files else ""))
        if method == "getUpdates":
            return []
        return {"message_id": next(_dry_ids)}
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", data=params, files=files, timeout=120)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {method}: {j.get('description')}")
    return j["result"]


def keyboard(rows):
    return json.dumps({"inline_keyboard": rows})


def make_draft(state, kind, key, text=None, video=None, photo=None):
    """Postni adminga yuboradi va ostiga ✅/❌ tugmali xabar qo'yadi."""
    if video:
        with open(video, "rb") as f:
            msg = tg("sendVideo", files={"video": f}, chat_id=ADMIN_ID, caption=text or "",
                     parse_mode="HTML", supports_streaming="true")
    elif photo:
        with open(photo, "rb") as f:
            msg = tg("sendPhoto", files={"photo": f}, chat_id=ADMIN_ID, caption=text or "", parse_mode="HTML")
    else:
        msg = tg("sendMessage", chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    attach_controls(state, kind, key, msg["message_id"])


def attach_controls(state, kind, key, content_id):
    did = str(content_id)
    ctl = tg("sendMessage", chat_id=ADMIN_ID, reply_to_message_id=content_id,
             text=f"⬆️ {KIND_LABEL[kind]} — kanalga chiqaraymi?",
             reply_markup=keyboard([[{"text": "✅ Chiqarish", "callback_data": f"ok:{did}"},
                                     {"text": "❌ Bekor", "callback_data": f"no:{did}"}]]))
    state["drafts"][did] = {"kind": kind, "key": key, "ctl": ctl["message_id"],
                            "created": now().isoformat(timespec="minutes")}


# ---------------------------------------------------------------- helpers

def now():
    return dt.datetime.now(TZ)


def load_state():
    base = {"offset": 0, "drafts": {}, "seen_news": [], "tips_done": [],
            "reels_done": [], "queue_done": [], "slots_done": []}
    if STATE_PATH.exists():
        base.update(json.loads(STATE_PATH.read_text("utf-8")))
    return base


def save_state(state):
    state["seen_news"] = state["seen_news"][-500:]
    state["slots_done"] = state["slots_done"][-100:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")


def fmt(text):
    """Oddiy matnni Telegram HTML ga: maxsus belgilar qochiriladi, **qalin** -> <b>."""
    t = html.escape(text.strip(), quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def footer():
    return "\n\n" + CONFIG["footer"]


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


_models = None


def gemini_models():
    """Sinab ko'riladigan modellar: avval 'latest' taxallusi, keyin config'dagisi, keyin eng yangi 'flash'lar.
    Google eski modellarni ro'yxatda qoldirsa ham yangi kalitlarga 404 qaytaradi, shuning uchun bir nechtasi kerak."""
    global _models
    if _models is not None:
        return _models
    names = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         headers={"x-goog-api-key": GEMINI_KEY}, params={"pageSize": 1000}, timeout=30)
        r.raise_for_status()
        names = [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception as e:
        print("model ro'yxatini olib bo'lmadi:", e)
    skip = ("lite", "preview", "exp", "image", "tts", "live", "audio", "thinking")
    flash = sorted((n for n in names if "flash" in n and not any(s in n for s in skip)), reverse=True)
    _models = list(dict.fromkeys(["gemini-flash-latest", GEMINI_MODEL] + flash))
    return _models


def gemini_json(prompt):
    last = None
    for model in list(gemini_models()):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}},
            timeout=90)
        if r.status_code == 404:
            print("Gemini model mavjud emas:", model)
            _models.remove(model)
            last = r
            continue
        r.raise_for_status()
        if _models[0] != model:
            _models.remove(model)
            _models.insert(0, model)
        print("Gemini model:", model)
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    raise RuntimeError(f"ishlaydigan Gemini modeli topilmadi (oxirgi javob: {last.status_code if last else '-'})")


def translate(text):
    """Gemini kaliti bo'lmasa zaxira: Google Translate'ning ochiq manzili."""
    r = requests.get("https://translate.googleapis.com/translate_a/single",
                     params={"client": "gtx", "sl": "auto", "tl": "uz", "dt": "t", "q": text[:4500]}, timeout=30)
    r.raise_for_status()
    return "".join(part[0] for part in r.json()[0] if part[0])


def notify(text):
    try:
        tg("sendMessage", chat_id=ADMIN_ID, text=f"⚠️ {text}"[:4000],
           link_preview_options=json.dumps({"is_disabled": True}))
    except Exception as e:
        print("notify failed:", e)


# ---------------------------------------------------------------- sources

def fetch_news(state, count):
    seen = set(state["seen_news"])
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=CONFIG.get("news_max_age_hours", 36))
    items = []
    for feed in CONFIG["news_feeds"]:
        try:
            parsed = feedparser.parse(feed["url"], agent="Mozilla/5.0 (JavohirAI news bot)")
        except Exception as e:
            print("feed error", feed["url"], e)
            continue
        for e in parsed.entries[:15]:
            link = e.get("link")
            stamp = e.get("published_parsed") or e.get("updated_parsed")
            if not link or link in seen or not stamp:
                continue
            when = dt.datetime(*stamp[:6], tzinfo=dt.timezone.utc)
            if when < cutoff:
                continue
            items.append({"title": strip_tags(e.get("title")), "summary": strip_tags(e.get("summary"))[:1500],
                          "link": link, "source": feed["name"], "when": when})
    items.sort(key=lambda x: x["when"], reverse=True)
    picked, titles = [], set()
    for it in items:
        k = it["title"].lower()[:60]
        if k in titles:
            continue
        titles.add(k)
        picked.append(it)
        if len(picked) >= count:
            break
    return picked


def news_post(it):
    try:
        return news_post_gemini(it) if GEMINI_KEY else news_post_translate(it)
    except Exception as e:
        print("Gemini xatosi, tarjimaga o'tildi:", e)
        return news_post_translate(it)


def news_post_translate(it):
    try:
        body = f"<b>📰 {fmt(translate(it['title']))}</b>\n\n{fmt(translate(it['summary'][:700]))}"
    except Exception as e:
        # Google Translate GitHub serverlarini ba'zan cheklaydi (429) — unda asl matn, tahrirlash uchun
        print("tarjima ishlamadi, asl matn qoldirildi:", e)
        body = (f"🇬🇧 <i>Tarjima qilinmadi — chiqarishdan oldin tahrirlang</i>\n\n"
                f"<b>📰 {fmt(it['title'])}</b>\n\n{fmt(it['summary'][:700])}")
    return news_footer(it, body)


def news_footer(it, body):
    src = f'🔗 <a href="{html.escape(it["link"])}">Manba: {html.escape(it["source"])}</a>'
    return f"{body}\n\n{src}{footer()}"


def news_post_gemini(it):
    data = gemini_json(
        "Sen o'zbek tilidagi 'Javohir | AI va Texnologiyalar' Telegram kanali muharririsan. "
        "Quyidagi inglizcha yangilikni o'zbek tilida (lotin yozuvida), oddiy va jonli uslubda qayta yoz. "
        "Faktlarni o'zgartirma, o'zingdan qo'shma. JSON qaytar: "
        '{"sarlavha": "qisqa sarlavha, boshida mos emoji", '
        '"matn": "2-4 gapdan iborat mazmun; muhim so\'zlarni **qalin** qil", '
        '"xulosa": "1 gap: bu oddiy foydalanuvchi uchun nimani anglatadi"}\n\n'
        f"Sarlavha: {it['title']}\nMazmun: {it['summary']}")
    body = f"<b>{fmt(data['sarlavha'])}</b>\n\n{fmt(data['matn'])}\n\n💬 {fmt(data['xulosa'])}"
    return news_footer(it, body)


def do_news(state, count=None):
    count = count or CONFIG.get("news_per_slot", 1)
    items = fetch_news(state, count)
    if not items:
        print("yangi yangilik topilmadi")
        return
    for it in items:
        state["seen_news"].append(it["link"])
        try:
            make_draft(state, "news", it["link"], text=news_post(it))
        except Exception as e:
            notify(f"Yangilikni tayyorlab bo'lmadi: {it['title']}\n{e}")


def do_tip(state):
    tips = json.loads((CONTENT / "maslahatlar.json").read_text("utf-8"))
    tip = next((t for t in tips if t["nomi"] not in state["tips_done"]), None)
    if tip:
        text = fmt(tip["post"])
    elif GEMINI_KEY:
        data = gemini_json(
            "Sen o'zbek tilidagi AI Telegram kanali muharririsan. Oddiy odamlar uchun foydali bitta "
            "AI vositasi yoki AI'dan foydalanish maslahati haqida post yoz (o'zbek, lotin yozuvi, 60-110 so'z). "
            "Bepul yoki bepul tarifi bor vositani tanla. Faqat aniq bilgan faktlaringni yoz. "
            f"Bular avval yozilgan, takrorlama: {', '.join(state['tips_done'][-60:])}. "
            'JSON qaytar: {"nomi": "vosita nomi", "post": "post matni; birinchi qator: 💡 sarlavha; '
            'muhim so\'zlar **qalin**; oxirida qanday boshlash bo\'yicha 1-2 qadam"}')
        tip = {"nomi": data["nomi"]}
        text = fmt(data["post"])
    else:
        notify("Maslahatlar ro'yxati tugadi. content/maslahatlar.json ga yangi qo'shing yoki GEMINI_API_KEY ulang.")
        return
    state["tips_done"].append(tip["nomi"])
    make_draft(state, "tip", tip["nomi"], text=text + footer())


def do_reel(state):
    folder = CONTENT / "reels"
    for vid in sorted(folder.glob("*.mp4")):
        if vid.name in state["reels_done"]:
            continue
        state["reels_done"].append(vid.name)
        cap_file = vid.with_suffix(".txt")
        caption = fmt(cap_file.read_text("utf-8")) if cap_file.exists() else ""
        caption = (caption + footer()).strip()
        if len(caption) > 1024:
            caption = caption[:1000] + "…"
        if vid.stat().st_size > 50 * 1024 * 1024:
            notify(f"{vid.name} 50 MB dan katta, bot yubora olmaydi. Siqilgan versiyasini qo'ying.")
            continue
        make_draft(state, "reel", vid.name, text=caption, video=vid)
        return
    print("yangi reels yo'q")


def parse_queue_file(path):
    lines = path.read_text("utf-8").splitlines()
    meta = {}
    while lines and re.match(r"^(vaqt|rasm|video)\s*:", lines[0], re.I):
        k, v = lines.pop(0).split(":", 1)
        meta[k.strip().lower()] = v.strip()
    return meta, "\n".join(lines).strip()


def do_queue(state, scheduled_only=False):
    """scheduled_only=True: faqat 'vaqt:' kelgan fayllar. Aks holda vaqtsiz navbatdagi bitta fayl ham."""
    folder = CONTENT / "navbat"
    took_free = scheduled_only
    for path in sorted(folder.glob("*.txt")):
        if path.name in state["queue_done"] or path.name.startswith("_"):
            continue
        meta, body = parse_queue_file(path)
        if "vaqt" in meta:
            try:
                when = dt.datetime.strptime(meta["vaqt"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            except ValueError:
                notify(f"{path.name}: vaqt formati noto'g'ri, masalan: vaqt: 2026-11-05 10:00")
                state["queue_done"].append(path.name)
                continue
            if when > now():
                continue
        elif took_free:
            continue
        else:
            took_free = True
        state["queue_done"].append(path.name)
        text = fmt(body) + footer()
        media = {k: path.parent / meta[k] for k in ("rasm", "video") if k in meta}
        missing = [m.name for m in media.values() if not m.exists()]
        if missing:
            notify(f"{path.name}: fayl topilmadi: {', '.join(missing)}")
            continue
        make_draft(state, "queue", path.name, text=text, photo=media.get("rasm"), video=media.get("video"))


JOBS = {"news": do_news, "tip": do_tip, "reel": do_reel, "queue": do_queue}


def run_schedule(state):
    t = now()
    today = t.strftime("%Y-%m-%d")
    for hhmm, kind in sorted(CONFIG["schedule"].items()):
        slot_id = f"{today} {hhmm}"
        h, m = map(int, hhmm.split(":"))
        slot_time = t.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot_id in state["slots_done"] or slot_time > t:
            continue
        state["slots_done"].append(slot_id)
        if t - slot_time > dt.timedelta(hours=CONFIG.get("max_late_hours", 2)):
            print("kechikkan slot o'tkazib yuborildi:", slot_id, kind)
            continue
        print("slot:", slot_id, kind)
        try:
            JOBS[kind](state)
        except Exception as e:
            notify(f"{KIND_LABEL[kind]} ishida xato: {e}")
    try:
        do_queue(state, scheduled_only=True)
    except Exception as e:
        notify(f"Navbat ishida xato: {e}")


# ---------------------------------------------------------------- updates

HELP = (
    "🤖 <b>Kanal avtopiloti</b>\n\n"
    "Har bir post avval sizga keladi: ✅ bossangiz kanalga chiqadi, ❌ bossangiz bekor bo'ladi.\n\n"
    "Buyruqlar:\n"
    "/yangilik — hozir yangilik tayyorlash\n"
    "/maslahat — hozir AI maslahat tayyorlash\n"
    "/reels — navbatdagi reelsni tayyorlash\n"
    "/navbat — navbatdagi postni tayyorlash\n"
    "/holat — kutilayotgan qoralamalar\n\n"
    "Menga istalgan matn, rasm yoki video yuborsangiz, uni ham kanalga chiqarishni taklif qilaman.\n\n"
    "ℹ️ Javob 15 daqiqagacha kechikishi mumkin — bot jadval bo'yicha ishlaydi."
)

COMMANDS = {"/yangilik": "news", "/maslahat": "tip", "/reels": "reel", "/navbat": "queue"}


def handle_callback(state, cq):
    try:
        if str(cq["from"]["id"]) != ADMIN_ID:
            return
        action, did = cq["data"].split(":", 1)
        draft = state["drafts"].pop(did, None)
        if not draft:
            status = "ℹ️ Bu qoralama allaqachon hal qilingan."
        elif action == "ok":
            tg("copyMessage", chat_id=CONFIG["channel"], from_chat_id=ADMIN_ID, message_id=did)
            status = f"✅ {KIND_LABEL[draft['kind']]} kanalga chiqdi ({now():%H:%M})."
        else:
            status = f"❌ {KIND_LABEL[draft['kind']]} bekor qilindi."
        tg("editMessageText", chat_id=ADMIN_ID, message_id=cq["message"]["message_id"], text=status)
    finally:
        try:
            tg("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception:
            pass  # 15 daqiqadan eski bosishlarga javob berib bo'lmaydi — bu normal


def handle_message(state, msg):
    if msg["chat"]["type"] != "private":
        return
    uid = str(msg["from"]["id"])
    text = (msg.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/id"):
        tg("sendMessage", chat_id=uid, parse_mode="HTML",
           text=f"Sizning Telegram ID: <code>{uid}</code>\n\n" + (HELP if uid == ADMIN_ID else
                "Bu ID ni GitHub'dagi ADMIN_ID sirli o'zgaruvchisiga yozing."))
        return
    if uid != ADMIN_ID:
        return
    cmd = text.split("@")[0].lower()
    if cmd in COMMANDS:
        before = len(state["drafts"])
        JOBS[COMMANDS[cmd]](state)
        if len(state["drafts"]) == before:
            tg("sendMessage", chat_id=uid, text="Hozircha yangi material topilmadi.")
    elif cmd == "/holat":
        pend = state["drafts"].values()
        lines = [f"• {KIND_LABEL[d['kind']]} — {d['created']}" for d in pend] or ["Kutilayotgan qoralama yo'q."]
        tg("sendMessage", chat_id=uid, text="\n".join(lines))
    elif cmd.startswith("/"):
        tg("sendMessage", chat_id=uid, text=HELP, parse_mode="HTML")
    else:
        attach_controls(state, "manual", f"msg{msg['message_id']}", msg["message_id"])


def process_updates(state):
    updates = tg("getUpdates", offset=state["offset"], timeout=0,
                 allowed_updates=json.dumps(["message", "callback_query"]))
    for u in updates:
        state["offset"] = u["update_id"] + 1
        try:
            if "callback_query" in u:
                handle_callback(state, u["callback_query"])
            elif "message" in u:
                handle_message(state, u["message"])
        except Exception as e:
            print("update error:", e)
            notify(f"Xabarni qayta ishlashda xato: {e}")


# ---------------------------------------------------------------- main

def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Telegram'ga yubormay, faqat ekranga chiqarish")
    ap.add_argument("--force", choices=list(JOBS), help="jadvalni kutmay shu ishni bajarish")
    args = ap.parse_args()
    DRY = args.dry
    if not DRY and not TOKEN:
        sys.exit("BOT_TOKEN topilmadi yoki noto'g'ri formatda (kerak: raqamlar:harflar).")
    if not DRY:
        try:
            me = tg("getMe")
        except RuntimeError as e:
            sys.exit(f"Telegram tokenni qabul qilmadi ({e}). BotFather'dagi eng oxirgi tokenni qayta kiriting.")
        print(f"Bot: @{me['username']}")

    state = load_state()
    try:
        process_updates(state)
        if not ADMIN_ID and not DRY:
            print("ADMIN_ID yo'q: botga /start yozing, u ID ni aytadi.")
        elif args.force:
            JOBS[args.force](state)
        else:
            run_schedule(state)
    finally:
        if not DRY:
            save_state(state)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
