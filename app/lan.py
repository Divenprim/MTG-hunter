"""Адрес в сети и сертификат для планшета.

Жило в `main.py` и делало там две вещи, которым в модуле с ручками не место:
печатало адреса и поднимало отдельный http-сервер **прямо при импорте**. То
есть `import app.main` -- в тестах, в любом скрипте -- мог открыть слушающий
порт на 0.0.0.0 и написать что-нибудь в stdout. Теперь это делается при
запуске сервера (`on_start`), а импорт модуля не делает ничего.

Наружу отсюда не уходит ни одного запроса: адреса берутся у своих же сетевых
адаптеров, а сертификат отдаётся только в свою сеть и только по явной просьбе.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from netutil import lan_addresses as _lan_addresses

# run.bat кладёт сюда то, чем он запустил uvicorn. Само приложение адреса, на
# котором его слушают, не знает, а показать его надо: с планшета нужен не
# localhost, а адрес этого компьютера в сети.
BIND_HOST = os.environ.get("MTGH_HOST", "127.0.0.1")
BIND_PORT = os.environ.get("MTGH_PORT", "8765")
LAN_OPEN = BIND_HOST not in ("127.0.0.1", "localhost", "::1", "")


def lan_addresses() -> list[str]:
    """Useful LAN addresses, with the default-route adapter first."""
    return _lan_addresses()


# По https сервер работает только в режиме для планшета, и адрес там другой.
# Подсказать планшету «http://...» значит подсказать неработающий адрес:
# соединения не будет, а выглядит это как «программа не работает».
SCHEME = os.environ.get("MTGH_SCHEME", "http")


def lan_urls() -> list[str]:
    return ["%s://%s:%s" % (SCHEME, ip, BIND_PORT) for ip in lan_addresses()]


# Корневой сертификат надо как-то донести до планшета, а по https он туда не
# попадёт: планшет ещё не знает этого сертификата и в соединение не пойдёт.
# Поэтому рядом с основным сервером поднимается крошечный обычный http, который
# умеет отдавать ровно один файл -- сам сертификат, и ничего больше.
CA_PORT = os.environ.get("MTGH_CA_PORT", "")
CA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "cert", "ca.pem")


def _serve_ca(port: int) -> None:
    import http.server

    data = open(CA_FILE, "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:                        # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/")
            if path in ("/ca.pem", "/ca"):
                self.send_response(200)
                # iOS downloads this as a configuration certificate/profile.
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="MTG-Hunter-CA.pem"',
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "":
                ip = lan_addresses()[0] if lan_addresses() else "THIS-PC"
                page = ("""<!doctype html><meta charset="utf-8">
<title>MTG Hunter — телефон</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:17px system-ui;max-width:680px;margin:30px auto;padding:0 18px;line-height:1.5}
a{display:inline-block;padding:12px 16px;background:#222;color:white;border-radius:10px;text-decoration:none}
code{background:#eee;padding:2px 5px;border-radius:4px}</style>
<h1>MTG Hunter на телефоне</h1>
<p>Обычный интерфейс можно открыть по HTTP без сертификата. Для камеры Safari/Chrome требуют HTTPS.</p>
<ol>
<li><a href="/ca.pem">Скачать локальный сертификат</a></li>
<li>На iPhone/iPad: Настройки → Профиль загружен → Установить.</li>
<li>Настройки → Основные → Об этом устройстве → Доверие сертификатам → включить <b>MTG Hunter local CA</b>.</li>
<li>После этого открыть <a href="https://%s:%s">https://%s:%s</a>.</li>
</ol>
<p>Это локальный сертификат, созданный на вашем компьютере; наружу он не отправляется.</p>"""
                        % (ip, BIND_PORT, ip, BIND_PORT)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            self.send_error(404)

        def log_message(self, *args: Any) -> None:       # noqa: D102
            pass

    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def _start_ca_server() -> None:
    if not CA_PORT or not os.path.exists(CA_FILE):
        return
    try:
        port = int(CA_PORT)
    except ValueError:
        return
    threading.Thread(target=_serve_ca, args=(port,), daemon=True).start()
    for ip in lan_addresses():
        announce("[сеть] сертификат для планшета: http://%s:%d/ca.pem"
                 % (ip, port))


def announce(text: str) -> None:
    """Сказать что-нибудь при запуске, не рискуя запуском.

    Кодировку вывода выбирает не программа: когда вывод уходит в канал -- в
    сборку, в лог, в чужой скрипт, -- Python берёт кодировку системы, и на
    английской Windows это cp1252, где кириллицы нет. Сообщение об адресе
    печатается на импорте модуля, то есть до того, как сервер поднимется, --
    и роняло его целиком. Со стороны это выглядит как «программа не
    запускается», без единого слова о причине.

    Потерять букву в сообщении не жалко, потерять сервер -- жалко.
    """
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        stream = getattr(sys.stdout, "buffer", None)
        if stream is not None:
            stream.write(text.encode("utf-8", "replace") + b"\n")
            stream.flush()


def _say_where() -> None:
    """Напечатать адреса при запуске: с планшета нужен не localhost."""
    if not LAN_OPEN:
        return
    for url in lan_urls():
        announce("[сеть] с планшета и телефона: %s" % url)
    announce("[сеть] пароля нет: кто в этой сети, тот и видит вашу коллекцию")


def on_start() -> None:
    """Сказать адреса и, если просили, поднять раздачу сертификата.

    Зовётся при запуске сервера, а не при импорте: раньше обе эти вещи
    случались от одного `import app.main`.
    """
    _say_where()
    _start_ca_server()
