window.AppModules = window.AppModules || {};

window.AppModules.conversation = {
    data() {
        return {
            currentView: 'generator',
            selectedModel: 'seedance-2.0',
            models: {
                'seedance-2.0': {
                    id: 'doubao-seedance-2-0-260128',
                    name: 'Seedance 2.0',
                    available: true,
                    supports: ['text', 'first_frame', 'last_frame', 'reference_image', 'reference_video', 'reference_audio'],
                    ratios: ['16:9', '9:16', '1:1', '21:9', '4:3', '3:4'],
                    durations: [5, 10, 15],
                    has_audio: true,
                },
            },

            conversations: [],
            currentConversation: null,
            conversationsLoaded: false,
            deletingConversationId: null,

            messages: [],
            currentVideo: null,
            messagesHasMore: false,       // 是否还有更早的消息
            messagesOldestCursor: null,    // 最早那条消息的 created_at（游标）
            messagesLoadingMore: false,    // 是否正在加载更多

            videoModalUrl: null,
            showVideoModal: false,
            
            imageModalUrl: null,
            showImageModal: false,

            // 对话重命名弹窗
            showRenameModal: false,
            renameTitle: '',
            renamingConvId: null,
            renameSaving: false,
            renameError: '',
        };
    },

    methods: {
        async loadModelsFromBackend() {
            try {
                const resp = await fetch('/api/models');
                if (!resp.ok) return;
                const data = await resp.json();
                if (data && typeof data === 'object') {
                    this.models = data;
                }
            } catch (_e) {
                // 保留前端默认模型配置作为兜底
            }
        },

        async init() {
            await this.loadModelsFromBackend();
            if (typeof this.initAuth === 'function') {
                await this.initAuth();
            }
            if (typeof this.initGenerator === 'function') {
                await this.initGenerator();
            }
        },


        async loadConversations() {
            if (!this.user) return;
            try {
                const resp = await fetch(`/api/conversations?user_id=${this.user.id}`);
                const data = await resp.json();
                this.conversations = data.conversations || [];
                this.conversationsLoaded = true;
            } catch (e) {
                console.error('加载对话列表失败:', e);
            }
        },

        async createNewConversation() {
            if (!this.user) return;
            try {
                const resp = await fetch('/api/conversations', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: this.user.id,
                        title: '新对话',
                    }),
                });
                const data = await resp.json();
                if (data.success && data.conversation) {
                    this.conversations.unshift(data.conversation);
                    await this.switchConversation(data.conversation);
                }
            } catch (e) {
                console.error('创建对话失败:', e);
            }
        },

        async switchConversation(conv) {
            // 若点击的是当前正在轮询的对话，仅切换视图，不中断轮询
            if (this.currentConversation?.id === conv.id) {
                this.currentView = 'generator';
                this.$nextTick(() => this.scrollChat());
                return;
            }

            if (typeof this.stopPolling === 'function') {
                this.stopPolling();
            }
            this.generating = false;
            this.currentTaskId = null;
            this.pollingStatus = '';
            this.statusText = '准备中...';
            this.progressPercent = 0;

            this.currentConversation = conv;
            this.currentVideo = null;
            this.messages = [];
            this.messagesHasMore = false;
            this.messagesOldestCursor = null;
            this.messagesLoadingMore = false;
            this.currentView = 'generator';

            try {
                const resp = await fetch(`/api/conversations/${conv.id}/messages?limit=20`);
                const data = await resp.json();
                const rawMessages = data.messages || [];
                this.messagesHasMore = data.has_more || false;
                this.messagesOldestCursor = data.oldest_cursor || null;

                this._parseAndAppendMessages(rawMessages, 'append');

                for (let i = this.messages.length - 1; i >= 0; i--) {
                    if (this.messages[i].videoUrl) {
                        this.currentVideo = this.messages[i].videoUrl;
                        break;
                    }
                }

                this.scrollChat();
                this._anchoreScrollOnLoad();
                this._bindChatScrollListener();
                if (typeof this.restoreActiveTaskForCurrentConversation === 'function') {
                    await this.restoreActiveTaskForCurrentConversation(conv.id);
                }
            } catch (e) {
                console.error('加载对话消息失败:', e);
            }
        },

        async deleteConversation(convId) {
            if (!convId || this.deletingConversationId === convId) return;

            const targetConversation = this.conversations.find(c => c.id === convId);
            const title = targetConversation?.title || '这个对话';
            if (!window.confirm(`确认删除“${title}”？此操作不可恢复。`)) return;

            this.deletingConversationId = convId;
            try {
                const resp = await fetch(`/api/conversations/${convId}`, { method: 'DELETE' });
                if (!resp.ok) {
                    let errorMessage = '删除失败';
                    try {
                        const errorData = await resp.json();
                        errorMessage = errorData.detail || errorMessage;
                    } catch (_) {
                        // ignore json parse error
                    }
                    throw new Error(errorMessage);
                }

                this.conversations = this.conversations.filter(c => c.id !== convId);
                if (this.currentConversation?.id === convId) {
                    if (typeof this.stopPolling === 'function') {
                        this.stopPolling();
                    }
                    this.generating = false;
                    this.currentConversation = null;
                    this.messages = [];
                    this.currentVideo = null;
                    this.currentTaskId = null;
                    if (this.conversations.length > 0) {
                        await this.switchConversation(this.conversations[0]);
                    }
                }
            } catch (e) {
                console.error('删除对话失败:', e);
                this.addMessage('system', `❌ 删除对话失败: ${e.message}`);
            } finally {
                this.deletingConversationId = null;
            }
        },
        
        async renameConversation(conv) {
            if (!conv || !conv.id) return;
            this.renamingConvId = conv.id;
            this.renameTitle = conv.title || '';
            this.renameError = '';
            this.showRenameModal = true;
        },

        closeRenameModal() {
            this.showRenameModal = false;
            this.renamingConvId = null;
            this.renameTitle = '';
        },

        async saveConversationTitle() {
            if (!this.renamingConvId || !this.renameTitle.trim()) {
                this.renameError = '标题不能为空';
                return;
            }
            this.renameSaving = true;
            this.renameError = '';

            try {
                const resp = await fetch(`/api/conversations/${this.renamingConvId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: this.renameTitle.trim() }),
                });
                if (!resp.ok) throw new Error('保存失败');

                const data = await resp.json();
                if (data.success) {
                    // 更新列表中的标题
                    const conv = this.conversations.find(c => c.id === this.renamingConvId);
                    if (conv) conv.title = this.renameTitle.trim();
                    
                    // 如果改的是当前选中的对话，也要同步
                    if (this.currentConversation?.id === this.renamingConvId) {
                        this.currentConversation.title = this.renameTitle.trim();
                    }
                    this.closeRenameModal();
                }
            } catch (e) {
                console.error('重命名对话失败:', e);
                this.renameError = e.message;
            } finally {
                this.renameSaving = false;
            }
        },

        addMessage(role, text, extra = {}) {
            this.messages.push({
                role,
                text,
                time: new Date().toLocaleString('zh-CN', { 
                    year: 'numeric', 
                    month: '2-digit', 
                    day: '2-digit', 
                    hour: '2-digit', 
                    minute: '2-digit', 
                    hour12: false 
                }).replace(/\//g, '-'),
                ...extra,
            });
            this.scrollChat();
        },

        scrollChat() {
            this.$nextTick(() => {
                const feed = document.getElementById('chatFeed');
                if (!feed) return;

                // 1. 立即滚动到底部（应对纯文本和已知高度的 DOM）
                feed.scrollTop = feed.scrollHeight;

                // 2. 找到所有媒体元素，监听它们的实际加载完成事件
                const mediaElements = feed.querySelectorAll('img, video');
                mediaElements.forEach(media => {
                    // 视频监听 loadedmetadata，图片监听 load
                    const eventName = media.tagName === 'VIDEO' ? 'loadedmetadata' : 'load';
                    
                    media.addEventListener(eventName, () => {
                        // 计算当前滚动条距离底部的距离
                        const distanceFromBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight;
                        
                        // 容差判断 (150px)：只有当用户视线还在底部附近时，才执行再次吸底。
                        // 如果用户已经往上滑动去阅读历史记录了，就不要粗暴地把他拽下来。
                        if (distanceFromBottom < 150) {
                            feed.scrollTop = feed.scrollHeight;
                        }
                    }, { once: true }); // once: true 保证每个元素只监听一次，防止内存泄漏
                });
            });
        },

        // 在内容/图片持续加载时，持续保持底部吸附（用于 switchConversation）
        _anchoreScrollOnLoad() {
            this.$nextTick(() => {
                const feed = document.getElementById('chatFeed');
                if (!feed) return;

                // 先立刻滚一次（纯文本消息已渲染）
                feed.scrollTop = feed.scrollHeight;

                // 用 ResizeObserver 监听内容高度变化（图片/附件加载后会涨高）
                if (this._chatScrollObserver) {
                    this._chatScrollObserver.disconnect();
                    this._chatScrollObserver = null;
                }

                const startTime = Date.now();
                const MAX_WATCH_MS = 3000; // 最多观察 3 秒

                const observer = new ResizeObserver(() => {
                    feed.scrollTop = feed.scrollHeight;
                    if (Date.now() - startTime > MAX_WATCH_MS) {
                        observer.disconnect();
                        this._chatScrollObserver = null;
                    }
                });

                // 观察 chatFeed 内部列表容器（子元素高度变化会触发回调）
                const inner = feed.firstElementChild;
                if (inner) observer.observe(inner);
                this._chatScrollObserver = observer;

                // 超时后强制断开，防止永久监听
                setTimeout(() => {
                    observer.disconnect();
                    this._chatScrollObserver = null;
                }, MAX_WATCH_MS);
            });
        },

        // 将原始消息数组（来自 API）解析并追加到 this.messages
        // mode: 'append'（向后追加）| 'prepend'（向前插入，用于加载更早消息）
        _parseAndAppendMessages(rawMessages, mode = 'append') {
            const parsed = rawMessages.map((msg, index) => {
                const m = {
                    role: msg.role,
                    text: msg.text,
                    time: new Date(msg.created_at).toLocaleString('zh-CN', { 
                        year: 'numeric', 
                        month: '2-digit', 
                        day: '2-digit', 
                        hour: '2-digit', 
                        minute: '2-digit', 
                        hour12: false 
                    }).replace(/\//g, '-'),
                    attachments: msg.attachments || [],
                    dbId: msg.id,
                    taskId: msg.task_id || null,
                    createdAt: msg.created_at,
                };

                if (m.role === 'system' && m.taskId) {
                    const meta = m.attachments.find(a => a.type === 'task_metadata');
                    if (meta) {
                        m.promptSnippet = meta.promptSnippet;
                        m.modelName = meta.modelName;
                        m.duration = meta.duration;
                        m.resolution = meta.resolution;
                        m.ratio = meta.ratio;
                    }
                    if (!m.promptSnippet) {
                        for (let j = index - 1; j >= 0; j--) {
                            if (rawMessages[j].role === 'user') {
                                m.promptSnippet = rawMessages[j].text.replace(/@参考(图片|视频|音频)\d+/g, '').trim().slice(0, 20);
                                break;
                            }
                        }
                    }
                }

                if (msg.video_signed_url) {
                    m.videoUrl = msg.video_signed_url;
                }
                return m;
            });

            if (mode === 'prepend') {
                this.messages = [...parsed, ...this.messages];
            } else {
                this.messages = [...this.messages, ...parsed];
            }
        },

        // 向上翻页：加载更早的消息
        async loadMoreMessages() {
            if (!this.currentConversation || !this.messagesHasMore || this.messagesLoadingMore) return;
            const feed = document.getElementById('chatFeed');
            if (!feed) return;

            this.messagesLoadingMore = true;
            const prevScrollHeight = feed.scrollHeight;

            try {
                const url = `/api/conversations/${this.currentConversation.id}/messages?limit=20&before=${encodeURIComponent(this.messagesOldestCursor)}`;
                const resp = await fetch(url);
                const data = await resp.json();
                const rawMessages = data.messages || [];

                this.messagesHasMore = data.has_more || false;
                this.messagesOldestCursor = data.oldest_cursor || null;

                if (rawMessages.length > 0) {
                    this._parseAndAppendMessages(rawMessages, 'prepend');
                    // 保持滚动位置：新内容插入顶部后偏移 scrollTop (防跳跃处理)
                    this.$nextTick(() => {
                        feed.scrollTop += (feed.scrollHeight - prevScrollHeight);
                    });
                }
            } catch (e) {
                console.error('加载更多消息失败:', e);
            } finally {
                this.messagesLoadingMore = false;
            }
        },

        // 绑定 chatFeed 的 scroll 事件，滚到顶时触发懒加载
        _bindChatScrollListener() {
            const feed = document.getElementById('chatFeed');
            if (!feed) return;

            // 移除旧监听，防止重复绑定
            if (this._chatScrollHandler) {
                feed.removeEventListener('scroll', this._chatScrollHandler);
            }

            this._chatScrollHandler = () => {
                if (feed.scrollTop <= 60 && this.messagesHasMore && !this.messagesLoadingMore) {
                    this.loadMoreMessages();
                }
            };

            feed.addEventListener('scroll', this._chatScrollHandler, { passive: true });
        },

        playInCurrentVideo(url) {
            if (!url) return;
            this.currentView = 'generator';
            this.currentVideo = url;
            this.closeVideoModal();
        },

        openVideoModal(url) {
            if (!url) return;
            this.videoModalUrl = url;
            this.showVideoModal = true;
            
            this.$nextTick(() => {
                const vid = this.$refs.videoModal;
                if (vid) {
                    // 👉 1. 彻底删除 vid.load(); 
                    
                    // 👉 2. 直接发起播放请求
                    const playPromise = vid.play();
                    if (playPromise !== undefined) {
                        playPromise.catch(error => {
                            console.warn("自动播放被拦截 (等待用户手动点击):", error);
                        });
                    }
                }
            });
        },

        closeVideoModal() {
            // 先暂停视频，防止关闭后仍能听到声音
            const vid = this.$refs.videoModal;
            if (vid) {
                vid.pause();
                vid.currentTime = 0;
            }
            this.showVideoModal = false;
            this.videoModalUrl = null;
        },

        openImageModal(url) {
            this.imageModalUrl = url;
            this.showImageModal = true;
        },

        closeImageModal() {
            this.showImageModal = false;
            this.imageModalUrl = null;
        },

        playConversationVideo(conv) {
            if (conv.thumbnail_signed_url) {
                this.playInCurrentVideo(conv.thumbnail_signed_url);
            }
        },
    },
};
