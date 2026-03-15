import logging, os, json, os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

REJECT_ACC, REJECT_REV, REJECT_TXT = range(3)

DB = "db.json"
TOKEN = os.getenv("ADMIN_TOKEN")
WORKER_TOKEN = os.getenv("WORKER_TOKEN")

def db():
    if not os.path.exists(DB):
        return {"u": {}, "t": {}, "n": 0, "platforms": [], "apps": {}}
    with open(DB, encoding="utf-8") as f:
        d = json.load(f)
    for k in ("platforms", "apps"):
        if k not in d:
            d[k] = {} if k == "apps" else []
    return d

def save(d):
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def main_kb():
    return ReplyKeyboardMarkup([["➕ задание", "📋 задания"], ["🗂 платформы", "🔍 проверить"], ["⚡ штрафы"]], resize_keyboard=True)

async def reupload_photo(file_id):
    from io import BytesIO
    try:
        from telegram import Bot as TGBot
        tg_file = await TGBot(WORKER_TOKEN).get_file(file_id)
        buf = BytesIO(await tg_file.download_as_bytearray())
        return buf
    except Exception as e:
        log.warning(f"reupload: {e}")
        return None

async def notify_worker(wid, text):
    try:
        await Bot(WORKER_TOKEN).send_message(wid, text)
    except Exception as e:
        log.warning(e)


# ── старт ──────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    if str(uid) not in d["u"]:
        d["u"][str(uid)] = {"role": "employer", "name": update.effective_user.full_name, "id": uid}
        save(d)
    await update.message.reply_text("админ", reply_markup=main_kb())


# ── платформы ──────────────────────────────────────────────────────────────────

