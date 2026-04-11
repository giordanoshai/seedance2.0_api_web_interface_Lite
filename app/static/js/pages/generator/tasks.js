window.AppModules = window.AppModules || {};
window.AppModules.generator_tasks = {
    data() {
        return {
            generating: false,
            cancelling: false,
            statusText: '准备中...',
            pollingStatus: '',
            volcanoStatus: '',
            progressPercent: 0,
            currentTaskId: null,
            pollTimers: {},
            activeTasks: {}, // 任务详情映射: { taskId: { statusText, pollingStatus, volcanoStatus, progressPercent } }
            _taskNotified: {},
            capacityInfo: {},
            capacityPollTimer: null,
            params: {
                ratio: '16:9',
                duration: 4,
                generate_audio: true,
                watermark: false,
                return_last_frame: false,
                draft: false,
                resolution: '720p',
                seed: '',
                camera_fixed: false,
                service_tier: 'default',
                execution_expires_after: 172800,
            },
            confirmModal: {
                show: false,
                title: '',
                message: '',
                confirmText: '确定',
                cancelText: '取消',
                resolve: null,
            },
        };
    },
    methods: {
        async submitTask(options = null) {
            const promptTextToSend = options?.promptText ?? this.promptText;
            const reusedAttachments = Array.isArray(options?.reusedAttachments) ? options.reusedAttachments : [];
            if (this.generating) return;
            if (!promptTextToSend.trim() && this.attachments.length === 0 && !this.firstFrame && !this.lastFrame && reusedAttachments.length === 0) return;

            this.applyDraftConstraints();

            const modelCfg = this.models[this.selectedModel];
            if (!modelCfg?.available) {
                this.addMessage('system', `模型 ${modelCfg?.name} 暂未开放 API 调用，请选择其他模型。`);
                return;
            }

            if (!this.currentConversation) {
                await this.createNewConversation();
                if (!this.currentConversation) {
                    this.addMessage('system', '❌ 无法创建对话，请重试。');
                    return;
                }
            }

            this.generating = true; // 防抖保护

            // --- 捕获当前状态以供后台提交 ---
            const currentPrompt = promptTextToSend;
            const currentAttachments = [...this.attachments];
            const currentFirstFrame = this.firstFrame ? { ...this.firstFrame } : null;
            const currentLastFrame = this.lastFrame ? { ...this.lastFrame } : null;
            const currentSelectedModel = this.selectedModel;
            const currentParams = JSON.parse(JSON.stringify(this.params));
            // 核心修复：清理前先捕捉所有候选引用，否则 resolveReferenceInputsByMentions 会失效
            const currentCandidates = typeof this.getMentionCandidateList === 'function' ? this.getMentionCandidateList() : [];

            // 👉 【未引用媒体校验逻辑】
            // 1. 用正则提取提示词中所有 Token，确保精确匹配（区分 @参考图片1 和 @参考图片10）
            const matchedTokens = Array.from(currentPrompt.matchAll(/@参考(图片|视频|音频)\d+/g)).map(m => m[0]);

            const unreferencedItems = currentCandidates.filter(c => {
                const isReferenceRole = c.role && (c.role.startsWith('reference_') || ['first_frame', 'last_frame'].includes(c.role));
                // 提取素材的基础 Token
                const baseToken = c.token ? c.token.match(/(@参考(?:图片|视频|音频)\d+)/)?.[1] : null;
                
                // 2. 比对是否被引用
                const isMentioned = baseToken && matchedTokens.includes(baseToken);
                
                // 仅校验当前对话刚上传/选中的参考素材 (source === 'current')
                // 排除首尾帧（首尾帧通常不需要在 prompt 中 @ 引用，除非特定需要，这里这里暂时不强制校验）
                const isFrameRole = ['first_frame', 'last_frame'].includes(c.role);
                return c.source === 'current' && !isFrameRole && !isMentioned;
            });

            if (unreferencedItems.length > 0) {
                const tokenList = unreferencedItems.map(i => i.token).join('<br>• ');
                const isConfirmed = await this.showConfirm(
                    '存在未引用的素材',
                    `您上传/选择了以下素材，但没有在提示词中引用它们：<br><br>• ${tokenList}<br><br>未引用的参考素材可能不会被 AI 正确识别。您确定要坚持发送吗？`
                );
                if (!isConfirmed) {
                    this.generating = false; // 用户选择取消
                    return;
                }
            }


            // --- 立即清空UI状态 ---
            // 注意：重试模式下，使用的选项不会污染当前正在编辑的内容。如果是正常点击发送，则清空。
            if (!options) {
                this.promptText = '';
                this.attachments = [];
                this.firstFrame = null;
                this.lastFrame = null;
                if (this.$refs) {
                    if (this.$refs.firstFrameInput) this.$refs.firstFrameInput.value = '';
                    if (this.$refs.lastFrameInput) this.$refs.lastFrameInput.value = '';
                }
                if (typeof this.updateCachedMentionableRefs === 'function') {
                    this.updateCachedMentionableRefs(); // 清除媒体引用UI
                }
            }
            
            // 稍等片刻后解除锁定，使用户能立即输入下一并发任务
            setTimeout(() => { this.generating = false; }, 300);

            this.currentVideo = null;
            this.statusText = '正在准备任务...';
            this.progressPercent = 5;

            const userAttachments = [];
            if (currentFirstFrame) userAttachments.push({ role: 'first_frame', type: 'image', preview: currentFirstFrame.preview });
            if (currentLastFrame) userAttachments.push({ role: 'last_frame', type: 'image', preview: currentLastFrame.preview });
            currentAttachments.forEach(a => userAttachments.push({ id: a.id, type: a.type, preview: a.preview, role: a.role }));
            // reusedAttachments 中已存在于 currentAttachments 的项（重试场景）跳过，避免UI重复显示
            const attachmentIdSet = new Set(currentAttachments.map(a => a.id));
            reusedAttachments.forEach(a => {
                if (attachmentIdSet.has(a.id)) return;
                userAttachments.push({
                    type: a.type || 'image',
                    role: a.role || 'reference_image',
                    preview: a.signed_url || null,
                    signed_url: a.signed_url || null,
                    storage_path: a.storage_path,
                });
            });

            const userMsg = {
                role: 'user',
                text: currentPrompt || '(仅图片/视频输入)',
                time: new Date().toLocaleString('zh-CN', { 
                    year: 'numeric', 
                    month: '2-digit', 
                    day: '2-digit', 
                    hour: '2-digit', 
                    minute: '2-digit', 
                    hour12: false 
                }).replace(/\//g, '-'),
                attachments: userAttachments,
            };
            this.messages.push(userMsg);

            // 👉 【新增代码】立刻推入一条“处理中”的系统占位消息
            const pendingMsgId = 'pending_' + Date.now(); // 生成一个临时ID
            const pendingSysMsg = {
                id: pendingMsgId,
                role: 'system',
                text: '<div class="flex items-center gap-2"><svg class="animate-spin h-4 w-4 text-primary" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg><span class="text-indigo-300">正在解析请求并上传素材，请稍候...</span></div>',
                time: userMsg.time,
                // 下面这些属性必须先定义为 null，框架才会去“监视”它们的后续变化
                taskId: null,
                promptSnippet: null,
                modelName: null,
                duration: null,
                resolution: null,
                ratio: null
            };
            this.messages.push(pendingSysMsg);
            
            this.scrollChat();

            if (this.messages.length <= 1 && currentPrompt.trim()) {
                const title = currentPrompt.trim().substring(0, 40);
                try {
                    await fetch(`/api/conversations/${this.currentConversation.id}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ title }),
                    });
                    this.currentConversation.title = title;
                    const conv = this.conversations.find(c => c.id === this.currentConversation.id);
                    if (conv) conv.title = title;
                } catch (e) {
                    console.error('更新对话标题失败:', e);
                }
            }

            try {
                this.statusText = '上传附件中...';
                this.progressPercent = 15;

                let firstFramePath = reusedAttachments.find(a => a.role === 'first_frame')?.storage_path || null;
                let lastFramePath = reusedAttachments.find(a => a.role === 'last_frame')?.storage_path || null;
                const uploadedReferences = [];

                const uploadedReferencesMap = {};
                const uploadPromises = []; // 使用并行上传解决"卡一下"问题

                if (this.enableFrames && currentFirstFrame) {
                    if (currentFirstFrame.file) {
                        uploadPromises.push(this.uploadToStorage(currentFirstFrame.file).then(path => {
                            firstFramePath = path;
                            uploadedReferencesMap['sys_first_frame'] = path;
                        }));
                    } else if (currentFirstFrame.storage_path) {
                        firstFramePath = currentFirstFrame.storage_path;
                        uploadedReferencesMap['sys_first_frame'] = firstFramePath;
                    }
                }
                if (this.enableFrames && currentLastFrame) {
                    if (currentLastFrame.file) {
                        uploadPromises.push(this.uploadToStorage(currentLastFrame.file).then(path => {
                            lastFramePath = path;
                            uploadedReferencesMap['sys_last_frame'] = path;
                        }));
                    } else if (currentLastFrame.storage_path) {
                        lastFramePath = currentLastFrame.storage_path;
                        uploadedReferencesMap['sys_last_frame'] = lastFramePath;
                    }
                }

                for (const att of currentAttachments) {
                    if (att.role === 'reference_image' || att.role === 'reference_video' || att.role === 'reference_audio') {
                        if (att.file) {
                            uploadPromises.push(this.uploadToStorage(att.file).then(path => {
                                uploadedReferencesMap[att.id] = path;
                                uploadedReferences.push({
                                    path,
                                    type: att.type || 'image',
                                    role: att.role,
                                    media_type: att.file?.type || null,
                                });
                            }));
                        } else if (reusedAttachments.some(r => r.id === att.id)) {
                            // 重用逻辑
                            uploadedReferencesMap[att.id] = att.storage_path || null;
                        } else {
                            uploadedReferencesMap[att.id] = att.storage_path || null;
                            uploadedReferences.push({
                                path: att.storage_path || null,
                                type: att.type || 'image',
                                role: att.role,
                                media_type: att.file?.type || null,
                            });
                        }
                    }
                }

                // 并行等待所有上传完成
                await Promise.all(uploadPromises);
 
                // 将成功上传的 storage_path 回填给刚推入本地 UI 的 userMsg，确保后续从该消息重试时路径正确
                userMsg.attachments.forEach(ua => {
                    if (ua.role === 'first_frame' && firstFramePath) ua.storage_path = firstFramePath;
                    if (ua.role === 'last_frame' && lastFramePath) ua.storage_path = lastFramePath;
                    if (ua.id && uploadedReferencesMap[ua.id]) {
                        ua.storage_path = uploadedReferencesMap[ua.id];
                    }
                });

                const resolvedReferenceInputs = this.resolveReferenceInputsByMentions(
                    currentPrompt,
                    uploadedReferencesMap,
                    currentCandidates
                );

                reusedAttachments.forEach(att => {
                    if ((att.role === 'reference_image' || att.role === 'reference_video' || att.role === 'reference_audio') && att.storage_path) {
                        if (!resolvedReferenceInputs.some(r => r.storage_path === att.storage_path)) {
                            resolvedReferenceInputs.push({
                                role: att.role,
                                storage_path: att.storage_path,
                                media_type: att.media_type || null,
                            });
                        }
                    }
                });

                const refImagePath = resolvedReferenceInputs.find(r => r.role === 'reference_image')?.storage_path || null;
                const refVideoPath = resolvedReferenceInputs.find(r => r.role === 'reference_video')?.storage_path || null;

                const persistedAttachments = [];
                reusedAttachments.forEach(att => {
                    persistedAttachments.push({
                        type: att.type || 'image',
                        role: att.role || 'reference_image',
                        storage_path: att.storage_path,
                    });
                });
                if (firstFramePath && !reusedAttachments.some(a => a.role === 'first_frame')) {
                    persistedAttachments.push({ type: 'image', role: 'first_frame', storage_path: firstFramePath });
                }
                if (lastFramePath && !reusedAttachments.some(a => a.role === 'last_frame')) {
                    persistedAttachments.push({ type: 'image', role: 'last_frame', storage_path: lastFramePath });
                }
                uploadedReferences.forEach(ref => {
                    persistedAttachments.push({
                        type: ref.type,
                        role: ref.role,
                        storage_path: ref.path,
                    });
                });

                resolvedReferenceInputs.forEach(ref => {
                    if (!ref.storage_path) return;
                    const exists = persistedAttachments.some(
                        p => p.role === ref.role && p.storage_path === ref.storage_path
                    );
                    if (!exists) {
                        persistedAttachments.push({
                            type: ref.type || (ref.role === 'reference_video' ? 'video' : ref.role === 'reference_audio' ? 'audio' : 'image'),
                            role: ref.role,
                            storage_path: ref.storage_path,
                        });
                    }
                });

                this.statusText = '提交任务至 AI...';
                this.progressPercent = 30;

                try {
                    await fetch('/api/messages', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            conversation_id: this.currentConversation.id,
                            user_id: this.user.id,
                            role: 'user',
                            text: currentPrompt || '(仅图片/视频输入)',
                            attachments: persistedAttachments,
                        }),
                    });
                } catch (e) {
                    console.error('保存用户消息失败:', e);
                }

                const resp = await fetch('/api/create_task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: currentSelectedModel,
                        prompt: currentPrompt,
                        first_frame_path: firstFramePath,
                        last_frame_path: lastFramePath,
                        reference_inputs: resolvedReferenceInputs.map(r => {
                            // 后端只接受 reference_image/video/audio 这三种 type
                            // 如果用户提及的是首帧或尾帧，映射为参考图类型
                            let effectiveType = r.role;
                            if (r.role === 'first_frame' || r.role === 'last_frame') {
                                effectiveType = 'reference_image';
                            }
                            return {
                                type: effectiveType,
                                storage_path: r.storage_path,
                                media_type: r.media_type || null,
                            };
                        }),
                        reference_image_path: refImagePath,
                        reference_video_path: refVideoPath,
                        reference_audio_path: resolvedReferenceInputs.find(r => r.role === 'reference_audio')?.storage_path || null,
                        ratio: currentParams.ratio,
                        duration: parseInt(currentParams.duration),
                        generate_audio: currentParams.generate_audio,
                        watermark: currentParams.watermark,
                        return_last_frame: currentParams.return_last_frame,
                        draft: currentParams.draft,
                        resolution: (currentSelectedModel === 'seedance-1.5-pro' || currentSelectedModel === 'seedance-2.0')
                            ? currentParams.resolution
                            : null,
                        seed: currentSelectedModel === 'seedance-1.5-pro' && currentParams.seed !== '' ? parseInt(currentParams.seed) : null,
                        camera_fixed: currentSelectedModel === 'seedance-1.5-pro' ? currentParams.camera_fixed : null,
                        service_tier: currentSelectedModel === 'seedance-1.5-pro' ? currentParams.service_tier : null,
                        execution_expires_after: currentSelectedModel === 'seedance-1.5-pro'
                            ? parseInt(currentParams.execution_expires_after)
                            : null,
                        conversation_id: this.currentConversation.id,
                    }),
                });

                if (!resp.ok) {
                    const err = await resp.json();
                    let errorMsg = '提交失败';
                    if (err.detail) {
                        if (typeof err.detail === 'object') {
                            errorMsg = err.detail.hint || err.detail.message || JSON.stringify(err.detail);
                        } else {
                            errorMsg = err.detail;
                        }
                    }
                    throw new Error(errorMsg);
                }

                const result = await resp.json();
                this.currentTaskId = result.task_id;

                const snippet = (currentPrompt || '').replace(/@参考(图片|视频|音频)\d+(_[^\s]+)?/g, '').trim().slice(0, 20) || '';
                const taskMeta = {
                    snippet,
                    modelName: this.models[currentSelectedModel]?.name || currentSelectedModel,
                    duration: currentParams.duration,
                    resolution: currentParams.resolution,
                    ratio: currentParams.ratio,
                };


                // 👉 【修改代码】从代理数组中找到那条消息并更新它，这样就能触发 UI 刷新！
                const targetMsg = this.messages.find(m => m.id === pendingMsgId);
                if (targetMsg) {
                    targetMsg.text = `任务已提交！<br><span class="text-primary font-bold">任务ID:</span> ${result.task_id}<br>正在排队处理...`;
                    targetMsg.taskId = result.task_id;
                    targetMsg.promptSnippet = taskMeta.snippet;
                    targetMsg.modelName = taskMeta.modelName;
                    targetMsg.duration = taskMeta.duration;
                    targetMsg.resolution = taskMeta.resolution;
                    targetMsg.ratio = taskMeta.ratio;
                }
                this.statusText = '视频生成中...';
                this.progressPercent = 40;

                try {
                    await fetch('/api/messages', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            conversation_id: this.currentConversation.id,
                            user_id: this.user.id,
                            role: 'system',
                            text: `任务已提交！任务ID: ${result.task_id}，正在排队处理...`,
                            task_id: result.task_id,
                            attachments: [{
                                type: 'task_metadata',
                                promptSnippet: taskMeta.snippet,
                                modelName: taskMeta.modelName,
                                duration: taskMeta.duration,
                                resolution: taskMeta.resolution,
                                ratio: taskMeta.ratio,
                            }]
                        }),
                    });
                } catch (e) {
                    console.error('保存系统消息失败:', e);
                }

                // 准备开始轮询：将任务初始状态存入 activeTasks
                this.activeTasks[result.task_id] = {
                    statusText: '视频生成中...',
                    pollingStatus: '',
                    volcanoStatus: 'queued',
                    progressPercent: 40,
                    cancelling: false,
                };

                this.startPolling(result.task_id, taskMeta);
            } catch (e) {
                console.error('[提交任务失败]', e);
                const errSnippet = (currentPrompt || '').slice(0, 15);
                const errorStr = `❌ 任务提交失败 | ${errSnippet}: ${e.message}`;
                // 👉 【修改代码】在报错时，同样找出代理对象并把转圈替换为报错文字
                const errorTargetMsg = this.messages.find(m => m.id === pendingMsgId);
                if (errorTargetMsg) {
                    errorTargetMsg.text = errorStr;
                }
                
                try {
                    await fetch('/api/messages', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            conversation_id: this.currentConversation.id,
                            user_id: this.user.id,
                            role: 'system',
                            text: errorStr,
                        }),
                    });
                } catch (err) {}
            }
        },

        startPolling(taskId, taskMeta = {}) {
            let elapsed = 0;
            this._taskNotified[taskId] = false;
            
            // 为了防止如果 `check_status` 下载视频过慢导致请求堆叠（比如下载耗时15秒，setInterval 就会发3个请求）
            let isPollingActive = false;
            
            this.pollTimers[taskId] = setInterval(async () => {
                elapsed += 5;
                if (this.activeTasks[taskId]) {
                    this.activeTasks[taskId].pollingStatus = `已等待 ${elapsed}s`;
                }

                if (this._taskNotified[taskId] || isPollingActive) {
                    return;
                }

                isPollingActive = true;
                try {
                    const resp = await fetch(`/api/check_status/${taskId}`);
                    
                    if (!resp.ok) {
                        this._consecutivePollErrors = (this._consecutivePollErrors || 0) + 1;
                        if (this._consecutivePollErrors > 20) {
                            this._taskNotified[taskId] = true;
                            this.stopPolling(taskId);
                            delete this.activeTasks[taskId];
                            this.addMessage('system', `❌ 无法获取状态，连续多次网络或网关错误，已停止轮询。`, { taskId });
                        }
                        return;
                    }
                    this._consecutivePollErrors = 0;

                    const data = await resp.json();
                    if (this._taskNotified[taskId]) return;

                    if (data.status === 'succeeded') {
                        this._taskNotified[taskId] = true;
                        this.stopPolling(taskId);
                        if (this.activeTasks[taskId]) {
                            this.activeTasks[taskId].progressPercent = 100;
                        }
                        
                        this.currentVideo = data.signed_video_url;
                        this.addMessage('system', '✅ 视频生成成功！', {
                            taskId,
                            videoUrl: data.signed_video_url,
                            promptSnippet: taskMeta.snippet,
                            modelName: taskMeta.modelName,
                            duration: taskMeta.duration,
                            resolution: taskMeta.resolution,
                        });

                        try {
                            const snippetToSave = taskMeta.snippet || '视频已生成';
                            await fetch('/api/messages', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    conversation_id: this.currentConversation.id,
                                    user_id: this.user.id,
                                    role: 'system',
                                    text: '✅ 视频生成成功！',
                                    task_id: taskId,
                                    video_url: data.video_url,
                                    attachments: [{
                                        type: 'task_metadata',
                                        promptSnippet: snippetToSave,
                                        modelName: taskMeta.modelName,
                                        duration: taskMeta.duration,
                                        resolution: taskMeta.resolution,
                                        ratio: taskMeta.ratio,
                                    }]
                                }),
                            });
                        } catch (e) {}

                        // 清理任务状态
                        setTimeout(() => { delete this.activeTasks[taskId]; }, 3000);

                        try {
                            this.mediaLibraryLoaded = false;
                            if (typeof this.loadMediaLibrary === 'function') {
                                await this.loadMediaLibrary(true);
                            }
                        } catch (e) { }
                        await this.loadConversations();

                    } else if (['failed', 'cancelled', 'expired', 'timeout', 'error'].includes(data.status)) {
                        this._taskNotified[taskId] = true;
                        this.stopPolling(taskId);
                        
                        const statusMap = { 'failed': '失败', 'cancelled': '已取消', 'expired': '已过期', 'timeout': '超时', 'error': '发生错误' };
                        const statusText = statusMap[data.status] || data.status;
                        const errText = `❌ 任务${statusText}: ${data.error_message || ''}`;
                        this.addMessage('system', errText, { taskId });

                        try {
                            await fetch('/api/messages', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    conversation_id: this.currentConversation.id,
                                    user_id: this.user.id,
                                    role: 'system',
                                    text: errText,
                                    task_id: taskId,
                                }),
                            });
                        } catch (e) {}
                        
                        delete this.activeTasks[taskId];
                    } else if (data.status && this.activeTasks[taskId]) {
                        const statusMap = { queued: '排队中', running: '生成中', processing: '处理中' };
                        this.activeTasks[taskId].statusText = statusMap[data.status] || '处理中...';
                        this.activeTasks[taskId].volcanoStatus = data.status;
                    }
                } catch (e) {
                    console.error('轮询错误:', e);
                } finally {
                    isPollingActive = false;
                    // 在 catch/finally 中如果被标志为完成，停止定时器
                    if (this._taskNotified[taskId]) {
                        this.stopPolling(taskId);
                    }
                }
            }, 5000);
        },

        stopPolling(taskId = null) {
            if (taskId) {
                if (this.pollTimers[taskId]) {
                    clearInterval(this.pollTimers[taskId]);
                    delete this.pollTimers[taskId];
                }
            } else {
                // 停止所有
                Object.keys(this.pollTimers).forEach(id => {
                    clearInterval(this.pollTimers[id]);
                });
                this.pollTimers = {};
            }
        },

        async cancelTask(taskId) {
            if (!taskId || this.activeTasks[taskId]?.cancelling) return;
            if (this.activeTasks[taskId]) this.activeTasks[taskId].cancelling = true;

            try {
                const resp = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error('取消失败');

                const result = await resp.json().catch(() => ({}));
                const cancelledOnServer = result.cancelled_on_server !== false;
                const cancelMsg = cancelledOnServer
                    ? `⏹️ 任务已取消（${taskId}）`
                    : `⏹️ 任务已中止（服务端处理中，本地已标记取消 ${taskId}）`;

                this.addMessage('system', cancelMsg, { taskId });
                this.stopPolling(taskId);
                delete this.activeTasks[taskId];

                try {
                    await fetch('/api/messages', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            conversation_id: this.currentConversation.id,
                            user_id: this.user.id,
                            role: 'system',
                            text: cancelMsg,
                            task_id: taskId,
                        }),
                    });
                } catch (e) {}
            } catch (e) {
                if (this.activeTasks[taskId]) this.activeTasks[taskId].cancelling = false;
                this.addMessage('system', `❌ 取消任务失败: ${e.message}`);
            }
        },

        async restoreActiveTaskForCurrentConversation(conversationId) {
            if (!this.user?.id || !conversationId) return;

            try {
                const resp = await fetch(`/api/tasks?user_id=${this.user.id}&limit=100`);
                if (!resp.ok) return;

                const data = await resp.json();
                const activeStatuses = new Set(['processing', 'queued', 'running']);
                const tasks = (Array.isArray(data.tasks) ? data.tasks : []).filter(t => t && t.conversation_id === conversationId && activeStatuses.has(t.status));

                for (const activeTask of tasks) {
                    if (this.pollTimers[activeTask.id]) continue;

                    this.activeTasks[activeTask.id] = {
                        statusText: { queued: '排队中', running: '生成中', processing: '处理中' }[activeTask.status] || '处理中...',
                        pollingStatus: '恢复轮询中...',
                        volcanoStatus: activeTask.status,
                        progressPercent: 35,
                        cancelling: false,
                    };
                    const snippet = (activeTask.prompt || '').slice(0, 20);
                    this.startPolling(activeTask.id, { snippet });
                }
            } catch (e) {
                console.warn('恢复活跃任务失败:', e);
            }
        },

        // 保持之前已有的 fetchCapacity, startCapacityPolling, stopCapacityPolling...
        async fetchCapacity() {
            try {
                const resp = await fetch('/api/system/capacity');
                if (!resp.ok) return;
                const data = await resp.json();
                this.capacityInfo = (data && typeof data === 'object') ? data : {};
            } catch (e) {
                console.warn('获取模型容量失败:', e);
            }
        },

        startCapacityPolling() {
            this.fetchCapacity();
            if (this.capacityPollTimer) clearInterval(this.capacityPollTimer);
            this.capacityPollTimer = setInterval(() => this.fetchCapacity(), 10000);
        },

        stopCapacityPolling() {
            if (this.capacityPollTimer) {
                clearInterval(this.capacityPollTimer);
                this.capacityPollTimer = null;
            }
        },

        showConfirm(title, message, confirmText = '确定', cancelText = '取消') {
            return new Promise((resolve) => {
                this.confirmModal = {
                    show: true,
                    title,
                    message,
                    confirmText,
                    cancelText,
                    resolve,
                };
            });
        },
    },
};
