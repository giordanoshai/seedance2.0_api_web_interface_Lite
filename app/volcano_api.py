"""
火山引擎 Seedance API 模块 — 视频生成任务管理
Base URL: https://ark.cn-beijing.volces.com
"""

import httpx
import json
import asyncio
from typing import Optional, Union
from app.config import settings
from app.dailylogger import logger


# 火山方舟 API 错误码 → 中文含义映射（常见敏感/内容审核类）
VOLCANO_ERROR_CODE_MSG: dict[str, str] = {
    "SensitiveContentDetected": "输入文本可能包含敏感信息，请更换提示词后重试。",
    "SensitiveContentDetected.SevereViolation": "输入文本可能包含严重违规信息，请更换提示词后重试。",
    "SensitiveContentDetected.Violence": "输入文本可能包含激进行为相关信息，请更换提示词后重试。",
    "InputTextSensitiveContentDetected": "输入文本可能包含敏感信息，请更换后重试。",
    "InputImageSensitiveContentDetected": "输入图像可能包含敏感信息，请更换图片后重试。",
    "InputVideoSensitiveContentDetected": "输入视频可能包含敏感信息，请更换视频后重试。",
    "InputAudioSensitiveContentDetected": "输入音频可能包含敏感信息，请更换音频后重试。",
    "OutputTextSensitiveContentDetected": "生成的文字可能包含敏感信息，请更换输入内容后重试。",
    "OutputImageSensitiveContentDetected": "生成的图像可能包含敏感信息，请更换输入内容后重试。",
    "OutputVideoSensitiveContentDetected": "生成的视频可能包含敏感信息，请更换输入内容后重试。",
    "OutputAudioSensitiveContentDetected": "生成的音频可能包含敏感信息，请更换输入内容后重试。",
    "InputTextSensitiveContentDetected.PolicyViolation": "输入文本可能违反平台规定，请更换后重试。",
    "InputImageSensitiveContentDetected.PolicyViolation": "输入图片可能违反平台规定，请更换后重试。",
    "InputVideoSensitiveContentDetected.PolicyViolation": "输入视频可能违反平台规定，请更换后重试。",
    "InputAudioSensitiveContentDetected.PolicyViolation": "输入音频可能违反平台规定，请更换后重试。",
    "InputImageSensitiveContentDetected.PrivacyInformation": "输入图片可能包含真实人物，请更换图片后重试。",
    "InputVideoSensitiveContentDetected.PrivacyInformation": "输入视频可能包含真实人物，请更换视频后重试。",
    "InputTextRiskDetection": "输入文本经风险识别检测到敏感内容，请更换后重试。",
    "InputImageRiskDetection": "输入图片经风险识别检测到敏感内容，请更换后重试。",
    "OutputTextRiskDetection": "输出文本经风险识别检测到敏感内容，请更换输入内容后重试。",
    "OutputImageRiskDetection": "输出图片经风险识别检测到敏感内容，请更换输入内容后重试。",
    "InvalidEndpoint.ClosedEndpoint": "推理接入点已关闭或暂时不可用，请稍后重试。",
    "AuthenticationError": "API Key 或鉴权信息校验失败，请检查配置。",
    "AccountOverdueError": "账号欠费，请前往费用中心充值后继续使用。",
    "RateLimitExceeded.EndpointRPMExceeded": "请求频率超出 RPM 限制，请稍后重试。",
    "RateLimitExceeded.EndpointTPMExceeded": "请求 Token 量超出 TPM 限制，请稍后重试。",
    "ServerOverloaded": "服务资源紧张，请稍后重试。",
    "QuotaExceeded": "账号额度已耗尽，请前往控制台开通或充值后继续使用。",
    "InsufficientBalance": "账号余额不足，请前往费用中心充值后继续使用。",
}