async def platforms_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    txt = "платформы:\n" + "\n".join(f"· {p}" for p in d["platforms"]) if d["platforms"] else "платформ нет"
    kb = [["➕ добавить", "🗑 удалить"], ["◀️ назад"]]
    await update.message.reply_text(txt, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def add_pl_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["pl_step"] = "add"
    await update.message.reply_text("название:")

async def add_pl_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    name = update.message.text.strip()
    ctx.user_data.pop("pl_step", None)
    if name not in d["platforms"]:
        d["platforms"].append(name)
        save(d)
        await update.message.reply_text(f"добавил: {name}", reply_markup=main_kb())
    else:
        await update.message.reply_text("уже есть", reply_markup=main_kb())

async def del_pl_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    if not d["platforms"]:
        await update.message.reply_text("нечего удалять", reply_markup=main_kb())
        return
    kb = [[InlineKeyboardButton(p, callback_data=f"dp_{p}")] for p in d["platforms"]]
    await update.message.reply_text("какую?", reply_markup=InlineKeyboardMarkup(kb))

async def del_pl_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    name = q.data[3:]
    if name in d["platforms"]:
        d["platforms"].remove(name)
        save(d)
    await q.edit_message_text(f"удалил: {name}")


# ── создание задания ───────────────────────────────────────────────────────────

async def create_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    if not d["platforms"]:
        await update.message.reply_text("сначала добавь платформы", reply_markup=main_kb())
        return
    ctx.user_data.clear()
    ctx.user_data["step"] = "pick_platform"
    kb = [[InlineKeyboardButton(p, callback_data=f"cp_{p}")] for p in d["platforms"]]
    await update.message.reply_text("платформа:", reply_markup=InlineKeyboardMarkup(kb))

async def pl_picked(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["pl"] = q.data[3:]
    ctx.user_data["step"] = "title"
    await q.edit_message_text(f"{ctx.user_data['pl']}\n\nссылка / название объекта:")

async def type_picked(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["type"] = q.data[3:]  # free или fixed
    if ctx.user_data["type"] == "fixed":
        ctx.user_data["step"] = "review_text"
        await q.edit_message_text("введи готовый текст отзыва:")
    else:
        await _save_task(q, ctx)

async def _save_task(q_or_msg, ctx, from_msg=False):
    d = db()
    existing = [int(k) for k in d["t"].keys() if k.isdigit()]
    tid = str(max(existing) + 1 if existing else 1)
    d["n"] = int(tid)
    eid = q_or_msg.from_user.id if not from_msg else q_or_msg.from_user.id
    d["t"][tid] = {
        "id": tid, "platform": ctx.user_data["pl"],
        "title": ctx.user_data["t"], "desc": ctx.user_data["d"],
        "city": ctx.user_data.get("city", ""), "theme": ctx.user_data.get("theme", ""),
        "price": ctx.user_data.get("price", "0"),
        "dl": ctx.user_data["dl"],
        "limit": ctx.user_data.get("limit", 1),
        "workers": [],
        "type": ctx.user_data.get("type", "free"),
        "review_text": ctx.user_data.get("review_text"),
        "eid": eid, "wid": None, "status": "open",
        "ts": datetime.now().strftime("%d.%m %H:%M"), "result": None
    }
    save(d)
    ctx.user_data.clear()
    txt = f"#{tid} добавлено [{d['t'][tid]['platform']}]"
    if from_msg:
        await q_or_msg.reply_text(txt, reply_markup=main_kb())
    else:
        await q_or_msg.edit_message_text(txt)

async def on_create_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = ctx.user_data.get("step")
    txt = update.message.text.strip()
    if step == "title":
        ctx.user_data["t"] = txt
        ctx.user_data["step"] = "city"
        await update.message.reply_text("город:")
    elif step == "city":
        ctx.user_data["city"] = txt
        ctx.user_data["step"] = "theme"
        await update.message.reply_text("тематика:")
    elif step == "theme":
        ctx.user_data["theme"] = txt
        ctx.user_data["step"] = "price"
        await update.message.reply_text("цена (руб):")
    elif step == "price":
        ctx.user_data["price"] = txt
        ctx.user_data["step"] = "desc"
        await update.message.reply_text("инструкция для рабочего:")
    elif step == "desc":
        ctx.user_data["d"] = txt
        ctx.user_data["step"] = "dl"
        await update.message.reply_text("дедлайн (или -):")
    elif step == "dl":
        ctx.user_data["dl"] = "—" if txt == "-" else txt
        ctx.user_data["step"] = "limit"
        await update.message.reply_text("лимит исполнителей (число):")
    elif step == "limit":
        ctx.user_data["limit"] = int(txt) if txt.isdigit() else 1
        ctx.user_data["step"] = "pick_type"
        kb = [[InlineKeyboardButton("📝 рабочий сам пишет", callback_data="tp_free"),
               InlineKeyboardButton("📋 готовый текст", callback_data="tp_fixed")]]
        await update.message.reply_text("тип задания:", reply_markup=InlineKeyboardMarkup(kb))
    elif step == "review_text":
        ctx.user_data["review_text"] = txt
        await _save_task(update.message, ctx, from_msg=True)
    else:
        return False
    return True


# ── список заданий ─────────────────────────────────────────────────────────────

async def all_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    tasks = [(k, v) for k, v in d["t"].items() if v["eid"] == uid]
    if not tasks:
        await update.message.reply_text("заданий нет")
        return
    icons = {"open": "🟡", "paused": "⏸", "active": "🔵", "review_check": "🔍", "done": "🟠", "closed": "✅"}
    for tid, t in tasks:
        wname = d["u"].get(str(t["wid"]), {}).get("name", "—") if t["wid"] else "—"
        icon = icons.get(t["status"], "?")
        ttype = "📋" if t.get("type") == "fixed" else "📝"
        txt = f"{icon} #{tid} {ttype} [{t['platform']}]\n{t['title']}\nисполнитель: {wname}"
        btns = []
        if t["status"] == "open":
            btns = [InlineKeyboardButton("⏸ пауза", callback_data=f"pause_{tid}"),
                    InlineKeyboardButton("🗑 удалить", callback_data=f"del_{tid}")]
        elif t["status"] == "paused":
            btns = [InlineKeyboardButton("▶️ возобновить", callback_data=f"resume_{tid}"),
                    InlineKeyboardButton("🗑 удалить", callback_data=f"del_{tid}")]
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup([btns]) if btns else None)

async def pause_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    tid = q.data[6:]
    t = d["t"].get(tid)
    if t and t["status"] == "open":
        t["status"] = "paused"
        save(d)
        await q.edit_message_text(f"⏸ #{tid} на паузе")

async def resume_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    tid = q.data[7:]
    t = d["t"].get(tid)
    if t and t["status"] == "paused":
        t["status"] = "open"
        save(d)
        await q.edit_message_text(f"▶️ #{tid} возобновлено")

async def del_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    tid = q.data[4:]
    if tid in d["t"]:
        del d["t"][tid]
        save(d)
        await q.edit_message_text(f"🗑 #{tid} удалено")


# ── проверка ───────────────────────────────────────────────────────────────────

async def check_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    accs = sum(1 for ak, ap in d["apps"].items() if ap.get("status") == "checking" and d["t"].get(str(ap.get("tid")), {}).get("eid") == uid)
    txts = sum(1 for t in d["t"].values() if t.get("status") == "review_check" and t.get("eid") == uid)
    revs = sum(1 for t in d["t"].values() if t.get("status") == "done" and t.get("eid") == uid)
    total = accs + txts + revs
    if total == 0:
        await update.message.reply_text("нечего проверять")
        return
    kb = []
    if accs: kb.append([InlineKeyboardButton(f"👤 аккаунты ({accs})", callback_data="chk_acc")])
    if txts: kb.append([InlineKeyboardButton(f"📝 тексты отзывов ({txts})", callback_data="chk_txt")])
    if revs: kb.append([InlineKeyboardButton(f"📸 скриншоты ({revs})", callback_data="chk_rev")])
    await update.message.reply_text("что проверяем?", reply_markup=InlineKeyboardMarkup(kb))

async def check_section(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    section = q.data[4:]  # acc / txt / rev
    d = db()
    await q.edit_message_reply_markup(reply_markup=None)

    if section == "acc":
        sent = False
        for app_key, app in d["apps"].items():
            if app.get("status") != "checking":
                continue
            t = d["t"].get(str(app.get("tid")), {})
            if t.get("eid") != uid:
                continue
            wname = d["u"].get(str(app["uid"]), {}).get("name", str(app["uid"]))
            username = d["u"].get(str(app["uid"]), {}).get("username", "")
            uinfo = f"@{username}" if username else wname
            caption = f"👤 аккаунт [{t.get('platform','')}]\nрабочий: {uinfo}"
            kb = [[InlineKeyboardButton("✅ одобрить", callback_data=f"acc_ok|{app_key}"),
                   InlineKeyboardButton("❌ отказать", callback_data=f"acc_no|{app_key}")]]
            buf = await reupload_photo(app["file_id"])
            try:
                if buf:
                    await q.message.reply_photo(buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb))
                else:
                    await q.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(kb))
                sent = True
            except Exception as e:
                log.warning(e)
        if not sent:
            await q.message.reply_text("пусто")

    elif section == "txt":
        sent = False
        for tid, t in d["t"].items():
            if t.get("status") != "review_check" or t.get("eid") != uid:
                continue
            wname = d["u"].get(str(t["wid"]), {}).get("name", str(t["wid"]))
            username = d["u"].get(str(t["wid"]), {}).get("username", "")
            uinfo = f"@{username}" if username else wname
            txt = f"📝 текст отзыва\n#{tid} [{t['platform']}] {t['title']}\nрабочий: {uinfo}\n\n{t.get('draft','')}"
            kb = [[InlineKeyboardButton("✅ одобрить", callback_data=f"txt_ok|{tid}"),
                   InlineKeyboardButton("❌ отклонить", callback_data=f"txt_no|{tid}")]]
            await q.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))
            sent = True
        if not sent:
            await q.message.reply_text("пусто")

    elif section == "rev":
        sent = False
        for tid, t in d["t"].items():
            if t.get("status") != "done" or t.get("eid") != uid:
                continue
            wname = d["u"].get(str(t["wid"]), {}).get("name", str(t["wid"]))
            username = d["u"].get(str(t["wid"]), {}).get("username", "")
            uinfo = f"@{username}" if username else wname
            caption = f"📸 скриншот отзыва\n#{tid} [{t['platform']}] {t['title']}\nрабочий: {uinfo}"
            kb = [[InlineKeyboardButton("✅ принять", callback_data=f"rev_ok|{tid}"),
                   InlineKeyboardButton("❌ отклонить", callback_data=f"rev_no|{tid}")]]
            buf = await reupload_photo(t["result"])
            try:
                if buf:
                    await q.message.reply_photo(buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb))
                else:
                    await q.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(kb))
                sent = True
            except Exception as e:
                log.warning(e)
        if not sent:
            await q.message.reply_text("пусто")


