from __future__ import annotations

import os
import re
import time
import json
import logging
import threading
from typing import Optional, Dict, Tuple, Any, List

import requests
from dotenv import load_dotenv

from FunPayAPI import Account
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater.events import NewOrderEvent, NewMessageEvent

load_dotenv()

FUNPAY_AUTH_TOKEN = os.getenv("FUNPAY_AUTH_TOKEN")

RAW_IDS = os.getenv("CATEGORY_IDS") or os.getenv("CATEGORY_ID") or ""
CATEGORY_IDS: List[int] = []
for t in re.split(r"[,\s;]+", RAW_IDS.strip()):
    if not t:
        continue
    try:
        CATEGORY_IDS.append(int(t))
    except Exception:
        pass

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(float(v))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default

AUTO_REFUND = _env_bool("AUTO_REFUND", True)
STRICT_SILENT_SKIP = _env_bool("STRICT_SILENT_SKIP", False)

FRIEND_LINK_HINT_URL = os.getenv("FRIEND_LINK_HINT_URL", "https://s.team/p")

DESSLY_API_BASE = "https://desslyhub.com/api/v1/service/steamgift"
DESSLY_API_KEY = os.getenv("DESSLY_API_KEY", "").strip()

CREATOR_NAME = os.getenv("CREATOR_NAME", "@tinechelovec")
CREATOR_URL = os.getenv("CREATOR_URL", "https://t.me/tinechelovec")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/by_thc")
GITHUB_URL = os.getenv("GITHUB_URL", "https://github.com/tinechelovec/Funpay-Steam-Gifts-Dessly")
BANNER_NOTE = os.getenv(
    "BANNER_NOTE",
    "Бот бесплатный и с открытым исходным кодом на GitHub. "
    "Создатель бота его НЕ продаёт. Если вы где-то видите платную версию — "
    "это решение перепродавца, к автору отношения не имеет."
)

LOG_NAME = "SteamGifts"

class LevelEmojiFilter(logging.Filter):
    MAP = {"DEBUG": "🐞", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "💥"}
    def filter(self, record: logging.LogRecord) -> bool:
        record.level_emoji = self.MAP.get(record.levelname, "•")
        return True

class PrettyConsoleFilter(logging.Filter):
    _ORDER_RE = re.compile(r"\[ORDER ([^\]]+)\]")
    _CYN = "\033[36m"; _RST = "\033[0m"; _RED = "\033[31m"
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            msg = self._ORDER_RE.sub(lambda m: f"{self._CYN}[ORDER {m.group(1)}]{self._RST}", msg)
            msg = (msg
                   .replace("Провайдер баланс", "💰 Провайдер")
                   .replace("Найдена friend-link", "🔗 Найдена friend-link")
                   .replace("Запросил у покупателя friend-link", "📨 Запросил у покупателя friend-link")
                   .replace("Create order", "🧾 Create order")
                   .replace("Pay order", "💳 Pay order")
                   .replace("Успешно оформлен и оплачен", "✅ Успешно оформлен и оплачен")
                   .replace("FAILED", f"{self._RED}FAILED{self._RST}")
            )
            record.msg, record.args = msg, ()
        except Exception:
            pass
        return True

try:
    import colorlog
    logger = colorlog.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)

    console_handler = colorlog.StreamHandler()
    console_handler.addFilter(LevelEmojiFilter())
    console_handler.addFilter(PrettyConsoleFilter())
    console_formatter = colorlog.ColoredFormatter(
        fmt="%(cyan)s%(asctime)s%(reset)s %(level_emoji)s "
            "%(log_color)s[%(levelname)-5s]%(reset)s "
            "%(bold_blue)s" + LOG_NAME + "%(reset)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        style="%",
    )
    console_handler.setFormatter(console_formatter)

    file_handler = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

except Exception:
    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.handlers.clear()
    logger.addHandler(ch)
    logger.addHandler(fh)

RED = "\033[31m"
BRIGHT_CYAN = "\033[96m"
RESET = "\033[0m"

