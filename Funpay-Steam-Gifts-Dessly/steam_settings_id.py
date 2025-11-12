from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

import requests

HERE = Path(__file__).resolve().parent
ITEMS_JSON = HERE / "steam_gifts.json"
DOTENV_PATHS = [HERE / ".env", Path.cwd() / ".env"]

DESSLY_URL_GAMES_BASE = "https://desslyhub.com/api/v1/service/steamgift/games"
DESSLY_URL_GET_BY_APP_ID = "https://desslyhub.com/api/v1/service/steamgift/games/app_id"
DESSLY_APIKEY_ENV = "DESSLY_API_KEY"

STEAM_STORE_API = "https://store.steampowered.com/api/appdetails"

CANCEL_TOKENS = {"0", "q", "й", "exit", "quit", "выход", "назад", "отмена", "cancel", "back"}

COUNTRY_BY_CODE: Dict[str, str] = {
    "CN": "Китай", "UA": "Украина", "AR": "Аргентина", "TR": "Турция", "IN": "Индия",
    "KZ": "Казахстан", "VN": "Вьетнам", "ID": "Индонезия", "PH": "Филиппины", "BY": "Беларусь",
    "UZ": "Узбекистан", "RU": "Россия", "BR": "Бразилия", "PK": "Пакистан", "KR": "Южная Корея",
    "CL": "Чили", "MY": "Малайзия", "HK": "Гонконг", "TH": "Таиланд", "JP": "Япония",
    "NZ": "Новая Зеландия", "ZA": "ЮАР", "TW": "Тайвань", "AU": "Австралия", "SG": "Сингапур",
    "CA": "Канада", "KW": "Кувейт", "UY": "Уругвай", "MX": "Мексика", "SA": "Саудовская Аравия",
    "CO": "Колумбия", "US": "США", "QA": "Катар", "PE": "Перу", "AE": "ОАЭ", "CR": "Коста-Рика",
    "GB": "Великобритания", "NO": "Норвегия", "DE": "Германия", "IL": "Израиль", "PL": "Польша",
    "CH": "Швейцария",
}
REGION_CHOICES = set(COUNTRY_BY_CODE.keys())

ENV_NOTICE_SHOWN = False

@dataclass
class SteamGiftItem:
    key: str
    title: str
    region: str
    app_id: Optional[int] = None
    sub_id: Optional[int] = None
    notes: str = ""
    last_price: Optional[float] = None
    currency: Optional[str] = None

def load_items() -> Dict[str, SteamGiftItem]:
    if ITEMS_JSON.exists():
        with ITEMS_JSON.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, SteamGiftItem] = {}
        for k, v in raw.items():
            out[str(k)] = SteamGiftItem(
                key=str(k),
                title=v.get("title", f"Item {k}"),
                region=v.get("region", "RU"),
                app_id=v.get("app_id"),
                sub_id=v.get("sub_id"),
                notes=v.get("notes", ""),
                last_price=v.get("last_price"),
                currency=v.get("currency") or "USD",
            )
        return out
    return {}

def save_items(items: Dict[str, SteamGiftItem]) -> None:
    payload = {
        k: {
            "title": it.title,
            "region": it.region,
            "app_id": it.app_id,
            "sub_id": it.sub_id,
            "notes": it.notes,
            "last_price": it.last_price,
            "currency": it.currency or "USD",
        }
        for k, it in items.items()
    }
    with ITEMS_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def _is_cancel_token(s: str) -> bool:
    return s.strip().lower() in CANCEL_TOKENS

def input_int(prompt: str, *, min_val: Optional[int] = None, max_val: Optional[int] = None,
              allow_blank: bool = False, allow_cancel: bool = True) -> Optional[int]:
    while True:
        s = input(prompt).strip()
        if allow_cancel and _is_cancel_token(s):
            return None
        if s == "" and allow_blank:
            return None
        if not s.lstrip("-").isdigit():
            print("Введите число.")
            continue
        val = int(s)
        if min_val is not None and val < min_val:
            print(f"Число должно быть ≥ {min_val}."); continue
        if max_val is not None and val > max_val:
            print(f"Число должно быть ≤ {max_val}."); continue
        return val

def input_str(prompt: str, *, allow_empty: bool = False, allow_cancel: bool = True) -> Optional[str]:
    while True:
        s = input(prompt).strip()
        if allow_cancel and _is_cancel_token(s):
            return None
        if not s and not allow_empty:
            print("Пустое значение недопустимо."); continue
        return s

