from dataclasses import replace
import ctypes
from ctypes import wintypes
import sys
import unittest
import uuid

from orcad_placement_agent.transport import (
    CommandTransport, CopyData, EditorWindow, IndeterminateDelivery, TransportError, WindowsAPI,
)


EDITOR = EditorWindow(1234, 555, 987654321, r"C:\Cadence\tools\bin\allegro.exe", "Board")
REQUEST_ID = "a" * 32


class FakeWindows:
    def __init__(self) -> None:
        self.current = EDITOR
        self.sent = []
        self.fail = False

    def inspect(self, hwnd):
        if self.current is None:
            raise TransportError("Window closed")
        return self.current

    def deliver(self, hwnd, payload, timeout_ms):
        self.sent.append((hwnd, payload, timeout_ms))
        if self.fail:
            raise IndeterminateDelivery("Timeout")


class TransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeWindows()
        self.transport = CommandTransport(self.api)

    def test_only_fixed_command_and_id_are_sent(self) -> None:
        self.transport.send(EDITOR, "opa_snapshot", REQUEST_ID)
        self.assertEqual(
            self.api.sent, [(1234, b"opa_snapshot " + b"a" * 32, 5000)]
        )

    def test_arbitrary_commands_and_injected_ids_are_rejected(self) -> None:
        for command, identifier in [
            ("skill", REQUEST_ID),
            ("opa_apply\nskill", REQUEST_ID),
            ("opa_apply", "../board"),
            ("opa_apply", REQUEST_ID + "\n"),
            ("opa_apply", "A" * 32),
        ]:
            with self.subTest(command=command, identifier=identifier):
                with self.assertRaises(TransportError):
                    self.transport.send(EDITOR, command, identifier)
        self.assertEqual(self.api.sent, [])

    def test_pid_and_creation_time_prevent_handle_reuse(self) -> None:
        for different in [
            replace(EDITOR, pid=666), replace(EDITOR, started=1),
            replace(EDITOR, executable=r"C:\elsewhere\allegro.exe"),
        ]:
            self.api.current = different
            with self.assertRaises(TransportError):
                self.transport.send(EDITOR, "opa_apply", REQUEST_ID)
        self.assertEqual(self.api.sent, [])

    def test_title_may_change_without_changing_identity(self) -> None:
        self.api.current = replace(EDITOR, title="Changed title")
        self.transport.send(EDITOR, "opa_snapshot", REQUEST_ID)
        self.assertEqual(len(self.api.sent), 1)

    def test_preexisting_other_application_cannot_be_targeted(self) -> None:
        self.api.current = replace(EDITOR, executable=r"C:\Cadence\unison.exe")
        with self.assertRaises(TransportError):
            self.transport.send(self.api.current, "opa_snapshot", REQUEST_ID)

    def test_timeout_is_indeterminate_and_not_retried(self) -> None:
        self.api.fail = True
        with self.assertRaises(IndeterminateDelivery):
            self.transport.send(EDITOR, "opa_apply", REQUEST_ID)
        self.assertEqual(len(self.api.sent), 1)

    def test_invalid_timeouts_are_rejected_before_dispatch(self) -> None:
        for timeout in [0, -1, 30001, 1.5, True]:
            with self.subTest(timeout=timeout):
                with self.assertRaises(TransportError):
                    self.transport.send(EDITOR, "opa_apply", REQUEST_ID, timeout)
        self.assertEqual(self.api.sent, [])


@unittest.skipUnless(sys.platform == "win32", "Native Windows message ABI test")
class NativeMessageTests(unittest.TestCase):
    def setUp(self):
        self.api = WindowsAPI()
        self.received = []
        self.callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM,
        )

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT), ("callback", self.callback_type),
                ("class_extra", ctypes.c_int), ("window_extra", ctypes.c_int),
                ("instance", wintypes.HINSTANCE), ("icon", wintypes.HANDLE),
                ("cursor", wintypes.HANDLE), ("background", wintypes.HANDLE),
                ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR),
            ]

        user = self.api.user
        user.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user.DefWindowProcW.restype = ctypes.c_ssize_t

        @self.callback_type
        def receive(hwnd, message, wparam, lparam):
            if message == 0x004A:
                data = ctypes.cast(lparam, ctypes.POINTER(CopyData)).contents
                self.received.append(
                    (data.dwData, ctypes.string_at(data.lpData, data.cbData))
                )
                return 1
            return user.DefWindowProcW(hwnd, message, wparam, lparam)

        self.callback = receive
        self.name = "OPATest" + uuid.uuid4().hex
        self.api.kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.api.kernel.GetModuleHandleW.restype = wintypes.HMODULE
        self.instance = self.api.kernel.GetModuleHandleW(None)
        descriptor = WindowClass(
            0, self.callback, 0, 0, self.instance, None, None, None, None, self.name
        )
        user.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user.RegisterClassW.restype = wintypes.ATOM
        user.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user.UnregisterClassW.restype = wintypes.BOOL
        user.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
        ]
        user.CreateWindowExW.restype = wintypes.HWND
        user.DestroyWindow.argtypes = [wintypes.HWND]
        user.DestroyWindow.restype = wintypes.BOOL
        self.assertTrue(user.RegisterClassW(ctypes.byref(descriptor)))
        self.addCleanup(user.UnregisterClassW, self.name, self.instance)
        self.hwnd = user.CreateWindowExW(
            0, self.name, "Own hidden test receiver", 0,
            0, 0, 1, 1, None, None, self.instance, None,
        )
        self.assertTrue(self.hwnd)
        self.addCleanup(user.DestroyWindow, self.hwnd)

    def test_null_terminated_copydata_reaches_own_window(self):
        self.api.deliver(self.hwnd, b"opa_snapshot " + b"a" * 32, 1000)
        self.assertEqual(
            self.received,
            [(0x26297811, b"opa_snapshot " + b"a" * 32 + b"\x00")],
        )

    def test_inspection_binds_real_process_creation_time(self):
        editor = self.api.inspect(self.hwnd)
        self.assertEqual(editor.hwnd, self.hwnd)
        self.assertGreater(editor.pid, 0)
        self.assertGreater(editor.started, 0)
        self.assertTrue(editor.executable)
        self.assertEqual(editor.title, "Own hidden test receiver")


if __name__ == "__main__":
    unittest.main()