# одобрить аккаунт
async def acc_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    app_key = q.data.split("|")[1]
    d = db()
    app = d["apps"].get(app_key)
    if not app:
        await q.edit_message_caption("не найдено")
        return
    app["status"] = "approved"
    save(d)
    wname = d["u"].get(str(app["uid"]), {}).get("name", "")
    t = d["t"].get(str(app.get("tid")), {})
    platform = t.get("platform", "")
    try:
        await q.edit_message_caption(f"✅ одобрено: {wname}")
    except:
        await q.edit_message_text(f"✅ одобрено: {wname}")
    from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
    tid = str(app.get("tid"))
    kb = [[IKB("📥 взять задание", callback_data=f"take|{tid}|{t.get('platform','')}|0")]]
    try:
        await Bot(WORKER_TOKEN).send_message(
            app["uid"],
            f"✅ аккаунт одобрен!\n\n#{tid} {t.get('title','')}\n\nнажми кнопку чтобы взять задание:",
            reply_markup=IKM(kb)
        )
    except Exception as e:
        log.warning(e)

# отказать аккаунт
async def acc_no_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["rej_acc"] = q.data.split("|")[1]
    try:
        await q.edit_message_caption("причина отказа:")
    except:
        await q.edit_message_text("причина отказа:")
    return REJECT_ACC