def yes_no(prompt: str) -> bool:
    while True:
        s = input(f"{prompt} (y/n, 0 — отмена): ").strip().lower()
        if _is_cancel_token(s): return False
        if s in ("y", "yes", "д", "да"): return True
        if s in ("n", "no", "н", "нет"): return False
        print("Ответьте 'y' или 'n'.")

def press_enter():
    input("Нажмите Enter, чтобы продолжить...")

def _load_dotenv_into_environ() -> None:
    for p in DOTENV_PATHS:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    if "=" not in line: continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass

def _env_apikey() -> Optional[str]:
    _load_dotenv_into_environ()
    return os.environ.get(DESSLY_APIKEY_ENV)

def show_env_notice_once():
    global ENV_NOTICE_SHOWN
    if ENV_NOTICE_SHOWN: return
    apikey = _env_apikey()
    if not apikey:
        print(f"⚠️  УВЕДОМЛЕНИЕ: .env не найден или отсутствует переменная {DESSLY_APIKEY_ENV}")
        print("    Работаем в УРЕЗАННОМ режиме: получение цен по регионам недоступно без API key.")
        print(f"    Добавьте {DESSLY_APIKEY_ENV}=<ваш ключ> в .env или передайте аргументом:  python steam_settings_id.py <API_KEY>\n")
    ENV_NOTICE_SHOWN = True

class ApiError(RuntimeError):
    pass

def dessly_get_by_app_id(app_id: int, apikey: str) -> dict:
    headers = {"accept": "application/json", "apikey": apikey}
    last_err: Optional[str] = None

    for url in (f"{DESSLY_URL_GAMES_BASE}/{app_id}", f"{DESSLY_URL_GAMES_BASE}/{app_id}/"):
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except requests.RequestException as e:
            last_err = f"Сеть/соединение: {e!r}"
            continue

        try:
            content = r.json()
        except Exception:
            content = None

        if r.status_code == 404 and isinstance(content, dict) and content.get("error_code") == -53:
            raise ApiError("Игра по этому APP_ID не найдена на Dessly (error_code -53).")
        if r.status_code >= 400:
            last_err = f"HTTP {r.status_code}: {r.text}"
            continue

        if isinstance(content, dict):
            if "game" in content and isinstance(content["game"], list) and not content["game"]:
                raise ApiError("Игра по этому APP_ID не найдена на Dessly (game: []).")
            return content
        return {"raw": r.text}

    for params in ({"app_id": str(app_id)}, {"appid": str(app_id)}):
        try:
            r = requests.get(DESSLY_URL_GET_BY_APP_ID, params=params, headers=headers, timeout=20)
        except requests.RequestException as e:
            last_err = f"Сеть/соединение: {e!r}"
            continue

        try:
            content = r.json()
        except Exception:
            content = None

        if r.status_code == 404 and isinstance(content, dict) and content.get("error_code") == -53:
            raise ApiError("Игра по этому APP_ID не найдена на Dessly (error_code -53).")
        if r.status_code >= 400:
            last_err = f"HTTP {r.status_code}: {r.text}"
            continue

        if isinstance(content, dict):
            if "game" in content and isinstance(content["game"], list) and not content["game"]:
                raise ApiError("Игра по этому APP_ID не найдена на Dessly (game: []).")
            return content
        return {"raw": r.text}

    raise ApiError(last_err or "Не удалось получить данные из Dessly")

def _regions_from_list(arr: List[dict]) -> Dict[str, Dict[str, Optional[float]]]:
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not isinstance(arr, list):
        return out
    for item in arr:
        if not isinstance(item, dict):
            continue
        code = str(item.get("region") or item.get("code") or "").upper()
        if not code:
            continue
        price_raw = item.get("price") or item.get("amount") or item.get("value") or item.get("price_original")
        try:
            price_val = float(str(price_raw)) if price_raw is not None else None
        except Exception:
            price_val = None
        if price_val is None:
            continue
        out[code] = {
            "price": price_val,
            "currency": "USD",
            "discount": str(item.get("discount")) if item.get("discount") is not None else None,
        }
    return out

