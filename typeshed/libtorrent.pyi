import datetime
import typing
from typing import Any
from typing import Callable
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import overload
from typing import Tuple
from typing import Union

from typing_extensions import TypedDict

_ConvertsToString = Union[str, bytes]

class tracker_source(int):
    name: str
    names: Dict[str, tracker_source]
    values: Dict[int, tracker_source]

    source_torrent: tracker_source
    source_client: tracker_source
    source_magnet_link: tracker_source
    source_tex: tracker_source

class file_slice:
    file_index: int
    offset: int
    size: int

class peer_request:
    piece: int
    start: int
    length: int

class error_category:
    def message(self, value: int) -> str: ...
    def name(self) -> str: ...

def system_category() -> error_category: ...
def generic_category() -> error_category: ...
def libtorrent_category() -> error_category: ...
def upnp_category() -> error_category: ...
def http_category() -> error_category: ...
def socks_category() -> error_category: ...
def bdecode_category() -> error_category: ...
def i2p_category() -> error_category: ...

class error_code:
    def __init__(self, value: int, category: error_category) -> None: ...
    def assign(self, value: int, category: error_category) -> None: ...
    def category(self) -> error_category: ...
    def clear(self) -> None: ...
    def message(self) -> str: ...
    def value(self) -> int: ...

class file_storage:
    def __init__(self) -> None: ...
    def is_valid(self) -> bool: ...
    def add_file(
        self,
        path: str,
        size: int,
        flags: int = ...,
        mtime: int = ...,
        linkpath: str = ...,
    ) -> None: ...
    def num_files(self) -> int: ...
    def hash(self, index: int) -> sha1_hash: ...
    def symlink(self, index: int) -> str: ...
    def file_path(self, index: int, save_path: str = ...) -> str: ...
    def file_name(self, index: int) -> str: ...
    def file_size(self, index: int) -> int: ...
    def file_offset(self, index: int) -> int: ...
    def file_flags(self, index: int) -> int: ...
    def total_size(self) -> int: ...
    def set_num_pieces(self, num_pieces: int) -> None: ...
    def num_pieces(self) -> int: ...
    def set_piece_length(self, piece_length: int) -> None: ...
    def piece_length(self) -> int: ...
    def piece_size(self, index: int) -> int: ...
    def set_name(self, name: str) -> None: ...
    def rename_file(self, index: int, path: str) -> None: ...
    def name(self) -> str: ...
    flag_pad_file: int
    flag_hidden: int
    flag_executable: int
    flag_symlink: int

class file_flags_t:
    flag_pad_file: int
    flag_hidden: int
    flag_executable: int
    flag_symlink: int

class create_torrent:
    @overload
    def __init__(
        self,
        fs: file_storage,
        piece_size: int = ...,
        pad_file_limit: int = ...,
        flags: int = ...,
    ): ...
    @overload
    def __init__(self, ti: torrent_info): ...
    def generate(self) -> Dict[bytes, Any]: ...
    def files(self) -> file_storage: ...
    def set_comment(self, comment: str) -> None: ...
    def set_creator(self, creator: str) -> None: ...
    def set_hash(self, index: int, b: bytes) -> None: ...
    def set_file_hash(self, index: int, b: bytes) -> None: ...
    def add_url_seed(self, url: _ConvertsToString) -> None: ...
    def add_http_seed(self, url: _ConvertsToString) -> None: ...
    def add_node(self, addr: str, port: int) -> None: ...
    def add_tracker(self, announce_url: str, tier: int = ...) -> None: ...
    def set_priv(self, priv: bool) -> None: ...
    def num_pieces(self) -> int: ...
    def piece_length(self) -> int: ...
    def piece_size(self, index: int) -> int: ...
    def priv(self) -> bool: ...
    def set_root_cert(self, pem: _ConvertsToString) -> None: ...
    def add_collection(self, c: _ConvertsToString) -> None: ...
    def add_similar_torrent(self, ih: sha1_hash) -> None: ...
    merkle: int
    modification_time: int
    optimize_alignment: int
    symlinks: int

class create_torrent_flags_t:
    merkle: int
    modification_time: int
    optimize_alignment: int
    symlinks: int

@overload
def add_files(
    t: create_torrent, fs: file_storage, path: str, flags: int = ...
) -> None: ...
@overload
def add_files(
    t: create_torrent,
    fs: file_storage,
    path: str,
    predicate: Callable[[str], bool],
    flags: int = ...,
) -> None: ...
@overload
def set_piece_hashes(
    t: create_torrent, path: str, callback: Callable[[int], Any]
) -> None: ...
@overload
def set_piece_hashes(t: create_torrent, path: str) -> None: ...
def generate_fingerprint(
    name: _ConvertsToString, major: int, minor: int, rev: int, tag: int
) -> str: ...

class announce_entry:
    def __init__(self, url: str) -> None: ...
    url: str
    trackerid: str
    tier: int
    fail_limit: int
    source: int
    verified: bool
    def reset(self) -> None: ...
    def trim(self) -> None: ...

class sha1_hash:
    def __init__(self, info_hash: _ConvertsToString) -> None: ...
    def clear(self) -> None: ...
    def is_all_zeros(self) -> bool: ...
    def to_bytes(self) -> bytes: ...
    def to_string(self) -> str: ...

peer_id = sha1_hash

class _WebSeed(TypedDict):
    type: int
    url: str
    auth: str

_Entry = Union[bytes, Dict[bytes, Any], List, int]