class VolcanoAPIError(RuntimeError):
    """火山引擎 API 返回业务错误时抛出，携带原始错误码。"""

    def __init__(self, message: str, error_code: str = "", http_status: int = 0):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status

    @property
    def chinese_message(self) -> str:
        """返回错误码对应的中文含义，未命中则返回空字符串。"""
        return VOLCANO_ERROR_CODE_MSG.get(self.error_code, "")


class VolcanoGatewayError(VolcanoAPIError):
    """火山引擎 API 层面网关错误（如 502, 503, 504）时抛出。"""
    pass


class VolcanoVideoAPI:
    """火山引擎视频生成 API 客户端"""

    def __init__(self):
        self.seedance20_url = settings.SEEDANCE20_URL
        self.seedance20_key = settings.SEEDANCE20_KEY

    @staticmethod
    def _is_seedance20_model(model: Optional[str]) -> bool:
        return bool(model and model == settings.SEEDANCE20_MODEL_ID)

    def _get_seedance20_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.seedance20_key}",
        }

    def _build_content(
        self,
        prompt: str = None,
        first_frame_url: str = None,
        last_frame_url: str = None,
        reference_image_url: str = None,
        reference_video_url: str = None,
        reference_audio_url: str = None,
        reference_inputs: Optional[list] = None,
    ) -> list:
        """
        构建 content 数组
        
        Args:
            prompt: 文字描述
            first_frame_url: 首帧图片URL
            last_frame_url: 尾帧图片URL
            reference_image_url: 参考图片URL
            reference_video_url: 参考视频URL
            reference_inputs: 多参考输入列表，元素格式 {"type": "reference_image|reference_video", "url": "..."}
        
        Returns:
            content 列表
        """
        content = []

        # 互斥逻辑校验：多模态参考 (Reference) 与 首尾帧 (First/Last Frame) 互斥
        # 优先级：多模态参考 > 首尾帧。如果提供了多模态参考，则忽略首帧和尾帧。
        has_reference = bool(
            reference_image_url or 
            reference_video_url or 
            reference_audio_url or 
            (reference_inputs and len(reference_inputs) > 0)
        )

        if has_reference and (first_frame_url or last_frame_url):
            logger.warning(
                f"[Volcano API] 检测到多模态参考与首尾帧组件冲突。优先保留多模态参考，将丢弃首帧({bool(first_frame_url)})/尾帧({bool(last_frame_url)})。"
            )
            first_frame_url = None
            last_frame_url = None

        if prompt:
            content.append({"type": "text", "text": prompt})

        if first_frame_url:
            content.append({
                "type": "image_url",
                "image_url": {"url": first_frame_url},
                "role": "first_frame",
            })

        if last_frame_url:
            content.append({
                "type": "image_url",
                "image_url": {"url": last_frame_url},
                "role": "last_frame",
            })

        if reference_image_url:
            content.append({
                "type": "image_url",
                "image_url": {"url": reference_image_url},
                "role": "reference_image",
            })

        if reference_video_url:
            content.append({
                "type": "video_url",
                "video_url": {"url": reference_video_url},
                "role": "reference_video",
            })

        if reference_audio_url:
            content.append({
                "type": "audio_url",
                "audio_url": {"url": reference_audio_url},
                "role": "reference_audio",
            })

        # 多参考输入优先；如果存在 reference_inputs，则不再重复追加单一 reference_image_url/reference_video_url/reference_audio_url。
        if reference_inputs:
            # 移除之前可能追加的单参考，避免重复。
            content = [
                item for item in content
                if item.get("role") not in ("reference_image", "reference_video", "reference_audio")
            ]
            for ref in reference_inputs:
                ref_type = ref.get("type")
                ref_url = ref.get("url")
                if not ref_type or not ref_url:
                    continue
                if ref_type == "reference_image":
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": ref_url},
                        "role": "reference_image",
                    })
                elif ref_type == "reference_video":
                    content.append({
                        "type": "video_url",
                        "video_url": {"url": ref_url},
                        "role": "reference_video",
                    })
                elif ref_type == "reference_audio":
                    content.append({
                        "type": "audio_url",
                        "audio_url": {"url": ref_url},
                        "role": "reference_audio",
                    })

        return content

    @staticmethod
    def _safe_payload_for_log(payload: dict) -> dict:
        """构造可安全打印的 payload 摘要，避免日志过长。"""
        # 兼容 content 作为字符串的情况
        prompt_text = payload.get("prompt", "")
        if isinstance(payload.get("content"), str):
            prompt_text = payload.get("content", "")

        safe_payload = {
            "model": payload.get("model"),
            "ratio": payload.get("ratio"),
            "duration": payload.get("duration"),
            "watermark": payload.get("watermark"),
            "generate_audio": payload.get("generate_audio"),
            "return_last_frame": payload.get("return_last_frame"),
            "prompt_preview": prompt_text[:120],
        }

        # 处理 Ark/Standard 格式的 content (当 content 是列表时)
        if "content" in payload and isinstance(payload["content"], list):
            safe_payload["content_count"] = len(payload["content"] or [])
            safe_payload["content_summary"] = []
            for item in payload["content"] or []:
                item_type = item.get("type")
                role = item.get("role")
                summary = {"type": item_type, "role": role}
                if item_type == "text":
                    text = item.get("text") or ""
                    summary["text_preview"] = text[:50]
                else:
                    url = (item.get(item_type) or {}).get("url") or ""
                    summary["url_preview"] = url[:1024]
                    safe_payload["content_summary"].append(summary)
        
        # 处理 Seedance 2.0 格式的扁平数组
        for key in ["image_urls", "video_urls", "audio_urls"]:
            if key in payload:
                urls = payload[key] or []
                safe_payload[f"{key}_count"] = len(urls)
                safe_payload[f"{key}_preview"] = [url[:60] + "..." for url in urls[:3]]
        
        return safe_payload

    @staticmethod
    def _build_http_error_message(prefix: str, exc: httpx.HTTPStatusError, payload: Optional[dict] = None) -> str:
        """拼接包含状态码、响应体、关键请求参数的详细错误信息。"""
        response = exc.response
        request = exc.request

        try:
            body_obj = response.json()
            body_text = json.dumps(body_obj, ensure_ascii=False)
        except Exception:
            body_text = response.text or ""

        body_text = body_text[:4000]

        details = [
            f"{prefix}",
            f"status={response.status_code}",
            f"method={request.method}",
            f"url={request.url}",
        ]

        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-tt-logid")
            or response.headers.get("x-trace-id")
        )
        if request_id:
            details.append(f"request_id={request_id}")

        if payload is not None:
            details.append(f"payload={json.dumps(payload, ensure_ascii=False)}")

        if body_text:
            details.append(f"response_body={body_text}")

        return " | ".join(details)

    @staticmethod
    def _extract_error_code(exc: httpx.HTTPStatusError) -> str:
        """从响应体中提取火山方舟错误码，解析失败时返回空字符串。"""
        try:
            body = exc.response.json()
            # 获取 Ark/Standard 格式: {"error": {"code": "..."}}
            error_code = (body.get("error") or {}).get("code", "")
            
            # 处理 Seedance 2.0 的特殊格式: {"detail": "余额不足：..."}
            if not error_code and exc.response.status_code == 403:
                detail = body.get("detail", "")
                if "余额不足" in detail:
                    return "InsufficientBalance"
            
            return error_code or ""
        except Exception as e:
            logger.warning(f"[Volcano API] 错误码提取失败: {e}")
            return ""

    async def create_video_task(
        self,
        model: str,
        prompt: str = None,
        first_frame_url: str = None,
        last_frame_url: str = None,
        reference_image_url: str = None,
        reference_video_url: str = None,
        reference_audio_url: str = None,
        reference_inputs: Optional[list] = None,
        ratio: str = "16:9",
        duration: int = 5,
        generate_audio: bool = True,
        watermark: bool = True,
        return_last_frame: bool = False,
        draft: bool = False,
        resolution: str = None,
        seed: int = None,
        camera_fixed: bool = None,
        service_tier: str = None,
        execution_expires_after: int = None,
    ) -> dict:
        """
        创建视频生成任务
        
        POST /api/v3/contents/generations/tasks
        
        Returns:
            API 响应，包含 task_id 等信息
        """
        logger.info(f"[Volcano API] 创建任务 | 模型: {model} | 比例: {ratio} | 时长: {duration}s | 参考输入: {len(reference_inputs) if reference_inputs else 0}个")
        content = self._build_content(
            prompt=prompt,
            first_frame_url=first_frame_url,
            last_frame_url=last_frame_url,
            reference_image_url=reference_image_url,
            reference_video_url=reference_video_url,
            reference_audio_url=reference_audio_url,
            reference_inputs=reference_inputs,
        )

        if self._is_seedance20_model(model):
            if not self.seedance20_url or not self.seedance20_key:
                msg = "Seedance 2.0 配置缺失：请检查 SEEDANCE20_URL 与 SEEDANCE20_KEY"
                logger.error(f"[Volcano API] {msg}")
                raise RuntimeError(msg)

            # 官方文档规范：
            # prompt 中引用素材的正确格式是「图片n」「视频n」「音频n」（中文），
            # n 为该素材在同类素材中的排序（从1开始计数）。
            # 参见：https://www.volcengine.com/docs/82379/2291680 第"提示词技巧"章节
            import re
            cleaned_prompt = prompt or ""
            # 将前端内部 Token 格式 (@参考图片N_name) 统一转换为官方中文格式（图片N）
            original_tokens = re.findall(r'@参考(?:图片|视频|音频)\d+(?:_[^\s]*)?', cleaned_prompt)
            cleaned_prompt = re.sub(r'@参考图片(\d+)(?:_[^\s]*)?', r'图片\1', cleaned_prompt)
            cleaned_prompt = re.sub(r'@参考视频(\d+)(?:_[^\s]*)?', r'视频\1', cleaned_prompt)
            cleaned_prompt = re.sub(r'@参考音频(\d+)(?:_[^\s]*)?', r'音频\1', cleaned_prompt)

            # 自动补全缺失的素材引用。
            # 如果提供了参考素材但 prompt 中缺少对应的「图片n」「视频n」「音频n」引用，
            # 模型可能无法正确感知该素材的意图，导致生成结果与预期不符（如画面错乱）。
            img_idx, vid_idx, aud_idx = 0, 0, 0
            if reference_inputs:
                for ref in reference_inputs:
                    t = ref.get("type")
                    if t == "reference_image":
                        img_idx += 1
                        if f"图片{img_idx}" not in cleaned_prompt:
                            cleaned_prompt += f" 图片{img_idx}"
                    elif t == "reference_video":
                        vid_idx += 1
                        if f"视频{vid_idx}" not in cleaned_prompt:
                            cleaned_prompt += f" 视频{vid_idx}"
                    elif t == "reference_audio":
                        aud_idx += 1
                        if f"音频{aud_idx}" not in cleaned_prompt:
                            cleaned_prompt += f" 音频{aud_idx}"
            else:
                # 兼容旧接口单参考参数
                if reference_image_url and "图片1" not in cleaned_prompt:
                    cleaned_prompt += " 图片1"
                if reference_video_url and "视频1" not in cleaned_prompt:
                    cleaned_prompt += " 视频1"
                if reference_audio_url and "音频1" not in cleaned_prompt:
                    cleaned_prompt += " 音频1"

            # 重新构建遵循标准的 content 列表
            s2_content = self._build_content(
                prompt=cleaned_prompt,
                first_frame_url=first_frame_url,
                last_frame_url=last_frame_url,
                reference_image_url=reference_image_url,
                reference_video_url=reference_video_url,
                reference_audio_url=reference_audio_url,
                reference_inputs=reference_inputs,
            )

            payload = {
                "model": model,
                "content": s2_content,
                "ratio": ratio,
                "duration": duration,
                "generate_audio": generate_audio,
                "watermark": watermark,
            }

            logger.info(f"[Volcano API] Seedance 2.0 准备提交 | 映射后提示词: {cleaned_prompt[:100]}... | 原始Token: {original_tokens}")

            # 设置较长的超时时间（120秒），因为火山 API 在创建任务时可能需要花时间去下载验证视频分辨率/时长
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    response = await client.post(
                        f"{self.seedance20_url}/contents/generations/tasks",
                        headers=self._get_seedance20_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    result = response.json()
                    logger.info(f"[Volcano API] Seedance 2.0 任务创建成功 | 任务ID: {result.get('id')}")
                    return {"id": result.get("id"), "api_request_raw": payload, "api_response_raw": result}
                except httpx.HTTPStatusError as e:
                    payload_log = self._safe_payload_for_log(payload)
                    msg = self._build_http_error_message("创建 Seedance 2.0 任务失败", e, payload=payload_log)
                    error_code = self._extract_error_code(e)
                    logger.error(f"[创建任务失败] 错误信息: {msg}, 错误码: {error_code}, HTTP状态: {e.response.status_code}")
                    raise VolcanoAPIError(
                        msg,
                        error_code=error_code,
                        http_status=e.response.status_code,
                    ) from e

        payload = {
            "model": model,
            "content": content,
            "ratio": ratio,
            "duration": duration,
            "watermark": watermark,
        }

        # 保留旧模型分支（当前仅 Seedance 2.0 可用）
        if False:
            payload["generate_audio"] = generate_audio
            payload["return_last_frame"] = return_last_frame
            payload["draft"] = draft

            if resolution:
                payload["resolution"] = resolution
            if seed is not None:
                payload["seed"] = seed
            if camera_fixed is not None:
                payload["camera_fixed"] = camera_fixed
            if service_tier:
                payload["service_tier"] = service_tier
            if execution_expires_after is not None:
                payload["execution_expires_after"] = execution_expires_after

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/v3/contents/generations/tasks",
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[Volcano API] 任务创建成功 | 模型: {model} | 任务ID: {result.get('id')}")
                return {"id": result.get("id"), "api_request_raw": payload, "api_response_raw": result}
            except httpx.HTTPStatusError as e:
                payload_log = self._safe_payload_for_log(payload)
                msg = self._build_http_error_message("创建火山视频任务失败", e, payload=payload_log)
                error_code = self._extract_error_code(e)
                logger.error(f"[创建任务失败] 错误信息: {msg}, 错误码: {error_code}, HTTP状态: {e.response.status_code}")
                raise VolcanoAPIError(
                    msg,
                    error_code=error_code,
                    http_status=e.response.status_code,
                ) from e

    async def query_task(self, task_id: str, model: Optional[str] = None, max_retries: int = 3) -> dict:
        """
        查询视频生成任务状态
        
        GET /api/v3/contents/generations/tasks/{task_id}
        
        Returns:
            任务详情，包含 status, content(video_url) 等
        """
        base_url = self.seedance20_url if self._is_seedance20_model(model) else self.base_url
        endpoint = f"/contents/generations/tasks/{task_id}" if self._is_seedance20_model(model) else f"/api/v3/contents/generations/tasks/{task_id}"
        headers = self._get_seedance20_headers() if self._is_seedance20_model(model) else self.headers

        if self._is_seedance20_model(model) and (not self.seedance20_url or not self.seedance20_key):
             msg = "Seedance 2.0 配置缺失：请检查 SEEDANCE20_URL 与 SEEDANCE20_KEY"
             logger.error(f"[Volcano API] {msg}")
             raise RuntimeError(msg)

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(f"{base_url}{endpoint}", headers=headers)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                # 检查是否为网关类错误（502, 503, 504）
                if e.response.status_code in (502, 503, 504):
                    logger.warning(f"[Volcano API] 查询重试({attempt+1}/{max_retries}) | 状态: {e.response.status_code} | URL: {e.request.url}")
                    last_exc = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))  # 指数退避
                        continue
                
                # 业务错误或其他致命错误直接抛出
                msg = self._build_http_error_message("查询火山任务失败", e)
                logger.error(msg)
                if e.response.status_code in (502, 503, 504):
                    raise VolcanoGatewayError(msg, http_status=e.response.status_code) from e
                raise RuntimeError(msg) from e
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(f"[Volcano API] 连接/超时重试({attempt+1}/{max_retries}) | 错误: {str(e)}")
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise VolcanoGatewayError(f"API 连接超时/异常: {str(e)}", http_status=504) from e
        
        # 如果重试耗尽且是因为网关错误
        if last_exc and isinstance(last_exc, httpx.HTTPStatusError):
             msg = self._build_http_error_message("查询火山任务最终重试失败 (网关异常)", last_exc)
             raise VolcanoGatewayError(msg, http_status=last_exc.response.status_code) from last_exc
        
        raise RuntimeError("查询任务遇到未知异常，重试已耗尽")

    async def query_task_list(
        self,
        page_num: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> dict:
        """
        查询视频生成任务列表
        
        GET /api/v3/contents/generations/tasks
        """
        params = {"page_num": page_num, "page_size": page_size}
        if status:
            params["status"] = status

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/v3/contents/generations/tasks",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                msg = self._build_http_error_message("查询火山任务列表失败", e, payload=params)
                logger.error(msg)
                raise RuntimeError(msg) from e

    async def cancel_task(self, task_id: str, model: Optional[str] = None) -> dict:
        """
        取消或删除视频生成任务
        
        DELETE /api/v3/contents/generations/tasks/{task_id}
        
        行为（官方文档）:
        - queued    -> 取消排队, 状态变为 cancelled
        - running   -> 不支持，返回错误
        - succeeded/failed/expired -> 删除记录，无返回参数
        - cancelled -> 不支持
        """
        if self._is_seedance20_model(model):
            if not self.seedance20_url or not self.seedance20_key:
                msg = "Seedance 2.0 配置缺失：请检查 SEEDANCE20_URL 与 SEEDANCE20_KEY"
                logger.error(f"[Volcano API] {msg}")
                raise RuntimeError(msg)

            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    response = await client.delete(
                        f"{self.seedance20_url}/contents/generations/tasks/{task_id}",
                        headers=self._get_seedance20_headers(),
                    )
                    response.raise_for_status()
                    # 官方文档：本接口无返回参数，body 可能为空
                    text = response.text.strip()
                    return response.json() if text else {"success": True}
                except httpx.HTTPStatusError as e:
                    msg = self._build_http_error_message("取消 Seedance 2.0 任务失败", e)
                    logger.error(msg)
                    raise RuntimeError(msg) from e

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.delete(
                    f"{self.base_url}/api/v3/contents/generations/tasks/{task_id}",
                    headers=self.headers,
                )
                response.raise_for_status()
                # 官方文档：本接口无返回参数，body 可能为空（204 或空 body）
                text = response.text.strip()
                return response.json() if text else {"success": True}
            except httpx.HTTPStatusError as e:
                msg = self._build_http_error_message("取消火山任务失败", e)
                logger.warning(msg)
                # running 状态不支持取消，不视为致命错误，上层自行决定是否继续本地标记
                raise RuntimeError(msg) from e

    async def download_video(self, video_url: str) -> bytes:
        """
        流式下载视频文件（从火山引擎临时链接）
        
        Args:
            video_url: 火山引擎返回的临时视频链接
        
        Returns:
            视频文件字节数据
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(video_url)
            response.raise_for_status()
            return response.content


# 全局 API 客户端实例
volcano_api = VolcanoVideoAPI()
