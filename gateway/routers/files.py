"""File upload / download — compatible with narrator-ai-cli three-step upload."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from gateway.config import settings
from gateway.response import err, ok
from gateway.store import store

router = APIRouter()


@router.post("/v2/files/upload/presigned-url")
async def presigned_url(body: dict):
    file_name = body.get("file_name", "upload.bin")
    file_size = int(body.get("file_size", 0))
    content_type = body.get("content_type", "application/octet-stream")
    file_id, object_key, _path = store.register_pending_upload(file_name, file_size, content_type)
    upload_url = f"{settings.public_url.rstrip('/')}/internal/upload/{file_id}"
    return ok({"file_id": file_id, "upload_url": upload_url, "object_key": object_key})


@router.put("/internal/upload/{file_id}")
async def internal_upload(file_id: str, request: Request):
    data = await request.body()
    rec = store.get_file(file_id)
    if not rec:
        return err(10007, "File not found")
    rec.path.write_bytes(data)
    return Response(status_code=200)


@router.post("/v2/files/upload/callback")
def upload_callback(body: dict):
    file_id = body.get("file_id", "")
    file_size = int(body.get("file_size", 0))
    rec = store.finalize_upload(file_id, file_size)
    if not rec:
        return err(10001, "Upload callback failed")
    return ok({"file_id": file_id, "status": "success"})


@router.post("/v2/files/download/presigned-url")
def download_presigned(body: dict):
    file_id = body.get("file_id", "")
    rec = store.get_file(file_id)
    if not rec or not rec.path.exists():
        return err(10007, "File not found")
    url = f"{settings.public_url.rstrip('/')}/media/{file_id}"
    return ok({"file_id": file_id, "file_name": rec.file_name, "download_url": url, "expires_in": 3600})


@router.get("/media/{file_id}")
def serve_media(file_id: str):
    rec = store.get_file(file_id)
    if not rec or not rec.path.exists():
        return err(10007, "File not found")
    return FileResponse(rec.path, filename=rec.file_name, media_type=rec.content_type)


@router.get("/v2/files/list")
def list_files(
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
    order_by: str = "completed_time",
    order: str = "desc",
):
    data = store.list_files(page=page, page_size=page_size, search=search)
    return ok(data)


@router.get("/v2/files/get_file_information")
def file_info(file_id: str):
    rec = store.get_file(file_id)
    if not rec:
        return err(10007, "File not found")
    return ok(
        {
            "file_id": rec.file_id,
            "file_name": rec.file_name,
            "file_size": rec.file_size,
            "category": rec.category,
            "content_type": rec.content_type,
            "object_key": rec.object_key,
            "created_at": rec.created_at,
            "status": "ready",
        }
    )


@router.get("/v2/files/user/storage_usage")
def storage_usage():
    files = list(store._files.values())  # noqa: SLF001
    used = sum(f.file_size for f in files if f.path.exists())
    max_size = 3 * 1024 * 1024 * 1024
    return ok(
        {
            "used_size": used,
            "max_size": max_size,
            "file_count": len(files),
            "usage_percentage": round(used / max_size * 100, 2) if max_size else 0,
        }
    )


@router.delete("/v2/files/user/files/{file_id}")
def delete_file(file_id: str):
    rec = store.get_file(file_id)
    if rec and rec.path.exists():
        rec.path.unlink(missing_ok=True)
    return ok({"status": "deleted", "file_id": file_id})


@router.post("/v2/files/upload")
def transfer_by_link(body: dict):
    return ok(
        {
            "upload_id": body.get("link", "")[:16],
            "file_name": "",
            "file_size": 0,
            "link_type": body.get("type", "url"),
            "error_info": "Link transfer not implemented in gateway; use file upload instead.",
        }
    )
