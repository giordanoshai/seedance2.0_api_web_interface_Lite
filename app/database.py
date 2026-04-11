"""
SQLite3 数据库模块 — 替代 Supabase 客户端的本地轻量数据库层
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import aiosqlite

from app.config import settings
from app.dailylogger import daily_logger

logger = daily_logger.get_logger()

DB_PATH = settings.SQLITE_DB_PATH
_LOCAL_USER = "local_user"


# ===== 初始化 =====

async def init_db() -> None:
    """初始化数据库，创建所有表（如不存在）"""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'local_user',
                title TEXT DEFAULT '新对话',
                thumbnail_url TEXT,
                last_task_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'local_user',
                model TEXT NOT NULL,
                prompt TEXT,
                input_path TEXT,
                volcano_task_id TEXT,
                status TEXT NOT NULL DEFAULT 'processing',
                ratio TEXT DEFAULT '16:9',
                duration INTEGER DEFAULT 5,
                generate_audio INTEGER DEFAULT 1,
                watermark INTEGER DEFAULT 1,
                content_inputs TEXT DEFAULT '[]',
                video_url TEXT,
                error_message TEXT,
                conversation_id TEXT,
                api_request_raw TEXT,
                api_response_raw TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'local_user',
                role TEXT NOT NULL CHECK(role IN ('user', 'system')),
                text TEXT NOT NULL,
                attachments TEXT DEFAULT '[]',
                task_id TEXT,
                video_url TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS media_library (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'local_user',
                name TEXT NOT NULL,
                file_type TEXT NOT NULL CHECK(file_type IN ('image', 'video', 'audio')),
                media_type TEXT,
                file_size INTEGER DEFAULT 0,
                storage_path TEXT NOT NULL,
                thumbnail_path TEXT,
                source_type TEXT NOT NULL CHECK(source_type IN ('uploaded', 'generated')),
                task_id TEXT,
                conversation_id TEXT,
                width INTEGER,
                height INTEGER,
                duration INTEGER,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
        """)
        await db.commit()
    logger.info("[DB] SQLite 数据库初始化完成: %s", DB_PATH)


# ===== 内部工具函数 =====

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row, cursor) -> dict:
    if row is None:
        return {}
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def _rows_to_list(rows, cursor) -> list:
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def _parse_json_fields(d: dict, fields: list) -> dict:
    for f in fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


# ===== 任务管理 =====

async def create_task_record(
    user_id: str,
    model: str,
    prompt: str,
    input_path: str,
    volcano_task_id: str,
    ratio: str = "16:9",
    duration: int = 5,
    generate_audio: bool = True,
    watermark: bool = True,
    content_inputs: list = None,
    conversation_id: str = None,
    api_request_raw: dict = None,
    api_response_raw: dict = None,
) -> dict:
    """在 tasks 表中创建一条新任务记录"""
    task_id = str(uuid.uuid4())
    now = _now_iso()
    logger.info("[DB] 创建任务记录: model=%s, volcano_task_id=%s", model, volcano_task_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO tasks
               (id, user_id, model, prompt, input_path, volcano_task_id, status,
                ratio, duration, generate_audio, watermark, content_inputs,
                conversation_id, api_request_raw, api_response_raw, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, _LOCAL_USER, model, prompt, input_path, volcano_task_id, "processing",
                ratio, duration, int(generate_audio), int(watermark),
                json.dumps(content_inputs or []),
                conversation_id,
                json.dumps(api_request_raw) if api_request_raw else None,
                json.dumps(api_response_raw) if api_response_raw else None,
                now, now,
            ),
        )
        await db.commit()
    task = await get_task(task_id)
    logger.info("[DB] 任务记录创建完成: local_task_id=%s, volcano_task_id=%s", task_id, volcano_task_id)
    return task


async def update_task_status(
    task_id: str, status: str, video_url: str = None, error_message: str = None
) -> dict:
    """更新任务状态"""
    updates = ["status = ?", "updated_at = ?"]
    values: list = [status, _now_iso()]

    if video_url is not None:
        updates.append("video_url = ?")
        values.append(video_url)
    if error_message is not None:
        updates.append("error_message = ?")
        values.append(error_message)

    values.append(task_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values
        )
        await db.commit()
    return await get_task(task_id)


async def get_task(task_id: str) -> dict:
    """获取单个任务"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                logger.warning("[DB] 获取任务为空: task_id=%s", task_id)
                return {}
            d = _row_to_dict(row, cur)
    return _parse_json_fields(d, ["content_inputs", "api_request_raw", "api_response_raw"])


async def get_user_tasks(user_id: str = _LOCAL_USER, limit: int = 20) -> list:
    """获取任务列表（按创建时间降序）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            result = _rows_to_list(rows, cur)
    return [_parse_json_fields(d, ["content_inputs"]) for d in result]


