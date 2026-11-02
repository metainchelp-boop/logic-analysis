"""Four reviewed immutable image identities. No environment or caller configuration."""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ImageProfile:
    name: str
    image_id: str
    expected_size_bytes: int
    session: str
    command: str
    max_image_bytes: int
    max_cipher_bytes: int
    max_archive_bytes: int
    max_expanded_bytes: int
    source_min_free_bytes: int
    receiver_min_free_bytes: int
    source_timeout_seconds: int
    receiver_timeout_seconds: int
    verify_timeout_seconds: int
    workflow_timeout_seconds: int
    large_export_enabled: bool


_MIB = 1024 * 1024
_GIB = 1024 * _MIB


def _small(name, digest, size):
    session = name + '-image-20261102-v1'
    return ImageProfile(name, 'sha256:' + digest, size, session, 'receive-' + session,
                        256 * _MIB, 512 * _MIB, 512 * _MIB, 512 * _MIB,
                        3 * _GIB, 2 * _GIB, 900, 900, 600, 930, False)


ORDER = ('autobid-web', 'autobid-engine', 'autobid-watchdog', 'content-studio')
PROFILES = MappingProxyType({
    'autobid-web': _small('autobid-web',
        '075e4cd227777d7ea5347c27c0842067bc963cead5c6b6cc60b71897105140ec', 84303740),
    'autobid-engine': _small('autobid-engine',
        '3b86b60dd010faba75e910bdac4d8acc1678a3eabf1f54463fe5a64bf1cc0f6d', 84303743),
    'autobid-watchdog': _small('autobid-watchdog',
        '935ce49a4c3981eda46e1ae39c76daf831fd90107410d1823ea133f7b86cffad', 84303745),
    # Source also requires the reviewed 29.4.0 client + containerd exporter policy.
    # This flag alone cannot bypass daemon identity, temp-path or space checks.
    # Docker 29.4.0 inspect Size counts packed resources, not inflated layer tar.
    # Verification hashes gzip output in 64KiB chunks; the 8GiB work budget is
    # separate from unchanged 2GiB archive/cipher bounds and the 1800s deadline.
    'content-studio': ImageProfile('content-studio',
        'sha256:b52374a33084ea20386af2380478a38cff92eebdbeff97c616ad7d80a112a0dc',
        1381032080, 'content-studio-image-20261102-v1',
        'receive-content-studio-image-20261102-v1',
        1536 * _MIB, 2 * _GIB, 2 * _GIB, 8 * _GIB,
        3 * _GIB, 4 * _GIB, 1800, 1800, 1800, 1830, True),
})


def lookup(name):
    if type(name) is not str or name not in PROFILES:
        raise ValueError('profile_refused')
    return PROFILES[name]
