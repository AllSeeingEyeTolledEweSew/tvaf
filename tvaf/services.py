# Copyright (c) 2020 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.


import contextlib
import threading
from typing import ContextManager
from typing import Iterator

import libtorrent as lt

from tvaf import config as config_lib
from tvaf import driver as driver_lib
from tvaf import lifecycle
from tvaf import plugins
from tvaf import request as request_lib
from tvaf import resume as resume_lib
from tvaf import session as session_lib


def startup() -> None:
    for func in plugins.get_plugins_for_func(startup):
        func()


def shutdown() -> None:
    for func in plugins.get_plugins_for_func(shutdown):
        func()


@contextlib.contextmanager
def stage_config(config: config_lib.Config) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        for func in plugins.get_plugins_for_func(stage_config):
            stack.enter_context(func(config))
        yield


def set_config(config: config_lib.Config):
    with stage_config(config):
        pass


_lifespan_lock = threading.Lock()


@lifecycle.singleton()
def get_config() -> config_lib.Config:
    try:
        return config_lib.Config.from_disk()
    except FileNotFoundError:
        return config_lib.Config()


@lifecycle.singleton()
def get_session_service() -> session_lib.SessionService:
    return session_lib.SessionService(config=get_config())


@lifecycle.singleton()
def get_session() -> lt.session:
    return get_session_service().session


@lifecycle.singleton()
def get_alert_driver() -> driver_lib.AlertDriver:
    return driver_lib.AlertDriver(session_service=get_session_service())


@lifecycle.singleton()
def get_resume_service() -> resume_lib.ResumeService:
    return resume_lib.ResumeService(
        session=get_session(), alert_driver=get_alert_driver()
    )


@lifecycle.singleton()
def get_request_service() -> request_lib.RequestService:
    return request_lib.RequestService(
        session=get_session(),
        resume_service=get_resume_service(),
        alert_driver=get_alert_driver(),
        config=get_config(),
    )


@contextlib.contextmanager
def stage_config_disk(config: config_lib.Config) -> Iterator[None]:
    yield
    config.write_to_disk()


@contextlib.contextmanager
def stage_config_global(config: config_lib.Config) -> Iterator[None]:
    yield
    get_config.cache_clear()


def stage_config_session_service(
    config: config_lib.Config,
) -> ContextManager[None]:
    return get_session_service().stage_config(config)


def stage_config_request_service(
    config: config_lib.Config,
) -> ContextManager[None]:
    return get_request_service().stage_config(config)


def lock_lifespan() -> None:
    if not _lifespan_lock.acquire(blocking=False):
        raise AssertionError("only one instance allowed")


def unlock_lifespan() -> None:
    _lifespan_lock.release()


def startup_alert_driver() -> None:
    get_alert_driver().start()


def startup_request_service() -> None:
    get_request_service().start()


def startup_resume_service() -> None:
    get_resume_service().start()


def load_resume_data() -> None:
    # Load resume data
    session = get_session()
    for atp in resume_lib.iter_resume_data_from_disk():
        session.async_add_torrent(atp)


def shutdown_drain_requests() -> None:
    request_service = get_request_service()
    request_service.terminate()
    request_service.join()


def shutdown_session() -> None:
    # Should be no more alert-generating actions

    # Libtorrent shutdown sequence
    session = get_session()
    session.pause()
    resume_service = get_resume_service()
    resume_service.terminate()
    resume_service.join()


def shutdown_drain_alerts() -> None:
    # Wait for alert consumers to finish
    alert_driver = get_alert_driver()
    alert_driver.terminate()
    alert_driver.join()
