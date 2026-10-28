"""TLS IMAP verification and optional archiving to a live-verified Sent folder."""
import imaplib
import re
import ssl
from email import policy
from email.parser import BytesParser


def connect(config, password):
    if not config.get('imap_host') or str(config.get('imap_security')) != 'SSL/TLS':
        raise ValueError('尚未核实 IMAP SSL/TLS 配置。')
    client = imaplib.IMAP4_SSL(config['imap_host'], int(config['imap_port']),
                               ssl_context=ssl.create_default_context(), timeout=20)
    try:
        # IMAP login is a single attempt; no automatic credential fallback.
        client.login(config.get('username') or config['sender'], password)
        return client
    except Exception:
        try:
            client.shutdown()
        except Exception:
            pass
        raise


def folders(client):
    status, data = client.list()
    if status != 'OK':
        raise ValueError('IMAP LIST 未成功，不能确定已发送文件夹。')
    result = []
    for line in data:
        if not isinstance(line, bytes):
            continue
        match = re.match(rb'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if match:
            name = match['name'].decode('ascii')
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            result.append((name, match['flags'].decode('ascii').split()))
    return result


def quoted(folder):
    return '"' + folder.replace('\\', '\\\\').replace('"', '\\"') + '"'


def locate_message(client, folder, message_id):
    if not re.fullmatch(r'<[^\s<>"\r\n]+>', message_id):
        raise ValueError('Message-ID 不正确。')
    status, _ = client.select(quoted(folder), readonly=True)
    if status != 'OK':
        raise ValueError('无法以只读方式打开已核实文件夹。')
    status, data = client.uid('search', None, 'HEADER', 'Message-ID', '"' + message_id + '"')
    if status != 'OK':
        raise ValueError('IMAP Message-ID 查询未成功。')
    return data[0].split() if data and data[0] else []


def archive_to_verified_sent(client, folder, msg):
    listed = folders(client)
    if folder not in [name for name, _ in listed]:
        raise ValueError('已发送文件夹不在本次服务器 LIST 结果中。')
    if locate_message(client, folder, msg['Message-ID']):
        return  # Already auto-saved by provider; never create a duplicate copy.
    status, _ = client.append(quoted(folder), '\\Seen', None, msg.as_bytes(policy=policy.SMTP))
    if status != 'OK':
        raise ValueError('IMAP APPEND 被拒绝。')


def inspect_received(client, message_id):
    ids = locate_message(client, 'INBOX', message_id)
    if not ids:
        return {'received': False}
    status, data = client.uid('fetch', ids[-1], '(BODY.PEEK[])')
    if status != 'OK':
        return {'received': True, 'mime_checked': False}
    raw = next((item[1] for item in data if isinstance(item, tuple)), None)
    if not raw:
        return {'received': True, 'mime_checked': False}
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    html = next((p.get_content() for p in msg.walk() if p.get_content_type() == 'text/html'), '')
    cids = {p.get('Content-ID', '').strip('<>') for p in msg.walk() if p.get_content_maintype() == 'image'}
    referenced = set(re.findall(r'cid:([^\s\"\x27>]+)', html))
    return {'received': True, 'mime_checked': True, 'html_present': bool(html),
            'cid_images_present': bool(referenced) and referenced.issubset(cids),
            'visual_check': '仍需用户目视核对正文、Logo、签名、链接及分段'}