async def acc_no_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    app_key = ctx.user_data.pop("rej_acc")
    reason = update.message.text.strip()
    d = db()
    app = d["apps"].get(app_key)
    if not app:
        await update.message.reply_text("не найдено", reply_markup=main_kb())
        return ConversationHandler.END
    app["status"] = "rejected"
    app["reason"] = reason
    save(d)
    await update.message.reply_text("отказ отправлен", reply_markup=main_kb())
    await notify_worker(app["uid"], f"❌ аккаунт отклонён\nпричина: {reason}")
    return ConversationHandler.END

# одобрить текст отзыва
async def txt_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.data.split("|")[1]
    d = db()
    t = d["t"].get(tid)
    if not t:
        await q.edit_message_text("не найдено")
        return
    t["status"] = "active"
    save(d)
    await q.edit_message_text(f"✅ текст одобрен #{tid}")
    from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
    kb = [[IKB("📸 отправить скриншот", callback_data=f"submit_{tid}")]]
    try:
        await Bot(WORKER_TOKEN).send_message(
            t["wid"],
            f"✅ текст одобрен!\n\nопубликуй отзыв и нажми кнопку:",
            reply_markup=IKM(kb)
        )
    except Exception as e:
        log.warning(e)

# отклонить текст отзыва
async def txt_no_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["rej_txt"] = q.data.split("|")[1]
    await q.edit_message_text("причина отклонения:")
    return REJECT_TXT

async def txt_no_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = ctx.user_data.pop("rej_txt")
    reason = update.message.text.strip()
    d = db()
    t = d["t"].get(tid)
    if not t:
        await update.message.reply_text("не найдено", reply_markup=main_kb())
        return ConversationHandler.END
    t["status"] = "active"
    t.pop("draft", None)
    save(d)
    await update.message.reply_text(f"↩ #{tid} отклонено", reply_markup=main_kb())
    await notify_worker(t["wid"], f"❌ текст отзыва отклонён\nпричина: {reason}\n\nперепиши и отправь снова")
    return ConversationHandler.END

