# ValutaTrade Hub (final project)

Консольное приложение (Python-пакет), имитирующее валютный кошелёк:
- регистрация/логин
- портфель с кошельками (fiat + crypto)
- buy / sell
- просмотр курсов (get-rate)
- отдельный Parser Service для обновления курсов (CoinGecko + ExchangeRate-API)
- кеш курсов в `data/rates.json` и история замеров в `data/exchange_rates.json`
- логирование операций и ошибок

## Установка
```bash
make install
```
## Демо
[![asciinema demo](https://asciinema.org/a/m7t1BXwJSnvnuaDDVXkbnD6dI.svg)](https://asciinema.org/a/m7t1BXwJSnvnuaDDVXkbnD6dI)
