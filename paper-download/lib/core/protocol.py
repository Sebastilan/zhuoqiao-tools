"""Publisher module contract: FetchResult and PublisherAdapter."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
PROTOCOL_VERSION = '1.5'
EC_HTTP_403 = 'http_403'
EC_CF_BLOCKED = 'cf_blocked'
EC_NO_OA = 'no_oa'
EC_SSH_FAIL = 'ssh_fail'
EC_RATE_LIMIT = 'rate_limit'
EC_TIMEOUT = 'timeout'
EC_NO_SUBSCRIPTION = 'no_subscription'
EC_NO_CAPABLE_NODE = 'no_capable_node'
EC_RELAY_PENDING = 'relay_pending'
EC_NO_ADAPTER = 'no_adapter'
EC_OTHER = 'other'
_VALID_ERROR_CLASSES = {EC_HTTP_403, EC_CF_BLOCKED, EC_NO_OA, EC_SSH_FAIL, EC_RATE_LIMIT, EC_TIMEOUT, EC_NO_SUBSCRIPTION, EC_NO_CAPABLE_NODE, EC_RELAY_PENDING, EC_NO_ADAPTER, EC_OTHER, ''}
_VALID_OUTPUT_FORMATS = {'pdf', 'xml', 'html', ''}
_VALID_EXEC_LOCATIONS = {'local', ''}

@dataclass
class FetchResult:
    ok: bool
    channel: str
    format: Optional[str]
    pdf_bytes: Optional[bytes]
    fulltext: Optional[str]
    elapsed_ms: int
    error_class: str
    error: str
    steps: List[str] = field(default_factory=list)
    node: str = ''
    relay_key: str = ''
    relay_url: str = ''
    pages: int = 0
    assets: dict = field(default_factory=dict)
    assets_missing: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.error_class not in _VALID_ERROR_CLASSES:
            raise ValueError("error_class '%s' not in valid set %s" % (self.error_class, _VALID_ERROR_CLASSES))
        if self.ok and (not (self.pdf_bytes or self.fulltext)):
            raise ValueError('FetchResult ok=True but both pdf_bytes and fulltext are None')
        if self.ok and self.format == 'pdf' and self.pdf_bytes:
            if self.pdf_bytes[:4] != b'%PDF':
                raise ValueError('FetchResult 声称 format=pdf，但字节不是 PDF（首 8 字节 %r，共 %d 字节）—— 多半是出版社拦截页/登录页。channel=%s' % (self.pdf_bytes[:8], len(self.pdf_bytes), self.channel))

    def to_legacy_dict(self):
        d = {'ok': self.ok, 'channel': self.channel, 'format': self.format, 'pdf_bytes': self.pdf_bytes, 'fulltext': self.fulltext, 'error': self.error}
        if self.steps:
            d['trace'] = {'steps': self.steps}
        if self.relay_key:
            d['relay_key'] = self.relay_key
            d['relay_url'] = self.relay_url
        return d

@dataclass
class HealthStatus:
    adapter: str
    channel: str
    status: str
    latency_ms: int
    checked_at: str
    error: str = ''
    node: str = ''

    def __post_init__(self):
        if self.status not in ('green', 'yellow', 'red'):
            raise ValueError("HealthStatus.status must be green/yellow/red, got '%s'" % self.status)

class PublisherAdapter(ABC):
    publisher_name = ''
    doi_prefixes = []
    channel_name = ''
    max_concurrency_per_node = 1
    estimated_seconds = -1.0
    protocol_version = PROTOCOL_VERSION
    output_format = ''
    execution_location = ''
    title_only = False

    @abstractmethod
    def sample_dois(self):
        ...

    def fetch(self, doi, **kwargs):
        return self._fetch_local(doi)

    def match(self, args):
        return True

    def fetch_batch(self, dois, **kwargs):
        return [self.fetch(doi, **kwargs) for doi in dois]
