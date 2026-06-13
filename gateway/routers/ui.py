"""Web UI routes — styled console for CLI-equivalent operations."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
WEB = Path(__file__).resolve().parents[1] / "web"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

router = APIRouter(tags=["ui"])


def _resources():
    try:
        from narrator_ai.commands.bgm import BGM_LIST
        from narrator_ai.commands.dubbing import DUBBING_LIST
        from narrator_ai.commands.task import NARRATION_TEMPLATES

        return {"bgm": BGM_LIST, "dubbing": DUBBING_LIST, "templates": NARRATION_TEMPLATES}
    except ImportError:
        return {"bgm": [], "dubbing": [], "templates": []}


@router.get("/ui", response_class=HTMLResponse)
@router.get("/ui/", response_class=HTMLResponse)
def ui_index():
    return FileResponse(WEB / "index.html")


@router.get("/ui/static/{path:path}")
def ui_static(path: str):
    target = WEB / "static" / path
    if not target.exists() or not target.is_file():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(target)


@router.get("/ui/api/resources")
def ui_resources():
    from gateway.response import ok

    return ok(_resources())


@router.get("/")
def root_redirect():
    return HTMLResponse(
        '<!DOCTYPE html><html><head>'
        '<meta http-equiv="refresh" content="0;url=/ui">'
        '<script>location.href="/ui"</script></head>'
        '<body>Redirecting to <a href="/ui">Narrator Console</a>...</body></html>'
    )
