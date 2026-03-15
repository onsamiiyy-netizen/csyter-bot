import logging, os, json, os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

SEND_ACCOUNT, SEND_REVIEW, WRITE_REVIEW = range(3)

DB = "db.json"
TOKEN = os.getenv("WORKER_TOKEN")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

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

HELP_URL = "https://t.me/XA1HS"
VACANCIES = {
    "1": {"title": "Исполнитель", "role": "executor"},
    "2": {"title": "Траффер", "role": "trafler"},
    "3": {"title": "Поиск заказчиков", "role": "finder"},
}

def main_kb(role=None):
    if role == "trafler":
        return ReplyKeyboardMarkup([["🔗 получить ссылку", "🆘 помощь"], ["🔄 сменить вакансию"]], resize_keyboard=True)
    elif role == "finder":
        return ReplyKeyboardMarkup([["🆘 помощь"], ["🔄 сменить вакансию"]], resize_keyboard=True)
    else:  # executor или None
        return ReplyKeyboardMarkup([["👤 профиль", "📋 выполнить задание"], ["📥 мои задания", "💸 вывести"], ["🔄 сменить вакансию"]], resize_keyboard=True)

def get_kb(uid, d):
    role = d["u"].get(str(uid), {}).get("vac_role")
    return main_kb(role)

async def notify_admins_photo(d, file_id, caption, kb):
    from io import BytesIO
    try:
        tg_file = await Bot(TOKEN).get_file(file_id)
        buf = BytesIO(await tg_file.download_as_bytearray())
    except Exception as e:
        log.warning(f"download: {e}")
        await notify_admins_text(d, caption)
        return
    for v in d["u"].values():
        if v.get("role") == "employer":
            try:
                buf.seek(0)
                await Bot(ADMIN_TOKEN).send_photo(v["id"], buf, caption=caption, reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                log.warning(e)

async def notify_admins_text(d, text, kb=None):
    bot = Bot(ADMIN_TOKEN)
    for v in d["u"].values():
        if v.get("role") == "employer":
            try:
                await bot.send_message(v["id"], text, reply_markup=InlineKeyboardMarkup(kb) if kb else None)
            except Exception as e:
                log.warning(e)


# ── старт / профиль ────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    if str(uid) not in d["u"]:
        d["u"][str(uid)] = {"role": "worker", "name": update.effective_user.full_name, "username": update.effective_user.username or "", "id": uid, "vacancy": None}
        save(d)
    u = d["u"][str(uid)]
    # если вакансия есть но нет роли — сбрасываем (старые данные)
    if u.get("vacancy") and not u.get("vac_role"):
        u["vacancy"] = None
        save(d)
    if not u.get("vacancy"):
        await _show_vacancy_select(update.message, d, first=True)
        return
    role = u.get("vac_role")
    await update.message.reply_text("привет 👋", reply_markup=main_kb(role))

async def _show_vacancy_select(msg, d, first=False):
    intro = "привет 👋\n\nдля начала выбери вакансию:" if first else "выбери вакансию:"
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"selvac_{k}")] for k, v in VACANCIES.items()]
    await msg.reply_text(intro, reply_markup=InlineKeyboardMarkup(kb))

VAC_DESCRIPTIONS = {
    "1": (
        "💼 Исполнитель\n\n"
        "Ты через бот берёшь задание на любую платформу, выполняешь и получаешь оплату.\n\n"
        "После подтверждения вакансии тебе станут доступны задания."
    ),
    "2": (
        "💼 Траффер\n\n"
        "Твоя задача — приглашать людей из сферы отзывов, которые будут активничать.\n\n"
        "Для тебя выдаётся спец ссылка, по ней ты приглашаешь людей.\n"
        "Оплата производится когда захочешь.\n\n"
        "По всем вопросам: @XA1HS"
    ),
    "3": (
        "💼 Поиск заказчиков\n\n"
        "Заказчик — человек, которому нужны отзывы (повысить рейтинг).\n\n"
        "Как искать:\n"
        "1. Заходишь на платформу (2ГИС, Яндекс, Google), вбиваешь сферу, звонишь и говоришь: \"Здравствуйте, помогаю в поднятии рейтинга. Интересно узнать подробнее?\"\n"
        "2. Пишешь в мессенджер: Добрый день! Мы помогаем бизнесу становиться заметнее через работу с отзывами...\n\n"
        "Если соглашаются — скидывай контакт @XA1HS\n\n"
        "Заработок: от 100 до 13 000 руб за одного заказчика.\n\n"
        "Платформы для поиска: 2ГИС, Яндекс, Google, Авито, ВК, Юла, ЦИАН, HH.ru, WhatsApp\n\n"
        "Сферы: автосервис, парикмахерская, гостиницы, клининг, ремонт техники, здоровье, мебель, съём квартир\n\n"
        "Если заказчик задаёт вопросы — скрин в @XA1HS"
    ),
}