# принять скриншот
async def rev_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.data.split("|")[1]
    d = db()
    t = d["t"].get(tid)
    if not t:
        await q.edit_message_caption("не найдено")
        return
    t["status"] = "closed"
    price = int(t.get("price", 0) or 0)
    wid = str(t["wid"])
    if wid in d["u"]:
        d["u"][wid]["balance"] = d["u"][wid].get("balance", 0) + price
    save(d)
    try:
        await q.edit_message_caption(f"✅ #{tid} принят")
    except:
        await q.edit_message_text(f"✅ #{tid} принят")
    await notify_worker(t["wid"], f"✅ отзыв #{tid} принят 🎉\n\n+{price} руб на баланс 💰")

# отклонить скриншот
async def rev_no_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["rej_rev"] = q.data.split("|")[1]
    try:
        await q.edit_message_caption("причина отклонения:")
    except:
        await q.edit_message_text("причина отклонения:")
    return REJECT_REV

async def rev_no_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = ctx.user_data.pop("rej_rev")
    reason = update.message.text.strip()
    d = db()
    t = d["t"].get(tid)
    if not t:
        await update.message.reply_text("не найдено", reply_markup=main_kb())
        return ConversationHandler.END
    t["status"] = "active"
    save(d)
    await update.message.reply_text(f"↩ #{tid} отклонено", reply_markup=main_kb())
    from telegram import InlineKeyboardButton as IKB, InlineKeyboardMarkup as IKM
    kb = [[IKB("📸 отправить скриншот заново", callback_data=f"submit_{tid}")]]
    try:
        await Bot(WORKER_TOKEN).send_message(
            t["wid"],
            f"❌ скриншот #{tid} отклонён\nпричина: {reason}\n\nисправь и отправь снова:",
            reply_markup=IKM(kb)
        )
    except Exception as e:
        log.warning(e)
    return ConversationHandler.END


async def withdraw_ok(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("|")
    wid = int(parts[1])
    amount = int(parts[2])
    d = db()
    u = d["u"].get(str(wid), {})
    u["balance"] = max(0, u.get("balance", 0) - amount)
    save(d)
    try:
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"✅ выплата подтверждена, -{amount} руб с баланса")
    except: pass
    try:
        await Bot(WORKER_TOKEN).send_message(wid, f"✅ заявка на вывод {amount} руб подтверждена\n\nожидай оплаты 💸")
    except Exception as e:
        log.warning(e)

async def withdraw_no_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["wno"] = q.data[5:]  # wid|amount
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except: pass
    await q.message.reply_text("причина отказа в выводе:")
    return 99

async def withdraw_no_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.user_data.pop("wno", "")
    parts = data.split("|")
    wid = int(parts[0])
    reason = update.message.text.strip()
    await update.message.reply_text("отказ отправлен", reply_markup=main_kb())
    try:
        await Bot(WORKER_TOKEN).send_message(wid, f"❌ заявка на вывод отклонена\nпричина: {reason}")
    except Exception as e:
        log.warning(e)
    return ConversationHandler.END


# ── вакансии ───────────────────────────────────────────────────────────────────

async def vacancies_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    vacs = d.get("vacs", {})
    txt = "💼 вакансии:\n" + "\n".join(f"· {v['title']}" for v in vacs.values()) if vacs else "вакансий нет"
    kb = [["➕ добавить вакансию", "🗑 удалить вакансию"], ["◀️ назад"]]
    await update.message.reply_text(txt, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def add_vac_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["vac_step"] = "title"
    await update.message.reply_text("название вакансии:")

async def on_vac_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = ctx.user_data.get("vac_step")
    txt = update.message.text.strip()
    if step == "title":
        ctx.user_data["vac_title"] = txt
        ctx.user_data["vac_step"] = "desc"
        await update.message.reply_text("описание:")
    elif step == "desc":
        ctx.user_data["vac_desc"] = txt
        ctx.user_data["vac_step"] = "price"
        await update.message.reply_text("оплата:")
    elif step == "price":
        ctx.user_data["vac_price"] = txt
        ctx.user_data["vac_step"] = "contact"
        await update.message.reply_text("юзернейм для связи (@username):")
    elif step == "contact":
        d = db()
        if "vacs" not in d:
            d["vacs"] = {}
        existing = [int(k) for k in d["vacs"].keys() if k.isdigit()]
        vn = str(max(existing) + 1 if existing else 1)
        d["vacs"][vn] = {
            "title": ctx.user_data.pop("vac_title"),
            "desc": ctx.user_data.pop("vac_desc"),
            "price": ctx.user_data.pop("vac_price"),
            "contact": txt
        }
        ctx.user_data.pop("vac_step", None)
        save(d)
        await update.message.reply_text("вакансия добавлена", reply_markup=main_kb())

async def del_vac_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    vacs = d.get("vacs", {})
    if not vacs:
        await update.message.reply_text("нечего удалять", reply_markup=main_kb())
        return
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"dv_{k}")] for k, v in vacs.items()]
    await update.message.reply_text("какую?", reply_markup=InlineKeyboardMarkup(kb))