async def count_active_tasks_by_model(model_id: str, max_age_hours: int = 12) -> int:
    """统计指定模型当前活跃任务数"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*) FROM tasks
               WHERE model = ? AND status IN ('processing', 'queued', 'running')
               AND created_at >= ?""",
            (model_id, cutoff),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_all_active_tasks(max_age_hours: int = 48) -> list:
    """获取所有活跃任务（供后台轮询器使用）"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT * FROM tasks
               WHERE status IN ('processing', 'queued', 'running')
               AND created_at >= ? ORDER BY created_at ASC""",
            (cutoff,),
        ) as cur:
            rows = await cur.fetchall()
            result = _rows_to_list(rows, cur)
    return [_parse_json_fields(d, ["content_inputs"]) for d in result]


# ===== 对话管理 =====

async def create_conversation(user_id: str = _LOCAL_USER, title: str = "新对话") -> dict:
    """创建一个新的对话"""
    conv_id = str(uuid.uuid4())
    now = _now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conv_id, _LOCAL_USER, title, now, now),
        )
        await db.commit()
    return await get_conversation(conv_id)


async def get_user_conversations(user_id: str = _LOCAL_USER, limit: int = 50) -> list:
    """获取对话列表（按更新时间降序）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return _rows_to_list(rows, cur)


async def get_conversation(conversation_id: str) -> dict:
    """获取单个对话"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row, cur) if row else {}


async def update_conversation(conversation_id: str, **kwargs) -> dict:
    """更新对话（可更新 title, thumbnail_url, last_task_id 等）"""
    allowed_fields = {"title", "thumbnail_url", "last_task_id"}
    data = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not data:
        return {}
    data["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values()) + [conversation_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE conversations SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
    return await get_conversation(conversation_id)


async def delete_conversation(conversation_id: str) -> bool:
    """删除对话（级联删除消息、媒体、任务）"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,)
        )
        await db.execute(
            "DELETE FROM media_library WHERE conversation_id = ?", (conversation_id,)
        )
        await db.execute(
            "UPDATE tasks SET conversation_id = NULL WHERE conversation_id = ?",
            (conversation_id,),
        )
        await db.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        await db.commit()
    return True


# ===== 聊天消息管理 =====

async def save_chat_message(
    conversation_id: str,
    user_id: str,
    role: str,
    text: str,
    attachments: list = None,
    task_id: str = None,
    video_url: str = None,
) -> dict:
    """保存一条聊天消息"""
    msg_id = str(uuid.uuid4())
    now = _now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO chat_messages
               (id, conversation_id, user_id, role, text, attachments, task_id, video_url, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                msg_id, conversation_id, _LOCAL_USER, role, text,
                json.dumps(attachments or []), task_id, video_url, now,
            ),
        )
        await db.commit()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (msg_id,)
        ) as cur:
            row = await cur.fetchone()
            d = _row_to_dict(row, cur)
    return _parse_json_fields(d, ["attachments"])


async def get_conversation_messages(
    conversation_id: str, limit: int = 20, before: str = None
) -> list:
    """获取对话的消息列表（按时间正序）"""
    if before:
        query = """SELECT * FROM (
            SELECT * FROM chat_messages WHERE conversation_id = ? AND created_at < ?
            ORDER BY created_at DESC LIMIT ?
        ) ORDER BY created_at ASC"""
        params = (conversation_id, before, limit)
    else:
        query = """SELECT * FROM (
            SELECT * FROM chat_messages WHERE conversation_id = ?
            ORDER BY created_at DESC LIMIT ?
        ) ORDER BY created_at ASC"""
        params = (conversation_id, limit)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            result = _rows_to_list(rows, cur)
    return [_parse_json_fields(d, ["attachments"]) for d in result]


async def update_chat_message(message_id: str, **kwargs) -> dict:
    """更新聊天消息（主要用于追加 video_url）"""
    allowed_fields = {"video_url", "text"}
    data = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not data:
        return {}
    set_clause = ", ".join(f"{k} = ?" for k in data)
    values = list(data.values()) + [message_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE chat_messages SET {set_clause} WHERE id = ?", values
        )
        await db.commit()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
            d = _row_to_dict(row, cur)
    return _parse_json_fields(d, ["attachments"])


# ===== 统计 =====

async def get_user_statistics(user_id: str = _LOCAL_USER) -> dict:
    """获取统计数据（直接聚合 tasks 表）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded_tasks,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_tasks,
                COALESCE(SUM(CASE WHEN status = 'succeeded' THEN duration ELSE 0 END), 0) as total_video_duration
            FROM tasks"""
        ) as cur:
            row = await cur.fetchone()
            d = _row_to_dict(row, cur)

        async with db.execute("SELECT COUNT(*) as cnt FROM conversations") as cur:
            row = await cur.fetchone()
            conv_count = row[0] if row else 0

    return {
        "total_tasks": d.get("total_tasks") or 0,
        "succeeded_tasks": d.get("succeeded_tasks") or 0,
        "failed_tasks": d.get("failed_tasks") or 0,
        "total_video_duration": d.get("total_video_duration") or 0,
        "total_conversations": conv_count,
    }


# ===== 媒体库 =====

async def add_to_media_library(
    user_id: str,
    name: str,
    file_type: str,
    storage_path: str,
    source_type: str,
    media_type: str = None,
    file_size: int = None,
    thumbnail_path: str = None,
    task_id: str = None,
    conversation_id: str = None,
    width: int = None,
    height: int = None,
    duration: int = None,
    metadata: dict = None,
) -> dict:
    """添加媒体到媒体库"""
    media_id = str(uuid.uuid4())
    now = _now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """INSERT INTO media_library
                   (id, user_id, name, file_type, media_type, file_size,
                    storage_path, thumbnail_path, source_type, task_id, conversation_id,
                    width, height, duration, metadata, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    media_id, _LOCAL_USER, name, file_type, media_type, file_size,
                    storage_path, thumbnail_path, source_type, task_id, conversation_id,
                    width, height, duration, json.dumps(metadata or {}), now, now,
                ),
            )
            await db.commit()
        except Exception as e:
            logger.exception("添加到媒体库失败: storage_path=%s, error=%s", storage_path, e)
            return {}

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM media_library WHERE id = ?", (media_id,)
        ) as cur:
            row = await cur.fetchone()
            d = _row_to_dict(row, cur)
    return _parse_json_fields(d, ["metadata"])


