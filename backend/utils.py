import os
import ssl
import asyncio
import threading
import urllib.request
import decky

_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

# Shared cancel flag for all installs
_cancel_event = threading.Event()


def cancel_install() -> None:
    """Signal any in-progress install to cancel."""
    _cancel_event.set()


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    return ctx


class InstallCancelledError(Exception):
    pass


async def download(url: str, dest: str, appid: int) -> None:
    """
    Download a URL to a file with progress reporting and cancellation support.
    Emits 'install_progress' events (0-100) to the frontend.
    Raises Exception if cancelled.
    """
    _cancel_event.clear()
    ctx = _make_ssl_context()
    chunk_size = 65536  # 64KB chunks
    req = urllib.request.Request(url, headers={"User-Agent": "DeckyModManager/1.0"})

    # Run the blocking urlopen in a thread executor so we don't block the event loop
    loop = asyncio.get_event_loop()

    def _open():
        return urllib.request.urlopen(req, context=ctx, timeout=30)

    response = await loop.run_in_executor(None, _open)

    try:
        total = int(response.headers.get('Content-Length', 0))
        downloaded = 0
        with open(dest, 'wb') as f:
            while True:
                if _cancel_event.is_set():
                    raise InstallCancelledError("Installation cancelled by user")

                # Read chunk in executor to avoid blocking
                chunk = await loop.run_in_executor(None, response.read, chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if total > 0:
                    percent = int(downloaded * 100 / total)
                    await decky.emit('install_progress', appid, percent)
                    # Yield control so the event loop can process other tasks
                    await asyncio.sleep(0)
    finally:
        response.close()