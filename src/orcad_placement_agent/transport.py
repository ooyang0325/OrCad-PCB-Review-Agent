"""Bounded command delivery to an explicitly identified Windows editor."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath
import re
import sys
from typing import Protocol


class TransportError(RuntimeError):
    """A command could not be delivered to the expected editor."""


class IndeterminateDelivery(TransportError):
    """The caller must reconcile; a timeout does not mean nothing happened."""


@dataclass(frozen=True)
class EditorWindow:
    hwnd: int
    pid: int
    started: int
    executable: str
    title: str

    def same_process(self, other: "EditorWindow") -> bool:
        return (
            self.hwnd == other.hwnd
            and self.pid == other.pid
            and self.started == other.started
            and PureWindowsPath(self.executable) == PureWindowsPath(other.executable)
        )


class WindowAPI(Protocol):
    def inspect(self, hwnd: int) -> EditorWindow: ...

    def deliver(self, hwnd: int, payload: bytes, timeout_ms: int) -> None: ...


class CopyData(ctypes.Structure):
    _fields_ = [
        ("dwData", ctypes.c_size_t),
        ("cbData", wintypes.DWORD),
        ("lpData", ctypes.c_void_p),
    ]


class WindowsAPI:
    """No process termination, shared-state changes, or arbitrary window selection."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise TransportError("Live command dispatch requires Windows.")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindow.restype = wintypes.BOOL
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetWindowTextW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
        ]
        self.user.GetWindowTextW.restype = ctypes.c_int
        self.user.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        self.user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        self.kernel.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        ]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)
        ]
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)
        ]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL

    def inspect(self, hwnd: int) -> EditorWindow:
        if not self.user.IsWindow(hwnd):
            raise TransportError("The selected editor window no longer exists.")
        pid = wintypes.DWORD()
        if not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            raise TransportError("Cannot identify the selected window's process.")
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            raise TransportError(
                f"Cannot inspect process {pid.value}: Windows error "
                f"{ctypes.get_last_error()}."
            )
        try:
            exit_code = wintypes.DWORD()
            if not self.kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise TransportError("Cannot read the selected process state.")
            if exit_code.value != 259:
                raise TransportError("The selected editor process has exited.")
            path = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(path))
            if not self.kernel.QueryFullProcessImageNameW(
                handle, 0, path, ctypes.byref(length)
            ):
                raise TransportError("Cannot read the selected process executable.")
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(
                handle, *(ctypes.byref(value) for value in times)
            ):
                raise TransportError("Cannot identify the editor's creation time.")
            started = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            self.kernel.CloseHandle(handle)
        title = ctypes.create_unicode_buffer(2048)
        self.user.GetWindowTextW(hwnd, title, len(title))
        return EditorWindow(hwnd, pid.value, started, path.value, title.value)

    def windows(self) -> list[EditorWindow]:
        handles: list[int] = []

        @self.callback_type
        def collect(hwnd: int, _unused: int) -> bool:
            if self.user.IsWindowVisible(hwnd):
                handles.append(hwnd)
            return True

        if not self.user.EnumWindows(collect, 0):
            raise TransportError("Windows enumeration failed.")
        windows = []
        for hwnd in handles:
            try:
                candidate = self.inspect(hwnd)
            except TransportError:
                # Unrelated/inaccessible windows and windows that closed during
                # enumeration are not candidates. Explicit attachment is strict.
                continue
            if PureWindowsPath(candidate.executable).name.lower() == "allegro.exe":
                windows.append(candidate)
        return windows

    def deliver(self, hwnd: int, payload: bytes, timeout_ms: int) -> None:
        buffer = ctypes.create_string_buffer(payload)
        message = CopyData(0x26297811, len(buffer), ctypes.cast(buffer, ctypes.c_void_p))
        receiver_result = ctypes.c_size_t()
        ctypes.set_last_error(0)
        delivered = self.user.SendMessageTimeoutW(
            hwnd, 0x004A, 0, ctypes.addressof(message),
            0x0002 | 0x0020, timeout_ms, ctypes.byref(receiver_result),
        )
        if not delivered:
            raise IndeterminateDelivery(
                "Windows command dispatch did not complete "
                f"(error {ctypes.get_last_error()}); do not retry a mutation."
            )
        # Neither a delivered message nor its receiver result is a board receipt.


class CommandTransport:
    COMMANDS = frozenset({"opa_snapshot", "opa_apply", "opa_save"})

    def __init__(self, api: WindowAPI | None = None) -> None:
        self.api = api if api is not None else WindowsAPI()

    def send(
        self, editor: EditorWindow, command: str, request_id: str,
        timeout_ms: int = 5000,
    ) -> None:
        if command not in self.COMMANDS:
            raise TransportError("Only registered placement-adapter commands are allowed.")
        if re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
            raise TransportError("Request IDs must be 32 lowercase hexadecimal digits.")
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 30000:
            raise TransportError("Dispatch timeout must be 1 to 30000 milliseconds.")
        observed = self.api.inspect(editor.hwnd)
        if not editor.same_process(observed):
            raise TransportError("The selected editor identity changed; attach again.")
        if PureWindowsPath(observed.executable).name.lower() != "allegro.exe":
            raise TransportError("The selected process is not classic PCB Editor.")
        self.api.deliver(
            editor.hwnd, f"{command} {request_id}".encode("ascii"), timeout_ms
        )
