"""Inspect actual wire MIME, without silently decoding invalid CID headers."""
import hashlib
import html
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import unquote


def inspect_inline_mime(raw, expected_images=()):
    message=BytesParser(policy=policy.default).parsebytes(raw)
    errors=[]
    images=[]
    related=[]
    html_parts=[]
    nodes=[]
    def visit(part, parents):
        nodes.append((part, parents))
        if part.is_multipart():
            for child in part.iter_parts():
                visit(child, parents+[part])
    visit(message, [])
    identifiers={}
    for part, _ in nodes:
        raw_cid=next((value for key,value in part.raw_items() if key.lower()=='content-id'),None)
        if raw_cid is not None:
            cid=re.sub(r'\r?\n[ \t]+',' ',raw_cid).strip()
            if '=?' in cid or not re.fullmatch(r'<[^\s<>]+@[^\s<>]+>',cid):
                errors.append('invalid_wire_content_id')
            else:
                bare=cid[1:-1]
                if bare in identifiers:
                    errors.append('duplicate_content_id')
                identifiers[bare]=part
    for part, parents in nodes:
        if part.get_content_type()=='multipart/related':
            children=list(part.iter_parts())
            start=part.get_param('start')
            root=next((p for p in children if str(p.get('Content-ID',''))==start),None) if start else (children[0] if children else None)
            root_ok=root is not None and root.get_content_type()=='text/html'
            if not root_ok:
                errors.append('related_html_root_not_found')
            if part.get_param('type')!='text/html':
                errors.append('related_type_missing_or_wrong')
            related.append({'type':part.get_param('type'),'start':start,'html_root_found':root_ok,
                            'children':[p.get_content_type() for p in children]})
        if part.get_content_maintype()=='image':
            data=part.get_payload(decode=True) or b''
            cid=str(part.get('Content-ID','')).strip().strip('<>')
            item={'content_id':cid,'content_type':part.get_content_type(),
                  'disposition':part.get_content_disposition(),'encoding':part.get('Content-Transfer-Encoding'),
                  'filename':part.get_filename(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            images.append(item)
            if item['disposition']!='inline':
                errors.append('image_not_inline')
            if str(item['encoding']).lower()!='base64':
                errors.append('image_not_base64')
            if part.get_content_type()=='image/jpeg' and not data.startswith(b'\xff\xd8\xff'):
                errors.append('jpeg_bytes_type_mismatch')
            if part.get_content_type()=='image/png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                errors.append('png_bytes_type_mismatch')
            if not any(parent.get_content_type()=='multipart/related' for parent in parents):
                errors.append('image_outside_related')
        if part.get_content_type()=='text/html':
            markup=part.get_content()
            refs={unquote(html.unescape(value)) for value in re.findall(r'cid:([^\s\"\x27>\)]+)',markup,re.I)}
            nearest=next((parent for parent in reversed(parents) if parent.get_content_type()=='multipart/related'),None)
            local_nodes=list(nearest.walk()) if nearest else []
            linked=bool(refs) and all(ref in identifiers and any(p is identifiers[ref] for p in local_nodes) for ref in refs)
            if not linked:
                errors.append('html_cid_not_linked_in_same_related')
            if re.search(r'file\s*:|(?:src|background)\s*=\s*[\"\x27][A-Za-z]:[\\/]',markup,re.I):
                errors.append('local_image_path_in_html')
            html_parts.append({'cid_references':sorted(refs),'all_linked_in_related':linked,
                               'local_file_reference':bool(re.search(r'file\s*:',markup,re.I))})
    expected={hashlib.sha256(data).hexdigest() for data in expected_images}
    hashes={item['sha256'] for item in images}
    originals=bool(expected) and expected.issubset(hashes)
    if expected and not originals:
        errors.append('original_image_bytes_missing_or_changed')
    if not images or not html_parts:
        errors.append('missing_html_or_image')
    return {'valid':not errors,'errors':sorted(set(errors)),
            'mime_types':[p.get_content_type() for p,_ in nodes],
            'related':related,'html_parts':html_parts,'images':images,
            'original_image_bytes_preserved':originals}


def require_valid_inline_mime(raw, expected_images=()):
    result=inspect_inline_mime(raw,expected_images)
    if not result['valid']:
        raise ValueError('HTML签名邮件MIME校验未通过：'+', '.join(result['errors']))
    return result