class torrent_info:
    @overload
    def __init__(self, entry: _Entry): ...
    @overload
    def __init__(self, entry: _Entry, limits: Dict[str, Any]): ...
    @overload
    def __init__(self, filename: str): ...
    @overload
    def __init__(self, filename: str, limits: Dict[str, Any]): ...
    @overload
    def __init__(self, info_hash: sha1_hash): ...
    @overload
    def __init__(self, ti: torrent_info): ...
    def add_http_seed(
        self, url: str, extern_auth: str, extra_headers: List[Tuple[str, str]]
    ) -> None: ...
    def add_node(self, hostname: str, port: int) -> None: ...
    def add_tracker(
        self, url: str, tier: int, source: tracker_source = ...
    ) -> None: ...
    def add_url_seed(
        self, url: str, extern_auth: str, extra_headers: List[Tuple[str, str]]
    ) -> None: ...
    def collections(self) -> List[str]: ...
    def comment(self) -> str: ...
    def creation_date(self) -> int: ...
    def creator(self) -> str: ...
    def files(self) -> file_storage: ...
    def hash_for_piece(self, index: int) -> bytes: ...
    def info_hash(self) -> sha1_hash: ...
    def is_i2p(self) -> bool: ...
    def is_merkle_torrent(self) -> bool: ...
    def is_valid(self) -> bool: ...
    def map_block(
        self, piece: int, offset: int, size: int
    ) -> List[file_slice]: ...
    def map_file(self, index: int, offset: int, size: int) -> peer_request: ...
    def merkle_tree(self) -> List[sha1_hash]: ...
    def metadata(self) -> bytes: ...
    def metadata_size(self) -> int: ...
    def name(self) -> str: ...
    def nodes(self) -> List[Tuple[str, int]]: ...
    def num_files(self) -> int: ...
    def num_pieces(self) -> int: ...
    def orig_files(self) -> file_storage: ...
    def piece_length(self) -> int: ...
    def piece_size(self, index: int) -> int: ...
    def priv(self) -> bool: ...
    def remap_files(self, storage: file_storage) -> None: ...
    def set_merkle_tree(self, tree: List[bytes]) -> None: ...
    def set_web_seeds(self, web_seeds: List[Dict[str, Any]]) -> None: ...
    def similar_torrents(self) -> List[sha1_hash]: ...
    def ssl_cert(self) -> str: ...
    def total_size(self) -> int: ...
    def trackers(self) -> Iterator[announce_entry]: ...
    def web_seeds(self) -> List[_WebSeed]: ...

class peer_info:
    flags: int
    source: int
    read_state: int
    write_state: int
    ip: Tuple[str, int]
    up_speed: int
    down_speed: int
    payload_up_speed: int
    payload_down_speed: int
    total_upload: int
    total_download: int
    pid: sha1_hash
    pieces: List[bool]
    last_request: int
    last_active: int
    download_queue_time: int
    queue_bytes: int
    request_timeout: int
    send_buffer_size: int
    used_send_buffer: int
    receive_buffer_size: int
    used_receive_buffer: int
    num_hashfails: int
    download_queue_length: int
    upload_queue_length: int
    failcount: int
    downloading_piece_index: int
    downloading_block_index: int
    downloading_progress: int
    downloading_total: int
    client: bytes
    connection_type: int
    pending_disk_bytes: int
    send_quota: int
    receive_quota: int
    rtt: int
    num_pieces: int
    download_rate_peak: int
    upload_rate_peak: int
    progress: float
    progress_ppm: int
    local_endpoint: Tuple[str, int]

    interesting: int
    choked: int
    remote_interested: int
    remote_choked: int
    supports_extensions: int
    local_connection: int
    handshake: int
    connecting: int
    queued: int
    on_parole: int
    seed: int
    optimistic_unchoke: int
    snubbed: int
    upload_only: int
    endgame_mode: int
    holepunched: int
    rc4_encrypted: int
    plaintext_encrypted: int

    standard_bittorrent: int
    web_seed: int

    tracker: int
    dht: int
    pex: int
    lsd: int
    resume_data: int

    bw_idle: int
    bw_limit: int
    bw_network: int
    bw_disk: int

class _BlockInfo(TypedDict):
    state: int
    num_peers: int
    bytes_progress: int
    block_size: int
    peer: Tuple[str, int]

class _PartialPieceInfo(TypedDict):
    piece_index: int
    blocks_in_piece: int
    blocks: List[_BlockInfo]

class _ErrorCode(TypedDict):
    value: int
    category: str

class _TrackerEndpoint(TypedDict):
    message: str
    local_address: Tuple[str, int]
    last_error: _ErrorCode
    next_announce: int
    min_announce: int
    scrape_incomplete: int
    scrape_complete: int
    scrape_downloaded: int
    fails: int
    updating: bool
    start_sent: bool
    complete_sent: bool

class _Tracker(TypedDict):
    url: str
    trackerid: str
    tier: int
    fail_limit: int
    source: int
    verified: bool
    endpoints: List[_TrackerEndpoint]

class move_flags_t(int):
    name: str
    names: Dict[str, move_flags_t]
    values: Dict[int, move_flags_t]

    always_replace_files: move_flags_t
    dont_replace: move_flags_t
    fail_if_exist: move_flags_t

class open_file_state:
    file_index: int
    # other fields are broken

