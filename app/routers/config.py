from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import count_active_tasks_by_model

router = APIRouter()


@router.get("/api/models")
async def get_models():
    """获取可用模型列表及其配置"""
    return JSONResponse(content=settings.MODELS)


@router.get("/api/system/capacity")
async def get_system_capacity():
    """查询各模型当前活跃任务数与并发上限"""
    result = {}
    for model_key, model_cfg in settings.MODELS.items():
        model_id = model_cfg["id"]
        limit = settings.MODEL_CONCURRENCY_LIMITS.get(model_key, 0)
        active = await count_active_tasks_by_model(model_id) if limit > 0 else 0
        result[model_key] = {
            "active": active,
            "limit": limit,
            "available": limit == 0 or active < limit,
        }
    return result