async def update_generated_media_by_task(
    user_id: str,
    task_id: str,
    file_size: int = None,
    width: int = None,
    height: int = None,
    duration: int = None,
    metadata: dict = None,
    name: str = None,
    storage_path: str = None,
    thumbnail_path: str = None,
) -> bool:
    """按 task_id 更新已写入媒体库的生成视频信息（合并 metadata）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, metadata FROM media_library WHERE task_id = ? AND source_type = 'generated' LIMIT 1",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return False
            existing_id = row[0]
            existing_meta = {}
            try:
                existing_meta = json.loads(row[1]) if row[1] else {}
            except Exception:
                pass

        updates: dict = {"updated_at": _now_iso()}
        if file_size is not None:
            updates["file_size"] = file_size
        if width is not None:
            updates["width"] = width
        if height is not None:
            updates["height"] = height
        if duration is not None:
            updates["duration"] = duration
        if name:
            updates["name"] = name
        if storage_path:
            updates["storage_path"] = storage_path
        if thumbnail_path:
            updates["thumbnail_path"] = thumbnail_path
        if metadata is not None:
            updates["metadata"] = json.dumps({**existing_meta, **metadata})

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [existing_id]
        await db.execute(f"UPDATE media_library SET {set_clause} WHERE id = ?", values)
        await db.commit()
    return True


async def get_media_library(
    user_id: str = _LOCAL_USER,
    file_type: str = None,
    source_type: str = None,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """获取媒体库（按创建时间倒序）"""
    conditions: list = []
    params: list = []
    if file_type:
        conditions.append("file_type = ?")
        params.append(file_type)
    if source_type:
        conditions.append("source_type = ?")
        params.append(source_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT * FROM media_library {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
            result = _rows_to_list(rows, cur)
    return [_parse_json_fields(d, ["metadata"]) for d in result]


async def delete_media_library_item(item_id: str, user_id: str = _LOCAL_USER) -> dict:
    """获取媒体库项并删除，返回被删除记录（含路径信息供物理文件清理）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM media_library WHERE id = ?", (item_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return {}
            d = _row_to_dict(row, cur)
        d = _parse_json_fields(d, ["metadata"])
        await db.execute("DELETE FROM media_library WHERE id = ?", (item_id,))
        await db.commit()
    return d


async def get_media_library_stats(user_id: str = _LOCAL_USER) -> dict:
    """获取媒体库统计数据"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT
                COUNT(*) as total_items,
                COALESCE(SUM(file_size), 0) as total_size,
                SUM(CASE WHEN file_type='image' THEN 1 ELSE 0 END) as total_images,
                SUM(CASE WHEN file_type='video' THEN 1 ELSE 0 END) as total_videos,
                SUM(CASE WHEN file_type='audio' THEN 1 ELSE 0 END) as total_audios,
                SUM(CASE WHEN source_type='uploaded' THEN 1 ELSE 0 END) as total_uploaded,
                SUM(CASE WHEN source_type='generated' THEN 1 ELSE 0 END) as total_generated,
                SUM(CASE WHEN source_type='uploaded' AND file_type='image' THEN 1 ELSE 0 END) as uploaded_images,
                SUM(CASE WHEN source_type='uploaded' AND file_type='video' THEN 1 ELSE 0 END) as uploaded_videos,
                SUM(CASE WHEN source_type='uploaded' AND file_type='audio' THEN 1 ELSE 0 END) as uploaded_audios,
                SUM(CASE WHEN source_type='generated' AND file_type='image' THEN 1 ELSE 0 END) as generated_images,
                SUM(CASE WHEN source_type='generated' AND file_type='video' THEN 1 ELSE 0 END) as generated_videos,
                SUM(CASE WHEN source_type='generated' AND file_type='audio' THEN 1 ELSE 0 END) as generated_audios
            FROM media_library"""
        ) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row, cur) if row else {}
