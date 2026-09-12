"""Conservative local triage. Redaction is never publication clearance."""
from collections import Counter
import hashlib
import hmac
import re

from .export_safety import canonical, reject, strict_json
from .storage import _SECRET_VALUE

# Broad patterns intentionally trade precision for reviewability. Never evaluate
# matches as regex/config code or persist removed values or an alias dictionary.
PATTERNS = (
    ('private_key', r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)'),
    ('authorization', r'(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]+'),
    ('url', r'(?i)\b(?:https?|ftp)://[^\s<>"\']+'),
    ('email', r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'),
    ('api_token', r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b'),
    ('credential', r'''(?ix)\b(?:api[_-]?key|password|passwd|secret|credential|access[_-]?token|refresh[_-]?token|client[_-]?secret|token) ["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)'''),
    ('account_project', r'''(?ix)\b(?:account|project|customer|tenant|organization|org|device|serial)(?:[_\s-]?(?:id|number|no))? ["']?\s*[:=#]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)'''),
    ('account_project', r'(?i)\b(?:acct|proj|org|cus|sub|tenant)[_-][A-Za-z0-9_-]{6,}\b'),
    ('uuid', r'(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b'),
    ('phone', r'(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?:\s*(?:ext\.?|x)\s*\d+)?\b'),
    ('phone', r'(?<!\w)\+\d{10,15}\b'),
    ('street_address', r'(?i)\b\d{1,6}\s+(?:[A-Za-z0-9.-]+\s+){1,5}(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|boulevard|blvd|court|ct|way)\b(?:[.,]?\s*(?:apt|suite|unit|#)\s*[A-Za-z0-9-]+)?'),
    ('ssn', r'\b\d{3}-\d{2}-\d{4}\b'),
    ('ip_address', r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    ('local_path', r'(?:/(?:Users|home|private|var)/[^\s<>"\']+|[A-Za-z]:\\[^\s<>"\']+)'),
    ('repository_secret', _SECRET_VALUE.pattern),
)
COMPILED = tuple((category, re.compile(pattern)) for category, pattern in PATTERNS)


def load_policy(boundary, key_file, denylist=None):
    key = boundary.read(key_file, 4096)
    if len(key) < 32:
        reject('private_key_too_short')
    terms = {}
    if denylist:
        value = strict_json(boundary.read(denylist, 1024 * 1024))
        if not isinstance(value, dict) or set(value) - {'personal_names', 'organizations', 'other'}:
            reject('invalid_denylist')
        for category, words in value.items():
            if (not isinstance(words, list) or len(words) > 1000
                    or any(not isinstance(w, str) or not w.strip() or len(w) > 256 for w in words)):
                reject('invalid_denylist')
            terms[category] = sorted(set(words), key=lambda w: (-len(w), w))
    return Sanitizer(key, terms)


class Sanitizer:
    def __init__(self, key, terms):
        self.key = key
        self.terms = terms
        self.counts = Counter()

    def ref(self, kind, value):
        return kind + '-' + hmac.new(self.key, canonical(value), hashlib.sha256).hexdigest()[:32]

    def text(self, text):
        for category, pattern in COMPILED:
            def replace(match):
                self.counts[category] += 1
                return '[REDACTED_' + category.upper() + ']'
            text = pattern.sub(replace, text)
        for category, words in sorted(self.terms.items()):
            for word in words:
                pattern = re.compile(r'(?<!\w)' + re.escape(word) + r'(?!\w)', re.IGNORECASE)
                def replace(match):
                    self.counts['denylist_' + category] += 1
                    return '[REDACTED_ENTITY_' + self.ref('alias', match[0].casefold())[6:18] + ']'
                text = pattern.sub(replace, text)
        # Remove terminal/control and bidi formatting characters, retaining layout.
        text, n = re.subn('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '', text)
        self.counts['control_characters'] += n
        return text

    def scan(self, value):
        """Count residual patterns in string values; never report matched values."""
        counts = Counter()
        if isinstance(value, str):
            # Our opaque aliases and markers aren't private identifiers.
            value = re.sub(r'\[REDACTED_[A-Za-z0-9_]+\]', '', value)
            for category, pattern in COMPILED:
                counts[category] += len(pattern.findall(value))
            for category, words in self.terms.items():
                for word in words:
                    counts['denylist_' + category] += len(re.findall(r'(?<!\w)' + re.escape(word) + r'(?!\w)', value, re.I))
        elif isinstance(value, dict):
            for key, item in value.items():
                counts.update(self.scan(key))
                counts.update(self.scan(item))
        elif isinstance(value, list):
            for item in value:
                counts.update(self.scan(item))
        return +counts