def dessly_list_editions(data: dict) -> List[Dict[str, Any]]:
    editions: List[Dict[str, Any]] = []
    if not isinstance(data, dict):
        return editions

    if isinstance(data.get("game"), list) and data["game"]:
        for g in data["game"]:
            if not isinstance(g, dict):
                continue
            ed_title = str(g.get("edition") or g.get("name") or "Edition").strip()
            pkg_id = g.get("package_id")
            regions = _regions_from_list(g.get("regions_info") or g.get("regions") or [])
            if not regions:
                continue
            editions.append({"edition": ed_title, "package_id": pkg_id, "regions": regions})
        if editions:
            return editions

    root = data.get("data") if isinstance(data.get("data"), dict) else data
    for key in ("regions", "region_prices", "prices"):
        arr = root.get(key) if isinstance(root, dict) else None
        regions = _regions_from_list(arr or [])
        if regions:
            editions.append({"edition": "Standard", "package_id": root.get("package_id"), "regions": regions})
            break

    return editions

def _region_to_cc(region: str) -> str:
    return region.upper() if len(region) == 2 else "RU"

def fetch_game_info(app_id: int, region: str = "RU") -> Optional[dict]:
    params = {"appids": str(app_id), "l": "ru", "cc": _region_to_cc(region)}
    try:
        r = requests.get(STEAM_STORE_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"⚠️ Не удалось получить данные из Steam Store API: {e}")
        return None
    node = data.get(str(app_id)) or {}
    if not node.get("success") or "data" not in node:
        print("⚠️ Steam Store API вернул пустой ответ для этого APP_ID.")
        return None
    d = node["data"]
    name = d.get("name")
    gnames = [g.get("description") for g in d.get("genres", []) if isinstance(g, dict) and g.get("description")]
    rdate = (d.get("release_date") or {}).get("date")
    p = d.get("price_overview") or {}
    price = None
    if "final_formatted" in p:
        price = p["final_formatted"]
    elif "final" in p and "currency" in p:
        try:
            price = f"{p['final']/100:.2f} {p['currency']}"
        except Exception:
            pass
    short = d.get("short_description")
    return {
        "name": name,
        "type": d.get("type"),
        "genres": [g for g in gnames if g],
        "release_date": rdate,
        "price": price,
        "short_description": short,
    }

def make_auto_notes_from_store(info: dict) -> str:
    parts = []
    if info.get("name"): parts.append(f"Steam: {info['name']}")
    if info.get("type"): parts.append(f"Тип: {info['type']}")
    if info.get("genres"): parts.append("Жанры: " + ", ".join(info["genres"][:5]))
    if info.get("release_date"): parts.append(f"Релиз: {info['release_date']}")
    if info.get("price"): parts.append(f"Прайс (витрина): {info['price']}")
    if info.get("short_description"):
        short = info["short_description"]
        parts.append("Описание: " + short[:160] + ("…" if len(short) > 160 else ""))
    return " | ".join(parts)

def summarize_item(it: SteamGiftItem) -> str:
    country = COUNTRY_BY_CODE.get(it.region, it.region)
    parts = [f"[{it.key}] {it.title} | регион: {it.region} — {country}"]
    parts.append(f"  app_id: {it.app_id or '-'}  sub_id: {it.sub_id or '-'}")
    if it.last_price is not None:
        parts.append(f"  цена: {it.last_price} {it.currency or 'USD'}".rstrip())
    if it.notes:
        parts.append(f"  заметки: {it.notes}")
    return "\n".join(parts)

def _available_region_codes(regions: Dict[str, Dict[str, Optional[float]]]) -> List[str]:
    return sorted([code for code, row in regions.items() if row and row.get("price") is not None])

def print_region_reference_available(codes: List[str]) -> None:
    print("\nДоступные регионы (вводите 2 буквы) — цены на API в USD:")
    print("  Код | Страна         | Валюта")
    print("  ----+----------------+--------")
    for code in sorted(codes):
        print(f"  {code:>3} | {COUNTRY_BY_CODE.get(code,'?'):<14} | USD")
    print()

def print_region_prices_table(regions: Dict[str, Dict[str, Optional[float]]]) -> None:
    codes = _available_region_codes(regions)
    print("\nЦены по регионам (Dessly, валюта USD):")
    print("  Код | Страна         | Цена (USD) | Скидка")
    print("  ----+----------------+------------+--------")
    for code in codes:
        row = regions.get(code, {})
        p = row.get("price")
        d = row.get("discount")
        s_price = "-" if p is None else f"{p:.4f}"
        s_disc = d if d else "-"
        print(f"  {code:>3} | {COUNTRY_BY_CODE.get(code,'?'):<14} | {s_price:<10} | {s_disc}")
    if not codes:
        print("  (нет ни одного региона с доступной ценой)")
    print()