class torrent_handle:
    def get_peer_info(self) -> List[peer_info]: ...
    def status(self, flags: int = ...) -> torrent_status: ...
    def get_download_queue(self) -> List[_PartialPieceInfo]: ...
    def file_progress(self, flags: int = ...) -> List[int]: ...
    def trackers(self) -> List[_Tracker]: ...
    def replace_trackers(self, trackers: Iterable[Dict[str, Any]]) -> None: ...
    def add_tracker(self, tracker: Dict[str, Any]) -> None: ...
    def add_url_seed(self, url: str) -> None: ...
    def remove_url_seed(self, url: str) -> None: ...
    def url_seeds(self) -> List[str]: ...
    def add_http_seed(self, url: str) -> None: ...
    def remove_http_seed(self, url: str) -> None: ...
    def http_seeds(self) -> List[str]: ...
    def torrent_file(self) -> torrent_info: ...
    def set_metadata(self, metadata: bytes) -> None: ...
    def is_valid(self) -> bool: ...
    def pause(self, flags: int = ...) -> None: ...
    def resume(self) -> None: ...
    def clear_error(self) -> None: ...
    def queue_position(self) -> int: ...
    def queue_position_up(self) -> None: ...
    def queue_position_down(self) -> None: ...
    def queue_position_top(self) -> None: ...
    def queue_position_bottom(self) -> None: ...
    def add_piece(
        self, index: int, data: Union[bytes, str], flags: int
    ) -> None: ...
    def read_piece(self, index: int) -> None: ...
    def have_piece(self, index: int) -> bool: ...
    def set_piece_deadline(
        self, index: int, deadline: int, flags: int = ...
    ) -> None: ...
    def reset_piece_deadline(self, index: int) -> None: ...
    def clear_piece_deadlines(self) -> None: ...
    def piece_availability(self) -> List[int]: ...
    @overload
    def piece_priority(self, index: int) -> int: ...
    @overload
    def piece_priority(self, index: int, priority: int) -> None: ...
    @overload
    def prioritize_pieces(self, priorities: List[Tuple[int, int]]) -> None: ...
    @overload
    def prioritize_pieces(self, priorities: List[int]) -> None: ...
    def get_piece_priorities(self) -> List[int]: ...
    def prioritize_files(self, priorities: List[int]) -> None: ...
    def get_file_priorities(self) -> List[int]: ...
    @overload
    def file_priority(self, index: int) -> int: ...
    @overload
    def file_priority(self, index: int, priority: int) -> None: ...
    def file_status(self) -> List[open_file_state]: ...
    def save_resume_data(self, flags: int = ...): ...
    def need_save_resume_data(self) -> bool: ...
    def force_reannounce(
        self, seconds: int = ..., tracker_idx: int = ..., flags: int = ...
    ) -> None: ...
    def force_dht_announce(self) -> None: ...
    def scrape_tracker(self, index: int = ...) -> None: ...
    def flush_cache(self) -> None: ...
    def set_upload_limit(self, limit: int) -> None: ...
    def upload_limit(self) -> int: ...
    def set_download_limit(self, limit: int) -> None: ...
    def download_limit(self) -> int: ...
    def connect_peer(
        self, endpoint: Tuple[str, int], source: int = ..., flags: int = ...
    ) -> None: ...
    def set_max_uploads(self, limit: int) -> None: ...
    def max_uploads(self) -> int: ...
    def set_max_connections(self, limit: int) -> None: ...
    def max_connections(self) -> int: ...
    def move_storage(self, path: str, flags: int = ...) -> None: ...
    def info_hash(self) -> sha1_hash: ...
    def force_recheck(self) -> None: ...
    def rename_file(self, index: int, path: str) -> None: ...
    def set_ssl_certificate(
        self,
        cert: str,
        private_key: str,
        dh_params: str,
        passphrase: str = ...,
    ) -> None: ...
    def flags(self) -> int: ...
    @overload
    def set_flags(self, flags: int) -> None: ...
    @overload
    def set_flags(self, flags: int, mask: int) -> None: ...
    def unset_flags(self, flags: int) -> None: ...
    ignore_min_interval: int
    overwrite_existing: int
    piece_granularity: int
    graceful_pause: int
    flush_disk_cache: int
    save_info_dict: int
    only_if_modified: int
    alert_when_available: int
    query_distributed_copies: int
    query_accurate_download_counters: int
    query_last_seen_complete: int
    query_pieces: int
    query_verified_pieces: int

class file_open_mode:
    read_only: int
    write_only: int
    read_write: int
    rw_mask: int
    sparse: int
    no_atime: int
    random_access: int

class file_progress_flags(int):
    piece_granularity: file_progress_flags

    name: str
    names: Dict[str, file_progress_flags]
    values: Dict[int, file_progress_flags]

class add_piece_flags_t:
    overwrite_existing: int

class pause_flags_t:
    graceful_pause: int

class save_resume_flags_t:
    flush_disk_cache: int
    save_info_dict: int
    only_if_modified: int

class reannounce_flags_t:
    ignore_min_interval: int

class deadline_flags_t:
    alert_when_available: int

class status_flags_t:
    query_distributed_copies: int
    query_accurate_download_counters: int
    query_last_seen_complete: int
    query_pieces: int
    query_verified_pieces: int