async def select_vacancy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    vid = q.data[7:]
    v = VACANCIES.get(vid)
    if not v:
        await q.edit_message_text("не найдено")
        return
    desc = VAC_DESCRIPTIONS.get(vid, v["title"])
    kb = [[InlineKeyboardButton("✅ подтвердить", callback_data=f"confirvac_{vid}"),
           InlineKeyboardButton("◀️ назад", callback_data="back_selvac")]]
    await q.edit_message_text(desc, reply_markup=InlineKeyboardMarkup(kb))

async def confirm_vacancy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    vid = q.data[10:]
    v = VACANCIES.get(vid)
    if not v:
        await q.edit_message_text("не найдено")
        return
    d = db()
    d["u"][str(uid)]["vacancy"] = {"id": vid, "title": v["title"]}
    d["u"][str(uid)]["vac_role"] = v["role"]
    save(d)
    await q.edit_message_text(f"✅ вакансия подтверждена: {v['title']}")
    await q.message.reply_text("готово 👇", reply_markup=get_kb(uid, d))

async def change_vacancy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"selvac_{k}")] for k, v in VACANCIES.items()]
    await q.message.reply_text("выбери вакансию:", reply_markup=InlineKeyboardMarkup(kb))

async def back_selvac(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"selvac_{k}")] for k, v in VACANCIES.items()]
    await q.edit_message_text("выбери вакансию:", reply_markup=InlineKeyboardMarkup(kb))

async def profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    done = sum(1 for t in d["t"].values() if t.get("wid") == uid and t.get("status") == "closed")
    active = sum(1 for t in d["t"].values() if t.get("wid") == uid and t.get("status") == "active")
    balance = d["u"][str(uid)].get("balance", 0)
    await update.message.reply_text(f"👤 {d['u'][str(uid)]['name']}\n\nв работе: {active}\nвыполнено: {done}\n💰 баланс: {balance} руб", reply_markup=main_kb())


# ── каталог ────────────────────────────────────────────────────────────────────

async def catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    u = d["u"].get(str(uid), {})
    if not u.get("vacancy"):
        await _show_vacancy_select(update.message, d, first=True)
        return
    if u.get("vac_role") != "executor":
        await update.message.reply_text("задания доступны только для исполнителей", reply_markup=main_kb(u.get("vac_role")))
        return
    platforms = list({v["platform"] for v in d["t"].values() if v["status"] == "open"})
    if not platforms:
        await update.message.reply_text("заданий пока нет")
        return
    kb = [[InlineKeyboardButton(p, callback_data=f"pl_{p}")] for p in platforms]
    await update.message.reply_text("выбери платформу:", reply_markup=InlineKeyboardMarkup(kb))

async def show_platform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    platform = q.data[3:]
    await _show_task(q, q.from_user.id, platform, 0)

async def skip_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, platform, idx = q.data.split("|")
    await _show_task(q, q.from_user.id, platform, int(idx))

async def back_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    platforms = list({v["platform"] for v in d["t"].values() if v["status"] == "open"})
    if not platforms:
        await q.edit_message_text("заданий пока нет")
        return
    kb = [[InlineKeyboardButton(p, callback_data=f"pl_{p}")] for p in platforms]
    await q.edit_message_text("выбери платформу:", reply_markup=InlineKeyboardMarkup(kb))

async def _show_task(q, uid, platform, idx):
    d = db()
    tasks = [(k, v) for k, v in d["t"].items() if v["platform"] == platform and v["status"] == "open"]
    back = [[InlineKeyboardButton("◀️ платформы", callback_data="back_cat")]]
    if not tasks or idx >= len(tasks):
        await q.edit_message_text("больше заданий нет", reply_markup=InlineKeyboardMarkup(back))
        return
    tid, t = tasks[idx]
    title = t.get("title") or t.get("t", "без названия")
    city = t.get("city", "")
    theme = t.get("theme", "")
    price = t.get("price", "")
    lines = [f"📌 {title}"]
    if city: lines.append(f"📍 {city}")
    if theme: lines.append(f"🏷 {theme}")
    if price: lines.append(f"💰 {price} руб")
    kb = [[
        InlineKeyboardButton("✅ выполнить", callback_data=f"take|{tid}|{platform}|{idx}"),
        InlineKeyboardButton("❌ отказаться", callback_data=f"skip|{platform}|{idx+1}")
    ], [InlineKeyboardButton("◀️ платформы", callback_data="back_cat")]]
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))


