# file: tele_fb_monitor1.py
# pip install pyTelegramBotAPI requests

import os
import re
import json
import time as _time
import threading
from datetime import datetime
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============== ENV ==============
BOT_TOKEN = os.getenv("BOT_TOKEN") or "<PUT_YOUR_BOT_TOKEN_HERE>"
if not BOT_TOKEN or BOT_TOKEN.startswith("<PUT_"):
    raise SystemExit("Thiếu BOT_TOKEN. Đặt ENV BOT_TOKEN hoặc sửa trực tiếp trong file.")

ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
AUTH_USER_IDS = {int(x.strip()) for x in os.getenv("AUTH_USER_IDS", "").split(",") if x.strip().isdigit()}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
GREEN, RED = "🟢", "🔴"

# ============== CHECK LIVE (GIỮ NGUYÊN) ==============
def check_live(uid: str, timeout: float = 10.0) -> str:
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

# ============== SUBSCRIPTIONS (thuê bao) ==============
SUBS_FILE = "subs.json"   # { "12345": {"granted_at":..., "expire_at":...} }
def now_ts() -> int: return int(_time.time())

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

subs = {int(k): v for k, v in _load_json(SUBS_FILE, {}).items()}
def save_subs(): _save_json(SUBS_FILE, {str(k): v for k, v in subs.items()})

def is_admin(uid: int) -> bool: return uid in ADMIN_IDS
def is_active_subscription(uid: int) -> bool:
    info = subs.get(uid)
    return bool(info and info.get("expire_at", 0) > now_ts())
def is_authorized(uid: int) -> bool:
    return is_admin(uid) or (uid in AUTH_USER_IDS) or is_active_subscription(uid)

# ============== STORE (UID được theo dõi) ==============
STORE_FILE = "store.json"  # owner_id -> {uid -> {...}}
store_map = {int(k): v for k, v in _load_json(STORE_FILE, {}).items()}
def save_store(): _save_json(STORE_FILE, {str(k): v for k, v in store_map.items()})

def get_store(owner: int) -> dict:
    if owner not in store_map: store_map[owner] = {}
    return store_map[owner]

def set_item(owner: int, uid: str, name: str="", note: str="", following: bool=True, kind: str="profile"):
    s = get_store(owner)
    if uid in s:
        s[uid]["name"] = name or s[uid].get("name","")
        s[uid]["note"] = note or s[uid].get("note","")
        s[uid]["following"] = following if following is not None else s[uid].get("following", True)
        if kind: s[uid]["kind"] = kind or s[uid].get("kind","profile")
    else:
        s[uid] = {"name": name or "", "note": note or "", "following": True if following is None else following,
                  "added": now_ts(), "kind": (kind or "profile")}
    save_store()

def get_following(owner: int, uid: str) -> bool: return get_store(owner).get(uid, {}).get("following", True)
def set_following(owner: int, uid: str, val: bool):
    if uid in get_store(owner):
        store_map[owner][uid]["following"] = val
    else:
        set_item(owner, uid, following=val)
        return
    save_store()

# ============== WIZARD STATE ==============
wizard_state = {}

# ============== MARKETING & ACCESS DECORATOR ==============
MARKETING_TEXT = (
    "⛔ <b>Bạn chưa có quyền dùng bot.</b>\n"
    "Liên hệ admin để đăng ký gói sử dụng.\n"
)

def require_access(fn):
    def wrapper(message, *args, **kwargs):
        uid = message.from_user.id
        if not is_authorized(uid):
            return bot.reply_to(message, MARKETING_TEXT)
        # Nhắc nhẹ nếu còn <=3 ngày
        if not is_admin(uid) and uid not in AUTH_USER_IDS:
            info = subs.get(uid)
            if info:
                left = info.get("expire_at", 0) - now_ts()
                if left > 0 and left // 86400 <= 3:
                    bot.send_message(message.chat.id, f"⏳ Gói của bạn còn <b>{max(0,left//86400)} ngày</b>.")
        return fn(message, *args, **kwargs)
    return wrapper