_DISCLAIMER_THREAD_STARTED = False
def _start_disclaimer_task():
    global _DISCLAIMER_THREAD_STARTED
    if _DISCLAIMER_THREAD_STARTED:
        return
    enable = _env_bool("DISCLAIMER_ENABLE", True)
    if not enable:
        return

    period = max(60, _env_int("DISCLAIMER_PERIOD_SEC", 900))
    text = os.getenv("DISCLAIMER_TEXT") or (
        "Спасибо, что пользуетесь ботом! Он полностью бесплатный и с открытым исходным кодом. "
    )

    def _loop():
        time.sleep(period)
        while True:
            try:
                logger.info(text)
            except Exception:
                pass
            time.sleep(period)

    t = threading.Thread(target=_loop, daemon=True, name="disclaimer")
    t.start()
    _DISCLAIMER_THREAD_STARTED = True

def _log_banner_free():
    border = "═" * 85
    try:
        logger.info(f"{RED}{border}{RESET}")
        logger.info(f"{RED}Информация о проекте / Steam Gifts Bot{RESET}")
        logger.info(f"{RED}{border}{RESET}")

        line = f"{RED}Создатель: {CREATOR_NAME}"
        if CREATOR_URL:
            line += f" | Контакт: {BRIGHT_CYAN}{CREATOR_URL}{RED}"
        logger.info(line + RESET)

        if CHANNEL_URL:
            logger.info(f"{RED}Канал: {BRIGHT_CYAN}{CHANNEL_URL}{RESET}")

        if GITHUB_URL:
            logger.info(f"{RED}GitHub: {BRIGHT_CYAN}{GITHUB_URL}{RESET}")

        logger.info(f"{RED}Дисклеймер: {BANNER_NOTE}{RESET}")
        logger.info(f"{RED}{border}{RESET}")
    except Exception:
        logger.info("===============================================")
        logger.info("Информация о проекте / Steam Gifts Bot")
        logger.info(f"Создатель: {CREATOR_NAME} {(' | ' + CREATOR_URL) if CREATOR_URL else ''}")
        if CHANNEL_URL:
            logger.info(f"Канал: {CHANNEL_URL}")
        if GITHUB_URL:
            logger.info(f"GitHub: {GITHUB_URL}")
        logger.info(f"Дисклеймер: {BANNER_NOTE}")
        logger.info("===============================================")

def _log_settings():
    logger.info("⚙️  Настройки:")
    logger.info(f"    AUTO_REFUND            = {AUTO_REFUND}")
    logger.info(f"    DESSLY_API_KEY         = {'OK' if DESSLY_API_KEY else 'MISSING'}")
    _start_disclaimer_task()

HERE = os.path.abspath(os.path.dirname(__file__))
ITEMS_JSON_PATH = os.path.join(HERE, "steam_gifts.json")

REGION_CHOICES = {
    "CN","UA","AR","TR","IN","KZ","VN","ID","PH","BY","UZ","RU","BR","PK","KR","CL","MY","HK","TH","JP",
    "NZ","ZA","TW","AU","SG","CA","KW","UY","MX","SA","CO","US","QA","PE","AE","CR","GB","NO","DE","IL",
    "PL","CH"
}