class torrent_status:
    handle: torrent_handle
    info_hash: sha1_hash
    torrent_file: torrent_info
    state: states
    is_seeding: bool
    is_finished: bool
    has_metadata: bool
    progress: float
    progress_ppm: int
    next_announce: datetime.timedelta
    current_tracker: str
    total_download: int
    total_upload: int
    total_payload_download: int
    total_payload_upload: int
    total_failed_bytes: int
    total_redundant_bytes: int
    download_rate: int
    upload_rate: int
    download_payload_rate: int
    upload_payload_rate: int
    num_seeds: int
    num_peers: int
    num_complete: int
    num_incomplete: int
    list_seeds: int
    list_peers: int
    connect_candidates: int
    pieces: List[bool]
    verified_pieces: List[bool]
    num_pieces: int
    total_done: int
    total_wanted_done: int
    total_wanted: int
    distributed_full_copies: int
    distributed_fraction: int
    distributed_copies: float
    block_size: int
    num_uploads: int
    num_connections: int
    uploads_limit: int
    connections_limit: int
    storage_mode: storage_mode_t
    up_bandwidth_queue: int
    down_bandwidth_queue: int
    all_time_upload: int
    all_time_download: int
    seed_rank: int
    has_incoming: bool
    errc: error_code
    error_file: int
    name: str
    save_path: str
    added_time: int
    completed_time: int
    last_seen_complete: int
    queue_position: int
    need_save_resume: bool
    moving_storage: bool
    announcing_to_trackers: bool
    announcing_to_lsd: bool
    announcing_to_dht: bool
    last_upload: Optional[datetime.datetime]
    last_download: Optional[datetime.datetime]
    active_duration: datetime.timedelta
    finished_duration: datetime.timedelta
    seeding_duration: datetime.timedelta
    flags: int
    class states(int):
        name: str
        names: Dict[str, torrent_status.states]
        values: Dict[int, torrent_status.states]

        checking_files: torrent_status.states
        downloading_metadata: torrent_status.states
        downloading: torrent_status.states
        finished: torrent_status.states
        seeding: torrent_status.states
        allocating: torrent_status.states
        checking_resume_data: torrent_status.states

class add_torrent_params:
    version: int
    ti: Optional[torrent_info]
    trackers: List[str]
    tracker_tiers: List[int]
    dht_nodes: List[Tuple[str, int]]
    name: str
    save_path: str
    storage_mode: storage_mode_t
    file_priorities: List[int]
    trackerid: str
    flags: int
    info_hash: sha1_hash
    max_uploads: int
    max_connections: int
    upload_limit: int
    download_limit: int
    total_uploaded: int
    total_downloaded: int
    active_time: int
    finished_time: int
    seeding_time: int
    added_time: int
    completed_time: int
    last_seen_complete: int
    last_download: int
    last_upload: int
    num_complete: int
    num_incomplete: int
    num_downloaded: int
    http_seeds: List[str]
    url_seeds: List[str]
    peers: List[Tuple[str, int]]
    banned_peers: List[Tuple[str, int]]
    unfinished_pieces: Dict[int, List[bool]]
    have_pieces: List[bool]
    verified_pieces: List[bool]
    piece_priorities: List[int]
    merkle_tree: List[sha1_hash]
    renamed_files: Dict[int, str]

class storage_mode_t(int):
    name: str
    names: Dict[str, storage_mode_t]
    values: Dict[int, storage_mode_t]

    storage_mode_allocate: storage_mode_t
    storage_mode_sparse: storage_mode_t

class options_t:
    delete_files: int

class session_flags_t:
    add_default_plugins: int

class torrent_flags:
    seed_mode: int
    upload_mode: int
    share_mode: int
    apply_ip_filter: int
    paused: int
    auto_managed: int
    duplicate_is_error: int
    update_subscribe: int
    super_seeding: int
    sequential_download: int
    stop_when_ready: int
    override_trackers: int
    override_web_seeds: int
    disable_dht: int
    disable_lsd: int
    disable_pex: int
    default_flags: int

class _CachedPieceInfo(TypedDict):
    piece: int
    last_use: float
    next_to_hash: int
    kind: int

class cache_status:
    pieces: List[_CachedPieceInfo]

class portmap_protocol(int):
    name: str
    names: Dict[str, portmap_protocol]
    values: Dict[int, portmap_protocol]

    none: portmap_protocol
    tcp: portmap_protocol
    udp: portmap_protocol

class portmap_transport(int):
    name: str
    names: Dict[str, portmap_transport]
    values: Dict[int, portmap_transport]

    none: portmap_protocol
    tcp: portmap_protocol
    udp: portmap_protocol

class peer_class_type_filter_socket_type_t(int):
    name: str
    names: Dict[str, peer_class_type_filter_socket_type_t]
    values: Dict[int, peer_class_type_filter_socket_type_t]

    tcp_socket: peer_class_type_filter_socket_type_t
    utp_socket: peer_class_type_filter_socket_type_t
    ssl_tcp_socket: peer_class_type_filter_socket_type_t
    ssl_utp_socket: peer_class_type_filter_socket_type_t
    i2p_socket: peer_class_type_filter_socket_type_t

class peer_class_type_filter:
    def __init__(self) -> None: ...
    def add(self, st: int, peer_class: int) -> None: ...
    def remove(self, st: int, peer_class: int) -> None: ...
    def allow(self, st: int, peer_class: int) -> None: ...
    def disallow(self, st: int, peer_class: int) -> None: ...
    def apply(self, st: int, peer_class_mask: int) -> int: ...
    tcp_socket: peer_class_type_filter_socket_type_t
    utp_socket: peer_class_type_filter_socket_type_t
    ssl_tcp_socket: peer_class_type_filter_socket_type_t
    ssl_utp_socket: peer_class_type_filter_socket_type_t
    i2p_socket: peer_class_type_filter_socket_type_t

