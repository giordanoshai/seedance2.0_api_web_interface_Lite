from fastapi import APIRouter, HTTPException
from typing import Optional

from app.dailylogger import daily_logger
from app.database import (
    create_conversation,
    get_user_conversations,
    get_conversation,
    update_conversation,
    delete_conversation,
    save_chat_message,
    get_conversation_messages,
    update_chat_message,
)
from app.oss_client import create_signed_url
from app.schemas import (
    CreateConversationRequest,
    SaveMessageRequest,
    UpdateConversationRequest,
)

router = APIRouter()
logger = daily_logger.get_logger()

_LOCAL_USER = "local_user"


# ===== 对话管理 API =====

@router.post("/api/conversations")
async def api_create_conversation(req: CreateConversationRequest):
    """新建对话"""
    conv = await create_conversation(user_id=_LOCAL_USER, title=req.title)
    return {"success": True, "conversation": conv}


@router.get("/api/conversations")
async def api_list_conversations(user_id: Optional[str] = None, limit: int = 50):
    """获取对话列表"""
    conversations = await get_user_conversations(_LOCAL_USER, limit)
    # 为有缩略图的对话获取 OSS 公开链接
    for conv in conversations:
        if conv.get("thumbnail_url"):
            try:
                conv["thumbnail_signed_url"] = await create_signed_url(conv["thumbnail_url"])
            except Exception as e:
                logger.warning(f"获取对话缩略图链接失败: {conv.get('id')}, error={e}")
                conv["thumbnail_signed_url"] = None
    return {"conversations": conversations}


@router.get("/api/conversations/{conversation_id}/messages")
async def api_get_messages(conversation_id: str, limit: int = 20, before: str = None):
    """获取对话的消息列表（支持游标分页）"""
    messages = await get_conversation_messages(conversation_id, limit=limit, before=before)
    # 为包含视频的消息获取链接
    for msg in messages:
        if msg.get("video_url"):
            try:
                msg["video_signed_url"] = await create_signed_url(msg["video_url"])
            except Exception as e:
                logger.warning(f"获取消息视频链接失败: {msg.get('id')}, error={e}")
                msg["video_signed_url"] = None
        # 为附件中的图片获取链接
        if msg.get("attachments"):
            for att in msg["attachments"]:
                if att.get("storage_path"):
                    try:
                        att["signed_url"] = await create_signed_url(att["storage_path"])
                    except Exception as e:
                        logger.warning(f"获取附件链接失败: {att.get('id')}, error={e}")
                        att["signed_url"] = None

    has_more = len(messages) >= limit
    oldest_cursor = messages[0]["created_at"] if messages else None
    return {"messages": messages, "has_more": has_more, "oldest_cursor": oldest_cursor}


@router.post("/api/messages")
async def api_save_message(req: SaveMessageRequest):
    """保存一条消息"""
    msg = await save_chat_message(
        conversation_id=req.conversation_id,
        user_id=_LOCAL_USER,
        role=req.role,
        text=req.text,
        attachments=req.attachments,
        task_id=req.task_id,
        video_url=req.video_url,
    )
    return {"success": True, "message": msg}


@router.patch("/api/conversations/{conversation_id}")
async def api_update_conversation(conversation_id: str, req: UpdateConversationRequest):
    """更新对话信息"""
    kwargs = {}
    if req.title is not None:
        kwargs["title"] = req.title
    if req.thumbnail_url is not None:
        kwargs["thumbnail_url"] = req.thumbnail_url
    conv = await update_conversation(conversation_id, **kwargs)
    return {"success": True, "conversation": conv}


@router.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(conversation_id: str):
    """删除对话"""
    await delete_conversation(conversation_id)
    return {"success": True, "message": "对话已删除"}
