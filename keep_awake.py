"""Keep Windows from going to sleep while a transcription run is working.

A laptop that idles into standby (Modern Standby on recent machines) freezes
the run until someone wakes it: a 3-hour recording once sat paused for three
and a half hours that way. A power request tells Windows the work matters;
it is dropped as soon as the run ends, and closing the lid still sleeps.
Standard library only, and a no-op outside Windows.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from ctypes import wintypes

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_POWER_REQUEST_SYSTEM_REQUIRED = 1
_POWER_REQUEST_EXECUTION_REQUIRED = 3   # Windows 8+: do not suspend this process
_CONTEXT_SIMPLE_STRING = 0x1


class _ReasonContext(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("Flags", wintypes.DWORD),
        ("SimpleReasonString", wintypes.LPWSTR),
    ]


@contextlib.contextmanager
def keep_awake(reason: str = "Transcribing audio"):
    if sys.platform != "win32":
        yield
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.PowerCreateRequest.restype = wintypes.HANDLE
    kernel32.PowerCreateRequest.argtypes = [ctypes.POINTER(_ReasonContext)]
    kernel32.PowerSetRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel32.PowerClearRequest.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    context = _ReasonContext(0, _CONTEXT_SIMPLE_STRING, reason)
    handle = kernel32.PowerCreateRequest(ctypes.byref(context))
    if handle in (None, wintypes.HANDLE(-1).value):
        handle = None
    held = []
    if handle:
        for kind in (_POWER_REQUEST_SYSTEM_REQUIRED, _POWER_REQUEST_EXECUTION_REQUIRED):
            if kernel32.PowerSetRequest(handle, kind):
                held.append(kind)
    # The older call as well: it covers machines where the request failed.
    kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        for kind in held:
            kernel32.PowerClearRequest(handle, kind)
        if handle:
            kernel32.CloseHandle(handle)