def _load_items_fallback() -> Dict[str, dict]:
    if not os.path.exists(ITEMS_JSON_PATH):
        return {}
    try:
        with open(ITEMS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        out: Dict[str, dict] = {}
        for k, v in data.items():
            out[str(k)] = {
                "title": v.get("title") or f"Item {k}",
                "region": (v.get("region") or "RU").upper(),
                "app_id": v.get("app_id"),
                "sub_id": v.get("sub_id"),
                "notes": v.get("notes") or "",
                "last_price": v.get("last_price"),
                "currency": v.get("currency"),
            }
        return out
    except Exception:
        return {}

_resolve_order_params = None
_load_items_api = None
try:
    from steam_settings_id import resolve_order_params as _resolve_order_params
    from steam_settings_id import load_items as _load_items_api
except Exception:
    _resolve_order_params = None
    _load_items_api = None

PKG_RE = re.compile(r"package_id\s+(\d+)", flags=re.IGNORECASE)

def _extract_package_id_from_notes(notes: str | None) -> Optional[int]:
    if not notes:
        return None
    m = PKG_RE.search(notes)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def _resolve_item_from_id(funpay_key: str) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    if _load_items_api:
        try:
            items = _load_items_api()
            meta = items.get(str(funpay_key))
            if meta is not None:
                title = getattr(meta, "title", None) if hasattr(meta, "title") else meta.get("title")
                notes = getattr(meta, "notes", None) if hasattr(meta, "notes") else meta.get("notes")
                region = getattr(meta, "region", None) if hasattr(meta, "region") else meta.get("region")
                sub_id = getattr(meta, "sub_id", None) if hasattr(meta, "sub_id") else meta.get("sub_id")
                pkg = _extract_package_id_from_notes(notes) or (int(sub_id) if sub_id else None)
                if region:
                    region = region.upper()
                if pkg and region in REGION_CHOICES:
                    return pkg, region, title, notes
        except Exception:
            pass

    data = _load_items_fallback()
    node = data.get(str(funpay_key))
    if not node:
        return None, None, None, None
    region = (node.get("region") or "").upper()
    pkg = _extract_package_id_from_notes(node.get("notes")) or node.get("sub_id")
    try:
        pkg = int(pkg) if pkg is not None else None
    except Exception:
        pkg = None
    if not pkg or region not in REGION_CHOICES:
        return None, None, None, None
    return pkg, region, node.get("title"), node.get("notes")

STEAM_GIFT_REGEX = re.compile(
    r"(?i)\bsteam(?:[._\s-]*gift|[._\s-]*gift)\b\s*[:=]?\s*([0-9]{1,10})"
)

def find_gift_key(text: str) -> Optional[str]:
    if not text:
        return None
    m = STEAM_GIFT_REGEX.search(text)
    if not m:
        return None
    return m.group(1)

FRIEND_LINK_RE = re.compile(
    r"(https?://\S*?(?:s\.team/[^ \n\r\t]+|steamcommunity\.com/(?:id|profiles)/[^ \n\r\t/]+))",
    flags=re.IGNORECASE
)

def extract_friend_link(text: str) -> Optional[str]:
    if not text:
        return None
    m = FRIEND_LINK_RE.search(text)
    if m:
        return m.group(1)
    return None

DESSLY_ERROR_DESCRIPTIONS: Dict[int, str] = {
    -1:  "Внутренняя ошибка сервера",
    -2:  "Недостаточно средств на балансе провайдера",
    -3:  "Некорректная сумма",
    -4:  "Некорректное тело запроса",
    -5:  "Доступ запрещён (проверьте API-ключ)",

    -151: "Некорректный ID транзакции",
    -152: "Транзакция не найдена",
    -153: "Не указан номер страницы",

    -51: "Невалидная ссылка для добавления в друзья",
    -52: "Некорректный app ID",
    -53: "Информация об игре не найдена",
    -54: "У пользователя нет основной игры",
    -55: "У пользователя уже есть эта игра",
    -56: "Невозможно добавить пользователя в друзья",
    -57: "Указан неверный регион покупателя",
    -58: "Регион получателя недоступен для подарка",
    -59: "Пользователь не добавил/удалил бота из друзей",

    -100: "Некорректный логин Steam",

    -120: "Некорректное значение валюты",
    -121: "Валюта не поддерживается",
}

def dessly_error_text(code: int) -> str:
    base = DESSLY_ERROR_DESCRIPTIONS.get(code, "Неизвестная ошибка провайдера")
    return f"{base} (код {code})"

def _pick_error_code(data: Any) -> Optional[int]:
    if not isinstance(data, dict):
        return None
    for k in ("error_code", "code"):
        if k in data:
            try:
                v = int(data[k])
                if v < 0:
                    return v
            except Exception:
                pass
    node = data.get("error") if isinstance(data.get("error"), dict) else None
    if node:
        try:
            v = int(node.get("error_code"))
            if v < 0:
                return v
        except Exception:
            pass
    return None

def _hint_for_error(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    hints = {
        -2:  "Пополните баланс провайдера или включите AUTO_REFUND, чтобы не держать покупателя.",
        -51: "Попросите покупателя прислать новую friend-link (s.team/p/...) или ссылку профиля Steam.",
        -52: "Проверьте APP_ID/Package ID — возможно, указан неверный идентификатор.",
        -53: "Проверьте доступность игры на сервисе и правильность APP_ID.",
        -54: "Это DLC: у получателя нет базовой игры — предложите базовую игру или другое издание.",
        -55: "У получателя игра уже есть — предложите другой товар/издание или возврат.",
        -56: "Нельзя добавить в друзья — попросите разблокировать приглашения/снять ограничения, попробовать позже.",
        -57: "Регион покупателя указан неверно — уточните регион, переоформите заказ с корректным регионом.",
        -58: "Подарок недоступен в регионе получателя — предложите другой регион/издание.",
        -59: "Получатель не добавил бота — попросите принять приглашение и повторить отправку.",
        -5:  "Проверьте API-ключ (заголовок apikey) и права доступа.",
        -1:  "Повторите попытку позже (временная ошибка на стороне сервера).",
    }
    return hints.get(code)

def _json_preview(obj: Any, limit: int = 1200) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        s = str(obj)
    if len(s) > limit:
        s = s[:limit] + "…"
    return s

def _format_error_for_log(stage: str, code_or_status: int, data: Optional[dict], body_preview: str) -> str:
    lines: List[str] = [f"❌ Этап: {stage}"]
    if isinstance(code_or_status, int) and code_or_status < 0:
        human = dessly_error_text(code_or_status)
        lines.append(f"Причина: {human}")
        hint = _hint_for_error(code_or_status)
        if hint:
            lines.append(f"Подсказка: {hint}")
    else:
        lines.append(f"HTTP статус: {code_or_status}")
        inner = _pick_error_code(data or {})
        if inner is not None:
            lines.append(f"Внутренний код провайдера: {dessly_error_text(inner)}")
            hint = _hint_for_error(inner)
            if hint:
                lines.append(f"Подсказка: {hint}")

    if isinstance(data, dict):
        for k in ("message", "detail", "reason"):
            if k in data and data[k]:
                v = data[k]
                if isinstance(v, (dict, list)):
                    v = _json_preview(v, 600)
                lines.append(f"{k}: {v}")
        if "error" in data and data["error"]:
            lines.append("error: " + _json_preview(data["error"], 600))
        if "errors" in data and data["errors"]:
            lines.append("errors: " + _json_preview(data["errors"], 600))

    if body_preview and body_preview.strip():
        lines.append("Фрагмент ответа: " + body_preview)

    return "\n".join(lines)

def _dessly_headers() -> dict:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "apikey": DESSLY_API_KEY or "",
    }

def dessly_send_game(invite_url: str, package_id: int, region: str) -> Tuple[bool, int, str, dict]:
    url = f"{DESSLY_API_BASE}/sendgames"
    payload = {"invite_url": invite_url, "package_id": str(package_id), "region": region}
    try:
        r = requests.post(url, json=payload, headers=_dessly_headers(), timeout=30)
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if status == 200:
            err = _pick_error_code(data)
            if err is not None and err < 0:
                msg = dessly_error_text(err)
                return False, err, msg, data

        ok = (status == 200)
        msg = (data.get("message") or data.get("detail") or r.text) if isinstance(data, dict) else r.text
        return ok, status, msg, data
    except Exception as e:
        return False, -1, f"Exception: {e}", {"exception": str(e)}

def _on_provider_failure(account: Account, chat_id: int, order_id: Any, code_or_status: int, body_preview: str, stage: str, data: Optional[dict] = None):
    report = _format_error_for_log(stage, code_or_status, data, body_preview)
    logger.error(f"[ORDER {order_id}] {report}")

    if code_or_status == -2:
        if AUTO_REFUND:
            try:
                account.send_message(
                    chat_id,
                    "Провайдер сообщает: недостаточно средств на стороне сервиса. Деньги возвращены. "
                    "Вы можете повторить заказ позже."
                )
                account.refund(order_id)
                logger.info(f"[ORDER {order_id}] Оформлён возврат покупателю (недостаточно средств у провайдера).")
            except Exception as e:
                logger.error(f"[ORDER {order_id}] Ошибка при возврате: {e}")
        else:
            try:
                account.send_message(
                    chat_id,
                    "Провайдер сообщает: недостаточно средств на стороне сервиса. "
                    "Автовозврат выключен — свяжитесь с продавцом для ручного возврата или дождитесь пополнения."
                )
            except Exception:
                pass
        return

    if AUTO_REFUND:
        try:
            account.send_message(
                chat_id,
                "На стороне провайдера возникла проблема. Средства будут возвращены."
            )
            account.refund(order_id)
            logger.info(f"[ORDER {order_id}] Оформлён возврат покупателю.")
        except Exception as e:
            logger.error(f"[ORDER {order_id}] Ошибка при возврате: {e}")
    else:
        try:
            account.send_message(
                chat_id,
                "На стороне провайдера возникла проблема. "
                "Автовозврат выключен — свяжитесь с продавцом."
            )
        except Exception:
            pass

def order_url(oid: Any) -> str:
    try:
        return f"https://funpay.com/orders/{int(oid)}/"
    except Exception:
        return "https://funpay.com/orders/"

STATE: Dict[int, dict] = {}

def handle_new_order(account: Account, order):
    oid = getattr(order, "id", None)
    buyer = getattr(order, "buyer_id", None)

    subcat = getattr(order, "subcategory", None) or getattr(order, "sub_category", None)
    subcat_id = getattr(subcat, "id", None)
    if not subcat_id or (CATEGORY_IDS and subcat_id not in CATEGORY_IDS):
        logger.info(f"[ORDER {oid}] Подкатегория {subcat_id} не в списке — пропускаю.")
        return

    desc = (
        getattr(order, "full_description", None)
        or getattr(order, "short_description", None)
        or getattr(order, "title", None)
        or ""
    )
    key = find_gift_key(str(desc))
    if not key:
        logger.info(f"[ORDER {oid}] Маркер steamgift не найден в описании — пропускаю.")
        return

    logger.info(f"[ORDER {oid}] Найден маркер steamgift -> key={key}")

    package_id, region, title, notes = _resolve_item_from_id(key)
    if not package_id or not region:
        logger.info(f"[ORDER {oid}] Позиция по key={key} не найдена или без package_id/region — пропускаю.")
        return

    logger.info(f"[ORDER {oid}] Резолв OK: PACKAGE_ID={package_id}, REGION={region}, TITLE={title or '-'}")

    text_all = " ".join([str(getattr(order, f, "") or "") for f in ("full_description", "short_description", "title")])
    friend_link = extract_friend_link(text_all)

    chat_id = getattr(order, "chat_id", None)
    if not buyer or not chat_id:
        logger.info(f"[ORDER {oid}] Нет buyer/chat_id — пропускаю.")
        return

    STATE[buyer] = {
        "step": "got_order",
        "order_id": oid,
        "chat_id": chat_id,
        "funpay_key": key,
        "package_id": package_id,
        "region": region,
        "title": title or f"Steam package {package_id}",
        "notes": notes or "-",
    }

    if friend_link:
        STATE[buyer]["friend_link"] = friend_link
        logger.info(f"[ORDER {oid}] Найдена friend-link: {friend_link}")
        proceed_send(account, buyer)
        return

    account.send_message(
        chat_id,
        (
            f"Спасибо за заказ!\n\n"
            f"Вы купили: {STATE[buyer]['title']} (регион: {STATE[buyer]['region']}).\n"
            "Чтобы отправить подарок, нужна ссылка для добавления в друзья (friend-link).\n"
            "Её можно сгенерировать в Steam → Add a Friend → Create Invite Link.\n\n"
            f"Пришлите ссылку вида: {FRIEND_LINK_HINT_URL}/… или ссылку на ваш профиль Steam."
        )
    )
    logger.info(f"[ORDER {oid}] Запросил у покупателя friend-link.")

def proceed_send(account: Account, buyer_id: int):
    st = STATE.get(buyer_id) or {}
    chat_id = st.get("chat_id")
    order_id = st.get("order_id")
    package_id = st.get("package_id")
    region = st.get("region")
    friend_link = st.get("friend_link")
    title = st.get("title") or "-"
    notes = st.get("notes") or "-"

    if not DESSLY_API_KEY:
        logger.error(f"[ORDER {order_id}] DESSLY_API_KEY не задан — невозможна отправка.")
        if chat_id:
            account.send_message(chat_id, "Техническая проблема: не настроен ключ провайдера. Свяжитесь с продавцом.")
        STATE.pop(buyer_id, None)
        return

    if not (chat_id and order_id and package_id and region and friend_link):
        logger.info(f"[ORDER {order_id}] Недостаточно данных для отправки (chat_id/package_id/region/link).")
        return

    ok, status, msg, data = dessly_send_game(friend_link, package_id, region)
    body_preview = (msg or json.dumps(data, ensure_ascii=False))[:500]
    logger.info(f"[ORDER {order_id}] Dessly sendgames -> ok={ok}, status={status}, msg={body_preview}")

    if not ok:
        _on_provider_failure(account, chat_id, order_id, status, body_preview, stage="SEND", data=data if isinstance(data, dict) else None)
        STATE.pop(buyer_id, None)
        return

    link = order_url(order_id)
    account.send_message(
        chat_id,
        (
            "Готово! Подарок отправлен.\n\n"
            "Подарок придет в течении 5 минут.\n"
            "Примите запрос в друзья в Steam — после этого подарок будет доставлен.\n\n"
            "Пожалуйста, оставьте отзыв — это очень помогает!"
        )
    )
    logger.info(f"[ORDER {order_id}] Успешная отправка через Dessly. Сообщение отправлено покупателю.")
    STATE.pop(buyer_id, None)

def handle_new_message(account: Account, message):
    user_id = getattr(message, "author_id", None)
    chat_id = getattr(message, "chat_id", None)
    text = getattr(message, "text", None) or ""
    if not (user_id and chat_id and text.strip()):
        return

    st = STATE.get(user_id)
    if not st:
        return

    order_id = st.get("order_id")

    if "friend_link" not in st:
        link = extract_friend_link(text)
        if not link:
            account.send_message(
                chat_id,
                (
                    "Похоже, ссылка не распознана.\n"
                    f"Пришлите friend-link вида {FRIEND_LINK_HINT_URL}/… или ссылку на профиль Steam "
                    "(steamcommunity.com/id/... или steamcommunity.com/profiles/...)."
                )
            )
            logger.info(f"[ORDER {order_id}] Покупатель прислал невалидный friend-link.")
            return
        st["friend_link"] = link
        logger.info(f"[ORDER {order_id}] Получен friend-link от покупателя: {link}")
        proceed_send(account, user_id)
        return

def main():
    if not FUNPAY_AUTH_TOKEN:
        raise RuntimeError("FUNPAY_AUTH_TOKEN не найден в .env")

    _log_banner_free()
    _log_settings()

    account = Account(FUNPAY_AUTH_TOKEN)
    account.get()
    logger.info(f"Авторизован на FunPay как @{getattr(account, 'username', '(unknown)')}")

    runner = Runner(account)
    logger.info("🚀 Steam Gifts Bot запущен. Ожидаю события FunPay...")

    for event in runner.listen(requests_delay=3.0):
        try:
            if isinstance(event, NewOrderEvent):
                order = account.get_order(event.order.id)
                handle_new_order(account, order)
            elif isinstance(event, NewMessageEvent):
                if getattr(event, "message", None) is not None:
                    handle_new_message(account, event.message)
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")

if __name__ == "__main__":
    main()
