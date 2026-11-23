"""Extract source resources to local files (no clawpartner runtime imports)."""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlparse
from urllib.request import urlopen

CSS_URL = re.compile(r'url\(\s*([\'"]?)(.*?)\1\s*\)', re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_resource(ref, base):
    if ref.startswith('data:'):
        header, encoded = ref.split(',', 1)
        mime = header[5:].split(';')[0]
        data = base64.b64decode(encoded) if ';base64' in header else unquote_to_bytes(encoded)
        return data, mimetypes.guess_extension(mime) or '.bin'
    address = urljoin(base, ref)
    parsed = urlparse(address)
    if parsed.scheme in ('http', 'https'):
        with urlopen(address, timeout=30) as response:
            data = response.read()
            mime = response.headers.get_content_type()
    elif parsed.scheme == 'file':
        from urllib.request import url2pathname
        data = Path(url2pathname(parsed.path)).read_bytes()
        mime = mimetypes.guess_type(parsed.path)[0]
    else:
        raise ValueError(f'Unsupported resource URL: {address}')
    extension = Path(unquote(parsed.path)).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,8}', extension):
        extension = mimetypes.guess_extension(mime or '') or '.bin'
    return data, extension


class AssetStore:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'assets').mkdir(parents=True, exist_ok=True)
        self.mapping = {}

    def save(self, data, extension, source):
        path = f'assets/{digest(data)}{extension}'
        (self.root / path).write_bytes(data)
        self.mapping[source] = path
        return path

    def reference(self, ref, base):
        if not ref or ref.startswith('#'):
            return ref
        address = ref if ref.startswith('data:') else urljoin(base, ref)
        if address in self.mapping:
            fragment = urlparse(ref).fragment if not ref.startswith('data:') else ''
            return self.mapping[address] + ('#' + fragment if fragment else '')
        data, ext = read_resource(ref, base)
        path = self.save(data, ext, address)
        # SVG fragment identifiers select an internal symbol.
        fragment = urlparse(ref).fragment if not ref.startswith('data:') else ''
        return path + ('#' + fragment if fragment else '')

    def css(self, text, base):
        def imported(match):
            ref = match.group(1) or match.group(2)
            return self.stylesheet(ref, base)
        text = re.sub(r'@import\s+(?:url\(\s*[\'"]?([^\s)\'"]+)[\'"]?\s*\)|[\'"]([^\'"]+)[\'"])\s*;', imported, text, flags=re.I)
        if re.search(r'@import\b', text, re.I):
            raise ValueError('CSS @import with media/layer conditions requires manual inlining')
        return CSS_URL.sub(lambda m: 'url("' + (m[2] if m[2].split('#')[0] in self.mapping.values() else self.reference(m[2], base)) + '")', text)

    def stylesheet(self, ref, base, active=None):
        address = urljoin(base, ref)
        active = getattr(self, '_active_css', set())
        if address in active:
            raise ValueError(f'Cyclic CSS import: {address}')
        self._active_css = active
        active.add(address)
        try:
            data, _ = read_resource(ref, base)
            return self.css(data.decode('utf-8-sig'), address)
        finally:
            active.remove(address)


def rewrite_html(text, resolve):
    """Rewrite resource attributes and CSS, preserving Jinja slots as text."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser')
    for tag in soup.find_all(True):
        for attr in ('src', 'poster', 'background'):
            if tag.get(attr):
                tag[attr] = resolve(tag[attr])
        if tag.name in ('image', 'use'):
            for attr in ('href', 'xlink:href'):
                if tag.get(attr):
                    tag[attr] = resolve(tag[attr])
        if tag.get('srcset'):
            # A data URL contains commas; tokenize candidates by descriptor boundary.
            candidates = re.findall(r'((?:data:[^\s]+|[^\s,]+))(?:\s+(\d+(?:\.\d+)?[wx]))?\s*(?:,|$)', tag['srcset'])
            if not candidates:
                raise ValueError('Unparseable srcset')
            tag['srcset'] = ', '.join(resolve(ref.rstrip(',')) + (' ' + size if size else '') for ref, size in candidates)
        if tag.get('style'):
            tag['style'] = CSS_URL.sub(lambda m: 'url("' + resolve(m[2]) + '")', tag['style'])
        if tag.name == 'style':
            value = tag.string or tag.get_text()
            tag.string = CSS_URL.sub(lambda m: 'url("' + resolve(m[2]) + '")', value)
    return str(soup)