class alert_category:
    error: int
    peer: int
    port_mapping: int
    storage: int
    tracker: int
    connect: int
    status: int
    ip_block: int
    performance_warning: int
    dht: int
    stats: int
    session_log: int
    torrent_log: int
    peer_log: int
    incoming_request: int
    dht_log: int
    dht_operation: int
    port_mapping_log: int
    picker_log: int
    file_progress: int
    piece_progress: int
    upload: int
    block_progress: int
    all: int

class alert:
    def message(self) -> str: ...
    def what(self) -> Optional[str]: ...
    def category(self) -> int: ...
    def __str__(self) -> str: ...
    class category_t:
        error_notification: int
        peer_notification: int
        port_mapping_notification: int
        storage_notification: int
        tracker_notification: int
        connect_notification: int
        status_notification: int
        ip_block_notification: int
        performance_warning: int
        dht_notification: int
        stats_notification: int
        session_log_notification: int
        torrent_log_notification: int
        peer_log_notification: int
        incoming_request_notification: int
        dht_log_notification: int
        dht_operation_notification: int
        port_mapping_log_notification: int
        picker_log_notification: int
        file_progress_notification: int
        piece_progress_notification: int
        upload_notification: int
        block_progress_notification: int
        all_categories: int

class operation_t(int):
    name: str
    names: Dict[str, operation_t]
    values: Dict[int, operation_t]

    unknown: operation_t
    bittorrent: operation_t
    iocontrol: operation_t
    getpeername: operation_t
    getname: operation_t
    alloc_recvbuf: operation_t
    alloc_sndbuf: operation_t
    file_write: operation_t
    file_read: operation_t
    file: operation_t
    sock_write: operation_t
    sock_read: operation_t
    sock_open: operation_t
    sock_bind: operation_t
    available: operation_t
    encryption: operation_t
    connect: operation_t
    ssl_handshake: operation_t
    get_interface: operation_t
    sock_listen: operation_t
    sock_bind_to_device: operation_t
    sock_accept: operation_t
    parse_address: operation_t
    enum_if: operation_t
    file_stat: operation_t
    file_copy: operation_t
    file_fallocate: operation_t
    file_hard_link: operation_t
    file_remove: operation_t
    file_rename: operation_t
    file_open: operation_t
    mkdir: operation_t
    check_resume: operation_t
    exception: operation_t
    alloc_cache_piece: operation_t
    partfile_move: operation_t
    partfile_read: operation_t
    partfile_write: operation_t
    hostname_lookup: operation_t
    symlink: operation_t
    handshake: operation_t
    sock_option: operation_t

def operation_name(op: operation_t) -> str: ...

class torrent_alert(alert):
    handle: torrent_handle
    torrent_name: str

class tracker_alert(torrent_alert):
    local_endpoint: Tuple[str, int]
    def tracker_url(self) -> str: ...

class torrent_removed_alert(torrent_alert):
    info_hash: sha1_hash

class read_piece_alert(torrent_alert):
    error: error_code
    buffer: bytes
    piece: int
    size: int

class peer_alert(torrent_alert):
    endpoint: Tuple[str, int]
    pid: sha1_hash

class tracker_error_alert(tracker_alert):
    error: error_code
    def error_message(self) -> str: ...
    times_in_row: int

class tracker_warning_alert(tracker_alert): ...

class tracker_reply_alert(tracker_alert):
    num_peers: int

class tracker_announce_alert(tracker_alert):
    event: int

class hash_failed_alert(torrent_alert):
    piece_index: int

class peer_ban_alert(peer_alert): ...

class peer_error_alert(peer_alert):
    error: error_code
    op: operation_t

class invalid_request_alert(peer_alert):
    request: peer_request

class torrent_error_alert(torrent_alert):
    error: error_code

class torrent_finished_alert(torrent_alert): ...

class piece_finished_alert(torrent_alert):
    piece_index: int

class block_finished_alert(peer_alert):
    piece_index: int
    block_index: int

class block_downloading_alert(peer_alert):
    piece_index: int
    block_index: int

class storage_moved_alert(torrent_alert):
    def storage_path(self) -> str: ...

class storage_move_failed_alert(torrent_alert):
    def file_path(self) -> str: ...
    error: error_code
    op: operation_t

class torrent_deleted_alert(torrent_alert):
    info_hash: sha1_hash

class torrent_paused_alert(torrent_alert): ...
class torrent_checked_alert(torrent_alert): ...

class url_seed_alert(torrent_alert):
    error: error_code
    def error_message(self) -> str: ...
    def server_url(self) -> str: ...

class file_error_alert(torrent_alert):
    error: error_code
    def filename(self) -> str: ...

class metadata_failed_alert(torrent_alert):
    error: error_code

class metadata_received_alert(torrent_alert): ...

class listen_failed_alert(alert):
    address: str
    port: int
    def listen_interface(self) -> str: ...
    error: error_code
    op: operation_t
    socket_type: int

class listen_succeeded_alert(alert):
    address: str
    port: int
    socket_type: int

class socket_type_t(int):
    name: str
    names: Dict[str, socket_type_t]
    values: Dict[int, socket_type_t]

    tcp: socket_type_t
    tcp_ssl: socket_type_t
    udp: socket_type_t
    i2p: socket_type_t
    socks5: socket_type_t
    utp_ssl: socket_type_t

class portmap_error_alert(alert):
    mapping: int
    error: error_code
    map_transport: portmap_transport

class portmap_alert(alert):
    mapping: int
    external_port: int
    map_protocol: portmap_protocol
    map_transport: portmap_transport

class portmap_log_alert(alert):
    map_transport: portmap_transport

