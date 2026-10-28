"""Preserve signature markup; resolve local assets into CID MIME resources."""
import base64
import hashlib
import html
import mimetypes
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        if not self.hidden and tag in ('br', 'p', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head'):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ('p', 'div', 'tr', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(markup):
    parser = PlainText()
    parser.feed(markup)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).replace('\xa0', ' ').splitlines() if line.strip())


def decode_html(path):
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('gb18030')


@dataclass
class ImageAsset:
    cid: str
    data: bytes
    media_type: str
    filename: str


@dataclass
class Signature:
    markup: str
    text: str
    images: list
    fingerprint: str


RESOURCE = re.compile(r'(?P<attr>\b(?:src|background)\s*=\s*)(?P<q>[\"\x27])(?P<url>.*?)(?P=q)|(?P<css>url\(\s*)(?P<cq>[\"\x27]?)(?P<curl>[^)\"\x27]+)(?P=cq)\s*\)', re.I | re.S)


def map_resources(markup, resolver):
    def replace(match):
        url = html.unescape(match.group('url') if match.group('attr') else match.group('curl')).strip()
        value = resolver(url)
        if match.group('attr'):
            return match.group('attr') + match.group('q') + html.escape(value, quote=True) + match.group('q')
        return match.group('css') + '"' + value.replace('"', '%22') + '")'
    return RESOURCE.sub(replace, markup)


def resolve_local(url, directory):
    parsed = urlsplit(url)
    if parsed.scheme == 'file':
        if parsed.netloc not in ('', 'localhost'):
            raise ValueError('不支持签名中的网络共享图片。')
        value = unquote(parsed.path)
        if re.match(r'^/[A-Za-z]:', value):
            value = value[1:]
        return Path(value)
    if parsed.scheme and not re.match(r'^[A-Za-z]:[\\/]', url):
        raise ValueError('签名图片必须是可读取的本地图片：' + parsed.scheme)
    return (Path(directory) / unquote(url).replace('\\', '/')).resolve()


def load_signature(path):
    path = Path(path)
    markup = decode_html(path)
    if re.search(r'<\s*(?:script|iframe|object|embed|form)\b|\bon[a-z]+\s*=|javascript\s*:', markup, re.I):
        raise ValueError('签名包含活动内容，请提供静态 HTML 签名。')
    if re.search(r'\bsrcset\s*=|\bsrc\s*=\s*[^\s\"\x27>]', markup, re.I):
        raise ValueError('签名含不支持的 srcset 或未加引号的图片路径，请先检查签名资源。')
    images = {}
    def resolve(url):
        if url.startswith('data:image/'):
            try:
                head, payload = url.split(',', 1)
                if ';base64' not in head:
                    raise ValueError()
                data = base64.b64decode(payload, validate=True)
                media = head[5:].split(';')[0]
                name = 'signature-image' + (mimetypes.guess_extension(media) or '.bin')
            except Exception:
                raise ValueError('签名内的 data 图片无效。') from None
        else:
            local = resolve_local(url, path.parent)
            if not local.is_file():
                raise ValueError('缺少签名图片文件：' + str(local))
            data = local.read_bytes()
            media = mimetypes.guess_type(local.name)[0] or ''
            name = local.name
        if not media.startswith('image/') or media == 'image/svg+xml':
            raise ValueError('签名图片格式不支持；请提供原始 PNG、JPEG 或 GIF 图片。')
        # Content-ID is an addr-spec, not an RFC 2047 text header. Keep the
        # entire header below 78 columns; Python otherwise encoded the old
        # 64-hex ID as encoded-words, breaking CID lookup in Foxmail.
        cid = 'img-' + hashlib.sha256(data).hexdigest()[:32] + '@independent-mail.local'
        images[cid] = ImageAsset(cid, data, media, name)
        return 'cid:' + cid
    markup = map_resources(markup, resolve)
    # Local links would disclose local paths and cannot work for recipients.
    if re.search(r'file\s*:', markup, re.I):
        raise ValueError('签名仍包含本机文件链接，请核对缺失资源。')
    digest = hashlib.sha256(markup.encode() + b''.join(x.data for x in images.values())).hexdigest()
    return Signature(markup, plain_text(markup), list(images.values()), digest)


def body_html(body):
    blocks = re.split(r'\n\s*\n', body.replace('\r\n', '\n'))
    return ''.join('<p style="margin:0 0 16px">' + html.escape(block).replace('\n', '<br>') + '</p>' for block in blocks)


def message_plain(msg):
    if msg.is_multipart():
        part = next(p for p in msg.walk() if p.get_content_type() == 'text/plain')
    else:
        part = msg
    return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8')


def preview_document(msg):
    part = next((p for p in msg.walk() if p.get_content_type() == 'text/html'), None)
    if part is None:
        content = body_html(message_plain(msg))
    else:
        content = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8')
        for image in msg.walk():
            cid = (image.get('Content-ID') or '').strip('<>')
            if cid and image.get_content_maintype() == 'image':
                data = base64.b64encode(image.get_payload(decode=True)).decode('ascii')
                content = content.replace('cid:' + cid, 'data:' + image.get_content_type() + ';base64,' + data)
    policy = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + policy + '"></head><body style="font-family:Arial,sans-serif;padding:20px">' + content + '</body></html>'