# ============== Helpers UI ==============
def type_keyboard(uid: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👤 Profile/Page", callback_data=f"type:profile:{uid}"),
        InlineKeyboardButton("👥 Group", callback_data=f"type:group:{uid}")
    )
    return kb

def _kind_label(kind: str) -> str: return "Group" if (kind or "profile") == "group" else "Profile/Page"

def build_result_card(owner_id: int, uid: str):
    info = get_store(owner_id).get(uid, {"name":"", "note":"", "following":True, "added":now_ts(), "kind":"profile"})
    name, note = info.get("name",""), info.get("note","")
    kind = info.get("kind","profile")
    status = check_live(uid); dot = GREEN if status == "live" else RED
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    text = (
        "🆕 <b>Đã thêm UID mới!</b>\n"
        "────────────────────\n"
        f"🆔 <b>UID:</b> <code>{uid}</code>\n"
        f"📄 <b>Loại:</b> {_kind_label(kind)}\n"
        f"👤 <b>Tên:</b> {name or '-'}\n"
        f"📝 <b>Ghi chú:</b> {note or '-'}\n"
        f"📅 <b>Ngày thêm:</b> {now_str}\n"
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
    title = "🔕 ĐÃ TẮT THEO DÕI UID" if action=="stop" else "🔔 ĐÃ BẬT LẠI THEO DÕI UID"
    body  = f"🆔 UID: <code>{uid}</code>\n⏱️ Thời gian: {ts}"
    text = f"<b>{title}</b>\n────────────────────\n{body}"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🟢 Tiếp tục theo dõi", callback_data=f"start:{owner_id}:{uid}"),
        InlineKeyboardButton("🛑 Dừng theo dõi UID này", callback_data=f"stop:{owner_id}:{uid}")
    )
    return text, kb

# ============== Extract UID/Group ID ==============
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

def extract_group_id(link: str, timeout: float = 8.0) -> str | None:
    m = re.search(r"facebook\.com/groups/(\d{5,})", link)
    if m: return m.group(1)
    m2 = re.search(r"facebook\.com/groups/([A-Za-z0-9.\-_]+)", link)
    if m2:
        slug = m2.group(1).split("?")[0].strip("/")
        if slug and not slug.isdigit():
            try:
                headers = {"User-Agent": USER_AGENT, "Connection": "keep-alive", "Accept": "*/*"}
                r = requests.get(f"https://graph.facebook.com/{slug}", params={"fields":"id"}, headers=headers, timeout=timeout)
                if r.headers.get("content-type","").startswith("application/json"):
                    gid = str(r.json().get("id") or "")
                    return gid if gid.isdigit() else None
            except Exception:
                return None
    if re.fullmatch(r"\d{5,}", link.strip()):
        return link.strip()
    return None

# ============== START / MENU / STATUS ==============
@bot.message_handler(commands=["start","trogiup","menu"])
def cmd_start(m):
    admin_note = ("\n\n<i>Lệnh ADMIN:</i> /grant, /revoke, /who, /approve, /extend, /expire" if is_admin(m.from_user.id) else "")
    bot.reply_to(m,
        "<b>Xin chào!</b>\n"
        "Lệnh: /myid, /status, /them, /themg, /themhg, /danhsach, /xoa, /getuid, /huy" + admin_note
    )

@bot.message_handler(commands=["myid"])
def cmd_myid(m): bot.reply_to(m, f"🆔 Your chat_id: <code>{m.from_user.id}</code>")

@bot.message_handler(commands=["status"])
def cmd_status(m):
    uid = m.from_user.id
    if is_admin(uid) or uid in AUTH_USER_IDS:
        return bot.reply_to(m, "✅ Bạn có quyền dùng bot (lifetime).")
    info = subs.get(uid)
    if not info: return bot.reply_to(m, "❌ Bạn chưa được duyệt.")
    left = max(0, info.get("expire_at",0) - now_ts())
    bot.reply_to(m, f"⏳ Gói còn <b>{left//86400} ngày</b>.")