def print_editions_list(editions: List[Dict[str, Any]]) -> None:
    print("\nНайденные издания по этому APP_ID:")
    for i, ed in enumerate(editions, start=1):
        title = ed.get("edition") or "Edition"
        pkg = ed.get("package_id")
        regions_count = len(ed.get("regions") or {})
        print(f"  {i}. {title}  (package_id: {pkg or '-'}, доступных регионов: {regions_count})")
    print()

def resolve_order_params(funpay_key: str | int, items: Optional[Dict[str, SteamGiftItem]] = None) -> Tuple[int, str]:
    data = items or load_items()
    key = str(funpay_key)
    if key not in data:
        raise KeyError(f"Товар с кодом {key} не найден в steam_gifts.json")
    it = data[key]
    if not it.app_id:
        raise ValueError(f"Для {key} не задан app_id.")
    if it.region not in REGION_CHOICES:
        raise ValueError(f"Недопустимый регион {it.region} (ожидались: {', '.join(sorted(REGION_CHOICES))})")
    return int(it.app_id), it.region

def cmd_create_item():
    show_env_notice_once()
    items = load_items()
    print("=== Создание позиции Steam (Dessly) ===")
    print("Подсказка: отмена — 0 / «отмена» / «назад».")

    apikey = (sys.argv[1].strip() if len(sys.argv) >= 2 and sys.argv[1].strip() else None) or _env_apikey()

    selected_regions: Dict[str, Dict[str, Optional[float]]] = {}
    selected_pkg_label: str = ""
    selected_pkg_id: Optional[int] = None
    app_id: Optional[int] = None

    while True:
        app_id = input_int("APP_ID (из URL магазина Steam): ", min_val=1, allow_cancel=True)
        if app_id is None:
            print("Отменено."); press_enter(); return
        if not apikey:
            print("ℹ️ API key отсутствует — цены по регионам показать не сможем (урезанный режим).")
            break
        try:
            raw = dessly_get_by_app_id(app_id, apikey)
            editions = dessly_list_editions(raw)
            if not editions:
                print("⚠️ По этому APP_ID нет изданий с доступными ценами.")
                if yes_no("Ввести другой APP_ID?"):
                    continue
                else:
                    break
            if len(editions) == 1:
                ed = editions[0]
            else:
                print_editions_list(editions)
                idx = input_int("Выберите издание (номер, 0 — отмена): ", min_val=0, max_val=len(editions), allow_cancel=True)
                if idx in (None, 0):
                    print("Отменено."); press_enter(); return
                ed = editions[idx - 1]
            selected_regions = ed["regions"]
            selected_pkg_label = str(ed.get("edition") or "Edition")
            selected_pkg_id = ed.get("package_id")
            break
        except ApiError as e:
            print(f"⚠️ {e}")
            if "не найдена" in str(e).lower() or "-53" in str(e):
                continue
            if not yes_no("Повторить попытку ввода APP_ID?"):
                print("Отменено."); press_enter(); return

    if selected_regions:
        print_region_prices_table(selected_regions)
    else:
        print("Цены по регионам недоступны (нет API key или не удалось получить данные).")

    available_codes = _available_region_codes(selected_regions)
    if selected_regions and not available_codes:
        print("⚠️ Для выбранного издания нет доступных регионов с ценой.")
        press_enter(); return
    if selected_regions:
        print_region_reference_available(available_codes)
    while True:
        region = input_str("Выбери регион (2 буквы из списка выше): ", allow_empty=False, allow_cancel=True)
        if region is None:
            print("Отменено."); press_enter(); return
        region = region.upper()
        if selected_regions and region not in available_codes:
            print("Этот регион недоступен для выбранного издания. Выберите из списка выше."); continue
        if not selected_regions and region not in REGION_CHOICES:
            print("Неверный код региона. Выберите из 42-х возможных."); continue
        break

    info = fetch_game_info(app_id, region)
    auto_title = (info or {}).get("name") or f"APP {app_id}"
    auto_notes = make_auto_notes_from_store(info) if info else ""
    if selected_pkg_label:
        extra = f"Пакет: {selected_pkg_label}"
        if selected_pkg_id:
            extra += f" (package_id {selected_pkg_id})"
        auto_notes = (auto_notes + (" | " if auto_notes else "") + extra).strip()
    if not info:
        print("ℹ️ Не удалось получить обогащение из Steam Store API — продолжим без него.")

    title = input_str(f"Название (Enter — {auto_title}): ", allow_empty=True, allow_cancel=True)
    if title is None:
        print("Отменено."); press_enter(); return
    if not title:
        title = auto_title

    auto_price: Optional[float] = None
    auto_curr: Optional[str] = None
    if selected_regions and region in selected_regions:
        rp = selected_regions.get(region, {})
        if rp and rp.get("price") is not None:
            auto_price, auto_curr = rp["price"], "USD"
            print(f"Автозаполняем цену для {region}: {auto_price} USD")

    default_notes = auto_notes
    notes = input_str("Заметки (Enter — автозаметки / пусто): ", allow_empty=True, allow_cancel=True)
    if notes is None:
        print("Отменено."); press_enter(); return
    if notes == "":
        notes = default_notes

    while True:
        funpay_id = input_int("Укажи ID товара для FunPay (целое ≥ 1): ", min_val=1, allow_cancel=True)
        if funpay_id is None:
            print("Отменено."); press_enter(); return
        key = str(funpay_id)
        if key in items:
            print("Этот ID уже занят — выбери другой."); continue
        break

    it = SteamGiftItem(
        key=key, title=title, region=region, app_id=app_id, sub_id=None, notes=notes
    )
    if auto_price is not None:
        it.last_price, it.currency = auto_price, "USD"

    print("Проверка данных позиции:")
    print(summarize_item(it))
    if yes_no("Сохранить позицию"):
        items[key] = it
        save_items(items)
        print("✅ Сохранено.")
    else:
        print("Сохранение отменено.")
    press_enter()