async def del_vac_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    vid = q.data[3:]
    d = db()
    if vid in d.get("vacs", {}):
        del d["vacs"][vid]
        save(d)
    await q.edit_message_text("удалено")


# ── штрафы ─────────────────────────────────────────────────────────────────────

async def fine_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    workers = [(k, v) for k, v in d["u"].items() if v.get("role") == "worker"]
    if not workers:
        await update.message.reply_text("рабочих нет", reply_markup=main_kb())
        return
    kb = [[InlineKeyboardButton(
        f"@{v.get('username', v.get('name', k))}",
        callback_data=f"fine_{k}"
    )] for k, v in workers]
    await update.message.reply_text("выбери рабочего:", reply_markup=InlineKeyboardMarkup(kb))

async def fine_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["fine_uid"] = q.data[5:]
    ctx.user_data["fine_step"] = "amount"
    await q.edit_message_text("сумма штрафа (руб):")

async def on_fine_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = ctx.user_data.get("fine_step")
    txt = update.message.text.strip()
    if step == "amount":
        if not txt.isdigit():
            await update.message.reply_text("введи число")
            return
        ctx.user_data["fine_amount"] = int(txt)
        ctx.user_data["fine_step"] = "reason"
        await update.message.reply_text("причина штрафа:")
    elif step == "reason":
        wid = ctx.user_data.pop("fine_uid")
        amount = ctx.user_data.pop("fine_amount")
        ctx.user_data.pop("fine_step", None)
        d = db()
        u = d["u"].get(str(wid), {})
        u["balance"] = max(0, u.get("balance", 0) - amount)
        save(d)
        wname = u.get("username") or u.get("name", wid)
        await update.message.reply_text(f"⚡ штраф -{amount} руб применён к @{wname}", reply_markup=main_kb())
        try:
            await Bot(WORKER_TOKEN).send_message(int(wid), f"⚡ тебе выписан штраф -{amount} руб\nпричина: {txt}\n\nновый баланс: {u['balance']} руб")
        except Exception as e:
            log.warning(e)


# ── штрафы ─────────────────────────────────────────────────────────────────────

FINE_AMOUNT, FINE_REASON = range(10, 12)

async def fines_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    # рабочие у которых есть выполненные задания
    wids = set()
    for t in d["t"].values():
        if t.get("status") in ("closed",) and t.get("wid"):
            wids.add(str(t["wid"]))
    if not wids:
        await update.message.reply_text("нет рабочих с выполненными заданиями")
        return
    kb = []
    for wid in wids:
        u = d["u"].get(wid, {})
        username = u.get("username", "")
        label = f"@{username}" if username else u.get("name", wid)
        balance = u.get("balance", 0)
        kb.append([InlineKeyboardButton(f"{label} · {balance} руб", callback_data=f"fine_{wid}")])
    await update.message.reply_text("выбери рабочего:", reply_markup=InlineKeyboardMarkup(kb))

async def fine_pick_worker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    wid = q.data[5:]
    ctx.user_data["fine_wid"] = wid
    d = db()
    u = d["u"].get(wid, {})
    username = u.get("username", "")
    name = f"@{username}" if username else u.get("name", wid)
    balance = u.get("balance", 0)
    await q.edit_message_text(f"рабочий: {name}\nбаланс: {balance} руб\n\nсумма штрафа:")
    return FINE_AMOUNT

