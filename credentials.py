"""Account-scoped Windows Credential Manager access. Never log secret values."""
import ctypes
import hashlib
import json
import os
from ctypes import wintypes


class CredentialUnavailable(RuntimeError):
    pass


class CredentialStore:
    def __init__(self):
        if os.name != 'nt':
            raise CredentialUnavailable('Windows 凭据管理器不可用；凭据仅保留在本次运行内存中。')
        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]
        self.record = Credential
        try:
            self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
            self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                           ctypes.POINTER(ctypes.POINTER(Credential))]
            self.api.CredReadW.restype = wintypes.BOOL
            self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
            self.api.CredWriteW.restype = wintypes.BOOL
            self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self.api.CredDeleteW.restype = wintypes.BOOL
            self.api.CredFree.argtypes = [ctypes.c_void_p]
            self.api.CredFree.restype = None
        except (OSError, AttributeError):
            raise CredentialUnavailable('Windows 凭据管理器不可用；凭据仅保留在本次运行内存中。') from None

    @staticmethod
    def target(config):
        identity = [str(config.get(k, '')).strip().lower() for k in ('host', 'port', 'security', 'sender')]
        identity.append((config.get('username') or config['sender']).strip().lower())
        return 'OpenDeskMail/SMTP/legacy/' + hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def read(self, config):
        pointer = ctypes.POINTER(self.record)()
        if not self.api.CredReadW(self.target(config), 1, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == 1168:
                return None
            raise CredentialUnavailable(f'Windows 凭据读取不可用（错误 {code}）；仅使用本次运行内存。')
        try:
            item = pointer.contents
            if item.UserName != (config.get('username') or config['sender']).strip():
                return None
            return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-16le')
        finally:
            self.api.CredFree(pointer)

    def write(self, config, password):
        if not password:
            raise ValueError('凭据不能为空。')
        encoded = password.encode('utf-16le')
        if len(encoded) > 2560:
            raise ValueError('凭据长度超过 Windows 凭据管理器上限。')
        buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        item = self.record()
        item.Type, item.Persist = 1, 2
        item.TargetName = self.target(config)
        item.UserName = (config.get('username') or config['sender']).strip()
        item.CredentialBlobSize = len(encoded)
        item.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        try:
            if not self.api.CredWriteW(ctypes.byref(item), 0):
                raise CredentialUnavailable(f'Windows 凭据保存不可用（错误 {ctypes.get_last_error()}）；仅使用本次运行内存。')
        finally:
            ctypes.memset(buffer, 0, len(encoded))

    def delete(self, config):
        if not self.api.CredDeleteW(self.target(config), 1, 0):
            code = ctypes.get_last_error()
            if code != 1168:
                raise CredentialUnavailable(f'Windows 凭据删除失败（错误 {code}）。')