def _choose_existing_key(items: Dict[str, SteamGiftItem]) -> Optional[str]:
    if not items:
        print("Каталог пуст."); return None
    print("\nТекущие позиции:")
    for k in sorted(items.keys(), key=lambda x: int(x) if str(x).isdigit() else x):
        it = items[k]
        print(f"  {k}: {it.title} ({it.region} — {COUNTRY_BY_CODE.get(it.region, it.region)})")
    sid = input_int("\nУкажи ID позиции (0 — назад): ", min_val=1, allow_cancel=True)
    if sid is None: return None
    key = str(sid)
    if key not in items:
        print("Позиция не найдена."); return None
    return key

def cmd_edit_item():
    show_env_notice_once()
    items = load_items()
    print("\n=== Редактирование позиции ===")
    key = _choose_existing_key(items)
    if not key: press_enter(); return
    it = items[key]

    print("\nЧто меняем?")
    print("  1) APP_ID")
    print("  2) Регион (2 буквы)")
    print("  3) Название")
    print("  4) Заметки")
    print("  5) Обновить инфо из Steam Store API по APP_ID (подтянуть название/заметки)")
    print("  6) Получить информацию по всем регионам (Dessly) и обновить цену для текущего региона (с выбором издания)")
    print("  7) Сменить ID (ключ) позиции")
    print("  0) Назад")
    choice = input_int("Выбор: ", min_val=0, max_val=7, allow_cancel=True)
    if choice in (None, 0): press_enter(); return

    changed = False
    apikey = (sys.argv[1].strip() if len(sys.argv) >= 2 and sys.argv[1].strip() else None) or _env_apikey()

    if choice == 1:
        val = input_int("Новый APP_ID (или прежний): ", min_val=1, allow_cancel=True)
        if val is None: print("Отменено."); press_enter(); return
        it.app_id = val; changed = True

    elif choice == 2:
        print("\nСправочник регионов (все возможные, цены на API в USD):")
        print_region_reference_available(sorted(COUNTRY_BY_CODE.keys()))
        while True:
            region = input_str("Новый регион (2 буквы): ", allow_empty=False, allow_cancel=True)
            if region is None: print("Отменено."); press_enter(); return
            region = region.upper()
            if region not in REGION_CHOICES:
                print("Неверный код региона. Выберите из списка выше."); continue
            it.region = region; changed = True; break

    elif choice == 3:
        title = input_str("Новое название: ", allow_empty=False, allow_cancel=True)
        if title is None: print("Отменено."); press_enter(); return
        it.title = title; changed = True

    elif choice == 4:
        notes = input_str("Новые заметки (можно пусто): ", allow_empty=True, allow_cancel=True)
        if notes is None: print("Отменено."); press_enter(); return
        it.notes = notes; changed = True

    elif choice == 5:
        if not it.app_id:
            print("Сначала укажи APP_ID (п.1).")
        else:
            info = fetch_game_info(it.app_id, it.region)
            if info:
                suggested_title = info.get("name") or it.title
                print(f"Найдено название в Steam: {suggested_title}")
                if yes_no("Обновить название на найденное"):
                    it.title = suggested_title; changed = True
                auto_notes = make_auto_notes_from_store(info)
                if auto_notes:
                    print("Автозаметки собраны из Steam.")
                    if yes_no("Заменить заметки на автозаметки"):
                        it.notes = auto_notes; changed = True
            else:
                print("⚠️ Не удалось получить данные из Steam Store API.")

    elif choice == 6:
        if not apikey:
            print("Нужен API key в .env или как аргумент командной строки.")
        elif not it.app_id:
            print("Нужен APP_ID.")
        else:
            try:
                raw = dessly_get_by_app_id(it.app_id, apikey)
                editions = dessly_list_editions(raw)
                if not editions:
                    print("⚠️ Нет изданий с доступными ценами.")
                else:
                    if len(editions) > 1:
                        print_editions_list(editions)
                        idx = input_int("Выберите издание (номер, 0 — отмена): ", min_val=0, max_val=len(editions), allow_cancel=True)
                        if idx in (None, 0):
                            print("Отменено."); press_enter(); return
                        ed = editions[idx - 1]
                    else:
                        ed = editions[0]
                    regions = ed["regions"]
                    print_region_prices_table(regions)
                    avail = _available_region_codes(regions)
                    if it.region in avail:
                        row = regions[it.region]
                        it.last_price, it.currency = row["price"], "USD"
                        print(f"Цена обновлена для {it.region} — {COUNTRY_BY_CODE.get(it.region)}: {it.last_price} USD")
                        pkg_label = str(ed.get("edition") or "Edition")
                        pkg_id = ed.get("package_id")
                        extra = f"Пакет: {pkg_label}" + (f" (package_id {pkg_id})" if pkg_id else "")
                        if extra not in (it.notes or ""):
                            it.notes = (it.notes + (" | " if it.notes else "") + extra).strip()
                        changed = True
                    else:
                        print("Текущий регион позиции отсутствует у выбранного издания — цену не обновляем.")
            except Exception as e:
                print(f"⚠️ Не удалось получить информацию по регионам: {e}")

    elif choice == 7:
        while True:
            new_id = input_int("Новый ID позиции (целое ≥ 1): ", min_val=1, allow_cancel=True)
            if new_id is None: print("Отменено."); press_enter(); return
            new_key = str(new_id)
            if new_key in items and new_key != it.key:
                print("Этот ID уже занят."); continue
            if new_key != it.key:
                items.pop(it.key)
                it.key = new_key
                items[new_key] = it
                changed = True
            break

    if changed:
        print("\nОбновлённая позиция:"); print(summarize_item(it))
        if yes_no("Сохранить изменения"):
            save_items(items); print("✅ Изменения сохранены.")
        else:
            print("Сохранение отменено.")
    else:
        print("Изменений нет.")
    press_enter()