class fastresume_rejected_alert(torrent_alert):
    error: error_code
    def file_path(self) -> str: ...
    op: operation_t

class peer_blocked_alert(peer_alert):
    reason: reason_t

class reason_t(int):
    name: str
    names: Dict[str, reason_t]
    values: Dict[int, reason_t]

    ip_filter: reason_t
    port_filter: reason_t
    i2p_mixed: reason_t
    privileged_ports: reason_t
    utp_disabled: reason_t
    tcp_disabled: reason_t
    invalid_local_interface: reason_t

class scrape_reply_alert(tracker_alert):
    incomplete: int
    complete: int

class scrape_failed_alert(tracker_alert):
    def error_message(self) -> str: ...
    error: error_code

class udp_error_alert(alert):
    endpoint: Tuple[str, int]
    error: error_code

class external_ip_alert(alert):
    external_address: str

class save_resume_data_alert(torrent_alert):
    params: add_torrent_params

class file_completed_alert(torrent_alert):
    index: int

class file_renamed_alert(torrent_alert):
    index: int
    def new_name(self) -> str: ...

class file_rename_failed_alert(torrent_alert):
    index: int
    error: error_code

class torrent_resumed_alert(torrent_alert): ...

class state_changed_alert(torrent_alert):
    state: torrent_status.states
    prev_state: torrent_status.states

class state_update_alert(alert):
    status: List[torrent_status]

class i2p_alert(alert):
    error: error_code

class dht_reply_alert(tracker_alert):
    num_peers: int

class dht_announce_alert(alert):
    ip: str
    port: int
    info_hash: sha1_hash

class dht_get_peers_alert(alert):
    info_hash: sha1_hash

class peer_unsnubbed_alert(peer_alert): ...
class peer_snubbed_alert(peer_alert): ...
class peer_connect_alert(peer_alert): ...

class peer_disconnected_alert(peer_alert):
    socket_type: int
    op: operation_t
    error: error_code
    reason: int

class request_dropped_alert(peer_alert):
    block_index: int
    piece_index: int

class block_timeout_alert(peer_alert):
    block_index: int
    piece_index: int

class unwanted_block_alert(peer_alert):
    block_index: int
    piece_index: int

class torrent_delete_failed_alert(torrent_alert):
    error: error_code
    info_hash: sha1_hash

class save_resume_data_failed_alert(torrent_alert):
    error: error_code

class performance_alert(torrent_alert):
    warning_code: performance_warning_t

class performance_warning_t(int):
    name: str
    names: Dict[str, performance_warning_t]
    values: Dict[int, performance_warning_t]

    outstanding_disk_buffer_limit_reached: performance_warning_t
    outstanding_request_limit_reached: performance_warning_t
    upload_limit_too_low: performance_warning_t
    download_limit_too_low: performance_warning_t
    send_buffer_watermark_too_low: performance_warning_t
    too_many_optimistic_unchoke_slots: performance_warning_t
    too_high_disk_queue_limit: performance_warning_t
    too_few_outgoing_ports: performance_warning_t
    too_few_file_descriptors: performance_warning_t

class stats_alert(torrent_alert):
    transferred: List[int]
    interval: int

class stats_channel(int):
    name: str
    names: Dict[str, stats_channel]
    values: Dict[int, stats_channel]

    upload_payload: stats_channel
    upload_protocol: stats_channel
    upload_ip_protocol: stats_channel
    download_payload: stats_channel
    download_protocol: stats_channel
    download_ip_protocol: stats_channel

class cache_flushed_alert(torrent_alert): ...

class incoming_connection_alert(alert):
    socket_type: int
    endpoint: Tuple[str, int]

class torrent_need_cert_alert(torrent_alert): ...

class add_torrent_alert(torrent_alert):
    error: error_code
    params: add_torrent_params

class dht_outgoing_get_peers_alert(alert):
    info_hash: sha1_hash
    obfuscated_info_hash: sha1_hash
    endpoint: Tuple[str, int]

class log_alert(alert):
    def log_message(self) -> str: ...

class torrent_log_alert(torrent_alert):
    def log_message(self) -> str: ...

class peer_log_alert(peer_alert):
    def log_message(self) -> str: ...

class picker_log_alert(peer_alert):
    picker_flags: int

class lsd_error_alert(alert):
    error: error_code

class _DHTActiveRequest(TypedDict):
    type: str
    outstanding_requests: int
    timeouts: int
    responses: int
    branch_factor: int
    nodes_left: int
    last_sent: int
    first_timeout: int

class _DHTRoutingBucket(TypedDict):
    num_nodes: int
    num_replacements: int

class dht_stats_alert(alert):
    active_requests: List[_DHTActiveRequest]
    routing_table: List[_DHTRoutingBucket]

class dht_log_alert(alert):
    module: int
    def log_message(self) -> str: ...

class dht_pkt_alert(alert):
    pkt_buf: bytes

class _DHTImmutableItem(TypedDict):
    key: sha1_hash
    value: bytes

class dht_immutable_item_alert(alert):
    target: sha1_hash
    item: _DHTImmutableItem

class _DHTMutableItem(TypedDict):
    key: bytes
    value: bytes
    signature: bytes
    seq: int
    salt: bytes
    authoritative: bool

class dht_mutable_item_alert(alert):
    key: bytes
    signature: bytes
    seq: int
    salt: str
    item: _DHTMutableItem
    authoritative: bool

class dht_put_alert(alert):
    target: sha1_hash
    public_key: bytes
    signature: bytes
    salt: str
    seq: int
    num_success: int

