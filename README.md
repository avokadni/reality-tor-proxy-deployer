# VLESS + REALITY -> Tor Deployer

Python-скрипт для автоматического разворачивания `VLESS + TCP + REALITY` с исходящим трафиком через `Tor SOCKS5` на удаленном сервере `Ubuntu 22.04`.

Скрипт подключается к серверу по SSH, ставит `tor` и `xray`, генерирует ключи `REALITY`, создает конфиг, перезапускает сервисы и выполняет проверку, что:

1. сам `Tor` работает;
2. цепочка `VLESS + REALITY -> Tor` действительно поднимается и отдает `IsTor=true`.

## Что поднимается

- Входящий `VLESS + TCP + REALITY` на выбранном порту.
- Исходящий трафик через локальный `Tor SOCKS5` на `127.0.0.1:9050`.
- Блокировка `UDP`.
- Блокировка `geoip:private`.

По умолчанию скрипт использует:

- `REALITY target`: `www.cloudflare.com:443`
- `REALITY SNI`: `www.cloudflare.com`
- `REALITY fingerprint`: `chrome`

Важно: это рабочий дефолт, но для реального использования лучше заменить target/SNI на свои.

## Что делает скрипт

- Подключается к серверу по SSH с паролем.
- Ставит пакеты `tor`, `curl`, `jq`, `openssl`, `unzip`.
- Ставит `xray` через официальный `XTLS/Xray-install`.
- Генерирует `x25519`-ключи и `shortId` для `REALITY`.
- Пишет серверный конфиг `xray`.
- Включает и перезапускает `tor` и `xray`.
- Открывает порт в `ufw`, если он активен.
- Проверяет прямой выход через `Tor`.
- Проверяет e2e-путь через временный локальный `VLESS + REALITY` клиент.
- Печатает готовую `vless://` ссылку для импорта в клиент.

## Требования

Локальная машина:

- Python 3
- Доступ к серверу по SSH
- Возможность установить зависимости из `requirements.txt`

Удаленный сервер:

- Ubuntu 22.04
- SSH password auth
- Пользователь `root` или пользователь с `sudo`
- Доступ в интернет для `apt` и загрузки `xray`

## Установка

```bash
git clone <your-repo-url>
cd vless-tor
python3 -m pip install -r requirements.txt
```

## Запуск

```bash
python3 deploy_vless_tor.py
```

Скрипт спросит:

- IP / hostname сервера
- SSH порт
- SSH пользователя
- SSH пароль
- порт для `VLESS`
- имя подключения (`remark`)

## Что будет в выводе

После успешного запуска скрипт выводит:

- имя `tor` service
- путь к конфигу `xray`
- `REALITY target`
- `REALITY SNI`
- `REALITY fingerprint`
- `REALITY client password`
- `REALITY short ID`
- готовую `vless://` ссылку
- результат проверки `Tor`
- результат проверки `VLESS + REALITY -> Tor`

## Архитектура

```text
+------------+        +-------------+        +-------------+        +------+
| VLESS      |        | Xray Server |        | Tor SOCKS5  |        | Tor  |
| Client     +------->+ REALITY In  +------->+ 127.0.0.1   +------->+ Net  |
|            |        |             |        | :9050       |        |      |
+------------+        +-------------+        +-------------+        +------+
```

## Ограничения

- Скрипт настраивает `xray` напрямую, не `Marzban`.
- Скрипт предполагает, что `sudo`-пароль совпадает с SSH-паролем, если вход не под `root`.
- Скрипт лучше запускать по числовому IP, а не по доменному имени, если в локальном Python есть проблемы с codec `idna`.
- Если на выбранном порту уже что-то слушает, скрипт завершится ошибкой.
- Если сервер не может достучаться до `GitHub`, `Tor network` или `check.torproject.org`, установка или проверка завершатся ошибкой.

## Troubleshooting

### `unknown encoding: idna`

Используй числовой IP сервера вместо hostname или переустанови локальный Python.

### `Unable to parse x25519 output`

Скрипт уже поддерживает старый и новый формат вывода `xray x25519`. Если ошибка повторяется, пришли полный вывод команды.

### `Remote port ... is already in use`

Выбери другой порт для `VLESS`.

### `Tor did not become ready in time`

Проверь:

- работает ли `tor`
- есть ли у сервера доступ в интернет
- не режет ли провайдер/хостер выход в Tor сеть

## Файлы проекта

- `deploy_vless_tor.py` — основной скрипт деплоя
- `requirements.txt` — Python-зависимости

## Полезные ссылки

- `Xray-install`: <https://github.com/XTLS/Xray-install>
- `Xray REALITY docs`: <https://xtls.github.io/en/config/transport.html>
- `Tor Project`: <https://www.torproject.org/>
