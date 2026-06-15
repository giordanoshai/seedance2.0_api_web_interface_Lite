"""
SD_Video — FastAPI 视频生成应用主程序（开源简化版：SQLite3 + 无登录）
"""
# 必须在所有 app.* 导入之前加载 .env，否则 os.getenv() 读不到值
from dotenv import load_dotenv
load_dotenv()

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from app.routers import router
from app.task_worker import background_poller
from app import database
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化数据库，启动后台任务轮询器"""
    await database.init_db()
    
    # 确保本地输出目录存在
    for sub in ["videos", "thumbnails"]:
        path = Path(settings.OUTPUT_DIR) / sub
        path.mkdir(parents=True, exist_ok=True)

    # 无 OSS 时，上传的参考素材也存本地，提前建好目录
    if not settings.OSS_ENABLED:
        (Path(settings.OUTPUT_DIR) / "local_user" / "upload").mkdir(parents=True, exist_ok=True)
        
    poller = asyncio.create_task(background_poller())
    yield
    poller.cancel()
    try:
        await poller
    except asyncio.CancelledError:
        pass


# ===== FastAPI 应用初始化 =====
app = FastAPI(title="SD_Video", description="AI 视频生成工作台", lifespan=lifespan)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
app.mount("/data", StaticFiles(directory="data"), name="data")

# 引入路由模块
app.include_router(router)

# ===== 启动 =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