class session_stats_alert(alert):
    values: Dict[str, int]

class session_stats_header_alert(alert): ...

class dht_get_peers_reply_alert(alert):
    info_hash: sha1_hash
    def num_peers(self) -> int: ...
    def peers(self) -> List[Tuple[str, int]]: ...

class block_uploaded_alert(peer_alert):
    block_index: int
    piece_index: int

class alerts_dropped_alert(alert):
    dropped_alerts: List[bool]

class socks5_alert(alert):
    error: error_code
    op: operation_t
    ip: Tuple[str, int]

class dht_live_nodes_alert(alert):
    node_id: sha1_hash
    num_nodes: int
    nodes: List[Tuple[sha1_hash, Tuple[str, int]]]

class dht_sample_infohashes_alert(alert):
    endpoint: Tuple[str, int]
    interval: datetime.timedelta
    num_infohashes: int
    num_samples: int
    samples: List[sha1_hash]
    num_nodes: int
    nodes: List[Tuple[sha1_hash, Tuple[str, int]]]

class dht_bootstrap_alert(alert): ...

class _UTPStats(TypedDict):
    num_idle: int
    num_syn_sent: int
    num_connected: int
    num_fin_sent: int
    num_close_wait: int

class session_status:
    has_incoming_connections: bool
    upload_rate: int
    download_rate: int
    total_upload: int
    total_download: int
    payload_upload_rate: int
    payload_download_rate: int
    total_payload_upload: int
    total_payload_download: int
    ip_overhead_upload_rate: int
    ip_overhead_download_rate: int
    total_ip_overhead_upload: int
    total_ip_overhead_download: int
    dht_upload_rate: int
    dht_download_rate: int
    total_dht_upload: int
    total_dht_download: int
    tracker_upload_rate: int
    tracker_download_rate: int
    total_tracker_upload: int
    total_tracker_download: int
    total_redundant_bytes: int
    total_failed_bytes: int
    num_peers: int
    num_unchoked: int
    allowed_upload_slots: int
    up_bandwidth_queue: int
    down_bandwidth_queue: int
    optimistic_unchoke_counter: int
    unchoke_counter: int
    dht_nodes: int
    dht_node_cache: int
    dht_torrents: int
    dht_global_nodes: int
    # active_requests is broken
    dht_total_allocations: int
    utp_stats: _UTPStats

class dht_lookup:
    type: Optional[str]
    outstanding_requests: int
    timeouts: int
    response: int
    branch_factor: int

class _PeerClassInfo(TypedDict):
    ignore_unchoke_slots: bool
    connection_limit_factor: int
    label: str
    upload_limit: int
    download_limit: int
    upload_priority: int
    download_priority: int

class dht_settings:
    def __init__(self) -> None: ...
    max_peers_reply: int
    search_branching: int
    max_fail_count: int
    max_torrents: int
    max_dht_items: int
    restrict_routing_ips: bool
    restrict_search_ips: bool
    max_torrent_search_reply: int
    extended_routing_table: bool
    aggressive_lookups: bool
    privacy_lookups: bool
    enforce_node_id: bool
    ignore_dark_internet: bool
    block_timeout: int
    block_ratelimit: int
    read_only: bool
    item_lifetime: int

class ip_filter:
    def __init__(self) -> None: ...
    def add_rule(self, start: str, end: str, flags: int) -> None: ...
    def access(self, addr: str) -> int: ...
    # export_filter is broken

class session:
    @overload
    def __init__(self, flags: int = ...) -> None: ...
    @overload
    def __init__(self, settings: Dict[str, Any], flags: int = ...) -> None: ...
    def post_torrent_updates(self, flags: int = ...) -> None: ...
    def post_dht_stats(self) -> None: ...
    def post_session_stats(self) -> None: ...
    def is_listening(self) -> bool: ...
    def listen_port(self) -> int: ...
    def add_dht_node(self, node: Tuple[str, int]) -> None: ...
    def is_dht_running(self) -> bool: ...
    def set_dht_settings(self, settings: dht_settings) -> None: ...
    def get_dht_settings(self) -> dht_settings: ...
    def dht_get_immutable_item(self, target: sha1_hash) -> None: ...
    def dht_get_mutable_item(self, key: str, salt: str) -> None: ...
    def dht_put_immutable_item(self, entry: _Entry) -> sha1_hash: ...
    def dht_put_mutable_item(
        self, private_key: str, public_key: str, data: str, salt: str
    ) -> None: ...
    def dht_get_peers(self, info_hash: sha1_hash) -> None: ...
    def dht_announce(
        self, info_hash: sha1_hash, port: int, flags: int
    ) -> None: ...
    def dht_live_nodes(self, nid: sha1_hash) -> None: ...
    def dht_sample_infohashes(
        self, ep: Tuple[str, int], target: sha1_hash
    ) -> None: ...
    @overload
    def add_torrent(self, params: Dict[str, Any]) -> torrent_handle: ...
    @overload
    def add_torrent(self, params: add_torrent_params) -> torrent_handle: ...
    @overload
    def async_add_torrent(self, params: Dict[str, Any]) -> None: ...
    @overload
    def async_add_torrent(self, params: add_torrent_params) -> None: ...
    def remove_torrent(
        self, handle: torrent_handle, option: int = ...
    ) -> None: ...
    def get_settings(self) -> Dict[str, Any]: ...
    def apply_settings(self, settings: Dict[str, Any]) -> None: ...
    def load_state(self, st: _Entry, flags: int = ...) -> None: ...
    def save_state(self, flags: int = ...) -> _Entry: ...
    def pop_alerts(self) -> List[alert]: ...
    def wait_for_alert(self, ms: int) -> alert: ...
    # def set_alert_notify(self, Callable[..., ...]) -> None: ...
    def add_extension(self, name: str) -> None: ...
    def set_ip_filter(self, f: ip_filter) -> None: ...
    def get_ip_filter(self) -> ip_filter: ...
    def find_torrent(self, info_hash: sha1_hash) -> torrent_handle: ...
    def get_torrents(self) -> List[torrent_handle]: ...
    def get_torrent_status(
        self, pred: Callable[[torrent_status], bool], flags: int = ...
    ) -> List[torrent_status]: ...
    def refresh_torrent_status(
        self, torrents: List[torrent_status], flags: int = ...
    ) -> List[torrent_status]: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def is_paused(self) -> bool: ...
    def get_cache_info(
        self, handle: torrent_handle = ..., flags: int = ...
    ) -> cache_status: ...
    def add_port_mapping(
        self, t: portmap_protocol, external_port: int, local_port: int
    ) -> List[int]: ...
    def delete_port_mapping(self, handle: int) -> None: ...
    def reopen_network_sockets(self, options: int = ...) -> None: ...
    def set_peer_class_filter(self, f: ip_filter) -> None: ...
    def set_peer_class_type_filter(
        self, f: peer_class_type_filter
    ) -> None: ...
    def create_peer_class(self, name: str) -> int: ...
    def delete_peer_class(self, cid: int) -> None: ...
    def get_peer_class(self, cid: int) -> _PeerClassInfo: ...
    def set_peer_class(self, cid: int, pci: Dict[str, Any]) -> None: ...
    tcp: portmap_protocol
    udp: portmap_protocol

    global_peer_class_id: int
    tcp_peer_class_id: int
    local_peer_class_id: int

    reopen_map_ports: int

