window.AppModules = window.AppModules || {};
window.AppModules.generator_ui = {
    data() {
        return {
            showAdvancedConfig: false,
        };
    },
    methods: {
        normalizeParamsForModel(modelId) {
            if (modelId === 'seedance-1.5-pro') {
                if (this.params.duration < 5) this.params.duration = 5;
                if (this.params.duration > 10) this.params.duration = 10;
                if (!['480p', '720p', '1080p'].includes(this.params.resolution)) {
                    this.params.resolution = '720p';
                }
            } else if (modelId === 'seedance-2.0') {
                // 2.0 默认配置：720P, 4秒, 音频 TRUE, 水印 FALSE
                this.params.resolution = '720p';
                this.params.duration = 4;
                this.params.generate_audio = true;
                this.params.watermark = false;
                this.params.draft = false;
            } else {
                this.params.duration = 5;
                this.params.resolution = '720p';
                this.params.draft = false;
            }
        },

        selectModel(key) {
            if (!this.models[key]?.available) return;
            this.selectedModel = key;
            this.normalizeParamsForModel(key);
            this.applyDraftConstraints();
        },

        applyDraftConstraints() {
            if (this.selectedModel === 'seedance-1.5-pro' && this.params.draft) {
                this.params.resolution = '480p';
                this.params.return_last_frame = false;
                this.params.service_tier = 'default';
            }
        },

        toggleDraftMode() {
            this.params.draft = !this.params.draft;
            this.applyDraftConstraints();
        },

        async regenerateFromMessage(msg) {
            if (this.generating) return;
            if (msg.role !== 'user') return;

            // 1. 设置 Prompt 文本
            this.promptText = msg.text;

            // 2. 清空并重置当前编辑区的附件状态
            this.attachments = [];
            this.firstFrame = null;
            this.lastFrame = null;
            this.enableFrames = false;

            if (msg.attachments && msg.attachments.length > 0) {
                const newAttachments = [];
                for (const att of msg.attachments) {
                    // 跳过任务元数据等非媒体附件
                    if (att.type === 'task_metadata') continue;
                    if (!att.storage_path && !att.signed_url && !att.preview) continue;

                    const attObj = {
                        id: 'att_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                        name: att.name || `历史${att.type === 'video' ? '视频' : att.type === 'audio' ? '音频' : '图片'}`,
                        type: att.type || 'image',
                        preview: att.preview || att.signed_url || (att.type === 'video' ? '/static/img/video_placeholder.png' : (att.type === 'audio' ? '/static/img/audio_placeholder.png' : null)),
                        signed_url: att.signed_url || null,
                        storage_path: att.storage_path,
                        role: att.role || 'reference_image',
                        isProcessing: false,
                        progress: 100
                    };

                    // 根据角色分配到不同的编辑槽位
                    if (att.role === 'first_frame') {
                        this.firstFrame = attObj;
                        this.enableFrames = true;
                    } else if (att.role === 'last_frame') {
                        this.lastFrame = attObj;
                        this.enableFrames = true;
                    } else if (att.role === 'reference_image' || att.role === 'reference_video' || att.role === 'reference_audio') {
                        newAttachments.push(attObj);
                    }
                }
                this.attachments = newAttachments;
            }

            // 3. 同步更新快捷引用区的渲染
            if (typeof this.updateCachedMentionableRefs === 'function') {
                this.updateCachedMentionableRefs();
            }

            // 4. 用户体验：自动聚焦到输入框，方便用户直接修改或发送
            this.$nextTick(() => {
                const input = document.getElementById('generatorPromptInput');
                if (input) {
                    input.focus();
                    // 将光标移至文末
                    input.selectionStart = input.selectionEnd = input.value.length;
                    // 触发展持高亮层的同步（如果需要）
                    if (typeof this.handlePromptInput === 'function') {
                        this.handlePromptInput({ target: input });
                    }
                }
            });
            
            // 不再调用 await this.submitTask(...)
        },

        toggleFramesEnabled() {
            this.enableFrames = !this.enableFrames;
            if (!this.enableFrames) {
                this.removeFirstFrame();
                this.removeLastFrame();
            }
        },

        getFrameAspectStyle() {
            if (this.params.ratio === '16:9') return 'aspect-video';
            if (this.params.ratio === '9:16') return 'aspect-[9/16]';
            if (this.params.ratio === '1:1') return 'aspect-square';
            if (this.params.ratio === '4:3') return 'aspect-[4/3]';
            if (this.params.ratio === '3:4') return 'aspect-[3/4]';
            return 'aspect-video';
        },

        formatDurationFromNow(dateStr) {
            if (!dateStr) return '';
            const now = new Date();
            const date = new Date(dateStr);
            const diff = now - date;
            const mins = Math.floor(diff / 60000);
            if (mins < 1) return '刚刚';
            if (mins < 60) return `${mins}分钟前`;
            const hours = Math.floor(mins / 60);
            if (hours < 24) return `${hours}小时前`;
            const days = Math.floor(hours / 24);
            return `${days}天前`;
        },
    },
};
