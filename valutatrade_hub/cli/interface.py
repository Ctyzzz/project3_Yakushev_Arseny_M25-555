from __future__ import annotations

import argparse
import shlex
import sys

from prettytable import PrettyTable

from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.usecases import CoreUseCases
from valutatrade_hub.core.utils import validate_currency_code
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import CoinGeckoClient, ExchangeRateApiClient
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


def _print_supported(u: CoreUseCases) -> None:
    print("Поддерживаемые валюты:", ", ".join(u.list_supported_codes()))


def _cmd_register(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        msg = u.register(args.username, args.password)
        print(msg)
    except ValueError as e:
        print(str(e))


def _cmd_login(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        msg = u.login(args.username, args.password)
        print(msg)
    except ValueError as e:
        print(str(e))


def _cmd_logout(u: CoreUseCases, args: argparse.Namespace) -> None:
    print(u.logout())


def _require_login(u: CoreUseCases) -> dict:
    session = u.current_user()
    if not session:
        raise RuntimeError("Сначала выполните login")
    return session


def _cmd_show_portfolio(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        session = _require_login(u)
        base = args.base or "USD"
        data = u.show_portfolio(int(session["user_id"]), base=base)

        if data["empty"]:
            print(f"Портфель пользователя '{session['username']}' пуст.")
            return

        print(f"Портфель пользователя '{session['username']}' (база: {data['base']}):")

        t = PrettyTable()
        t.field_names = ["Currency", "Balance", f"Value in {data['base']}"]

        for row in data["rows"]:
            t.add_row([row["code"], f"{row['balance']:.4f}", f"{row['value']:.4f}"])

        print(t)
        print("-" * 40)
        print(f"ИТОГО: {data['total']:.4f} {data['base']}")
    except RuntimeError as e:
        print(str(e))
    except CurrencyNotFoundError as e:
        print(str(e))
        _print_supported(u)
    except ApiRequestError as e:
        print(str(e))
        print("Подсказка: выполните update-rates или проверьте сеть/ключ API.")


def _cmd_buy(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        session = _require_login(u)
        res = u.buy(int(session["user_id"]), args.currency, float(args.amount))
        print(
            f"Покупка выполнена: {float(args.amount):.4f} {args.currency.upper()} "
            f"по курсу {res.get('rate', 0):.4f} USD/{args.currency.upper()}"
        )
        if "cost_usd" in res:
            print(f"Оценочная стоимость покупки: {res['cost_usd']:.4f} USD")
        print(f"Изменения: {res.get('before_after')}")
    except RuntimeError as e:
        print(str(e))
    except (ValueError, TypeError) as e:
        print(str(e))
    except CurrencyNotFoundError as e:
        print(str(e))
        _print_supported(u)
    except InsufficientFundsError as e:
        print(str(e))
    except ApiRequestError as e:
        print(str(e))
        print("Подсказка: update-rates или проверьте сеть/ключ API.")


def _cmd_sell(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        session = _require_login(u)
        res = u.sell(int(session["user_id"]), args.currency, float(args.amount))
        print(
            f"Продажа выполнена: {float(args.amount):.4f} {args.currency.upper()} "
            f"по курсу {res.get('rate', 0):.4f} USD/{args.currency.upper()}"
        )
        if "proceeds_usd" in res:
            print(f"Оценочная выручка: {res['proceeds_usd']:.4f} USD")
        print(f"Изменения: {res.get('before_after')}")
    except RuntimeError as e:
        print(str(e))
    except (ValueError, TypeError) as e:
        print(str(e))
    except CurrencyNotFoundError as e:
        print(str(e))
        _print_supported(u)
    except InsufficientFundsError as e:
        print(str(e))
    except ApiRequestError as e:
        print(str(e))
        print("Подсказка: update-rates или проверьте сеть/ключ API.")


def _cmd_get_rate(u: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        res = u.get_rate(args.from_code, args.to_code)
        print(
            f"Курс {args.from_code.upper()}→{args.to_code.upper()}: {res['rate']:.8f} "
            f"(обновлено: {res['updated_at']})"
        )
        inv = 1.0 / float(res["rate"]) if float(res["rate"]) != 0 else 0.0
        print(f"Обратный курс {args.to_code.upper()}→{args.from_code.upper()}: {inv:.8f}")
        if res.get("stale"):
            print("Внимание: данные могут быть устаревшими (TTL). Попробуйте update-rates.")
    except CurrencyNotFoundError as e:
        print(str(e))
        print("Подсказка: используйте show-rates или список поддерживаемых валют.")
        _print_supported(u)
    except ApiRequestError as e:
        print(str(e))
        print("Повторите попытку позже или выполните update-rates.")


def _cmd_update_rates(_: CoreUseCases, args: argparse.Namespace) -> None:
    try:
        cfg = ParserConfig()
        storage = RatesStorage(cfg)

        src = (args.source or "").lower().strip()
        if src in ("", "all"):
            clients = [CoinGeckoClient(cfg), ExchangeRateApiClient(cfg)]
        elif src == "coingecko":
            clients = [CoinGeckoClient(cfg)]
        elif src in ("exchangerate", "exchangerate-api", "exchangerateapi"):
            clients = [ExchangeRateApiClient(cfg)]
        else:
            print("Неизвестный источник. Используйте: coingecko или exchangerate")
            return

        updater = RatesUpdater(clients=clients, storage=storage)

        print("INFO: Starting rates update...")
        result = updater.run_update()

        sources = result.get("sources", {})
        for src_name, info in sources.items():
            if bool(info.get("ok")):
                print(f"INFO: Fetching from {src_name}... OK ({int(info.get('count', 0))} rates)")
            else:
                print(f"ERROR: Failed to fetch from {src_name}: {info.get('error')}")

        print(f"INFO: Writing {result['total']} rates to data/rates.json...")

        if result["ok"]:
            print(
                f"Update successful. Total rates updated: {result['total']}. "
                f"Last refresh: {result['last_refresh']}"
            )
        else:
            print(
                f"Update completed with errors. Total rates updated: {result['total']}. "
                f"Last refresh: {result['last_refresh']}"
            )
            print("Check logs/parser.log for details.")
    except ApiRequestError as e:
        print(str(e))
        print("Проверьте сеть/лимиты и переменную окружения EXCHANGERATE_API_KEY.")
    except Exception as e:
        print(f"Ошибка: {e}")


def _cmd_show_rates(u: CoreUseCases, args: argparse.Namespace) -> None:
    data = u.db.read_rates()
    pairs = data.get("pairs", {})
    last = data.get("last_refresh")

    if not pairs:
        print("Локальный кеш курсов пуст. Выполните 'update-rates', чтобы загрузить данные.")
        return

    currency = (args.currency or "").upper().strip()
    top = args.top
    base = (args.base or "USD").upper().strip()

    try:
        validate_currency_code(base)
    except Exception as e:
        print(str(e))
        return

    rows: list[tuple[str, float, str]] = []
    for k, v in pairs.items():
        frm, to = k.split("_", 1)
        rate = float(v["rate"])
        updated_at = str(v["updated_at"])

        if currency and (currency != frm and currency != to):
            continue

        shown_key = k
        shown_rate = rate

        if base != to:
            # хотим frm -> base, считаем через USD-мост
            try:
                frm_to_usd = float(u.get_rate(frm, "USD")["rate"]) if to != "USD" else rate
                base_to_usd = float(u.get_rate(base, "USD")["rate"])
                if base_to_usd == 0:
                    continue
                shown_rate = frm_to_usd / base_to_usd
                shown_key = f"{frm}_{base}"
            except Exception:
                continue

        rows.append((shown_key, shown_rate, updated_at))

    if not rows:
        print(f"Курс для '{currency or '...'}' не найден в кеше.")
        return

    if top is not None:
        rows.sort(key=lambda x: x[1], reverse=True)
        rows = rows[: int(top)]
    else:
        rows.sort(key=lambda x: x[0])

    print(f"Rates from cache (updated at {last}):")

    t = PrettyTable()
    t.field_names = ["Pair", "Rate", "Updated at"]
    for k, r, upd in rows:
        t.add_row([k, f"{r:.8f}", upd])
    print(t)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="project", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    reg = sub.add_parser("register")
    reg.add_argument("--username", required=True)
    reg.add_argument("--password", required=True)
    reg.set_defaults(fn=_cmd_register)

    login_parser = sub.add_parser("login")
    login_parser.add_argument("--username", required=True)
    login_parser.add_argument("--password", required=True)
    login_parser.set_defaults(fn=_cmd_login)

    logout_parser = sub.add_parser("logout")
    logout_parser.set_defaults(fn=_cmd_logout)

    sp = sub.add_parser("show-portfolio")
    sp.add_argument("--base", required=False)
    sp.set_defaults(fn=_cmd_show_portfolio)

    buy_parser = sub.add_parser("buy")
    buy_parser.add_argument("--currency", required=True)
    buy_parser.add_argument("--amount", required=True, type=float)
    buy_parser.set_defaults(fn=_cmd_buy)

    sell_parser = sub.add_parser("sell")
    sell_parser.add_argument("--currency", required=True)
    sell_parser.add_argument("--amount", required=True, type=float)
    sell_parser.set_defaults(fn=_cmd_sell)

    gr = sub.add_parser("get-rate")
    gr.add_argument("--from", dest="from_code", required=True)
    gr.add_argument("--to", dest="to_code", required=True)
    gr.set_defaults(fn=_cmd_get_rate)

    ur = sub.add_parser("update-rates")
    ur.add_argument("--source", required=False)
    ur.set_defaults(fn=_cmd_update_rates)

    sr = sub.add_parser("show-rates")
    sr.add_argument("--currency", required=False)
    sr.add_argument("--top", required=False, type=int)
    sr.add_argument("--base", required=False)
    sr.set_defaults(fn=_cmd_show_rates)

    shell = sub.add_parser("shell")
    shell.set_defaults(fn=None)

    return p


def run_cli() -> None:
    configure_logging()
    u = CoreUseCases()
    parser = build_parser()

    # Если запустили без аргументов - REPL
    if len(sys.argv) == 1:
        _repl(u, parser)
        return

    ns = parser.parse_args()
    if ns.cmd == "shell":
        _repl(u, parser)
        return
    if hasattr(ns, "fn") and ns.fn:
        ns.fn(u, ns)
    else:
        parser.print_help()


def _repl(u: CoreUseCases, parser: argparse.ArgumentParser) -> None:
    print("ValutaTrade Hub REPL. Введите команду (help для справки, exit для выхода).")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line == "help":
            parser.print_help()
            continue

        try:
            argv = shlex.split(line)
        except ValueError as e:
            print(f"Ошибка парсинга команды: {e}")
            continue

        try:
            ns = parser.parse_args(argv)
            if ns.cmd == "shell":
                print("Вы уже в REPL.")
                continue
            if hasattr(ns, "fn") and ns.fn:
                ns.fn(u, ns)
            else:
                parser.print_help()
        except SystemExit:
            continue
