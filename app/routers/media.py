import asyncio
import time
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from fastapi.responses import JSONResponse

from app.config import settings
from app.dailylogger import daily_logger
from app.database import (
    add_to_media_library,
    update_generated_media_by_task,
    get_media_library,
    delete_media_library_item,
    get_media_library_stats,
)
from app.oss_client import (
    get_public_url,
    upload_file_to_bucket,
    delete_file,
)
from app.thumbnail_utils import (
    get_image_dimensions,
    generate_image_thumbnail,
    get_video_info,
    extract_video_thumbnail,
)

router = APIRouter()
logger = daily_logger.get_logger()

_LOCAL_USER = "local_user"


@router.get("/api/media/library")
async def get_media_lib(
    user_id: Optional[str] = None,
    file_type: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取媒体库列表
    - file_type: 可选过滤，'image' / 'video' / 'audio'
    - source_type: 可选过滤，'uploaded' / 'generated'
    """
    try:
        media_items = await get_media_library(_LOCAL_USER, file_type, source_type, limit, offset)

        # OSS 公开读 Bucket，直接生成公开 URL，无需签名
        for item in media_items:
            if item.get("storage_path"):
                item["signed_url"] = get_public_url(item["storage_path"])
            if item.get("thumbnail_path"):
                item["thumbnail_signed_url"] = get_public_url(item["thumbnail_path"])

        return {
            "media": media_items,
            "has_more": len(media_items) >= limit,
            "count": len(media_items),
        }
    except Exception as e:
        logger.exception(f"获取媒体库失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取媒体库失败: {str(e)}")


@router.get("/api/media/library/mentions")
async def get_media_mentions(
    user_id: Optional[str] = None,
    limit: int = 10,
):
    """轻量级端点：仅供 @ mention 使用"""
    try:
        media_items = await get_media_library(_LOCAL_USER, None, None, min(limit, 20), 0)

        signed_items = []
        for item in media_items:
            result = {
                "id": item.get("id"),
                "name": item.get("name"),
                "file_type": item.get("file_type"),
                "storage_path": item.get("storage_path"),
                "signed_url": get_public_url(item["storage_path"]) if item.get("storage_path") else None,
                "thumbnail_signed_url": get_public_url(item["thumbnail_path"]) if item.get("thumbnail_path") else None,
            }
            signed_items.append(result)

        return {"items": signed_items}
    except Exception as e:
        logger.exception(f"获取提及列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取提及列表失败: {str(e)}")


@router.get("/api/media/library/stats")
async def get_media_stats(user_id: Optional[str] = None):
    """获取媒体库统计信息"""
    try:
        stats = await get_media_library_stats(_LOCAL_USER)
        return stats
    except Exception as e:
        logger.error(f"获取媒体库统计失败: error={e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.delete("/api/media/{item_id}")
async def delete_media(item_id: str, user_id: Optional[str] = None):
    """删除媒体库中的项"""
    try:
        media = await delete_media_library_item(item_id, _LOCAL_USER)
        if not media:
            raise HTTPException(status_code=404, detail="媒体不存在")

        # 删除物理文件（识别并处理 OSS 或本地）
        storage_path = media.get("storage_path")
        if storage_path:
            try:
                await delete_file(storage_path)
            except Exception as e:
                logger.warning("删除物理文件失败: path=%s, error=%s", storage_path, e)
 
        thumbnail_path = media.get("thumbnail_path")
        if thumbnail_path and thumbnail_path != storage_path:
            try:
                await delete_file(thumbnail_path)
            except Exception as e:
                logger.warning("删除缩略图文件失败: path=%s, error=%s", thumbnail_path, e)

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除媒体库项失败: item_id={item_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post("/api/upload")
async def api_upload_file(
    file: UploadFile = File(...),
    file_path: str = Form(...),
):
    """接收前端上传的文件并转存到 OSS"""
    try:
        file_data = await file.read()
        await upload_file_to_bucket(None, file_path, file_data, file.content_type)
        return {"success": True, "path": file_path}
    except Exception as e:
        logger.error(f"上传文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))