"""Read-only Windows volume discovery without WMI or administrator access.

SetupAPI supplies disk PnP ancestry; storage device numbers join disks to
volume GUIDs for this inventory only. Neither labels nor drive letters select
a device. Unsupported/spanned volumes cannot satisfy this join.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from uuid import UUID


class _Guid(c.Structure):
    _fields_ = [('data', c.c_ubyte * 16)]


class _Interface(c.Structure):
    _fields_ = [('cbSize', w.DWORD), ('guid', _Guid), ('flags', w.DWORD),
                ('reserved', c.c_size_t)]


class _DevInfo(c.Structure):
    _fields_ = [('cbSize', w.DWORD), ('guid', _Guid), ('devInst', w.DWORD),
                ('reserved', c.c_size_t)]


class _DeviceNumber(c.Structure):
    _fields_ = [('kind', w.DWORD), ('number', w.DWORD), ('partition', w.DWORD)]


def _function(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


class _WindowsInventory:
    def __init__(self):
        setup = c.WinDLL('setupapi', use_last_error=True)
        kernel = c.WinDLL('kernel32', use_last_error=True)
        ptr, dword, handle = c.c_void_p, w.DWORD, w.HANDLE
        self.class_devs = _function(setup, 'SetupDiGetClassDevsW', handle, ptr, w.LPCWSTR, handle, dword)
        self.enum = _function(setup, 'SetupDiEnumDeviceInterfaces', w.BOOL, handle, ptr, ptr, dword, ptr)
        self.detail = _function(setup, 'SetupDiGetDeviceInterfaceDetailW', w.BOOL, handle, ptr, ptr, dword, ptr, ptr)
        self.instance = _function(setup, 'SetupDiGetDeviceInstanceIdW', w.BOOL, handle, ptr, w.LPWSTR, dword, ptr)
        self.destroy = _function(setup, 'SetupDiDestroyDeviceInfoList', w.BOOL, handle)
        self.open = _function(kernel, 'CreateFileW', handle, w.LPCWSTR, dword, dword, ptr, dword, dword, handle)
        self.close = _function(kernel, 'CloseHandle', w.BOOL, handle)
        self.ioctl = _function(kernel, 'DeviceIoControl', w.BOOL, handle, dword, ptr, dword, ptr, dword, ptr, ptr)
        self.first = _function(kernel, 'FindFirstVolumeW', handle, w.LPWSTR, dword)
        self.next = _function(kernel, 'FindNextVolumeW', w.BOOL, handle, w.LPWSTR, dword)
        self.end = _function(kernel, 'FindVolumeClose', w.BOOL, handle)
        self.info = _function(kernel, 'GetVolumeInformationW', w.BOOL, w.LPCWSTR, w.LPWSTR, dword, ptr, ptr, ptr, w.LPWSTR, dword)
        self.paths = _function(kernel, 'GetVolumePathNamesForVolumeNameW', w.BOOL, w.LPCWSTR, w.LPWSTR, dword, ptr)
        self.invalid = c.c_void_p(-1).value

    def device_number(self, path):
        # DesiredAccess=0: metadata only, no reads/writes to disk sectors.
        handle = self.open(path, 0, 3, None, 3, 0, None)
        if handle == self.invalid:
            raise c.WinError(c.get_last_error())
        try:
            result, size = _DeviceNumber(), w.DWORD()
            if not self.ioctl(handle, 0x2D1080, None, 0, c.byref(result), c.sizeof(result), c.byref(size), None):
                raise c.WinError(c.get_last_error())
            if size.value != c.sizeof(result):
                raise OSError('Incomplete storage device number')
            return result.kind, result.number
        finally:
            self.close(handle)

    def disks(self):
        guid = _Guid.from_buffer_copy(UUID('53f56307-b6bf-11d0-94f2-00a0c91efb8b').bytes_le)
        handle = self.class_devs(c.byref(guid), None, None, 0x12)  # PRESENT | DEVICEINTERFACE
        if handle == self.invalid:
            raise c.WinError(c.get_last_error())
        try:
            index = 0
            while True:
                interface = _Interface()
                interface.cbSize = c.sizeof(interface)
                if not self.enum(handle, None, c.byref(guid), index, c.byref(interface)):
                    if c.get_last_error() == 259:  # NO_MORE_ITEMS
                        break
                    raise c.WinError(c.get_last_error())
                index += 1
                size = w.DWORD()
                self.detail(handle, c.byref(interface), None, 0, c.byref(size), None)
                if c.get_last_error() != 122 or size.value < 6:
                    raise c.WinError(c.get_last_error())
                detail = c.create_string_buffer(size.value)
                c.cast(detail, c.POINTER(w.DWORD))[0] = 8 if c.sizeof(c.c_void_p) == 8 else 6
                dev = _DevInfo()
                dev.cbSize = c.sizeof(dev)
                if not self.detail(handle, c.byref(interface), detail, size.value, None, c.byref(dev)):
                    raise c.WinError(c.get_last_error())
                instance = c.create_unicode_buffer(1024)
                if not self.instance(handle, c.byref(dev), instance, len(instance), None):
                    raise c.WinError(c.get_last_error())
                yield c.wstring_at(c.addressof(detail) + 4), instance.value
        finally:
            self.destroy(handle)

    def volumes(self):
        root = c.create_unicode_buffer(1024)
        handle = self.first(root, len(root))
        if handle == self.invalid:
            raise c.WinError(c.get_last_error())
        try:
            while True:
                yield root.value
                if not self.next(handle, root, len(root)):
                    if c.get_last_error() == 18:  # NO_MORE_FILES
                        break
                    raise c.WinError(c.get_last_error())
        finally:
            self.end(handle)

    def metadata(self, root):
        label = c.create_unicode_buffer(261)
        if not self.info(root, label, len(label), None, None, None, None, 0):
            raise c.WinError(c.get_last_error())
        size = w.DWORD()
        paths = c.create_unicode_buffer(32768)
        if not self.paths(root, paths, len(paths), c.byref(size)):
            raise c.WinError(c.get_last_error())
        return label.value, paths.value.rstrip('\\')


def volume_inventory():
    from mklink.probe_volumes import usb_ancestor
    api = _WindowsInventory()
    disks = {}
    errors = []
    for path, instance in api.disks():
        identity = usb_ancestor(instance)
        if identity is None:
            continue
        try:
            number = api.device_number(path)
        except OSError as exc:
            errors.append(str(exc))
            continue
        disks.setdefault(number, []).append((path, instance, identity))
    rows = []
    for root in api.volumes():
        try:
            number = api.device_number(root.rstrip('\\'))
        except OSError:
            continue  # Offline/optical/spanned volumes are not candidates.
        matches = disks.get(number, [])
        if len(matches) != 1:
            if matches:
                errors.append('Ambiguous storage device number')
            continue
        path, instance, identity = matches[0]
        try:
            label, drive = api.metadata(root)
            # Recheck both sides after enumeration; never reuse a cached number
            # across unplug/replug, or trust a drive-letter reassignment.
            if (api.device_number(path) != number
                    or api.device_number(root.rstrip('\\')) != number
                    or usb_ancestor(instance) != identity):
                raise OSError('USB volume changed during enumeration')
        except OSError as exc:
            errors.append(str(exc))
            continue
        rows.append({'pnp_id': instance, 'root': root, 'drive': drive,
                     'label': label, 'usb_identity': identity})
    if errors:
        raise OSError('Native USB volume inventory incomplete: ' + '; '.join(errors[:3]))
    return rows
