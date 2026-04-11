"""
后台任务轮询器 — 服务端主动轮询活跃任务，确保即使浏览器关闭也能完成视频转存
"""

import asyncio
import os
import tempfile
import time

from app.dailylogger import daily_logger
from app.database import (
    get_all_active_tasks,
    get_task,
    update_task_status,
    update_conversation,
    update_generated_media_by_task,
    add_to_media_library,
)
from app.oss_client import save_local_file
from app.volcano_api import volcano_api
from app.config import settings
from app.thumbnail_utils import get_video_info, extract_video_thumbnail

logger = daily_logger.get_logger()

# 轮询间隔（秒）
POLL_INTERVAL = 10

# 正在处理中的任务 ID 集合，防止同一任务被并发重入
_processing_tasks: set[str] = set()

_LOCAL_USER = "local_user"


async def _process_task(task: dict) -> None:
    """处理单个活跃任务，逻辑与前端触发的 check_status 一致"""
    task_id = task["id"]

    if task_id in _processing_tasks:
        return

    _processing_tasks.add(task_id)
    try:
        # 二次校验：从数据库重新读取最新状态，防止竞争条件
        fresh_task = await get_task(task_id)
        if not fresh_task:
            logger.warning("[worker] task_id=%s 数据库记录不存在，跳过", task_id)
            return
        current_status = fresh_task.get("status", "")
        if current_status in ("succeeded", "failed", "cancelled", "expired", "timeout", "error"):
            logger.debug("[worker] task_id=%s 已处于终态 %s，跳过", task_id, current_status)
            return

        volcano_task_id = task.get("volcano_task_id")
        if not volcano_task_id:
            logger.warning("[worker] task_id=%s 缺少 volcano_task_id，跳过", task_id)
            return

        try:
            volcano_result = await volcano_api.query_task(volcano_task_id, model=task.get("model"))
        except Exception as e:
            logger.warning("[worker] 查询火山任务失败: task_id=%s, error=%s", task_id, e)
            return

        new_status = volcano_result.get("status", "running")

        if new_status == "succeeded":
            content = volcano_result.get("content", {})
            video_url = content.get("video_url", "")

            if not video_url:
                await update_task_status(task_id, "failed", error_message="火山返回视频URL为空")
                return

            try:
                video_data = await volcano_api.download_video(video_url)

                ts = int(time.time())
                storage_path = f"videos/{_LOCAL_USER}/{ts}_{task_id}.mp4"

                # 再次校验任务未被取消
                check = await get_task(task_id)
                if check and check.get("status") in ("cancelled", "succeeded"):
                    logger.info(
                        "[worker] task_id=%s 下载视频后发现状态已变更为 %s，跳过写入",
                        task_id, check.get("status"),
                    )
                    return

                await save_local_file(storage_path, video_data)
                await update_task_status(task_id, "succeeded", video_url=storage_path)

                # 更新对话缩略图
                if task.get("conversation_id"):
                    try:
                        await update_conversation(task["conversation_id"], thumbnail_url=storage_path)
                    except Exception:
                        pass

                # 媒体库回填
                try:
                    file_size = len(video_data)
                    video_info = {"duration": int(task.get("duration") or 0), "width": None, "height": None}

                    tmp_file = None
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
                            thumbnail_path = f"thumbnails/{_LOCAL_USER}/{ts}_{task_id}.jpg"
                            await save_local_file(thumbnail_path, thumbnail_data)
                            logger.info("[worker] 视频缩略图已保存到本地: path=%s", thumbnail_path)
                        except Exception as thumb_err:
                            logger.warning("[worker] 视频缩略图提取失败: task_id=%s, error=%s", task_id, thumb_err)
                            thumbnail_path = storage_path
                    except Exception:
                        pass
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
                        thumbnail_path=thumbnail_path,
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
                            thumbnail_path=thumbnail_path,
                            task_id=task_id,
                            conversation_id=task.get("conversation_id"),
                            width=video_info.get("width"),
                            height=video_info.get("height"),
                            duration=video_info.get("duration"),
                            metadata=metadata,
                        )
                except Exception:
                    logger.exception("[worker] 媒体库回填失败: task_id=%s", task_id)

                logger.info("[worker] 任务完成: task_id=%s -> %s", task_id, storage_path)

            except Exception as e:
                await update_task_status(task_id, "failed", error_message=f"视频转存失败: {str(e)}")
                logger.exception("[worker] 视频转存失败: task_id=%s", task_id)

        elif new_status in ("failed", "cancelled", "expired", "timeout", "error"):
            error_msg = volcano_result.get("error", {}).get("message", "未知错误")
            await update_task_status(task_id, new_status, error_message=error_msg)
            logger.info("[worker] 任务终态: task_id=%s, status=%s", task_id, new_status)

        else:
            await update_task_status(task_id, new_status)

    finally:
        _processing_tasks.discard(task_id)


async def background_poller() -> None:
    """后台轮询主循环，每隔 POLL_INTERVAL 秒扫描一次所有活跃任务"""
    logger.info("[worker] 后台任务轮询器已启动，轮询间隔 %ds", POLL_INTERVAL)
    while True:
        try:
            tasks = await get_all_active_tasks(max_age_hours=12)
            if tasks:
                logger.debug("[worker] 发现 %d 个活跃任务", len(tasks))
                await asyncio.gather(
                    *[_process_task(t) for t in tasks],
                    return_exceptions=True,
                )
        except Exception:
            logger.exception("[worker] 轮询主循环异常")

        await asyncio.sleep(POLL_INTERVAL)
