import os
import asyncio
import base64
import mimetypes
import oss2
from app.config import settings
from app.dailylogger import daily_logger

logger = daily_logger.get_logger()

def get_bucket():
    """获取阿里云 OSS Bucket 实例"""
    auth = oss2.Auth(settings.OSS_KEY_ID, settings.OSS_ACCESSKEY)
    return oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)

def is_local_path(file_path: str) -> bool:
    """判断文件是否属于本地存储"""
    if not file_path:
        return False

    clean_path = file_path.replace("\\", "/").strip().lstrip("/")

    # 生成视频和缩略图始终本地存储
    local_prefixes = ("videos/", "thumbnails/")
    if any(clean_path.startswith(prefix) for prefix in local_prefixes):
        return True

    # 未配置 OSS 时，用户上传的素材也存本地
    if not settings.OSS_ENABLED:
        return True

    return False

def get_public_url(file_path: str) -> str:
    """获取文件的公共访问 URL（智能路由：OSS 或 本地静态路由）"""
    if not file_path:
        return ""
        
    # 如果已经是完整的绝对链接，直接返回
    if file_path.strip().startswith(("http://", "https://")):
        return file_path.strip()
        
    # 统一路径格式处理
    clean_path = file_path.replace("\\", "/").strip().lstrip("/")
    
    is_local = is_local_path(clean_path)
    if is_local:
        # 本地生成的视频或缩略图，映射到 FastAPI 挂载的静态路由 /outputs
        result = f"/outputs/{clean_path}"
    else:
        # 其他用户上传的参考图，统一去阿里云 OSS 拿
        result = f"https://{settings.OSS_URI}/{clean_path}"
    
    logger.debug("[Routing] Path: %s -> URL: %s (is_local: %s)", file_path, result, is_local)
    return result

# ==================== OSS / 本地双模式操作 ====================

async def upload_file(file_path: str, file_data: bytes, content_type: str = "application/octet-stream") -> str:
    """上传文件：OSS 已配置时传云端，否则保存本地"""
    if not settings.OSS_ENABLED:
        return await save_local_file(file_path, file_data)
    bucket = get_bucket()
    try:
        headers = {"Content-Type": content_type}
        await asyncio.to_thread(bucket.put_object, file_path, file_data, headers=headers)
        logger.info("[Storage] 参考文件已上传至 OSS: %s", file_path)
        return file_path
    except Exception as e:
        logger.error("OSS 上传失败: path=%s, error=%s", file_path, e)
        raise

async def download_file(file_path: str) -> bytes:
    """下载文件：OSS 已配置时从云端拉取，否则读本地"""
    if not settings.OSS_ENABLED:
        clean_path = file_path.replace("\\", "/").strip().lstrip("/")
        abs_path = os.path.abspath(os.path.join(settings.OUTPUT_DIR, clean_path.replace("/", os.sep)))
        def _read():
            with open(abs_path, "rb") as f:
                return f.read()
        return await asyncio.to_thread(_read)
    bucket = get_bucket()
    try:
        result = await asyncio.to_thread(bucket.get_object, file_path)
        return result.read()
    except Exception as e:
        logger.error("OSS 下载失败: path=%s, error=%s", file_path, e)
        raise


async def get_api_url(storage_path: str, file_type: str = "image") -> str:
    """获取传给 Seedance API 的媒体 URL。
    OSS 模式：返回公网 URL。
    无 OSS 模式：图片转 base64 data URL；视频/音频不支持，抛出 ValueError。
    """
    if settings.OSS_ENABLED:
        return get_public_url(storage_path)
    if file_type != "image":
        type_cn = {"video": "视频", "audio": "音频"}.get(file_type, file_type)
        raise ValueError(f"未配置 OSS 时不支持参考{type_cn}，请配置阿里云 OSS 后使用。")
    clean_path = storage_path.replace("\\", "/").strip().lstrip("/")
    abs_path = os.path.abspath(os.path.join(settings.OUTPUT_DIR, clean_path.replace("/", os.sep)))
    def _encode():
        with open(abs_path, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(storage_path)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return await asyncio.to_thread(_encode)

# ==================== 本地操作 (供生成视频使用) ====================

async def save_local_file(file_path: str, file_data: bytes) -> str:
    """保存数据到本地输出目录"""
    def _save_sync():
        abs_path = os.path.abspath(os.path.join(settings.OUTPUT_DIR, file_path.replace("/", os.sep)))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(file_data)
        return abs_path

    abs_saved_path = await asyncio.to_thread(_save_sync)
    logger.info("[Storage] 生成文件已保存到本地: %s", abs_saved_path)
    return file_path

async def delete_local_file(file_path: str) -> None:
    """从本地输出目录删除文件"""
    abs_path = os.path.abspath(os.path.join(settings.OUTPUT_DIR, file_path.replace("/", os.sep)))
    if os.path.exists(abs_path):
        try:
            await asyncio.to_thread(os.remove, abs_path)
            logger.info("[Storage] 本地文件已删除: %s", abs_path)
        except Exception as e:
            logger.warning("本地文件删除失败: path=%s, error=%s", abs_path, e)

async def delete_file(file_path: str) -> None:
    """智能删除：根据路径前缀自动判断删 OSS 还是删本地"""
    if is_local_path(file_path):
        await delete_local_file(file_path)
    else:
        bucket = get_bucket()
        try:
            await asyncio.to_thread(bucket.delete_object, file_path)
            logger.info("[Storage] OSS 文件已删除: %s", file_path)
        except Exception as e:
            logger.error("OSS 删除失败: path=%s, error=%s", file_path, e)

# ==================== 兼容包装函数 ====================

async def create_signed_url(file_path: str, expiry: int = None) -> str:
    return get_public_url(file_path)

async def create_signed_url_from_bucket(bucket: str, file_path: str, expiry: int = None) -> dict:
    return {"signedURL": get_public_url(file_path)}

async def create_signed_urls_batch(bucket: str, file_paths: list, expiry: int = None) -> list:
    return [{"path": p, "signedURL": get_public_url(p)} for p in (file_paths or [])]

def get_public_file_url(bucket: str, file_path: str) -> str:
    return get_public_url(file_path)

async def upload_file_to_bucket(bucket: str, file_path: str, file_data: bytes, content_type: str = "application/octet-stream") -> str:
    """前端上传接口统一调这里：参考图/视频/音頻存 OSS，供自工引擎 API 公网访问"""
    return await upload_file(file_path, file_data, content_type)

async def download_file_from_bucket(bucket: str, file_path: str) -> bytes:
    """从 OSS 下载文件（参考素材存 OSS）"""
    return await download_file(file_path)

async def delete_file_from_bucket(bucket: str, file_path: str) -> None:
    await delete_file(file_path)