"""Diagnose: Lehnt der Server einen Upload ab (Fehler 400/403/413), steht der genaue Grund im App-Protokoll.

Streamlit meldet im Browser nur „AxiosError … 400“; der eigentliche Grund (z. B. „Invalid session_id“) steht in
der Server-Antwort, die man sonst nicht sieht. Wird einmal pro Prozess eingehängt.
"""

from __future__ import annotations

import sys

from starlette.exceptions import HTTPException


def install() -> None:
    if getattr(HTTPException, "_upload_debug", False):
        return
    original = HTTPException.__init__

    def logged_init(self, status_code: int, detail=None, *args, **kwargs):
        if status_code in (400, 403, 413):
            print(f"[Upload-Diagnose] Server antwortet {status_code}: {detail}", file=sys.stderr, flush=True)
        original(self, status_code, detail, *args, **kwargs)

    HTTPException.__init__ = logged_init
    HTTPException._upload_debug = True
