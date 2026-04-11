import os

# ==================== 开源版配置模版 (可在此修改或通过环境变量覆盖) ====================

OSS_KEY_ID = os.getenv("OSS_KEY_ID", "")  # 阿里云 OSS KEY_ID
OSS_ACCESSKEY = os.getenv("OSS_ACCESSKEY", "")  # 阿里云 OSS ACCESSKEY
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")  # 阿里云 OSS BUCKET_NAME
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")  # 阿里云 OSS ENDPOINT
OSS_URI = os.getenv("OSS_URI", "your_bucket_name.oss-cn-shanghai.aliyuncs.com")  # 阿里云 OSS URI

# 火山引擎 / Seedance 配置
VM_SEEDANCE_20 = os.getenv("VM_SEEDANCE_20", "doubao-seedance-2-0-260128")
SEEDANCE20_URL = os.getenv("SEEDANCE20_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
SEEDANCE20_KEY = os.getenv("SEEDANCE20_KEY", "[ENCRYPTION_KEY]")



# ====================================================================================

class Settings:
    """集中管理所有配置项"""

    # 火山引擎 Ark API (兼容旧逻辑)
    ARK_API_KEY: str = SEEDANCE20_KEY
    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com"

    # Seedance 2.0 上游代理 API
    SEEDANCE20_URL: str = SEEDANCE20_URL
    SEEDANCE20_KEY: str = SEEDANCE20_KEY
    SEEDANCE20_MODEL_ID: str = VM_SEEDANCE_20

    # 本地 SQLite 数据库路径
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", "data/app.db")

    # 阿里云 OSS
    OSS_KEY_ID: str = OSS_KEY_ID
    OSS_ACCESSKEY: str = OSS_ACCESSKEY
    OSS_BUCKET_NAME: str = OSS_BUCKET_NAME
    OSS_ENDPOINT: str = OSS_ENDPOINT
    OSS_URI: str = OSS_URI

    # 存储路径配置
    STORAGE_BUCKET: str = os.getenv("STORAGE_BUCKET", "private")
    THUMBNAIL_BUCKET: str = os.getenv("THUMBNAIL_BUCKET", "thumbnails")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "outputs")

    # 可用模型配置
    MODELS: dict = {
        "seedance-2.0": {
            "id": VM_SEEDANCE_20,
            "name": "Seedance 2.0",
            "available": bool(SEEDANCE20_URL and SEEDANCE20_KEY != "[ENCRYPTION_KEY]" and VM_SEEDANCE_20),
            "supports": [
                "text", "first_frame", "last_frame",
                "reference_image", "reference_video", "reference_audio",
            ],
            "ratios": ["16:9", "9:16", "1:1", "21:9", "4:3", "3:4"],
            "durations": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            "has_audio": True,
            "resolutions": ["720p"],
        },
        "seedance-1.5": {
            "id": VM_SEEDANCE_15,
            "name": "Seedance 1.5 Pro",
            "available": bool(ARK_API_KEY != "[ENCRYPTION_KEY]" and VM_SEEDANCE_15),
            "supports": ["text", "first_frame", "last_frame", "reference_image", "reference_video", "reference_audio"],
            "ratios": ["16:9", "9:16", "1:1", "21:9", "4:3", "3:4"],
            "durations": [5, 10],
            "has_audio": True,
            "resolutions": ["720p", "1080p"],
        },
        "seedance-lite": {
            "id": VM_SEEDANCE_LITE,
            "name": "Seedance Lite",
            "available": bool(ARK_API_KEY != "[ENCRYPTION_KEY]" and VM_SEEDANCE_LITE),
            "supports": ["text", "reference_image"],
            "ratios": ["16:9", "9:16", "1:1"],
            "durations": [5, 10],
            "has_audio": False,
            "resolutions": ["540p"],
        }
    }

    # 全局并发限制
    MODEL_CONCURRENCY_LIMITS: dict = {
        "seedance-2.0": int(os.getenv("LIMIT_SEEDANCE_20", "10")),
        "seedance-1.5": int(os.getenv("LIMIT_SEEDANCE_15", "5")),
        "seedance-lite": int(os.getenv("LIMIT_SEEDANCE_LITE", "20")),
    }


settings = Settings()
