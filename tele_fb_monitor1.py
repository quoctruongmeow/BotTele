# file: tele_fb_monitor1.py
# pip install pyTelegramBotAPI requests

import os
import re
import time
from datetime import datetime
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# =============== ENV ===============
BOT_TOKEN = os.getenv("BOT_TOKEN") or "<PUT_YOUR_BOT_TOKEN_HERE>"
if not BOT_TOKEN or BOT_TOKEN.startswith("<PUT_"):
    raise SystemExit("Thiếu BOT_TOKEN. Đặt biến môi trường BOT_TOKEN hoặc sửa trực tiếp trong file.")

ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
AUTH_USER_IDS = {int(x.strip()) for x in os.getenv("AUTH_USER_IDS", "").split(",") if x.strip().isdigit()}

print("DEBUG -> ADMIN_IDS loaded:", ADMIN_IDS)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def is_authorized(uid: int) -> bool:
    return is_admin(uid) or (uid in AUTH_USER_IDS)

# =============== THUẬT TOÁN CHECK (GIỮ NGUYÊN) ===============
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
def check_live(uid: str, timeout: float = 10.0) -> str:
    """
    GIỮ NGUYÊN: gọi graph.facebook + redirect=false, dò 'height' & 'width'
    Trả về: 'live' | 'die' | 'error'
    """
    url = f"https://graph.facebook.com/{uid}/picture"
    headers = {
        "Connection": "keep-alive",
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(url, params={"redirect": "false"}, headers=headers, timeout=timeout)
        body = r.text or ""
        if body:
            return "live" if ("height" in body and "width" in body) else "die"
    except Exception:
        pass
    return "error"

# =============== STATE (RAM) ===============
# store_map: owner_id -> { uid -> {"name": str, "note": str, "following": bool, "added": ts, "kind": "profile"|"group"} }
store_map: dict[int, dict[str, dict]] = {}
wizard_state: dict[int, dict] = {}

GREEN = "🟢"; RED = "🔴"

def get_store(owner: int) -> dict:
    if owner not in store_map:
        store_map[owner] = {}
    return store_map[owner]

def set_item(owner: int, uid: str, name: str = "", note: str = "", following: bool = True, kind: str = "profile"):
    s = get_store(owner)
    if uid in s:
        s[uid]["name"] = name or s[uid].get("name", "")
        s[uid]["note"] = note or s[uid].get("note", "")
        s[uid]["following"] = following if following is not None else s[uid].get("following", True)
        if kind: s[uid]["kind"] = kind or s[uid].get("kind", "profile")
    else:
        s[uid] = {
            "name": name or "",
            "note": note or "",
            "following": True if following is None else following,
            "added": int(time.time()),
            "kind": (kind or "profile"),
        }

def get_following(owner: int, uid: str) -> bool:
    return get_store(owner).get(uid, {}).get("following", True)

def set_following(owner: int, uid: str, val: bool):
    if uid in get_store(owner):
        store_map[owner][uid]["following"] = val
    else:
        set_item(owner, uid, following=val)

def reset_wizard(uid: int): wizard_state.pop(uid, None)

# =============== ACCESS DECORATOR ===============
def require_access(fn):
    def wrapper(message, *args, **kwargs):
        if not is_authorized(message.from_user.id):
            bot.reply_to(message, "⛔ Bạn chưa được cấp quyền sử dụng bot. Liên hệ admin để /grant.")
            return
        return fn(message, *args, **kwargs)
    return wrapper

# =============== UI HELPERS ===============
def type_keyboard(uid: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👤 Profile/Page", callback_data=f"type:profile:{uid}"),
        InlineKeyboardButton("👥 Group", callback_data=f"type:group:{uid}")
    )
    return kb

def _kind_label(kind: str) -> str:
    return "Group" if (kind or "profile") == "group" else "Profile/Page"

def build_result_card(owner_id: int, uid: str):
    info = get_store(owner_id).get(uid, {"name": "", "note": "", "following": True, "added": int(time.time()), "kind":"profile"})
    name, note = info.get("name",""), info.get("note","")
    kind = info.get("kind","profile")
    status = check_live(uid)
    dot = GREEN if status == "live" else RED
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    text = (
        "🆕 <b>Đã thêm UID mới!</b>\n"
        "────────────────────\n"
        f"🆔 <b>UID:</b> <code>{uid}</code>\n"
        f"📄 <b>Loại:</b> {_kind_label(kind)}\n"
        f"👤 <b>Tên:</b> {name or '-'}\n"
        f"📝 <b>Ghi chú:</b> {note or '-'}\n"
        f"📅 <b>Ngày thêm:</b> {now}\n"
        f"📌 <b>Trạng thái hiện tại:</b> {dot} {status.upper()}"
    )
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🌐 Mở Facebook", url=f"https://facebook.com/{uid}"))
    if get_following(owner_id, uid):
        kb.add(
            InlineKeyboardButton("🟢 Tiếp tục theo dõi", callback_data=f"noop:{owner_id}:{uid}"),
            InlineKeyboardButton("🛑 Dừng theo dõi UID này", callback_data=f"stop:{owner_id}:{uid}"),
        )
    else:
        kb.add(InlineKeyboardButton("✅ Bắt đầu theo dõi lại", callback_data=f"start:{owner_id}:{uid}"))
    return text, kb

def build_toggle_card(uid: str, action: str, owner_id: int):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if action == "stop":
        title = "🔕 ĐÃ TẮT THEO DÕI UID"
        body  = (f"🆔 UID: <code>{uid}</code>\n📣 Thông báo: ĐÃ TẮT\n⏱️ Thời gian: {ts}")
    else:
        title = "🔔 ĐÃ BẬT LẠI THEO DÕI UID"
        body  = (f"🆔 UID: <code>{uid}</code>\n📣 Thông báo: ĐÃ BẬT LẠI\n⏱️ Thời gian: {ts}")
    text = f"<b>{title}</b>\n────────────────────\n{body}"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🟢 Tiếp tục theo dõi", callback_data=f"start:{owner_id}:{uid}"),
        InlineKeyboardButton("🛑 Dừng theo dõi UID này", callback_data=f"stop:{owner_id}:{uid}")
    )
    return text, kb

