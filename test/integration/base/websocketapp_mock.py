from typing import Callable, Optional
from unittest.mock import MagicMock

def init_wsa_mock(
        wsa_mock: MagicMock,
        url: str,
        on_open: Callable = None,
        on_message: Callable = None,
        on_error: Callable = None,
        on_close: Callable = None,
):
    wsa_mock.url = url

    wsa_mock._on_open = on_open
    wsa_mock._on_message = on_message
    wsa_mock._on_error = on_error
    wsa_mock._on_close = on_close

    wsa_mock.on_open.side_effect = on_open
    wsa_mock.on_message.side_effect = on_message
    wsa_mock.on_error.side_effect = on_error
    wsa_mock.on_close.side_effect = on_close

    wsa_mock.last_ping_tm = 0
    wsa_mock.keep_running = False

    return wsa_mock


def send(wsa_mock: MagicMock, message: str):
    wsa_mock.on_message(wsa_mock, message)


def close(wsa_mock: MagicMock):
    wsa_mock.keep_running = False
    wsa_mock.on_close(wsa_mock, None, None)


def run_forever(wsa_mock: MagicMock, sslopt: dict = None, ping_interval: float = 0, ping_timeout: Optional[float] = None):
    wsa_mock.keep_running = True
    wsa_mock.on_open(wsa_mock)

def create_wsa_mock():
    wsa_mock = MagicMock()

    wsa_mock.send.side_effect = lambda *args, **kwargs: send(wsa_mock, *args, **kwargs)
    wsa_mock.close.side_effect = lambda: close(wsa_mock)
    wsa_mock.run_forever.side_effect = lambda *args, **kwargs: run_forever(wsa_mock, *args, **kwargs)

    return wsa_mock
