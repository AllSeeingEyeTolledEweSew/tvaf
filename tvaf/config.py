# Copyright (c) 2021 AllSeeingEyeTolledEweSew
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

"""Config abstraction in tvaf.

Config in tvaf is modeled as a json-compatible dictionary.

tvaf uses a global singleton Config dictionary. This has no well-defined
schema. The available options, and requirements for each, are only defined
implicitly by config-handling code.

Config is updated in a two-step "staging" process:
  1. Validate the new config, possibly reserving any new resources.
  2. Apply the config to the running state.

Config updates are handled by "stage functions". Our goal is that config
handling for the entire app can be split into stage functions which are
independent from each other. Each focuses on just one part of the running
state.

A stage function takes the new Config dict as an argument, and returns an async
context manager. On __aenter__, the context manager should validate some aspect
of the new config. On normal __aexit__, the context manager must update the
running state. The context manager should be prepared to do cleanup on an
abnormal __aexit__.

When new config is received, the app will call every available stage function
with the new config, and __aenter__ its context manager. __aexit__ is called in
reverse order. Any exceptions raised from "later" stage functions will be
propagated via __aexit__ to "earlier" ones.

NB: Stage functions must NOT raise an exception during __aexit__. This would
mean that running state is only partially updated, and may be broken. Stage
functions must do everything they can to ensure that exceptions are raised ONLY
from __aenter__. Stage functions must also propagate any exceptions through
__aexit__, and not suppress them.

This module only has scaffolding for config management. It doesn't contain the
global Config instance for the tvaf app. That lives in tvaf.services.

Example:
    Here's a stage function which handles the config value "my_port",
    and manages a listening server socket.

    Note that the "my_port" config value is effectively required, as long as
    this stage function is used by the app.

    Note that we try to bind the new server socket in __aenter__, to ensure no
    exceptions may be raised from __aexit__. If an exception propagates to us,
    we clean up the new socket we reserved.

        @contextlib.asynccontextmanager
        async def stage_server_socket(config):
            port = config.require_int("my_port")
            new_socket = socket.create_server(("", port))  # may raise
            try:
                yield
            except Exception:
                new_socket.close()
                raise
            global_socket.close()
            global_socket = new_socket
"""

import contextlib
import json
import os
import pathlib
from typing import Any
from typing import AsyncContextManager
from typing import AsyncIterator
from typing import Callable
from typing import MutableMapping
from typing import Optional
from typing import Type
from typing import TypeVar
from typing import Union

from . import concurrency

# Design notes:

# Config is stored as json. This is so external programs can easily manipulate
# the config if necessary.

# Config is a dict of json-compatible python primitives. I tried using a
# dataclass to map it, but as of 3.8, translating between dataclasses and json
# is still quite cumbersome. We either need ad-hoc code in several different
# places, or complex metaclass code. All type conversion also needs to be
# centralized, which impacts modularity.

# Config updates are "staged" such that e.g. when the HTTP port is changed, we:
#  - bind a socket to the new port
#  - attempt any other config changes
#  - if other changes fail, close the new socket
#  - if other changes succeed, start the server on the new port and close
#    the old server.
# This makes certain changes impossible, such as changing the binding from
# 0.0.0.0:21 to 127.0.0.1:21, as the old server breaks the new binding. However
# I notice that nginx has the same limitation, so it's probably good enough.

# In Python we prefer to work with "disposable" objects which are configured
# only once, and re-created as necessary. However, tvaf's top-level App code
# doesn't know the right life cycle for its various components (for example,
# should the App re-create the server for a particular config change?).
# So we design our components to be long-lived objects which can be
# re-configured over their lifetimes.


class Error(Exception):
    """Base class for errors."""


class InvalidConfigError(Error):
    """A config item was invalid."""


_T = TypeVar("_T")