# ── взять задание ──────────────────────────────────────────────────────────────

async def take_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # убираем кнопки сразу
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except: pass
    _, tid, platform, idx = q.data.split("|")
    uid = q.from_user.id
    d = db()
    t = d["t"].get(tid)

    if not t or t["status"] != "open":
        await q.edit_message_text("задание уже недоступно")
        return

    app_key = f"{uid}_{tid}"
    app = d["apps"].get(app_key, {})
    status = app.get("status")

    if status == "checking":
        await q.edit_message_text("🔍 аккаунт уже на проверке, ожидай")
        return
    if status == "rejected":
        ctx.user_data["check_tid"] = tid
        await q.edit_message_text(f"❌ аккаунт отклонён\nпричина: {app.get('reason','')}\n\nскинь новый скриншот профиля:")
        return
    if status != "approved":
        ctx.user_data["check_tid"] = tid
        await q.edit_message_text("скинь скриншот своего профиля на этой платформе:")
        return

    # аккаунт одобрен — берём задание
    if "workers" not in t:
        t["workers"] = []
    if uid in t["workers"]:
        await q.edit_message_text("ты уже берёшь это задание")
        return
    t["workers"].append(uid)
    limit = t.get("limit", 1)
    if len(t["workers"]) >= limit:
        t["status"] = "active"
    t["wid"] = uid
    save(d)

    name = d["u"].get(str(uid), {}).get("name", str(uid))
    await notify_admins_text(d, f"🔔 {name} взял #{tid} [{platform}] {t['title']}")

    kb = [[InlineKeyboardButton("✅ готово", callback_data=f"done|{tid}")]]
    await q.edit_message_text(f"📌 {t['title']}\n\n{t['desc']}", reply_markup=InlineKeyboardMarkup(kb))


# ── скриншот аккаунта ──────────────────────────────────────────────────────────

async def check_acc_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("нужен скриншот, не текст")
        return SEND_ACCOUNT

    uid = update.effective_user.id
    tid = ctx.user_data.pop("check_tid", None)
    if not tid:
        await update.message.reply_text("что-то пошло не так", reply_markup=main_kb())
        return ConversationHandler.END

    file_id = update.message.photo[-1].file_id
    d = db()
    t = d["t"].get(tid, {})

    app_key = f"{uid}_{tid}"
    d["apps"][app_key] = {"uid": uid, "tid": tid, "file_id": file_id, "status": "checking"}
    save(d)

    await update.message.reply_text("скриншот отправлен на проверку, ожидай ✅", reply_markup=main_kb())

    name = d["u"].get(str(uid), {}).get("name", str(uid))
    caption = f"🔍 проверка аккаунта\n\nзадание: #{tid} [{t.get('platform','')}] {t.get('title','')}\nрабочий: {name}"
    kb = [[InlineKeyboardButton("✅ одобрить", callback_data=f"acc_ok|{app_key}"),
           InlineKeyboardButton("❌ отказать", callback_data=f"acc_no|{app_key}")]]
    await notify_admins_photo(d, file_id, caption, kb)


# ── кнопка готово ──────────────────────────────────────────────────────────────

