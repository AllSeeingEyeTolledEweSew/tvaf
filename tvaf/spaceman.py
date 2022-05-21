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

# flake8: noqa
"""Spaceman (Space Management) code."""


class Spaceman:
    def __init__(self):
        self.config = None
        self.trackers = None
        self.conn = None

    def is_pinned(self, torrent_status, meta) -> bool:
        assert torrent_status.infohash == meta.infohash
        if not meta.managed:
            return True
        if time.time() < meta.atime + self.config.pin_time:
            return True
        threshold = self.get_seed_threshold(torrent_status.tracker)
        if threshold is not None and torrent_status.seeders < threshold:
            return True
        if self.is_required_for_hnr(torrent_status):
            return True
        return False

    def get_seed_threshold(self, tracker):
        TODO

    def is_required_for_hnr(torrent_status):
        TODO

    def evaluate(self, torrent_status, meta) -> Tuple[bool, float]:
        if self.is_pinned(torrent_status, meta):
            return (True, 0)
        TODO
