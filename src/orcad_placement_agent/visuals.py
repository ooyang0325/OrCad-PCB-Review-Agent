"""Capture only the bound Cadence window, bracketed by fresh native snapshots."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import binascii
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Callable
import uuid
import zlib

from .protocol import Receipt, Request
from .session import Session, write_json, write_new
from .transport import EditorWindow, TransportError, WindowsAPI


MAX_PIXELS = 16 * 1024 * 1024
MAX_PNG_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class VisualError(RuntimeError):
    """No trustworthy window-only visual observation was established."""


@dataclass(frozen=True)
class WindowImage:
    width: int
    height: int
    png: bytes


def encode_png(width: int, height: int, bgra: bytes) -> bytes:
    if (
        type(width) is not int or type(height) is not int
        or not 0 < width <= 8192 or not 0 < height <= 8192
        or width * height > MAX_PIXELS or len(bgra) != width * height * 4
    ):
        raise VisualError("Invalid or excessive image dimensions.")
    rows = bytearray()
    stride = width * 4
    for start in range(0, len(bgra), stride):
        row = bgra[start:start + stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        rows.append(0)
        rows.extend(rgb)

    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack(">I", len(content)) + kind + content
            + struct.pack(">I", binascii.crc32(kind + content) & 0xFFFFFFFF)
        )

    png = (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    if len(png) > MAX_PNG_BYTES:
        raise VisualError("Captured PNG exceeds the 8 MiB limit.")
    return png


def png_dimensions(png: bytes) -> tuple[int, int]:
    if (
        len(png) < 45 or len(png) > MAX_PNG_BYTES or not png.startswith(PNG_SIGNATURE)
        or png[8:16] != b"\x00\x00\x00\rIHDR"
        or png[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82"
    ):
        raise VisualError("Capture worker did not return a complete bounded PNG.")
    width, height = struct.unpack(">II", png[16:24])
    if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > MAX_PIXELS:
        raise VisualError("Capture worker returned invalid image dimensions.")
    return width, height


class BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
        ("planes", wintypes.WORD), ("bits", wintypes.WORD),
        ("compression", wintypes.DWORD), ("size_image", wintypes.DWORD),
        ("x_pixels", wintypes.LONG), ("y_pixels", wintypes.LONG),
        ("colors_used", wintypes.DWORD), ("colors_important", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("header", BitmapHeader), ("colors", wintypes.DWORD * 1)]


def _window_png(editor: EditorWindow) -> bytes:
    api = WindowsAPI()
    observed = api.inspect(editor.hwnd)
    if not editor.same_process(observed) or Path(observed.executable).name.lower() != "allegro.exe":
        raise VisualError("The capture target is not the exact bound Cadence process.")
    user = api.user
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsIconic.restype = wintypes.BOOL
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetClientRect.restype = wintypes.BOOL
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.ReleaseDC.restype = ctypes.c_int
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user.PrintWindow.restype = wintypes.BOOL
    user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    if not user.IsWindowVisible(editor.hwnd) or user.IsIconic(editor.hwnd):
        raise VisualError("The bound Cadence window must be visible and not minimized.")
    previous_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not previous_dpi:
        raise VisualError("Cannot establish DPI-consistent window capture.")
    dc = memory = bitmap = previous_bitmap = None
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteObject.restype = wintypes.BOOL
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.DeleteDC.restype = wintypes.BOOL
    try:
        rectangle = wintypes.RECT()
        if not user.GetClientRect(editor.hwnd, ctypes.byref(rectangle)):
            raise VisualError("Cannot read the bound window dimensions.")
        width, height = rectangle.right, rectangle.bottom
        if not 200 <= width <= 8192 or not 150 <= height <= 8192 or width * height > MAX_PIXELS:
            raise VisualError("The bound window is too small or large for trustworthy capture.")
        dc = user.GetDC(editor.hwnd)
        if not dc:
            raise VisualError("Cannot obtain the bound window's device context.")
        memory = gdi.CreateCompatibleDC(dc)
        if not memory:
            raise VisualError("Cannot create a window capture buffer.")
        info = BitmapInfo()
        info.header = BitmapHeader(
            ctypes.sizeof(BitmapHeader), width, -height, 1, 32, 0,
            width * height * 4, 0, 0, 0, 0,
        )
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise VisualError("Cannot allocate the window capture bitmap.")
        previous_bitmap = gdi.SelectObject(memory, bitmap)
        if not previous_bitmap or previous_bitmap == ctypes.c_void_p(-1).value:
            raise VisualError("Cannot select the window capture bitmap.")
        ctypes.memset(bits, 0, width * height * 4)
        # PrintWindow renders the specified client, not whatever overlaps it on
        # the desktop. There is intentionally no screen/desktop BitBlt fallback.
        if not user.PrintWindow(editor.hwnd, memory, 0x1 | 0x2):
            raise VisualError("Cadence did not render its window for capture.")
        after_rect = wintypes.RECT()
        if not user.GetClientRect(editor.hwnd, ctypes.byref(after_rect)):
            raise VisualError("Window dimensions became unavailable during capture.")
        if (after_rect.right, after_rect.bottom) != (width, height) or not editor.same_process(api.inspect(editor.hwnd)):
            raise VisualError("The capture window changed while rendering.")
        pixels = ctypes.string_at(bits, width * height * 4)
        step = max(1, width * height // 4096) * 4
        colors = {pixels[index:index + 3] for index in range(0, len(pixels), step)}
        if len(colors) < 2:
            raise VisualError("Window capture is blank or uniform; no visual success is claimed.")
        return encode_png(width, height, pixels)
    finally:
        if memory and previous_bitmap and previous_bitmap != ctypes.c_void_p(-1).value:
            gdi.SelectObject(memory, previous_bitmap)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if dc:
            user.ReleaseDC(editor.hwnd, dc)
        user.SetThreadDpiAwarenessContext(previous_dpi)


def bounded_capture(editor: EditorWindow, timeout: float = 12.0) -> WindowImage:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "orcad_placement_agent.visuals", "_capture"],
            input=json.dumps(asdict(editor)).encode("utf-8"), capture_output=True,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise VisualError("Window capture timed out; only its isolated capture worker was stopped.") from error
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise VisualError(f"Window capture failed: {message[:1000]}")
    width, height = png_dimensions(result.stdout)
    return WindowImage(width, height, result.stdout)


def fit_view(session: Session) -> str:
    editor = session.editor()
    api = WindowsAPI()
    if not editor.same_process(api.inspect(editor.hwnd)):
        raise VisualError("The bound editor changed before display-only view fitting.")
    request_id = uuid.uuid4().hex
    result_path = session.root / f"{request_id}.result.csv"
    if result_path.exists():
        raise VisualError("View-fit request identity collided with an existing result.")
    try:
        api.deliver(
            editor.hwnd, f"opa_viewfit {request_id} {session.nonce}".encode("ascii"), 5000
        )
    except TransportError as error:
        raise VisualError(f"Display-only view fit was not confirmed: {error}") from error
    deadline = time.monotonic() + 5.0
    while not result_path.is_file():
        if time.monotonic() >= deadline:
            raise VisualError("No view-fit receipt arrived; load the current trusted adapter.")
        time.sleep(0.05)
    if result_path.stat().st_size > 8192:
        raise VisualError("Invalid oversized view-fit receipt.")
    receipt = Receipt.decode(result_path.read_bytes(), session.nonce, request_id)
    if receipt.status != "snapshot" or receipt.message != "Display-only view fit completed.":
        raise VisualError(f"Native view fit was rejected: {receipt.message}")
    return request_id


def capture_observation(
    session: Session, *, capture: Callable[[EditorWindow], WindowImage] = bounded_capture,
    inspect_window: Callable[[int], EditorWindow] | None = None,
    prepare_view: Callable[[Session], str | None] = fit_view,
) -> dict[str, object]:
    editor = session.editor()
    inspect_window = inspect_window if inspect_window is not None else WindowsAPI().inspect
    if not editor.same_process(inspect_window(editor.hwnd)):
        raise VisualError("The bound editor identity changed before capture.")
    before = session.exchange(Request(session.nonce, uuid.uuid4().hex, "snapshot"))
    if before.status != "snapshot":
        raise VisualError(f"Native pre-capture inspection failed: {before.message}")
    fit_request = prepare_view(session)
    image = capture(editor)
    width, height = png_dimensions(image.png)
    if (width, height) != (image.width, image.height):
        raise VisualError("Capture dimensions disagree with the image.")
    if not editor.same_process(inspect_window(editor.hwnd)):
        raise VisualError("The bound editor changed during capture.")
    after = session.exchange(Request(session.nonce, uuid.uuid4().hex, "snapshot"))
    if after.status != "snapshot":
        raise VisualError(f"Native post-capture inspection failed: {after.message}")
    if (
        before.one("board") != after.one("board")
        or Path(after.one("board")[1]).resolve() != session.working
        or before.one("scene") != after.one("scene")
    ):
        raise VisualError("Native board state changed during capture; no observation was published.")
    observation_id = uuid.uuid4().hex
    image_path = session.root / f"visual-{observation_id}.png"
    metadata_path = session.root / f"visual-{observation_id}.json"
    observation: dict[str, object] = {
        "schema_version": 1, "kind": "pcb-visual-observation",
        "observation_id": observation_id, "before_request_id": before.request_id,
        "after_request_id": after.request_id, "scene_native": after.one("scene")[1],
        "editor": asdict(editor), "captured_at": datetime.now(timezone.utc).isoformat(),
        "width": width, "height": height,
        "view_fit_request_id": fit_request,
        "method": "Guarded display-only fit; PrintWindow client/render-full-content; no desktop fallback",
        "image_path": str(image_path), "metadata_path": str(metadata_path),
        "before_snapshot_receipt_path": str(session.root / f"{before.request_id}.receipt.json"),
        "snapshot_receipt_path": str(session.root / f"{after.request_id}.receipt.json"),
        "limitations": "Current visible layers/framing only; inspect pixels yourself. Not DRC or electrical proof.",
    }
    write_new(image_path, image.png)
    try:
        write_json(metadata_path, observation)
    except OSError:
        image_path.unlink()
        raise
    return observation


def main() -> int:
    if sys.argv[1:] != ["_capture"]:
        print("This worker is internal to bound visual inspection.", file=sys.stderr)
        return 2
    try:
        value = json.loads(sys.stdin.buffer.read(8192))
        if not isinstance(value, dict) or set(value) != {"hwnd", "pid", "started", "executable", "title"}:
            raise VisualError("Invalid capture worker identity.")
        if any(type(value[key]) is not int or value[key] <= 0 for key in ("hwnd", "pid", "started")):
            raise VisualError("Invalid capture process identifiers.")
        if any(not isinstance(value[key], str) for key in ("executable", "title")):
            raise VisualError("Invalid capture process metadata.")
        sys.stdout.buffer.write(_window_png(EditorWindow(**value)))
        return 0
    except (VisualError, TransportError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
