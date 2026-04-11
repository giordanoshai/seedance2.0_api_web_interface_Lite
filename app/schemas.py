from pydantic import BaseModel
from typing import Optional, List


# ===== 请求模型 =====

class CreateTaskRequest(BaseModel):
    """创建视频生成任务的请求体"""
    model: str = "seedance-2.0"
    prompt: Optional[str] = None
    # 上传到 OSS 后的路径
    first_frame_path: Optional[str] = None
    last_frame_path: Optional[str] = None
    reference_image_path: Optional[str] = None
    reference_video_path: Optional[str] = None
    reference_audio_path: Optional[str] = None
    # 多参考输入
    reference_inputs: Optional[List[dict]] = None
    # 参数设置
    ratio: str = "16:9"
    duration: int = 5
    generate_audio: bool = True
    watermark: bool = True
    # Seedance 2.0 支持的参数
    return_last_frame: bool = False
    draft: bool = False
    resolution: Optional[str] = None
    seed: Optional[int] = None
    camera_fixed: Optional[bool] = None
    service_tier: Optional[str] = None
    execution_expires_after: Optional[int] = None
    # 对话关联
    conversation_id: Optional[str] = None
    # 兼容字段（不再强制校验，后端忽略）
    user_id: Optional[str] = None
    access_token: Optional[str] = None


class CreateConversationRequest(BaseModel):
    """创建对话的请求体"""
    user_id: Optional[str] = None
    title: str = "新对话"


class SaveMessageRequest(BaseModel):
    """保存消息的请求体"""
    conversation_id: str
    user_id: Optional[str] = None
    role: str
    text: str
    attachments: list = []
    task_id: Optional[str] = None
    video_url: Optional[str] = None


class UpdateConversationRequest(BaseModel):
    """更新对话的请求体"""
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None