async def fine_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("введи число:")
        return FINE_AMOUNT
    ctx.user_data["fine_amount"] = int(txt)
    await update.message.reply_text("причина штрафа:")
    return FINE_REASON

async def fine_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wid = ctx.user_data.pop("fine_wid")
    amount = ctx.user_data.pop("fine_amount")
    reason = update.message.text.strip()
    d = db()
    u = d["u"].get(wid, {})
    old_balance = u.get("balance", 0)
    u["balance"] = max(0, old_balance - amount)
    save(d)
    username = u.get("username", "")
    name = f"@{username}" if username else u.get("name", wid)
    await update.message.reply_text(f"⚡️ штраф применён\n{name}: -{amount} руб\nпричина: {reason}", reply_markup=main_kb())
    try:
        await Bot(WORKER_TOKEN).send_message(int(wid), f"⚡️ тебе выписан штраф -{amount} руб\nпричина: {reason}\n\nновый баланс: {u['balance']} руб")
    except Exception as e:
        log.warning(e)
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("ок", reply_markup=main_kb())
    return ConversationHandler.END

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("fine_step"):
        await on_fine_input(update, ctx)
        return
    if ctx.user_data.get("step") in ("title", "city", "theme", "price", "desc", "dl", "limit", "review_text"):
        await on_create_input(update, ctx)
        return
    if ctx.user_data.get("pl_step") == "add":
        await add_pl_input(update, ctx)
        return
    txt = update.message.text
    if txt == "📋 задания": await all_tasks(update, ctx)
    elif txt == "🔍 проверить": await check_menu(update, ctx)
    elif txt == "🗂 платформы": await platforms_menu(update, ctx)
    elif txt == "⚡ штрафы": await fine_start(update, ctx)
    elif txt == "⚡️ штрафы": await fines_menu(update, ctx)
    elif txt == "◀️ назад": await start(update, ctx)
    elif txt == "➕ задание": await create_start(update, ctx)
    elif txt == "➕ добавить": await add_pl_start(update, ctx)
    elif txt == "🗑 удалить": await del_pl_start(update, ctx)
    else: await update.message.reply_text("?", reply_markup=main_kb())


async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(acc_no_start, pattern=r"^acc_no\|")],
        states={REJECT_ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, acc_no_done)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(rev_no_start, pattern=r"^rev_no\|")],
        states={REJECT_REV: [MessageHandler(filters.TEXT & ~filters.COMMAND, rev_no_done)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(txt_no_start, pattern=r"^txt_no\|")],
        states={REJECT_TXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, txt_no_done)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    ))

    app.add_handler(CallbackQueryHandler(pl_picked, pattern="^cp_"))
    app.add_handler(CallbackQueryHandler(type_picked, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(del_pl_done, pattern="^dp_"))
    app.add_handler(CallbackQueryHandler(del_vac_done, pattern="^dv_"))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_no_start, pattern=r"^wno\|")],
        states={99: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_no_done)]},
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(fine_pick_worker, pattern="^fine_")],
        states={
            FINE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fine_amount)],
            FINE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, fine_reason)],
        },
        fallbacks=[CommandHandler("cancel", cancel)], per_message=False
    ))
    app.add_handler(CallbackQueryHandler(withdraw_ok, pattern=r"^wok\|"))
    app.add_handler(CallbackQueryHandler(check_section, pattern="^chk_"))
    app.add_handler(CallbackQueryHandler(fine_pick, pattern="^fine_"))
    app.add_handler(CallbackQueryHandler(acc_ok, pattern=r"^acc_ok\|"))
    app.add_handler(CallbackQueryHandler(txt_ok, pattern=r"^txt_ok\|"))
    app.add_handler(CallbackQueryHandler(rev_ok, pattern=r"^rev_ok\|"))
    app.add_handler(CallbackQueryHandler(pause_task, pattern="^pause_"))
    app.add_handler(CallbackQueryHandler(resume_task, pattern="^resume_"))
    app.add_handler(CallbackQueryHandler(del_task, pattern="^del_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    return app
