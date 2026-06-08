"""
Parsing primitives shared across every search engine adapter and page module:
URL/domain handling, price/model extraction, and the image-domain index.

These are page-agnostic. Per-page modules must import from here rather than keep
their own copies — divergent copies are how price/model extraction silently drifts.
"""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

_PRICE_RE = re.compile(r'\$\s*[\d,]+(?:\.\d{1,2})?')
_MODEL_RE = re.compile(
    r'(?:model|model\s*#|model\s*no|part\s*#|sku|item\s*#)[:\s#]+([A-Z0-9][\w\-/]{2,})', re.I
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lstrip('www.')
    except Exception:
        return ''


def _is_homepage(url: str) -> bool:
    """Return True if the URL is a bare domain homepage with no meaningful path."""
    try:
        path = urlparse(url).path
        return not path or path == '/'
    except Exception:
        return False


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text or '')
    return m.group(0).strip() if m else None


def _extract_model(text: str) -> Optional[str]:
    m = _MODEL_RE.search(text or '')
    return m.group(1).strip() if m else None


def _img_index(images: List[Dict]) -> Dict[str, str]:
    """Build domain → image-url index from DDG image results."""
    idx: Dict[str, str] = {}
    for img in images:
        d = _domain(img.get('url', ''))
        if d and d not in idx:
            idx[d] = img.get('image') or img.get('thumbnail', '')
    return idx


def _cite_to_url(cite_html: str) -> str:
    """Convert a Bing display URL (with › separators) into a real URL."""
    text = re.sub(r'<[^>]+>', '', cite_html).strip()
    text = text.replace(' › ', '/').replace('› ', '/').replace(' ›', '/')
    # Strip Bing's display ellipsis — path was truncated, keep only what we have
    text = re.sub(r'[…\.]{2,}\s*$', '', text).rstrip('/')
    if not text.startswith('http'):
        text = 'https://' + text
    return text