class Config(dict, MutableMapping[str, Any]):
    """A json-compatible dict."""

    @classmethod
    async def from_disk(
        cls: Type["_C"], path: Union[str, os.PathLike]
    ) -> "_C":
        """Reads a Config dict from a file.

        The file will be parsed as JSON.

        Args:
            path: A path-like object, naming to the file to read.

        Returns:
            A Config dict read from the file.

        Raises:
            InvalidConfigError: If the file contains invalid JSON.
        """
        path = pathlib.Path(path)
        contents = await concurrency.to_thread(path.read_text)
        try:
            data = json.loads(contents)
        except json.JSONDecodeError as exc:
            raise InvalidConfigError(str(exc)) from exc
        return cls(data)

    async def write_to_disk(self, path: Union[str, os.PathLike]) -> None:
        """Writes the Config to a file.

        The data will be written as pretty-printed JSON.

        Args:
            path: A path-like object, naming the file to write.
        """
        path = pathlib.Path(path)
        contents = json.dumps(self, sort_keys=True, indent=4)
        await concurrency.to_thread(path.write_text, contents)

    def _get(self, key: str, type_: Type[_T]) -> Optional[_T]:
        value = self.get(key)
        if key in self and not isinstance(value, type_):
            raise InvalidConfigError(f'"{key}": {value!r} is not a {type_}')
        return value

    def _require(self, key: str, type_: Type[_T]) -> _T:
        value = self._get(key, type_)
        if value is None:
            raise InvalidConfigError(f'"{key}": missing')
        return value

    def get_int(self, key: str) -> Optional[int]:
        """Get and validate an optional int value.

        Args:
            key: The name of the value to get.

        Returns:
            An int value, or None.

        Raises:
            InvalidConfigError: If the key exists but its value is not an int.
        """
        return self._get(key, int)

    def get_str(self, key: str) -> Optional[str]:
        """Get and validate an optional str value.

        Args:
            key: The name of the value to get.

        Returns:
            A str value, or None.

        Raises:
            InvalidConfigError: If the key exists but its value is not a str.
        """
        return self._get(key, str)

    def get_bool(self, key: str) -> Optional[bool]:
        """Get and validate an optional bool value.

        Args:
            key: The name of the value to get.

        Returns:
            A bool value, or None.

        Raises:
            InvalidConfigError: If the key exists but its value is not a bool.
        """
        return self._get(key, bool)

    def require_int(self, key: str) -> int:
        """Get a required int value.

        Args:
            key: The name of the value to get.

        Returns:
            An int value.

        Raises:
            InvalidConfigError: If the key does not exist or its value is not
                an int.
        """
        return self._require(key, int)

    def require_str(self, key: str) -> str:
        """Get a required str value.

        Args:
            key: The name of the value to get.

        Returns:
            A str value.

        Raises:
            InvalidConfigError: If the key does not exist or its value is not a
                str.
        """
        return self._require(key, str)

    def require_bool(self, key: str) -> bool:
        """Get a required bool value.

        Args:
            key: The name of the value to get.

        Returns:
            A bool value.

        Raises:
            InvalidConfigError: If the key does not exist or its value is not a
                bool.
        """
        return self._require(key, bool)


_C = TypeVar("_C", bound=Config)


@contextlib.asynccontextmanager
async def stage_config(
    config: Config, *stages: Callable[[Config], AsyncContextManager]
) -> AsyncIterator[None]:
    """Applies a new Config to a sequence of stage functions.

    This implements the config update process described above.

    See above documentation for stage function requirements.

    stage_config will call each stage function in order with the given config,
    and __aenter__ its context manager. __aexit__ is called in reverse order.
    Any exceptions in later stage functions will be propagated via __aexit__ to
    earlier ones.

    stage_config returns an async context manager. stage_config really just
    "chains" several stage functions into a single stage function.

    Args:
        config: The new config to apply.
        stages: A list of stage functions to receive the new config.

    Returns:
        An overall context manager which represents applying the config to all
        the given stages.
    """
    async with contextlib.AsyncExitStack() as stack:
        for stage in stages:
            await stack.enter_async_context(stage(config))
        yield