def extract_uid_from_link(link: str, timeout: float = 8.0) -> str | None:
    m = re.search(r"[?&]id=(\d{5,})", link)
    if m: return m.group(1)
    m2 = re.search(r"facebook\.com/(?:profile\.php\?id=)?(\d{7,})", link)
    if m2: return m2.group(1)
    m3 = re.search(r"facebook\.com/([A-Za-z0-9.\-_]+)/?", link)
    if m3:
        uname = m3.group(1).lower()
        if uname in {"profile.php","people","pages"}: return None
        try:
            headers = {"User-Agent": USER_AGENT, "Connection": "keep-alive", "Accept": "*/*"}
            r = requests.get(f"https://graph.facebook.com/{uname}", params={"fields":"id"}, headers=headers, timeout=timeout)
            if r.headers.get("content-type","").startswith("application/json"):
                uid = str(r.json().get("id") or "")
                return uid if uid.isdigit() else None
        except Exception:
            return None
    return None

# =============== MENU/DEBUG ===============
HELP_BULK = (
    "📘 <b>HƯỚNG DẪN THÊM UID HÀNG LOẠT:</b>\n\n"
    "⚠️ <b>LƯU Ý QUAN TRỌNG:</b>\n"
    "• <b>Bulk add</b> chỉ hỗ trợ <b>Profile/Page</b>\n"
    "• <b>Group</b> vui lòng thêm thủ công bằng <code>/them</code>\n\n"
    "🔢 <b>Các format hỗ trợ:</b>\n"
    "1️⃣ <u>UID đơn giản</u>:\n"
    "<code>1000001234567890</code>\n"
    "<code>1000001234567891</code>\n\n"
    "2️⃣ <u>UID + Tên + Ghi chú (Space)</u>:\n"
    "<code>1000001234567890 Võ Nhật Khánh Unlock 282</code>\n"
    "<code>1000001234567891 Nguyễn Bá Vinh Dame 282</code>\n\n"
    "3️⃣ <u>UID + Tên + Ghi chú (Tab)</u>:\n"
    "<code>1000001234567890\tNguyễn Văn A\tUnlock 282</code>\n"
    "<code>1000001234567891\tTrần Thị B\tDame 282</code>\n\n"
    "4️⃣ <u>UID + Tên + Ghi chú (|)</u>:\n"
    "<code>1000001234567890|Nguyễn Văn A|Unlock 282</code>\n"
    "<code>1000001234567891|Trần Thị B|Dame 282</code>\n\n"
    "5️⃣ <u>Link Facebook</u>:\n"
    "<code>https://facebook.com/1000001234567890</code>\n"
    "<code>https://fb.com/1000001234567891</code>\n\n"
    "⚠️ <b>Lưu ý</b>:\n"
    "• Tối đa <b>1000 UID/lần</b>\n"
    "• UID trùng lặp sẽ bị bỏ qua\n"
    "• Bot sẽ tự động check trạng thái sau khi thêm\n"
    "• Tất cả UID sẽ được set loại <b>Profile/Page</b>\n\n"
    "📝 <i>Vui lòng paste danh sách UID:</i>"
)

