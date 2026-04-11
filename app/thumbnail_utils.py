"""
缩微图处理工具 — 图片和视频缩微图生成
"""

import subprocess
import tempfile
import os
import json
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


async def generate_image_thumbnail(
    image_data: bytes,
    size: tuple = (320, 180),
    quality: int = 85,
) -> bytes:
    """
    生成图片缩微图
    
    Args:
        image_data: 原始图片数据（字节）
        size: 缩微图尺寸 (宽, 高)，默认 (320, 180)
        quality: JPEG 质量 (1-100)，默认 85
    
    Returns:
        缩微图数据（字节）
    """
    if not Image:
        raise RuntimeError("Pillow 库未安装，请运行: pip install Pillow")
    
    try:
        # 打开原始图片
        img = Image.open(BytesIO(image_data))
        
        # 转换 RGBA 到 RGB（处理透明背景）
        if img.mode in ("RGBA", "LA", "P"):
            # 创建白色背景
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        
        # 按宽高比调整大小
        img.thumbnail(size, Image.Resampling.LANCZOS)
        
        # 创建指定大小的新图片 (使用黑色背景)
        thumb = Image.new("RGB", size, (0, 0, 0))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        thumb.paste(img, offset)
        
        # 保存为 JPEG
        output = BytesIO()
        thumb.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        raise RuntimeError(f"生成图片缩微图失败: {str(e)}")


async def extract_video_thumbnail(
    video_path: str,
    timestamp: str = "00:00:00",
    size: tuple = (320, 180),
    output_format: str = "jpeg",
) -> bytes:
    """
    从视频中提取缩微图（关键帧）
    
    Args:
        video_path: 视频文件路径或URL
        timestamp: 提取时间戳 (HH:MM:SS 或 秒数)，默认第1秒
        size: 输出尺寸 (宽, 高)，默认 (320, 180)
        output_format: 输出格式 ("jpeg" 或 "png")
    
    Returns:
        缩微图数据（字节）
    
    Note:
        需要系统安装 ffmpeg
        在 Windows: choco install ffmpeg
        在 macOS: brew install ffmpeg
        在 Linux: sudo apt-get install ffmpeg
    """
    try:
        # 检测 ffmpeg
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        raise RuntimeError("ffmpeg 未安装或不在 PATH 中。请先安装 ffmpeg")
    
    temp_output = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_output = os.path.join(tmpdir, f"thumbnail.{output_format}")
            
            # 构建 ffmpeg 命令
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-ss", timestamp,
                "-vf", f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2:black",
                "-vframes", "1",
                "-y",
                temp_output,
            ]
            
            # 执行 ffmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg 提取失败: {result.stderr}")
            
            # 读取生成的缩微图
            if not os.path.exists(temp_output):
                raise RuntimeError("缩微图生成失败")
            
            with open(temp_output, "rb") as f:
                thumbnail_data = f.read()
            
            return thumbnail_data
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg 处理超时")
    except Exception as e:
        raise RuntimeError(f"提取视频缩微图失败: {str(e)}")


async def get_image_dimensions(image_data: bytes) -> tuple:
    """
    获取图片尺寸 (宽, 高)
    """
    if not Image:
        raise RuntimeError("Pillow 库未安装")
    
    try:
        img = Image.open(BytesIO(image_data))
        return (img.width, img.height)
    except Exception as e:
        raise RuntimeError(f"获取图片尺寸失败: {str(e)}")


async def ensure_min_image_size(
    image_data: bytes,
    min_width: int = 300,
    min_height: int = 300,
    quality: int = 92,
) -> tuple[bytes, int, int, bool]:
    """
    确保图片最小尺寸要求。

    Returns:
        (处理后图片字节, 宽, 高, 是否已处理)
    """
    if not Image:
        raise RuntimeError("Pillow 库未安装")

    try:
        img = Image.open(BytesIO(image_data))
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.width, img.height
        if width >= min_width and height >= min_height:
            return image_data, width, height, False

        scale = max(min_width / max(width, 1), min_height / max(height, 1))
        new_width = max(min_width, int(round(width * scale)))
        new_height = max(min_height, int(round(height * scale)))

        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        output = BytesIO()
        resized.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue(), new_width, new_height, True
    except Exception as e:
        raise RuntimeError(f"图片最小尺寸修复失败: {str(e)}")


async def get_video_info(video_path: str) -> dict:
    """
    获取视频信息（时长、分辨率等）
    
    Returns:
        字典包含:
        - duration: 视频时长（秒）
        - width: 视频宽度
        - height: 视频高度
        - fps: 帧率
    """
    try:
        # 使用 JSON 格式输出，避免由于索引偏移导致的解析失败
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration,width,height,r_frame_rate:format=duration",
            "-of", "json",
            video_path,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe 获取失败: {result.stderr}")
        
        data = json.loads(result.stdout)
        if not data:
            raise RuntimeError("无法解析视频信息: JSON 为空")
            
        streams = data.get("streams", [])
        fmt = data.get("format", {})
        
        # 基础数据初始化
        duration = 0
        width = 0
        height = 0
        fps = 0
        
        if streams:
            video_stream = streams[0]
            width = int(video_stream.get("width") or 0)
            height = int(video_stream.get("height") or 0)
            
            # 优先从 stream 获取时长，获取不到再看 format
            duration_str = video_stream.get("duration") or fmt.get("duration")
            if duration_str:
                try:
                    duration = float(duration_str)
                except:
                    duration = 0
            
            # 安全解析帧率 (如 "24/1")
            fps_str = video_stream.get("r_frame_rate", "0/1")
            if fps_str and "/" in fps_str:
                try:
                    num, denom = map(float, fps_str.split("/"))
                    fps = num / denom if denom > 0 else 0
                except:
                    fps = 0
            elif fps_str:
                try:
                    fps = float(fps_str)
                except:
                    fps = 0

        return {
            "duration": int(duration),
            "width": width,
            "height": height,
            "fps": round(fps, 3),
        }
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe 获取超时")
    except Exception as e:
        raise RuntimeError(f"获取视频信息失败: {str(e)}")