class save_state_flags_t:
    save_settings: int
    save_dht_settings: int
    save_dht_state: int

def high_performance_seed() -> Dict[str, Any]: ...
def min_memory_usage() -> Dict[str, Any]: ...
def default_settings() -> Dict[str, Any]: ...
def read_resume_data(data: bytes) -> add_torrent_params: ...
def write_resume_data(atp: add_torrent_params) -> Dict[bytes, Any]: ...
def write_resume_data_buf(atp: add_torrent_params) -> bytes: ...

class stats_metric:
    name: Optional[str]
    value_index: int
    type: metric_type_t

class metric_type_t(int):
    name: str
    names: Dict[str, metric_type_t]
    values: Dict[int, metric_type_t]

    counter: metric_type_t
    gauge: metric_type_t

def session_stats_metrics() -> List[stats_metric]: ...
def find_metric_idx(name: str) -> int: ...

create_ut_metadata_plugin: str
create_ut_pex_plugin: str
create_smart_ban_plugin: str

class choking_algorithm_t(int):
    name: str
    names: Dict[str, choking_algorithm_t]
    values: Dict[int, choking_algorithm_t]

    fixed_slots_choker: choking_algorithm_t
    rate_based_choker: choking_algorithm_t

class seed_choking_algorithm_t(int):
    name: str
    names: Dict[str, seed_choking_algorithm_t]
    values: Dict[int, seed_choking_algorithm_t]

    round_robin: seed_choking_algorithm_t
    fastest_upload: seed_choking_algorithm_t
    anti_leech: seed_choking_algorithm_t

class suggest_mode_t(int):
    name: str
    names: Dict[str, suggest_mode_t]
    values: Dict[int, suggest_mode_t]

    no_piece_suggestions: suggest_mode_t
    suggest_read_cache: suggest_mode_t

class io_buffer_mode_t(int):
    name: str
    names: Dict[str, io_buffer_mode_t]
    values: Dict[int, io_buffer_mode_t]

    enable_os_cache: io_buffer_mode_t
    disable_os_cache: io_buffer_mode_t

class bandwidth_mixed_algo_t(int):
    name: str
    names: Dict[str, bandwidth_mixed_algo_t]
    values: Dict[int, bandwidth_mixed_algo_t]

    prefer_tcp: bandwidth_mixed_algo_t
    peer_proportional: bandwidth_mixed_algo_t

class enc_policy(int):
    name: str
    names: Dict[str, enc_policy]
    values: Dict[int, enc_policy]

    pe_forced: enc_policy
    pe_enabled: enc_policy
    pe_disabled: enc_policy

class enc_level(int):
    name: str
    names: Dict[str, enc_level]
    values: Dict[int, enc_level]

    pe_rc4: enc_level
    pe_plaintext: enc_level
    pe_both: enc_level

class proxy_type_t(int):
    name: str
    names: Dict[str, proxy_type_t]
    values: Dict[int, proxy_type_t]

    none: proxy_type_t
    socks4: proxy_type_t
    socks5: proxy_type_t
    socks5_pw: proxy_type_t
    http: proxy_type_t
    http_pw: proxy_type_t
    i2p_proxy: proxy_type_t

def bdecode(_: bytes) -> _Entry: ...
def bencode(_: Optional[_Entry]) -> bytes: ...
@overload
def make_magnet_uri(handle: torrent_handle) -> str: ...
@overload
def make_magnet_uri(ti: torrent_info) -> str: ...
def parse_magnet_uri(uri: str) -> add_torrent_params: ...
def parse_magnet_uri_dict(uri: str) -> Dict[str, Any]: ...

__version__: str