@bot.message_handler(commands=["start","trogiup","menu"])
def cmd_start(m):
    admin_note = ("\n\n<i>Lệnh ADMIN:</i> /grant, /revoke, /who" if is_admin(m.from_user.id) else "")
    bot.reply_to(m,
        "<b>Xin chào!</b>\n"
        "Lệnh: /myid, /them, /themhg, /danhsach, /xoa, /dung, /tieptuc\n"
        "Nếu bạn chưa được cấp quyền, gửi /myid cho admin để được /grant." + admin_note
    )

# /myid LUÔN HOẠT ĐỘNG CHO MỌI NGƯỜI (KHÔNG CHECK QUYỀN)
@bot.message_handler(commands=["myid"])
def cmd_myid(m):
    bot.reply_to(m, f"🆔 Your chat_id: <code>{m.from_user.id}</code>")

@bot.message_handler(commands=["checkenv"])
def cmd_checkenv(m):
    from os import getenv
    bot.reply_to(
        m,
        "<b>ENV hiện tại:</b>\n"
        f"BOT_TOKEN: <code>{(getenv('BOT_TOKEN') or '')[:10]}...</code>\n"
        f"ADMIN_IDS: <code>{getenv('ADMIN_IDS')}</code>\n"
        f"AUTH_USER_IDS: <code>{getenv('AUTH_USER_IDS')}</code>"
    )

# =============== ADMIN: /grant /revoke /who ===============
def _resolve_target_id(message) -> int | None:
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    return None

@bot.message_handler(commands=["grant"])
def cmd_grant(m):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "⛔ Chỉ admin mới dùng được /grant.")
    target = _resolve_target_id(m)
    if not target:
        return bot.reply_to(m, "Dùng: <code>/grant &lt;chat_id&gt;</code> hoặc reply vào tin nhắn của user rồi gõ /grant.")
    if target in ADMIN_IDS:
        return bot.reply_to(m, "Người này đã là admin, mặc định có quyền.")
    AUTH_USER_IDS.add(target)
    bot.reply_to(m, f"✅ Đã cấp quyền cho user: <code>{target}</code>")

@bot.message_handler(commands=["revoke"])
def cmd_revoke(m):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "⛔ Chỉ admin mới dùng được /revoke.")
    target = _resolve_target_id(m)
    if not target:
        return bot.reply_to(m, "Dùng: <code>/revoke &lt;chat_id&gt;</code> hoặc reply vào tin nhắn của user rồi gõ /revoke.")
    if target in AUTH_USER_IDS:
        AUTH_USER_IDS.remove(target)
        bot.reply_to(m, f"🗑️ Đã thu hồi quyền của user: <code>{target}</code>")
    else:
        bot.reply_to(m, "User này chưa được cấp quyền hoặc đã bị thu hồi trước đó.")