# ============== ADMIN CMDS ==============
def _resolve_target_id(message) -> int | None:
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].isdigit(): return int(parts[1])
    if message.reply_to_message: return message.reply_to_message.from_user.id
    return None

@bot.message_handler(commands=["grant"])
def cmd_grant(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    target = _resolve_target_id(m)
    if not target: return bot.reply_to(m, "Dùng: /grant <chat_id> hoặc reply user rồi /grant")
    AUTH_USER_IDS.add(target)
    bot.reply_to(m, f"✅ Đã cấp quyền trọn đời cho user: <code>{target}</code>")

@bot.message_handler(commands=["revoke"])
def cmd_revoke(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    target = _resolve_target_id(m)
    if not target: return bot.reply_to(m, "Dùng: /revoke <chat_id>")
    removed = False
    if target in AUTH_USER_IDS: AUTH_USER_IDS.remove(target); removed=True
    if target in subs: subs.pop(target, None); save_subs(); removed=True
    bot.reply_to(m, "🗑️ Đã thu hồi quyền." if removed else "User này chưa có quyền.")

@bot.message_handler(commands=["who"])
def cmd_who(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    admins = ", ".join(map(str, sorted(ADMIN_IDS))) or "(trống)"
    users = ", ".join(map(str, sorted(AUTH_USER_IDS))) or "(trống)"
    active = [str(uid) for uid, inf in subs.items() if inf.get("expire_at",0) > now_ts()]
    bot.reply_to(m, f"<b>Admins:</b> {admins}\n<b>Lifetime:</b> {users}\n<b>Subscribers active:</b> {', '.join(active) or '(trống)'}")

@bot.message_handler(commands=["approve"])
def cmd_approve(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    parts = m.text.split()
    if len(parts) < 2: return bot.reply_to(m, "Cú pháp: /approve <chat_id> [days=30]")
    try:
        target = int(parts[1]); days = int(parts[2]) if len(parts)>=3 else 30
    except Exception:
        return bot.reply_to(m, "Cú pháp: /approve <chat_id> [days=30]")
    subs[target] = {"granted_at": now_ts(), "expire_at": now_ts() + days*86400}
    save_subs()
    bot.reply_to(m, f"✅ Đã duyệt <code>{target}</code> {days} ngày.")

@bot.message_handler(commands=["extend"])
def cmd_extend(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    parts = m.text.split()
    if len(parts) < 3: return bot.reply_to(m, "Cú pháp: /extend <chat_id> <days>")
    target, days = int(parts[1]), int(parts[2])
    if target not in subs: subs[target] = {"granted_at": now_ts(), "expire_at": now_ts()}
    base = max(subs[target]["expire_at"], now_ts())
    subs[target]["expire_at"] = base + days*86400
    save_subs()
    bot.reply_to(m, f"⏳ Đã cộng thêm {days} ngày cho <code>{target}</code>.")

@bot.message_handler(commands=["expire"])
def cmd_expire(m):
    if not is_admin(m.from_user.id): return bot.reply_to(m, "⛔ Admin only.")
    parts = m.text.split()
    if len(parts) < 2: return bot.reply_to(m, "Cú pháp: /expire <chat_id>")
    target = int(parts[1]); info = subs.get(target)
    if info:
        subs[target]["expire_at"] = 0; save_subs()
        return bot.reply_to(m, f"❌ Đã set hết hạn cho <code>{target}</code>.")
    bot.reply_to(m, "User chưa có gói.")

# ============== /getuid (username/link -> id) ==============
@bot.message_handler(commands=["getuid"])
@require_access
def cmd_getuid(m):
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2: return bot.reply_to(m, "Dùng: <code>/getuid &lt;username hoặc link&gt;</code>")
    arg = parts[1].strip()
    # group?
    gid = extract_group_id(arg)
    if gid: return bot.reply_to(m, f"👥 <b>Group ID:</b> <code>{gid}</code>")
    # profile/page?
    uid = extract_uid_from_link(arg) if arg.startswith("http") else None
    if not uid and re.fullmatch(r"[A-Za-z0-9.\-_]+", arg):
        uid = extract_uid_from_link("https://facebook.com/"+arg)
    if uid: return bot.reply_to(m, f"👤 <b>UID:</b> <code>{uid}</code>")
    bot.reply_to(m, "❌ Không lấy được ID.")

# ============== /danhsach, phân trang & tổng LIVE/DIE/UNKNOWN ==============
def calc_totals(owner: int):
    s = get_store(owner); live=died=unknown=0
    for uid in s.keys():
        st = check_live(uid)
        if st=="live": live += 1
        elif st=="die": died += 1
        else: unknown += 1
    return live, died, unknown

@bot.message_handler(commands=["danhsach"])
@require_access
def cmd_danhsach(m):
    if not get_store(m.from_user.id): return bot.reply_to(m, "📭 Danh sách trống.")
    send_list_page(m.chat.id, m.from_user.id, page=1)

def send_list_page(chat_id: int, owner: int, page: int, page_size: int = 5, edit_msg_id: int | None = None):
    items = list(get_store(owner).items())
    total_pages = max(1, (len(items)+page_size-1)//page_size)
    page = max(1, min(page, total_pages))
    chunk = items[(page-1)*page_size: page*page_size]

    blocks=[]
    for uid, info in chunk:
        st = check_live(uid); dot = GREEN if st=="live" else RED
        name = info.get("name","-"); note = info.get("note","-"); kind = info.get("kind","profile")
        ts = info.get("added",0); added = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S") if ts else "-"
        blocks.append(
            "────────────────────\n"
            f"🆔 <b>UID:</b> <a href=\"https://facebook.com/{uid}\">{uid}</a>\n"
            f"📄 <b>Loại:</b> {_kind_label(kind)}\n"
            f"👤 <b>Tên:</b> {name}\n"
            f"📝 <b>Ghi chú:</b> {note}\n"
            f"📌 <b>Trạng thái:</b> {dot} {st.upper()}\n"
            f"📅 <b>Ngày thêm:</b> {added}\n"
        )

    live_all, died_all, unknown_all = calc_totals(owner)
    header = f"📂 <b>Danh sách UID bạn đang theo dõi:</b> (Trang {page}/{total_pages})\n\n"
    footer = f"\n<b>Tổng:</b> {len(get_store(owner))} UID | 🟢 {live_all} LIVE, 🔴 {died_all} DIE, ⚪ {unknown_all} UNKNOWN"
    text = header + ("\n".join(blocks) if blocks else "—") + footer

    kb = InlineKeyboardMarkup(row_width=3)
    prev_btn = InlineKeyboardButton("⏮", callback_data=f"list:{owner}:{page-1}") if page>1 else None
    next_btn = InlineKeyboardButton("⏭", callback_data=f"list:{owner}:{page+1}") if page<total_pages else None
    if prev_btn and next_btn: kb.add(prev_btn, InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"), next_btn)
    elif prev_btn: kb.add(prev_btn, InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"))
    elif next_btn: kb.add(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noopnav"), next_btn)

    try:
        if edit_msg_id:
            bot.edit_message_text(chat_id=chat_id, message_id=edit_msg_id, text=text, reply_markup=kb, disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("list:") or c.data=="noopnav")
def cb_list(c):
    if c.data=="noopnav": return bot.answer_callback_query(c.id)
    _, owner_str, page_str = c.data.split(":")
    owner, page = int(owner_str), int(page_str)
    if c.from_user.id!=owner and not is_admin(c.from_user.id):
        return bot.answer_callback_query(c.id, "⛔ Không có quyền.")
    send_list_page(c.message.chat.id, owner, page, edit_msg_id=c.message.message_id)
    bot.answer_callback_query(c.id)

# ============== /xoa /huy ==============
@bot.message_handler(commands=["xoa"])
@require_access
def cmd_xoa(m):
    parts=m.text.split()
    if len(parts)<2: return bot.reply_to(m, "Dùng: /xoa <uid>")
    uid=parts[1]; removed=get_store(m.from_user.id).pop(uid, None)
    save_store()
    bot.reply_to(m, f"{'Đã xóa' if removed else 'Không tìm thấy'} UID <code>{uid}</code>.")

@bot.message_handler(commands=["huy"])
@require_access
def cmd_cancel(m):
    wizard_state.pop(m.from_user.id, None)
    bot.reply_to(m, "❎ Đã hủy thao tác.")

# ============== /them (wizard) ==============
@bot.message_handler(commands=["them"])
@require_access
def cmd_them(m):
    wizard_state.pop(m.from_user.id, None)
    bot.reply_to(m, "➕ Gửi UID (hoặc link profile/page):")
    bot.register_next_step_handler(m, step_uid)

def step_uid(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    if t.startswith("http"):
        maybe = extract_uid_from_link(t)
        if not maybe:
            bot.reply_to(msg, "Không lấy được UID từ link. Nhập lại ID số:")
            return bot.register_next_step_handler(msg, step_uid)
        t = maybe
    if not re.fullmatch(r"\d{6,}", t):
        bot.reply_to(msg, "UID không hợp lệ. Nhập lại:")
        return bot.register_next_step_handler(msg, step_uid)
    wizard_state[msg.from_user.id] = {"uid": t, "note":"", "name":"", "kind":"profile"}
    bot.send_message(msg.chat.id, f"🧩 Chọn loại cho <code>{t}</code>:", reply_markup=type_keyboard(t))

def step_note(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    wizard_state[msg.from_user.id]["note"]=t
    uid=wizard_state[msg.from_user.id]["uid"]
    bot.send_message(msg.chat.id, f"🖋️ Nhập tên cho <code>{uid}</code>:")
    bot.register_next_step_handler(msg, step_name)

def step_name(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    data = wizard_state[msg.from_user.id]
    uid, note, kind = data["uid"], data["note"], data.get("kind","profile")
    set_item(msg.from_user.id, uid, name=t, note=note, following=True, kind=kind)
    bot.send_message(msg.chat.id, f"🤖 Đang xử lý UID <code>{uid}</code>…")
    text, kb = build_result_card(msg.from_user.id, uid)
    bot.send_message(msg.chat.id, text, reply_markup=kb, disable_web_page_preview=True)
    wizard_state.pop(msg.from_user.id, None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("type:"))
def choose_type(c):
    _, t, uid = c.data.split(":", 2)
    if not is_authorized(c.from_user.id): return bot.answer_callback_query(c.id, "⛔")
    st = wizard_state.get(c.from_user.id) or {"uid": uid, "note":"", "name":"", "kind":"profile"}
    st["uid"]=uid; st["kind"]="group" if t=="group" else "profile"
    wizard_state[c.from_user.id]=st
    bot.answer_callback_query(c.id, "Đã chọn.")
    bot.send_message(c.message.chat.id, f"🖊️ Nhập ghi chú cho <code>{uid}</code> (vd: unlock 282):")
    bot.register_next_step_handler(c.message, step_note)

# ============== /themg (group) ==============
@bot.message_handler(commands=["themg","themnhom","themgroup"])
@require_access
def cmd_them_group(m):
    wizard_state.pop(m.from_user.id, None)
    bot.reply_to(m, "➕ Gửi ID hoặc link nhóm (facebook.com/groups/…):")
    bot.register_next_step_handler(m, step_g_uid)

def step_g_uid(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    gid = extract_group_id(t) if t.startswith("http") else (t if re.fullmatch(r"\d{5,}", t) else None)
    if not gid:
        bot.reply_to(msg, "❌ Không lấy được Group ID. Gửi lại:")
        return bot.register_next_step_handler(msg, step_g_uid)
    wizard_state[msg.from_user.id] = {"uid": gid, "note":"", "name":"", "kind":"group"}
    bot.send_message(msg.chat.id, f"🖊️ Nhập ghi chú cho Group <code>{gid}</code>:")
    bot.register_next_step_handler(msg, step_g_note)

def step_g_note(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    wizard_state[msg.from_user.id]["note"]=t
    gid = wizard_state[msg.from_user.id]["uid"]
    bot.send_message(msg.chat.id, f"🖋️ Nhập tên hiển thị cho Group <code>{gid}</code>:")
    bot.register_next_step_handler(msg, step_g_name)

def step_g_name(msg):
    if not is_authorized(msg.from_user.id): return
    t=(msg.text or "").strip()
    if t.lower() in {"/huy","huy"}: return cmd_cancel(msg)
    data = wizard_state.get(msg.from_user.id) or {}
    gid, note = data.get("uid"), data.get("note","")
    set_item(msg.from_user.id, gid, name=t, note=note, following=True, kind="group")
    bot.send_message(msg.chat.id, f"🤖 Đang xử lý Group <code>{gid}</code>…")
    text, kb = build_result_card(msg.from_user.id, gid)
    bot.send_message(msg.chat.id, text, reply_markup=kb, disable_web_page_preview=True)
    wizard_state.pop(msg.from_user.id, None)

# ============== Toggle buttons ==============
@bot.callback_query_handler(func=lambda c: c.data.startswith(("noop:","stop:","start:")))
def follow_buttons(c):
    parts = c.data.split(":")
    if len(parts)==3:
        action, owner_str, uid = parts; 
        try: owner=int(owner_str)
        except: owner=c.from_user.id
    else:
        action, uid = parts[0], parts[-1]; owner=c.from_user.id
    if owner!=c.from_user.id and not is_admin(c.from_user.id):
        return bot.answer_callback_query(c.id, "⛔")
    if action=="noop":
        return bot.answer_callback_query(c.id, "Đang theo dõi.")
    if action=="stop":
        set_following(owner, uid, False)
        bot.answer_callback_query(c.id, "Đã tắt.")
        text, kb = build_toggle_card(uid, "stop", owner)
        bot.send_message(c.message.chat.id, text, reply_markup=kb, disable_web_page_preview=True)
    elif action=="start":
        set_following(owner, uid, True)
        bot.answer_callback_query(c.id, "Đã bật lại.")
        text, kb = build_toggle_card(uid, "start", owner)
        bot.send_message(c.message.chat.id, text, reply_markup=kb, disable_web_page_preview=True)

# ============== /themhg (bulk) ==============
HELP_BULK = ("📘 <b>Thêm UID hàng loạt</b>\n"
             "• Mỗi dòng 1 mục, hỗ trợ: UID | UID Tên GhiChú | UID<Tab>Tên<Tab>GhiChú | Link profile\n"
             "• Tối đa 1000 UID/lần (mặc định loại Profile/Page)\n"
             "• VD:\n<code>1000001 Nguyen Van A Unlock 282\n"
             "1000002|Tran B|Dame 282\n"
             "https://facebook.com/1000003</code>\n\n"
             "Paste danh sách:")
@bot.message_handler(commands=["themhangloat","themnhg","themnhgloat","themhangloạt","themhg","themhng"])
@require_access
def cmd_themhangloat(m):
    bot.reply_to(m, HELP_BULK)
    bot.register_next_step_handler(m, step_bulk_receive)

def parse_one_line(ln: str) -> tuple[str,str,str] | None:
    if ln.startswith(("http://","https://")):
        uid = extract_uid_from_link(ln)
        return (uid,"","") if uid else None
    if "|" in ln:
        parts=[p.strip() for p in ln.split("|")]
        if parts and parts[0].isdigit():
            uid=parts[0]; name = parts[1] if len(parts)>=2 else ""; note = parts[2] if len(parts)>=3 else ""
            return (uid,name,note)
    if "\t" in ln:
        parts=[p.strip() for p in ln.split("\t")]
        if parts and parts[0].isdigit():
            uid=parts[0]; name = parts[1] if len(parts)>=2 else ""; note = parts[2] if len(parts)>=3 else ""
            return (uid,name,note)
    toks=ln.split()
    if toks and toks[0].isdigit():
        uid=toks[0]
        if len(toks)>=3: note=" ".join(toks[-2:]); name=" ".join(toks[1:-2]) or ""
        elif len(toks)==2: name=toks[1]; note=""
        else: name=note=""
        return (uid,name,note)
    if re.fullmatch(r"\d{6,}", ln): return (ln,"","")
    return None

def step_bulk_receive(msg):
    if not is_authorized(msg.from_user.id): return
    text=(msg.text or "").strip()
    if not text and msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text.strip()
    if not text: return bot.reply_to(msg, "Bạn chưa gửi danh sách.")
    lines=[ln.strip() for ln in text.splitlines() if ln.strip()]
    seen=set(); items=[]
    for ln in lines:
        if len(items)>=1000: break
        parsed=parse_one_line(ln)
        if not parsed: continue
        uid,name,note = parsed
        if uid in seen: continue
        seen.add(uid); items.append((uid,name,note))
    if not items: return bot.reply_to(msg, "Không parse được UID hợp lệ.")
    owner=msg.from_user.id
    summary=[]
    for uid,name,note in items:
        set_item(owner, uid, name=name, note=note, following=True, kind="profile")
        summary.append(f"{uid}: {check_live(uid)}")
    bot.reply_to(msg, "<b>Đã thêm:</b>\n<code>"+ "\n".join(summary[:60]) + "</code>")
    for uid,name,note in items[:20]:
        text_card, kb = build_result_card(owner, uid)
        bot.send_message(msg.chat.id, text_card, reply_markup=kb, disable_web_page_preview=True)

# ============== EXPIRY WATCHER (ONLY USER NOTIFY) ==============
NOTICES_FILE = "notices.json"  # { "12345": "7"|"3"|"1"|"expired" }
_notices = _load_json(NOTICES_FILE, {})
def _get_notice(uid:int) -> str: return str(_notices.get(str(uid), ""))
def _mark_notice(uid:int, tag:str):
    _notices[str(uid)] = tag
    _save_json(NOTICES_FILE, _notices)

def expiry_watcher():
    while True:
        try:
            now = now_ts()
            for uid, info in list(subs.items()):
                exp = int(info.get("expire_at", 0))
                if exp <= 0:
                    continue
                left = exp - now
                days = left // 86400

                # Remind 7/3/1 days
                if days in (7,3,1) and _get_notice(uid) != str(days):
                    try:
                        bot.send_message(uid, f"⏳ Gói của bạn còn <b>{days} ngày</b>. Liên hệ admin để gia hạn khi cần.")
                    except Exception:
                        pass
                    _mark_notice(uid, str(days))

                # Expired
                if left <= 0 and _get_notice(uid) != "expired":
                    try:
                        bot.send_message(uid, "⛔ Gói của bạn đã <b>hết hạn</b>. Liên hệ admin để gia hạn.")
                    except Exception:
                        pass
                    _mark_notice(uid, "expired")
        except Exception:
            pass
        _time.sleep(3600)  # check mỗi 1h

# ============== RUN ==============
if __name__ == "__main__":
    # bật cron nhắc hạn (chỉ user)
    t = threading.Thread(target=expiry_watcher, daemon=True)
    t.start()
    print("Bot is running…")
 bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20, none_stop=True)