def cmd_delete_item():
    items = load_items()
    print("\n=== Удаление позиции ===")
    key = _choose_existing_key(items)
    if not key: press_enter(); return
    if yes_no(f"Удалить позицию {key} безвозвратно"):
        items.pop(key, None); save_items(items); print("✅ Удалено.")
    else:
        print("Удаление отменено.")
    press_enter()

def print_items(items: Dict[str, SteamGiftItem]) -> None:
    if not items:
        print("Пока нет ни одной позиции."); return
    for k in sorted(items.keys(), key=lambda x: int(x) if str(x).isdigit() else x):
        print(summarize_item(items[k])); print("-" * 40)

def cmd_list_items():
    print("\n=== Список позиций ===")
    items = load_items()
    print_items(items)
    press_enter()

def main_menu():
    show_env_notice_once()
    while True:
        print("\n==============================")
        print("     Мастер айдишников Steam ")
        print("          (Dessly API)       ")
        print("==============================")
        print("Подсказка: в любом месте можно ввести 0 / «отмена» / «назад».")
        print("\nДоступные действия:")
        print("  1. Создать позицию (APP_ID → выбор издания → цены по регионам → инфо Steam)")
        print("  2. Редактировать позицию")
        print("  3. Удалить позицию")
        print("  4. Посмотреть список")
        print("  0. Выход\n")

        choice = input_int("Выберите пункт (0–4): ", min_val=0, max_val=4, allow_cancel=True)
        if choice in (None, 0):
            print("Выход."); break
        if choice == 1: cmd_create_item()
        elif choice == 2: cmd_edit_item()
        elif choice == 3: cmd_delete_item()
        elif choice == 4: cmd_list_items()

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nВыход (Ctrl+C).")
