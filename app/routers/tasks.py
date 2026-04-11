import asyncio
import time
import json
import os
import tempfile
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.dailylogger import daily_logger
from app.volcano_api import volcano_api, VolcanoAPIError, VolcanoGatewayError
from app.database import (
    create_task_record,
    update_task_status,
    get_task,
    get_user_tasks,
    count_active_tasks_by_model,
    create_conversation,
    get_user_conversations,
    get_conversation,
    update_conversation,
    delete_conversation,
    save_chat_message,
    get_conversation_messages,
    update_chat_message,
    get_user_statistics,
    add_to_media_library,
    update_generated_media_by_task,
    get_media_library,
    delete_media_library_item,
    get_media_library_stats,
)
from app.oss_client import (
    create_signed_url,
    get_public_url,
    upload_file,
    upload_file_to_bucket,
    download_file_from_bucket,
    save_local_file,
)
from app.thumbnail_utils import (
    get_image_dimensions,
    generate_image_thumbnail,
    get_video_info,
    ensure_min_image_size,
    extract_video_thumbnail,
)
from app.schemas import (
    CreateTaskRequest,
    CreateConversationRequest,
    SaveMessageRequest,
    UpdateConversationRequest,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/template")
logger = daily_logger.get_logger()

_LOCAL_USER = "local_user"


@router.post("/api/create_task")
async def create_task(req: CreateTaskRequest):
    """
    创建视频生成任务

    流程:
    1. 为上传的文件获取 OSS 公开链接
    2. 调用火山引擎 API 创建任务
    3. 在 SQLite 数据库中记录任务信息
    """
    logger.info(
        "[创建任务] 模型: %s, 提示词: %s...",
        req.model,
        (req.prompt or "N/A")[:50],
    )
    logger.info("创建任务原始 Payload: %s", req.model_dump_json())

    # 获取模型配置
    model_config = settings.MODELS.get(req.model)
    if not model_config:
        raise HTTPException(status_code=400, detail=f"不支持的模型: {req.model}")

    if not model_config["available"]:
        raise HTTPException(
            status_code=400,
            detail=f"模型 {model_config['name']} 暂未开放 API 调用",
        )

    model_id = model_config["id"]

    # 检查全局并发上限
    concurrency_limit = settings.MODEL_CONCURRENCY_LIMITS.get(req.model, 0)
    if concurrency_limit > 0:
        active_count = await count_active_tasks_by_model(model_id)
        if active_count >= concurrency_limit:
            raise HTTPException(
                status_code=429,
                detail=f"当前模型队列已满，处理中任务已达上限（{active_count}/{concurrency_limit}），请稍后再试。",
            )

    # 为上传的文件获取 OSS 链接
    first_frame_url = None
    last_frame_url = None
    reference_image_url = None
    reference_video_url = None
    reference_audio_url = None
    reference_inputs = []

    try:
        if req.first_frame_path:
            first_frame_url = await create_signed_url(req.first_frame_path)
        if req.last_frame_path:
            last_frame_url = await create_signed_url(req.last_frame_path)

        if req.reference_inputs:
            for idx, ref in enumerate(req.reference_inputs):
                ref_type = (ref or {}).get("type")
                storage_path = (ref or {}).get("storage_path")
                media_type = (ref or {}).get("media_type")
                if ref_type not in ("reference_image", "reference_video", "reference_audio"):
                    logger.warning(
                        "[校验失败] reference_inputs[%d] type 非法: %s. 完整列表: %s",
                        idx, ref_type, json.dumps(req.reference_inputs, ensure_ascii=False),
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"reference_inputs[{idx}] type 非法: {ref_type}",
                    )
                if not storage_path:
                    raise HTTPException(
                        status_code=400,
                        detail=f"reference_inputs[{idx}] storage_path 不能为空",
                    )
                signed_url = await create_signed_url(storage_path)
                reference_inputs.append(
                    {
                        "type": ref_type,
                        "storage_path": storage_path,
                        "media_type": media_type,
                        "url": signed_url,
                    }
                )

        # 兼容旧字段
        if not reference_inputs:
            if req.reference_image_path:
                reference_image_url = await create_signed_url(req.reference_image_path)
                reference_inputs.append(
                    {
                        "type": "reference_image",
                        "storage_path": req.reference_image_path,
                        "url": reference_image_url,
                    }
                )
            if req.reference_video_path:
                reference_video_url = await create_signed_url(req.reference_video_path)
                reference_inputs.append(
                    {
                        "type": "reference_video",
                        "storage_path": req.reference_video_path,
                        "url": reference_video_url,
                    }
                )
            if req.reference_audio_path:
                reference_audio_url_compat = await create_signed_url(req.reference_audio_path)
                reference_inputs.append(
                    {
                        "type": "reference_audio",
                        "storage_path": req.reference_audio_path,
                        "url": reference_audio_url_compat,
                    }
                )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件链接失败: {str(e)}")

    # 将上传图片写入媒体库
    upload_media_items = []
    if req.first_frame_path:
        upload_media_items.append(("first_frame", req.first_frame_path, "image"))
    if req.last_frame_path:
        upload_media_items.append(("last_frame", req.last_frame_path, "image"))

    seen_ref_paths = set()
    for ref in reference_inputs:
        if ref.get("type") == "reference_image" and ref.get("storage_path"):
            sp = ref["storage_path"]
            if sp not in seen_ref_paths:
                upload_media_items.append(("reference_image", sp, "image"))
                seen_ref_paths.add(sp)
        if ref.get("type") == "reference_video" and ref.get("storage_path"):
            sp = ref["storage_path"]
            if sp not in seen_ref_paths:
                upload_media_items.append(("reference_video", sp, "video"))
                seen_ref_paths.add(sp)

    # 音频写入媒体库
    seen_ref_audio_paths = set()
    for ref in reference_inputs:
        if ref.get("type") == "reference_audio" and ref.get("storage_path"):
            audio_path = ref["storage_path"]
            if audio_path not in seen_ref_audio_paths:
                seen_ref_audio_paths.add(audio_path)
                try:
                    audio_bytes = await download_file_from_bucket(settings.STORAGE_BUCKET, audio_path)
                    filename = audio_path.split("/")[-1] if "/" in audio_path else audio_path
                    await add_to_media_library(
                        user_id=_LOCAL_USER,
                        name=filename,
                        file_type="audio",
                        storage_path=audio_path,
                        source_type="uploaded",
                        media_type=ref.get("media_type") or "audio/mpeg",
                        file_size=len(audio_bytes),
                        conversation_id=req.conversation_id,
                        metadata={"role": "reference_audio"},
                    )
                except Exception as e:
                    logger.warning(f"创建任务 — 尝试将引用音频添加到媒体库失败: {e}")

    for role, storage_path, file_type in upload_media_items:
        try:
            file_data = await download_file_from_bucket(settings.STORAGE_BUCKET, storage_path)
            file_size = len(file_data)
            width, height = None, None
            thumbnail_path = None

            if file_type == "image":
                try:
                    import hashlib
                    file_hash = hashlib.md5(storage_path.encode()).hexdigest()[:8]
                    thumbnail_bytes = await generate_image_thumbnail(file_data)
                    ts = int(time.time())
                    thumbnail_path = f"thumbnails/{_LOCAL_USER}/{ts}_{role}_{file_hash}.jpg"
                    await save_local_file(thumbnail_path, thumbnail_bytes)
                except Exception as e:
                    logger.warning("生成图片缩略图本地保存失败: path=%s, error=%s", storage_path, e, exc_info=True)
            elif file_type == "video":
                tmp_file = None
                try:
                    import hashlib
                    file_hash = hashlib.md5(storage_path.encode()).hexdigest()[:8]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                        f.write(file_data)
                        tmp_file = f.name
                    probed = await get_video_info(tmp_file)
                    if probed:
                        width, height = probed.get("width"), probed.get("height")
                    thumbnail_data = await extract_video_thumbnail(tmp_file, size=(480, 270))
                    ts = int(time.time())
                    thumbnail_path = f"thumbnails/{_LOCAL_USER}/{ts}_{role}_{file_hash}.jpg"
                    await save_local_file(thumbnail_path, thumbnail_data)
                except Exception as e:
                    logger.warning("生成视频缩略图本地保存失败: path=%s, error=%s", storage_path, e, exc_info=True)
                finally:
                    if tmp_file and os.path.exists(tmp_file):
                        os.remove(tmp_file)

            filename = storage_path.split("/")[-1] if "/" in storage_path else storage_path
            await add_to_media_library(
                user_id=_LOCAL_USER,
                name=filename,
                file_type=file_type,
                storage_path=storage_path,
                source_type="uploaded",
                media_type="video/mp4" if file_type == "video" else "image/jpeg",
                file_size=file_size,
                thumbnail_path=thumbnail_path,
                conversation_id=req.conversation_id,
                width=width,
                height=height,
                metadata={"role": role},
            )
        except Exception as e:
            logger.error("上传素材入库异常: path=%s, error=%s", storage_path, e)

    # 参考图尺寸约束：火山接口要求至少 300x300
    for i, ref in enumerate(reference_inputs):
        if ref.get("type") != "reference_image" or not ref.get("storage_path"):
            continue
        try:
            original_reference_image_path = ref["storage_path"]
            original_image_bytes = await download_file_from_bucket(
                settings.STORAGE_BUCKET, original_reference_image_path
            )
            fixed_image_bytes, fixed_w, fixed_h, changed = await ensure_min_image_size(
                original_image_bytes,
                min_width=300,
                min_height=300,
            )
            if changed:
                ts = int(time.time())
                fixed_path = f"{_LOCAL_USER}/upload/refs_{ts}_reference_image_{i + 1}_min300.jpg"
                await upload_file(fixed_path, fixed_image_bytes, "image/jpeg")
                reference_inputs[i]["storage_path"] = fixed_path
                reference_inputs[i]["url"] = await create_signed_url(fixed_path)
                logger.info(
                    "reference_image 尺寸过小，已自动放大后重传: original_path=%s -> fixed_path=%s, size=%sx%s",
                    original_reference_image_path, fixed_path, fixed_w, fixed_h,
                )
        except Exception as e:
            logger.error(f"创建任务 — 参考图处理失败: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"参考图处理失败: {str(e)}")

    # 回填兼容字段
    first_ref_image = next((r for r in reference_inputs if r.get("type") == "reference_image"), None)
    first_ref_video = next((r for r in reference_inputs if r.get("type") == "reference_video"), None)
    first_ref_audio = next((r for r in reference_inputs if r.get("type") == "reference_audio"), None)
    req.reference_image_path = first_ref_image.get("storage_path") if first_ref_image else None
    req.reference_video_path = first_ref_video.get("storage_path") if first_ref_video else None
    req.reference_audio_path = first_ref_audio.get("storage_path") if first_ref_audio else None
    reference_image_url = first_ref_image.get("url") if first_ref_image else None
    reference_video_url = first_ref_video.get("url") if first_ref_video else None
    reference_audio_url = first_ref_audio.get("url") if first_ref_audio else None

    # 调用火山引擎 API
    try:
        # Seedance 2.0 强制分辨率为 720p
        effective_resolution = "720p"

        volcano_result = await volcano_api.create_video_task(
            model=model_id,
            prompt=req.prompt,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            reference_image_url=reference_image_url,
            reference_video_url=reference_video_url,
            reference_audio_url=reference_audio_url,
            reference_inputs=[
                {"type": r.get("type"), "url": r.get("url")}
                for r in reference_inputs if r.get("url")
            ],
            ratio=req.ratio,
            duration=req.duration,
            generate_audio=req.generate_audio,
            watermark=req.watermark,
            return_last_frame=req.return_last_frame,
            draft=req.draft,
            resolution=effective_resolution,
            seed=req.seed,
            camera_fixed=req.camera_fixed,
            service_tier=req.service_tier,
            execution_expires_after=req.execution_expires_after,
        )
    except HTTPException:
        raise
    except VolcanoAPIError as e:
        logger.warning(
            "[API 错误] 火山引擎返回业务错误 | 错误码: %s | 中文提示: %s | 完整消息: %s",
            e.error_code, e.chinese_message, e,
        )
        hint = e.chinese_message
        error_str = str(e).lower()
        if e.error_code in ("InvalidParameter", "MissingParameter"):
            if "video pixel count" in error_str and "927408" in error_str:
                hint = "参考视频分辨率过大（不得超过 720p 约 92万像素）。请压缩视频分辨率后再重试！"
            elif "video total duration" in error_str:
                hint = "上传的参考视频时长总和过长（限制所有参考视频总时长不能超过 15 秒）。请裁剪视频后再尝试！"
        detail: dict = {"error_code": e.error_code, "message": str(e)}
        if hint:
            detail["hint"] = hint
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        logger.exception("火山引擎 create_video_task 调用失败")
        raise HTTPException(status_code=502, detail=f"火山引擎 API 调用失败: {str(e)}")

    volcano_task_id = volcano_result.get("id", "")
    api_request_raw = volcano_result.get("api_request_raw", {})
    api_response_raw = volcano_result.get("api_response_raw", {})

    # 构建 content_inputs 记录
    content_inputs = []
    if req.prompt:
        content_inputs.append({"type": "text", "text": req.prompt})
    if req.first_frame_path:
        content_inputs.append({"type": "image_url", "path": req.first_frame_path, "role": "first_frame"})
    if req.last_frame_path:
        content_inputs.append({"type": "image_url", "path": req.last_frame_path, "role": "last_frame"})
    for ref in reference_inputs:
        ref_type = ref.get("type")
        if ref_type == "reference_image":
            content_inputs.append({"type": "image_url", "path": ref.get("storage_path"), "role": "reference_image"})
        elif ref_type == "reference_video":
            content_inputs.append({"type": "video_url", "path": ref.get("storage_path"), "role": "reference_video"})
        elif ref_type == "reference_audio":
            content_inputs.append({"type": "audio_url", "path": ref.get("storage_path"), "role": "reference_audio"})

    # 在数据库中创建任务记录
    try:
        task = await create_task_record(
            user_id=_LOCAL_USER,
            model=model_id,
            prompt=req.prompt or "",
            input_path=(
                req.first_frame_path or req.reference_image_path
                or req.reference_video_path or req.reference_audio_path or ""
            ),
            volcano_task_id=volcano_task_id,
            ratio=req.ratio,
            duration=req.duration,
            generate_audio=req.generate_audio,
            watermark=req.watermark,
            content_inputs=content_inputs,
            conversation_id=req.conversation_id,
            api_request_raw=api_request_raw,
            api_response_raw=api_response_raw,
        )
        logger.info(f"[任务创建成功] 任务ID: {volcano_task_id} | 数据库记录: {task.get('id')}")
    except Exception as e:
        logger.error(f"[数据库错误] 任务记录创建失败 | 火山任务ID: {volcano_task_id} | 错误: {e}")
        raise HTTPException(status_code=500, detail=f"数据库写入失败: {str(e)}")

    # 如果有对话关联，更新对话的最新任务
    if req.conversation_id and task.get("id"):
        try:
            await update_conversation(req.conversation_id, last_task_id=task["id"])
        except Exception as e:
            logger.warning(
                "更新对话 last_task_id 失败: conversation_id=%s, task_id=%s, error=%s",
                req.conversation_id, task.get("id"), e,
            )

    return {
        "success": True,
        "task_id": task.get("id"),
        "volcano_task_id": volcano_task_id,
        "status": "processing",
    }


@router.get("/api/check_status/{task_id}")
async def check_status(task_id: str):
    """查询任务状态"""
    logger.debug("[查询任务状态] 开始: task_id=%s", task_id)
    task = await get_task(task_id)
    if not task:
        logger.warning("[查询任务状态] 任务不存在: task_id=%s", task_id)
        raise HTTPException(status_code=404, detail="任务不存在")

    # 如果已是终态，直接返回
    if task["status"] in ("succeeded", "failed", "cancelled", "expired", "timeout", "error"):
        result = {
            "task_id": task_id,
            "status": task["status"],
            "video_url": task.get("video_url"),
            "error_message": task.get("error_message"),
        }
        if task["status"] == "succeeded" and task.get("video_url"):
            try:
                signed_url = await create_signed_url(task["video_url"])
                result["signed_video_url"] = signed_url
            except Exception as e:
                logger.warning(
                    "已成功任务签名链接生成失败: task_id=%s, video_url=%s, error=%s",
                    task_id, task.get("video_url"), e,
                )
        logger.debug("[查询任务状态] 命中终态: task_id=%s, status=%s", task_id, task.get("status"))
        return result

    # 向火山引擎查询最新状态
    volcano_task_id = task.get("volcano_task_id")
    if not volcano_task_id:
        raise HTTPException(status_code=500, detail="缺少火山任务ID")

    try:
        volcano_result = await volcano_api.query_task(volcano_task_id, model=task.get("model"))
    except VolcanoGatewayError as e:
        logger.warning(
            f"[查询任务状态] 上游网关暂时不可用 (跳过本次更新): task_id={task_id}, error={str(e)}"
        )
        return {
            "task_id": task_id,
            "status": task["status"],
            "video_url": task.get("video_url"),
            "message": "服务商 API 暂时繁忙，正在重试中...",
        }
    except Exception as e:
        logger.exception("火山引擎 query_task 调用失败")
        raise HTTPException(status_code=502, detail=f"查询火山引擎任务失败: {str(e)}")

    new_status = volcano_result.get("status", "running")

    # 任务成功 — 执行转存逻辑
    if new_status == "succeeded":
        content = volcano_result.get("content", {})
        video_url = content.get("video_url", "")

        if video_url:
            try:
                video_data = await volcano_api.download_video(video_url)
                user_id = _LOCAL_USER
                storage_path = f"videos/{user_id}/{task_id}.mp4"
                await save_local_file(storage_path, video_data)
                await update_task_status(task_id, "succeeded", video_url=storage_path)
                logger.info("任务视频本地存储成功: task_id=%s, storage_path=%s", task_id, storage_path)

                # 更新对话缩略图
                if task.get("conversation_id"):
                    try:
                        await update_conversation(
                            task["conversation_id"],
                            thumbnail_url=storage_path,
                        )
                    except Exception as e:
                        logger.warning(
                            "更新对话缩略图失败: conversation_id=%s, task_id=%s, error=%s",
                            task.get("conversation_id"), task_id, e,
                        )

                # 回填媒体库
                try:
                    file_size = len(video_data)
                    video_info = {"duration": int(task.get("duration") or 0), "width": None, "height": None}
                    tmp_file = None
                    thumbnail_path = None

                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
                            f.write(video_data)
                            tmp_file = f.name
                        probed = await get_video_info(tmp_file)
                        if probed:
                            video_info = {
                                "duration": int(probed.get("duration") or video_info["duration"]),
                                "width": int(probed.get("width") or 0) or None,
                                "height": int(probed.get("height") or 0) or None,
                            }
                        try:
                            thumbnail_data = await extract_video_thumbnail(tmp_file, size=(480, 270))
                            thumbnail_path = f"thumbnails/{_LOCAL_USER}/{task_id}.jpg"
                            await save_local_file(thumbnail_path, thumbnail_data)
                            logger.info("[Storage] 视频缩略图已保存到本地: task_id=%s, path=%s", task_id, thumbnail_path)
                        except Exception as thumb_err:
                            logger.warning("视频缩略图本地提取失败: task_id=%s, error=%s", task_id, thumb_err)
                            thumbnail_path = storage_path
                    except Exception as info_err:
                        logger.warning("视频信息处理失败: task_id=%s, error=%s", task_id, info_err)
                    finally:
                        if tmp_file and os.path.exists(tmp_file):
                            os.remove(tmp_file)

                    prompt_name = (task.get("prompt") or "").strip().replace("\n", " ").replace("\r", " ")
                    media_name = prompt_name[:20] or f"generated_{task_id}.mp4"
                    metadata = {
                        "model": task.get("model"),
                        "prompt": task.get("prompt"),
                        "ratio": task.get("ratio"),
                        "generate_audio": task.get("generate_audio"),
                        "watermark": task.get("watermark"),
                        "resolution": (
                            f"{video_info['width']}x{video_info['height']}"
                            if video_info.get("width") and video_info.get("height")
                            else task.get("ratio")
                        ),
                    }

                    updated = await update_generated_media_by_task(
                        user_id=_LOCAL_USER,
                        task_id=task_id,
                        file_size=file_size,
                        width=video_info.get("width"),
                        height=video_info.get("height"),
                        duration=video_info.get("duration"),
                        metadata=metadata,
                        name=media_name,
                        storage_path=storage_path,
                        thumbnail_path=thumbnail_path or storage_path,
                    )

                    if not updated:
                        await add_to_media_library(
                            user_id=_LOCAL_USER,
                            name=media_name,
                            file_type="video",
                            storage_path=storage_path,
                            source_type="generated",
                            media_type="video/mp4",
                            file_size=file_size,
                            thumbnail_path=storage_path,
                            task_id=task_id,
                            conversation_id=task.get("conversation_id"),
                            width=video_info.get("width"),
                            height=video_info.get("height"),
                            duration=video_info.get("duration"),
                            metadata=metadata,
                        )
                except Exception as e:
                    logger.exception("媒体库回填失败: task_id=%s, error=%s", task_id, str(e))

                signed_url = await create_signed_url(storage_path)
                return {
                    "task_id": task_id,
                    "status": "succeeded",
                    "video_url": storage_path,
                    "signed_video_url": signed_url,
                }
            except Exception as e:
                await update_task_status(
                    task_id, "failed", error_message=f"视频转存失败: {str(e)}"
                )
                logger.exception("任务转存失败: task_id=%s", task_id)
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error_message": f"视频转存失败: {str(e)}",
                }

    # 任务失败或其他状态
    if new_status in ("failed", "cancelled", "expired", "timeout", "error"):
        error_msg = volcano_result.get("error", {}).get("message", "未知错误")
        await update_task_status(task_id, new_status, error_message=error_msg)
        logger.warning("任务进入终态: task_id=%s, status=%s, error=%s", task_id, new_status, error_msg)
        return {
            "task_id": task_id,
            "status": new_status,
            "error_message": error_msg,
        }

    # 仍在处理中
    await update_task_status(task_id, new_status)
    logger.debug("任务状态更新: task_id=%s, status=%s", task_id, new_status)
    return {
        "task_id": task_id,
        "status": new_status,
    }


@router.get("/api/tasks")
async def list_tasks(user_id: Optional[str] = None, limit: int = 20):
    """获取任务列表"""
    tasks = await get_user_tasks(_LOCAL_USER, limit)
    return {"tasks": tasks}


@router.delete("/api/tasks/{task_id}")
async def cancel_or_delete_task(task_id: str):
    """取消或删除任务"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    volcano_task_id = task.get("volcano_task_id")
    model = task.get("model")
    cancelled_on_server = False
    volcano_status = None
    message = "任务已取消"

    if volcano_task_id:
        try:
            volcano_result = await volcano_api.query_task(volcano_task_id, model=model)
            volcano_status = volcano_result.get("status")
        except Exception as e:
            logger.warning("取消任务 — 查询火山侧状态失败: task_id=%s, error=%s", task_id, e)

        if volcano_status == "running":
            message = "任务正在运行中，服务端无法中断；本地已标记为取消"
        elif volcano_status == "cancelled":
            cancelled_on_server = True
            message = "任务已在服务端取消"
        elif volcano_status is None and task.get("status") in ("processing", "queued", "running"):
            try:
                await volcano_api.cancel_task(volcano_task_id, model=model)
                cancelled_on_server = True
            except Exception as e:
                logger.warning("取消任务 — 盲取消失败: task_id=%s, error=%s", task_id, e)
        else:
            try:
                await volcano_api.cancel_task(volcano_task_id, model=model)
                cancelled_on_server = True
                message = "任务已取消" if volcano_status == "queued" else "任务记录已删除"
            except Exception as e:
                logger.warning("取消任务 — DELETE 请求失败: task_id=%s, error=%s", task_id, e)

    await update_task_status(task_id, "cancelled")
    return {
        "success": True,
        "message": message,
        "cancelled_on_server": cancelled_on_server,
        "volcano_status": volcano_status,
    }


@router.get("/api/video/{task_id}")
async def get_video_url(task_id: str):
    """获取视频链接"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] != "succeeded" or not task.get("video_url"):
        raise HTTPException(status_code=400, detail="视频尚未生成")

    try:
        signed_url = await create_signed_url(task["video_url"])
        return {"signed_video_url": signed_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取视频链接失败: {str(e)}")