async def task_done_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except: pass
    tid = q.data.split("|")[1]
    uid = q.from_user.id
    d = db()
    t = d["t"].get(tid)
    if not t:
        await q.edit_message_text("не найдено")
        return

    if t.get("type") == "fixed":
        # готовый текст — показываем и просим скриншот
        ctx.user_data["submit_tid"] = tid
        kb = [[InlineKeyboardButton("📸 отправить скриншот", callback_data=f"submit_{tid}")]]
        await q.edit_message_text(
            f"скопируй и опубликуй отзыв:\n\n{t['review_text']}\n\nпосле публикации нажми кнопку:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        # рабочий сам пишет — сначала текст на проверку
        ctx.user_data["write_tid"] = tid
        await q.edit_message_text("напиши текст своего отзыва — отправлю на проверку:")
        return WRITE_REVIEW


# ── рабочий пишет текст отзыва ────────────────────────────────────────────────

async def review_text_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tid = ctx.user_data.pop("write_tid", None)
    if not tid:
        await update.message.reply_text("что-то пошло не так", reply_markup=main_kb())
        return ConversationHandler.END

    review_txt = update.message.text.strip()
    d = db()
    t = d["t"].get(tid)
    if not t:
        await update.message.reply_text("задание не найдено", reply_markup=main_kb())
        return ConversationHandler.END

    t["draft"] = review_txt
    t["status"] = "review_check"
    save(d)

    await update.message.reply_text("текст отправлен на проверку, ожидай ✅", reply_markup=main_kb())

    name = d["u"].get(str(uid), {}).get("name", str(uid))
    kb = [[InlineKeyboardButton("✅ одобрить текст", callback_data=f"txt_ok|{tid}"),
           InlineKeyboardButton("❌ отклонить", callback_data=f"txt_no|{tid}")]]
    await notify_admins_text(d,
        f"📝 текст отзыва на проверке\n\n#{tid} [{t['platform']}] {t['title']}\nрабочий: {name}\n\n{review_txt}",
        kb
    )
    return ConversationHandler.END


# ── сдать скриншот ─────────────────────────────────────────────────────────────

async def submit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except: pass
    ctx.user_data["submit_tid"] = q.data[7:]
    ctx.user_data["step"] = "submit_photo"
    await q.message.reply_text("скинь скриншот опубликованного отзыва:")

async def submit_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("нужен скриншот, не текст")
        return

    uid = update.effective_user.id
    tid = ctx.user_data.pop("submit_tid", None)
    ctx.user_data.pop("step", None)
    d = db()
    t = d["t"].get(tid)
    if not t:
        await update.message.reply_text("не найдено", reply_markup=main_kb())
        return ConversationHandler.END

    file_id = update.message.photo[-1].file_id
    t["status"] = "done"
    t["result"] = file_id
    save(d)

    await update.message.reply_text("сдано, ждём проверки 👍", reply_markup=main_kb())

    name = d["u"].get(str(uid), {}).get("name", str(uid))
    caption = f"📸 скриншот отзыва\n\n#{tid} [{t['platform']}] {t['title']}\nрабочий: {name}"
    kb = [[InlineKeyboardButton("✅ принять", callback_data=f"rev_ok|{tid}"),
           InlineKeyboardButton("❌ отклонить", callback_data=f"rev_no|{tid}")]]
    await notify_admins_photo(d, file_id, caption, kb)


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("ок", reply_markup=main_kb())
    return ConversationHandler.END


# ── вывод средств ──────────────────────────────────────────────────────────────

async def withdraw_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    balance = d["u"].get(str(uid), {}).get("balance", 0)
    if balance < 300:
        await update.message.reply_text(f"минимальная сумма вывода 300 руб\nтвой баланс: {balance} руб", reply_markup=main_kb())
        return
    ctx.user_data["withdraw_step"] = "phone"
    ctx.user_data["withdraw_amount"] = balance
    await update.message.reply_text(f"баланс: {balance} руб\n\nукажи номер телефона или карты:")

async def on_withdraw_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = ctx.user_data.get("withdraw_step")
    txt = update.message.text.strip()
    if step == "phone":
        ctx.user_data["withdraw_phone"] = txt
        ctx.user_data["withdraw_step"] = "bank"
        await update.message.reply_text("укажи банк:")
    elif step == "bank":
        uid = update.effective_user.id
        d = db()
        u = d["u"].get(str(uid), {})
        amount = ctx.user_data.pop("withdraw_amount", 0)
        phone = ctx.user_data.pop("withdraw_phone", "")
        ctx.user_data.pop("withdraw_step", None)
        name = u.get("name", str(uid))
        await update.message.reply_text("заявка на вывод отправлена, ожидай 💸", reply_markup=main_kb())
        kb = [[
            InlineKeyboardButton("✅ подтвердить", callback_data=f"wok|{uid}|{amount}"),
            InlineKeyboardButton("❌ отказать", callback_data=f"wno|{uid}|{amount}")
        ]]
        await notify_admins_text(d,
            f"💸 заявка на вывод\n\nрабочий: {name}\nсумма: {amount} руб\nтелефон/карта: {phone}\nбанк: {txt}",
            kb
        )


# ── мои задания ────────────────────────────────────────────────────────────────

async def my_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    d = db()
    tasks = [(k, v) for k, v in d["t"].items() if v.get("wid") == uid and v["status"] in ("active", "done", "review_check")]
    if not tasks:
        await update.message.reply_text("активных заданий нет", reply_markup=main_kb())
        return
    icons = {"active": "🔵", "done": "🟠", "review_check": "🔍"}
    for tid, t in tasks:
        icon = icons.get(t["status"], "?")
        txt = f"{icon} #{tid} [{t['platform']}]\n{t['title']}"
        kb = [[InlineKeyboardButton("❌ отказ от задания", callback_data=f"canceltask|{tid}")]]
        await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def cancel_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except: pass
    tid = q.data.split("|")[1]
    uid = q.from_user.id
    d = db()
    t = d["t"].get(tid)
    if not t or t.get("wid") != uid:
        await q.answer("не найдено")
        return
    if "workers" not in t:
        t["workers"] = []
    if uid in t["workers"]:
        t["workers"].remove(uid)
    if t["status"] == "active" and len(t["workers"]) < t.get("limit", 1):
        t["status"] = "open"
    t["wid"] = None
    save(d)
    await q.edit_message_text(f"#{tid} возвращено в каталог")
    name = d["u"].get(str(uid), {}).get("name", str(uid))
    await notify_admins_text(d, f"↩ {name} отказался от задания #{tid} [{t['platform']}] {t['title']}")


# ── вакансии ───────────────────────────────────────────────────────────────────

async def vacancies(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = db()
    vacs = d.get("vacs", {})
    if not vacs:
        await update.message.reply_text("вакансий пока нет", reply_markup=main_kb())
        return
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"vac_{k}")] for k, v in vacs.items()]
    await update.message.reply_text("💼 вакансии:", reply_markup=InlineKeyboardMarkup(kb))

