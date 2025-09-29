from urllib.parse import unquote_plus
import os, json, logging, asyncio, secrets, string
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")
BOT_USERNAME = os.getenv("BOT_USERNAME")  

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
rt = Router()
dp.include_router(rt)

PARENTS_FILE = "parents.json"
TOKENS_FILE = "pending_tokens.json"  


def load_tokens() -> dict:
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            txt = f.read().strip()
            if not txt:
                return {}
            d = json.loads(txt)
            return {k: v.lstrip("\ufeff").strip() for k, v in d.items()}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logging.warning("WARN: %s повреждён — начинаю с пустого.", TOKENS_FILE)
        return {}

def save_tokens(tokens: dict):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)

def save_parent(student_id: str, chat_id: int):
    try:
        with open(PARENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.setdefault(student_id, [])
    if chat_id not in data[student_id]:
        data[student_id].append(chat_id)
    with open(PARENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logging.info("Saved binding: %s -> %s", student_id, chat_id)

def gen_token(prefix="bind", n=8):
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(n))

PENDING = load_tokens()  

@rt.message(CommandStart(deep_link=True))
async def start_with_arg(m: Message, command: CommandStart):
    arg_raw = command.args or ""
    arg = unquote_plus(arg_raw).strip()  # декодируем и убираем лишнее
    logging.info("Deep-link start from %s (%s): arg_raw=%r, arg=%r", m.from_user.username, m.chat.id, arg_raw, arg)
    if arg and arg in PENDING:
        student_id = PENDING.pop(arg)
        save_parent(student_id, m.chat.id)
        save_tokens(PENDING)
        return await m.answer(f"✅ Готово! Вы привязаны к ученику: {student_id}. Теперь вы будете получать уведомления.")
    return await m.answer("❓ Токен не найден или устарел. Попросите новую персональную ссылку/QR у школы.")

@rt.message(CommandStart())
async def start_plain(m: Message):
    logging.info("Plain /start from %s (%s)", m.from_user.username, m.chat.id)
    await m.answer("Здравствуйте! Чтобы привязаться к ученику, откройте персональную ссылку/QR из школы.")

@rt.message(Command("bind"))
async def bind_cmd(m: Message):
    parts = m.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Пришлите: /bind <код>")
    code = parts[1].strip()
    logging.info("Manual bind from %s (%s): code=%r", m.from_user.username, m.chat.id, code)
    student_id = PENDING.pop(code, None)
    if not student_id:
        return await m.answer("Код не найден или устарел. Попросите новый у школы.")
    save_parent(student_id, m.chat.id)
    save_tokens(PENDING)  
    await m.answer(f"✅ Готово! Вы привязаны к ученику: {student_id}.")

@rt.message(Command("whoami"))
async def whoami(m: Message):
    await m.answer(f"Ваш chat_id: {m.chat.id}")

@rt.message(Command("pending"))
async def pending(m: Message):
    if not PENDING:
        return await m.answer("Список ожиданий пуст.")
    txt = "\n".join([f"{k} → {v}" for k, v in PENDING.items()])
    await m.answer(f"Ожидают привязки:\n{txt}")

@rt.message(Command("my_students"))
async def my_students(m: Message):
    try:
        with open(PARENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    attached = [s for s, ids in data.items() if m.chat.id in ids]
    await m.answer("Вы привязаны к: " + (", ".join(attached) if attached else "нет привязок"))

@rt.message(Command("unbind"))
async def unbind(m: Message):
    parts = m.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Использование: /unbind <student_id>\nНапример: /unbind ivan_petrov")

    sid = parts[1].strip()

    try:
        with open(PARENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    if sid in data and m.chat.id in data[sid]:
        data[sid].remove(m.chat.id)

        # если список пуст, можно удалить ключ полностью
        if not data[sid]:
            data.pop(sid)

        with open(PARENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return await m.answer(f"❌ Привязка к {sid} удалена.")
    else:
        return await m.answer("Привязка не найдена. Проверьте имя ученика.")



ADMINS = {int(os.getenv("ADMIN_CHAT_ID", "0"))}  
@rt.message(Command("gen"))
async def gen(m: Message):
    if m.chat.id not in ADMINS or not BOT_USERNAME:
        return await m.answer("Недоступно.")
    parts = m.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await m.answer("Использование: /gen <student_id>")
    sid = parts[1].lstrip("\ufeff").strip()
    existing = next((t for t, s in PENDING.items() if s == sid), None)
    token = existing or gen_token()
    PENDING[token] = sid
    save_tokens(PENDING)
    link = f"https://t.me/{BOT_USERNAME}?start={token}"
    await m.answer(f"{sid} → {link}")

async def main():
    logging.info("Bot is starting…")
    me = await bot.get_me()
    logging.info("Bot @%s is polling", me.username)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
