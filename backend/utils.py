import os
import asyncio
import threading
import urllib.request
import urllib.error
import decky

import fetch

# How long a single read may go without receiving any data before we treat the
# transfer as stalled and reconnect (an inactivity timeout, not a total-time cap —
# a slow-but-progressing download won't trip it).
_STALL_TIMEOUT_SECONDS = 30
# Consecutive reconnect attempts that make zero new progress before we give up.
# As long as the download keeps advancing, the counter resets, so a slow link can
# resume through many stalls and still finish.
_MAX_STALLS = 8

# Shared cancel flag for all installs
_cancel_event = threading.Event()


def cancel_install() -> None:
    """Signal any in-progress install to cancel."""
    _cancel_event.set()


async def _report_queue_progress(percent: int) -> None:
    """Mirror download progress to the background download queue, if a job is active.
    Imported lazily so utils has no import-time dependency on download_queue (which imports
    utils), and a no-op when nothing is queued."""
    try:
        import download_queue
        await download_queue.report_progress(percent)
    except Exception:
        pass


class InstallCancelledError(Exception):
    pass


async def download(url: str, dest: str, appid: int) -> None:
    """
    Download a URL to a file with progress reporting and cancellation support.
    Emits 'install_progress' events (0-100) to the frontend.

    Resilient to slow / intermittently-stalling links: a read that goes silent for
    _STALL_TIMEOUT_SECONDS reconnects and resumes from where it left off using an HTTP
    Range request, appending to the same file rather than restarting. It keeps resuming
    as long as progress is being made, and only fails after _MAX_STALLS consecutive
    reconnects with zero new bytes. Servers that ignore Range (respond 200 instead of
    206) are handled by restarting the file from scratch.

    Raises InstallCancelledError if cancelled, or Exception if the download truly stalls.
    """
    _cancel_event.clear()
    ctx = fetch.ssl_context()
    chunk_size = 65536  # 64KB chunks
    loop = asyncio.get_event_loop()

    # Start clean — callers pass a fresh temp path, but guard against a leftover.
    if os.path.exists(dest):
        os.remove(dest)

    downloaded = 0
    total = 0
    last_percent = -1
    stalls = 0

    while True:
        if _cancel_event.is_set():
            raise InstallCancelledError("Installation cancelled by user")

        progress_before = downloaded
        headers = {"User-Agent": fetch.USER_AGENT}
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"
        req = urllib.request.Request(url, headers=headers)

        def _open():
            return urllib.request.urlopen(req, context=ctx, timeout=_STALL_TIMEOUT_SECONDS)

        response = None
        try:
            response = await loop.run_in_executor(None, _open)

            # If we asked to resume but the server sent the whole file (200, not 206),
            # it ignored Range — restart from byte 0 and truncate what we had.
            resuming = downloaded > 0 and getattr(response, "status", 200) == 206
            if downloaded > 0 and not resuming:
                downloaded = 0

            if resuming:
                # Content-Range: "bytes <start>-<end>/<total>"
                cr = response.headers.get("Content-Range", "")
                if "/" in cr:
                    try:
                        total = int(cr.rsplit("/", 1)[1])
                    except ValueError:
                        pass
            else:
                cl = response.headers.get("Content-Length")
                total = int(cl) if cl else 0

            with open(dest, "ab" if resuming else "wb") as f:
                while True:
                    if _cancel_event.is_set():
                        raise InstallCancelledError("Installation cancelled by user")
                    chunk = await loop.run_in_executor(None, response.read, chunk_size)
                    if not chunk:
                        # Clean EOF — done if we have the whole file (or size unknown).
                        if total and downloaded < total:
                            break  # premature close; fall through to resume
                        await decky.emit("install_progress", appid, 100)
                        await _report_queue_progress(100)
                        return
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        percent = int(downloaded * 100 / total)
                        if percent != last_percent:
                            last_percent = percent
                            await decky.emit("install_progress", appid, percent)
                            await _report_queue_progress(percent)
                    await asyncio.sleep(0)  # yield to the event loop
        except InstallCancelledError:
            raise
        except Exception as e:
            # Stalled read, dropped connection, timeout — reconnect and resume below.
            decky.logger.warning(f"Download interrupted at {downloaded} bytes: {e}")
        finally:
            if response is not None:
                response.close()

        # Decide whether to keep going: reset the stall counter whenever we advanced.
        if downloaded > progress_before:
            stalls = 0
        else:
            stalls += 1
            if stalls >= _MAX_STALLS:
                raise Exception(
                    f"Download stalled: no progress after {_MAX_STALLS} reconnect attempts "
                    f"({downloaded} bytes received)"
                )
            await asyncio.sleep(min(2 ** stalls, 10))  # backoff before retrying