@bot.message_handler(commands=["who"])
def cmd_who(m):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "⛔ Chỉ admin mới dùng được /who.")
    admins = ", ".join(str(i) for i in sorted(ADMIN_IDS)) or "(trống)"
    users  = ", ".join(str(i) for i in sorted(AUTH_USER_IDS)) or "(trống)"
    bot.reply_to(m, f"<b>Admins:</b> {admins}\n<b>Authorized users:</b> {users}")

# =============== USER COMMANDS ===============
@bot.message_handler(commands=["danhsach"])
@require_access
def cmd_danhsach(m):
    owner = m.from_user.id
    store = get_store(owner)
    if not store:
        return bot.reply_to(m, "📭 Danh sách trống.")
    send_list_page(m.chat.id, owner, page=1)

def send_list_page(chat_id: int, owner: int, page: int, page_size: int = 5, edit_msg_id: int | None = None):
    items = list(get_store(owner).items())
    total_pages = (len(items) + page_size - 1) // page_size
    page = max(1, min(page, max(total_pages, 1)))
    chunk = items[(page-1)*page_size: page*page_size]

    blocks = []
    for uid, info in chunk:
        status = check_live(uid)
        dot = GREEN if status == "live" else RED
        name = info.get("name","-")
        note = info.get("note","-")
        kind = info.get("kind","profile")
        ts = info.get("added", 0)
        added = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "-"
        blocks.append(
            "────────────────────\n"
            f"🆔 <b>UID:</b> <a href=\"https://facebook.com/{uid}\">{uid}</a>\n"
            f"📄 <b>Loại:</b> {_kind_label(kind)}\n"
            f"👤 <b>Tên:</b> {name}\n"
            f"📝 <b>Ghi chú:</b> {note}\n"
            f"📌 <b>Trạng thái:</b> {dot} {status.upper()}\n"
            f"📅 <b>Ngày thêm:</b> {added}\n"
        )

    header = f"📂 <b>Danh sách UID bạn đang theo dõi:</b> (Trang {page}/{total_pages})\n\n"
    text = header + ("\n".join(blocks) if blocks else "—")

    kb = InlineKeyboardMarkup(row_width=3)
    prev_btn = InlineKeyboardButton("⏮", callback_data=f"list:{owner}:{page-1}") if page > 1 else None
    next_btn = InlineKeyboardButton("⏭", callback_data=f"list:{owner}:{page+1}") if page < total_pages else None
    if prev_btn and next_btn:
        kb.add(prev_btn, InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"), next_btn)
    elif prev_btn:
        kb.add(prev_btn, InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"))
    elif next_btn:
        kb.add(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"), next_btn)

    if edit_msg_id:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=edit_msg_id, text=text,
                                  reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)
    else:
        bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("list:") or c.data == "noopnav")
def cb_list(c):
    if c.data == "noopnav":
        return bot.answer_callback_query(c.id)
    _, owner_str, page_str = c.data.split(":")
    owner = int(owner_str)
    page = int(page_str)
    if (c.from_user.id != owner) and (not is_admin(c.from_user.id)):
        return bot.answer_callback_query(c.id, "⛔ Không có quyền xem danh sách này.")
    send_list_page(c.message.chat.id, owner, page, edit_msg_id=c.message.message_id)
    bot.answer_callback_query(c.id)

@bot.message_handler(commands=["xoa"])
@require_access
def cmd_xoa(m):
    parts = m.text.split()
    if len(parts) < 2:
        return bot.reply_to(m, "Dùng: <code>/xoa &lt;uid&gt;</code>")
    uid = parts[1]
    removed = get_store(m.from_user.id).pop(uid, None)
    if removed is None:
        bot.reply_to(m, f"UID <code>{uid}</code> không có trong danh sách của bạn.")
    else:
        bot.reply_to(m, f"Đã xóa UID <code>{uid}</code> khỏi danh sách của bạn.")

@bot.message_handler(commands=["huy"])
@require_access
def cmd_cancel(m):
    reset_wizard(m.from_user.id)
    bot.reply_to(m, "❎ Đã hủy thao tác hiện tại.")

# ---------- Wizard /them ----------
@bot.message_handler(commands=["them"])
@require_access
def cmd_them(m):
    reset_wizard(m.from_user.id)
    bot.reply_to(m, "➕ <b>Vui lòng nhập UID bạn muốn theo dõi:</b>\nVí dụ: <code>100023509740024</code>")
    bot.register_next_step_handler(m, step_uid)

def step_uid(msg):
    if not is_authorized(msg.from_user.id): return
    if msg.text and msg.text.strip().lower() in {"/huy", "huy"}:
        return cmd_cancel(msg)
    uid = (msg.text or "").strip()
    if not re.fullmatch(r"\d{6,}", uid):
        bot.reply_to(msg, "UID không hợp lệ. Vui lòng nhập lại (hoặc /huy):")
        return bot.register_next_step_handler(msg, step_uid)
    # default type = profile
    wizard_state[msg.from_user.id] = {"uid": uid, "note": "", "name": "", "kind": "profile"}
    bot.send_message(msg.chat.id, f"🧩 <b>Chọn loại UID cho</b> <code>{uid}</code>:", reply_markup=type_keyboard(uid))

def step_note(msg):
    if not is_authorized(msg.from_user.id): return
    if msg.text and msg.text.strip().lower() in {"/huy", "huy"}:
        return cmd_cancel(msg)
    wizard_state[msg.from_user.id]["note"] = (msg.text or "").strip()
    uid = wizard_state[msg.from_user.id]["uid"]
    bot.send_message(msg.chat.id, f"🖋️ <b>Nhập tên cho UID</b> <code>{uid}</code>\nVí dụ: Tran Tang")
    bot.register_next_step_handler(msg, step_name)

def step_name(msg):
    if not is_authorized(msg.from_user.id): return
    if msg.text and msg.text.strip().lower() in {"/huy", "huy"}:
        return cmd_cancel(msg)
    name = (msg.text or "").strip()
    data = wizard_state[msg.from_user.id]
    uid = data["uid"]; note = data["note"]; kind = data.get("kind","profile")
    set_item(msg.from_user.id, uid, name=name, note=note, following=True, kind=kind)

    bot.send_message(msg.chat.id, f"🤖 Bot đang xử lý UID <code>{uid}</code>. Sẽ báo cho bạn khi hoàn thành!")
    text, kb = build_result_card(msg.from_user.id, uid)
    bot.send_message(msg.chat.id, text, reply_markup=kb, disable_web_page_preview=True)

    reset_wizard(msg.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("type:"))
def choose_type(c):
    _, t, uid = c.data.split(":", 2)
    if not is_authorized(c.from_user.id):
        bot.answer_callback_query(c.id, "⛔ Bạn chưa được cấp quyền."); return
    st = wizard_state.get(c.from_user.id) or {"uid": uid, "note": "", "name": "", "kind":"profile"}
    st["uid"] = uid
    if t == "group":
        st["kind"] = "group"
        bot.answer_callback_query(c.id, "Đã chọn loại: Group ✅")
    else:
        st["kind"] = "profile"
        bot.answer_callback_query(c.id, "Đã chọn loại: Profile/Page ✅")
    wizard_state[c.from_user.id] = st
    bot.send_message(c.message.chat.id, f"🖊️ <b>Nhập ghi chú cho UID</b> <code>{uid}</code>\nVí dụ: Dame 282, unlock 282")
    bot.register_next_step_handler(c.message, step_note)

# ---------- Toggle buttons ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith(("noop:", "stop:", "start:")) )
def follow_buttons(c):
    parts = c.data.split(":")
    if len(parts) == 3:
        action, owner_str, uid = parts
        try: owner = int(owner_str)
        except: owner = c.from_user.id
    else:
        action, uid = parts[0], parts[-1]; owner = c.from_user.id

    if (owner != c.from_user.id) and (not is_admin(c.from_user.id)):
        bot.answer_callback_query(c.id, "⛔ Không có quyền thao tác mục này."); return

    if action == "noop":
        bot.answer_callback_query(c.id, "Vẫn đang theo dõi UID này."); return

    if action == "stop":
        set_following(owner, uid, False)
        bot.answer_callback_query(c.id, "Đã dừng theo dõi.")
        text, kb = build_toggle_card(uid, "stop", owner)
        bot.send_message(c.message.chat.id, text, reply_markup=kb, disable_web_page_preview=True)
    elif action == "start":
        set_following(owner, uid, True)
        bot.answer_callback_query(c.id, "Đã tiếp tục theo dõi.")
        text, kb = build_toggle_card(uid, "start", owner)
        bot.send_message(c.message.chat.id, text, reply_markup=kb, disable_web_page_preview=True)

# =============== /themhg (bulk) ===============
@bot.message_handler(commands=["themhangloat","themnhg","themnhgloat","themhangloạt","themhg","themhng"])
@require_access
def cmd_themhangloat(m):
    bot.reply_to(m, HELP_BULK)
    bot.register_next_step_handler(m, step_bulk_receive)

def step_bulk_receive(msg):
    if not is_authorized(msg.from_user.id): return
    text = (msg.text or "").strip()
    if not text and msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text.strip()
    if not text:
        bot.reply_to(msg, "Bạn chưa gửi danh sách. Gõ /themhg để xem hướng dẫn và thử lại."); return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    seen = set(); items = []
    for ln in lines:
        if len(items) >= 1000: break
        parsed = parse_one_line(ln)
        if not parsed: continue
        uid, name, note = parsed
        if uid in seen: continue
        seen.add(uid)
        items.append((uid, name, note))

    if not items:
        bot.reply_to(msg, "Không parse được UID hợp lệ nào. Kiểm tra lại định dạng."); return

    owner = msg.from_user.id
    summary_rows = []
    for uid, name, note in items:
        set_item(owner, uid, name=name, note=note, following=True, kind="profile")  # bulk = profile/page
        status = check_live(uid)
        summary_rows.append(f"{uid}: {status}")
    bot.reply_to(msg, "<b>Đã thêm hàng loạt:</b>\n<code>" + "\n".join(summary_rows[:50]) + "</code>")

    for uid, name, note in items[:20]:
        text_card, kb = build_result_card(owner, uid)
        bot.send_message(msg.chat.id, text_card, reply_markup=kb, disable_web_page_preview=True)

def parse_one_line(ln: str) -> tuple[str,str,str] | None:
    if ln.startswith("http://") or ln.startswith("https://"):
        uid = extract_uid_from_link(ln)
        if uid: return (uid, "", "")
        return None
    if "|" in ln:
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) >= 1 and parts[0].isdigit():
            uid = parts[0]; name = parts[1] if len(parts) >= 2 else ""; note = parts[2] if len(parts) >= 3 else ""
            return (uid, name, note)
    if "\t" in ln:
        parts = [p.strip() for p in ln.split("\t")]
        if len(parts) >= 1 and parts[0].isdigit():
            uid = parts[0]; name = parts[1] if len(parts) >= 2 else ""; note = parts[2] if len(parts) >= 3 else ""
            return (uid, name, note)
    toks = ln.split()
    if len(toks) >= 1 and toks[0].isdigit():
        uid = toks[0]
        if len(toks) >= 3:
            note = " ".join(toks[-2:])
            name = " ".join(toks[1:-2]) or ""
        elif len(toks) == 2:
            name = toks[1]; note = ""
        else:
            name = ""; note = ""
        return (uid, name, note)
    if re.fullmatch(r"\d{6,}", ln):
        return (ln, "", "")
    return None

# =============== RUN ===============
if __name__ == "__main__":
    print("Bot (admin/user + grant/revoke/who) is running…")
    bot.infinity_polling(skip_pending=True, timeout=60)
