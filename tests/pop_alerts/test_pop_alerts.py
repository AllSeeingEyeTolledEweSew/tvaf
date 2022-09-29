# Copyright (c) 2022 AllSeeingEyeTolledEweSew
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

from typing import cast

import libtorrent as lt
import pytest

from tests import conftest
from tvaf import config as config_lib
from tvaf import session as session_lib
from tvaf._internal import pop_alerts as pop_alerts_lib


@pytest.fixture
def session(config: config_lib.Config) -> lt.session:
    session_service = session_lib.SessionService(
        config=config, alert_mask=lt.alert_category.status
    )
    return session_service.session


@pytest.fixture
def atp(mkatp: conftest.MkAtp) -> lt.add_torrent_params:
    return mkatp()


@pytest.fixture(params=[True, False], ids=["force_thread_wait", "default_thread_wait"])
def use_thread_wait(request: pytest.FixtureRequest) -> bool:
    return cast(bool, request.param)


@conftest.timeout(5)
async def test_pop_alerts_pre_setup(
    session: lt.session, atp: lt.add_torrent_params, use_thread_wait: bool
) -> None:
    with pop_alerts_lib.get_pop_alerts(
        session, use_thread_wait=use_thread_wait
    ) as pop_alerts:
        session.async_add_torrent(atp)
        while True:
            if any(isinstance(a, lt.add_torrent_alert) for a in await pop_alerts()):
                break


@conftest.timeout(5)
@pytest.mark.parametrize("pre_drain", [True, False])
async def test_pop_alerts_post_setup(
    session: lt.session,
    atp: lt.add_torrent_params,
    use_thread_wait: bool,
    pre_drain: bool,
) -> None:
    if pre_drain:
        session.pop_alerts()
    session.async_add_torrent(atp)
    with pop_alerts_lib.get_pop_alerts(
        session, use_thread_wait=use_thread_wait
    ) as pop_alerts:
        while True:
            if any(isinstance(a, lt.add_torrent_alert) for a in await pop_alerts()):
                break