async def show_vacancy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    vid = q.data[4:]
    d = db()
    v = d.get("vacs", {}).get(vid)
    if not v:
        await q.edit_message_text("не найдено")
        return
    txt = f"💼 {v['title']}\n\n{v['desc']}\n\n💰 оплата: {v.get('price', '—')}\n\n👤 {v.get('contact', '—')}"
    kb = [[InlineKeyboardButton("◀️ назад", callback_data="back_vac")]]
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def back_vac(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = db()
    vacs = d.get("vacs", {})
    if not vacs:
        await q.edit_message_text("вакансий пока нет")
        return
    kb = [[InlineKeyboardButton(v["title"], callback_data=f"vac_{k}")] for k, v in vacs.items()]
    await q.edit_message_text("💼 вакансии:", reply_markup=InlineKeyboardMarkup(kb))

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("step") == "submit_photo":
        await submit_photo(update, ctx)
        return
    txt = update.message.text
    if ctx.user_data.get("withdraw_step"):
        await on_withdraw_input(update, ctx)
        return
    uid = update.effective_user.id
    d = db()
    role = d["u"].get(str(uid), {}).get("vac_role")
    if txt == "👤 профиль": await profile(update, ctx)
    elif txt == "📋 выполнить задание": await catalog(update, ctx)
    elif txt == "📥 мои задания": await my_tasks(update, ctx)
    elif txt == "💸 вывести": await withdraw_start(update, ctx)
    elif txt in ("🆘 помощь", "🔗 получить ссылку"):
        await update.message.reply_text(f"👉 {HELP_URL}")
    elif txt == "🔄 сменить вакансию":
        d2 = db()
        kb = [[InlineKeyboardButton(v["title"], callback_data=f"selvac_{k}")] for k, v in VACANCIES.items()]
        await update.message.reply_text("выбери вакансию:", reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text("?", reply_markup=main_kb(role))


async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(task_done_btn, pattern=r"^done\|")],
        states={WRITE_REVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, review_text_received)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    ))

    app.add_handler(CallbackQueryHandler(show_platform, pattern="^pl_"))
    app.add_handler(CallbackQueryHandler(skip_task, pattern=r"^skip\|"))
    app.add_handler(CallbackQueryHandler(take_task, pattern=r"^take\|"))
    app.add_handler(CallbackQueryHandler(back_cat, pattern="^back_cat$"))
    app.add_handler(CallbackQueryHandler(select_vacancy, pattern="^selvac_"))
    app.add_handler(CallbackQueryHandler(confirm_vacancy, pattern="^confirvac_"))
    app.add_handler(CallbackQueryHandler(back_selvac, pattern="^back_selvac$"))
    app.add_handler(CallbackQueryHandler(change_vacancy, pattern="^change_vac$"))
    app.add_handler(CallbackQueryHandler(show_vacancy, pattern="^vac_"))
    app.add_handler(CallbackQueryHandler(back_vac, pattern="^back_vac$"))
    app.add_handler(CallbackQueryHandler(cancel_task, pattern=r"^canceltask\|"))
    async def msg_router(u, c):
        if c.user_data.get("check_tid"):
            await check_acc_photo(u, c)
        elif c.user_data.get("step") == "submit_photo":
            await submit_photo(u, c)
        elif u.message and u.message.photo:
            await u.message.reply_text("?")
        else:
            await on_text(u, c)

    app.add_handler(CallbackQueryHandler(submit_start, pattern="^submit_"))
    app.add_handler(MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), msg_router))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    return app
