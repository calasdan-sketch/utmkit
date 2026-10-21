"""QR generation through an optional backend.

The core kit never depends on ``qrcode``; QR is enabled when it's installed
(``pip install utmkit[qr]``) or when a custom backend is injected.
"""
from __future__ import annotations

from typing import Callable, Optional


class QrUnavailable(RuntimeError):
    """No QR backend present."""


Backend = Callable[[str, str], None]  # (data, output_path) -> None


def default_backend() -> Optional[Backend]:
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None

    def render(data: str, out_path: str) -> None:
        img = qrcode.make(data)
        img.save(out_path)

    return render


def get_backend(injected: Optional[Backend] = None) -> Backend:
    backend = injected or default_backend()
    if backend is None:
        raise QrUnavailable(
            "QR support needs the 'qrcode' package: pip install 'utmkit[qr]' "
            "(or omit --qr)"
        )
    return backend
