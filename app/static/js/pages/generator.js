/**
 * Cinematic AI - 视频生成主模块
 * 逻辑已拆分至 /static/js/pages/generator/*.js
 */

window.AppModules = window.AppModules || {};

window.AppModules.generator = {
    data() {
        // 合并子模块的基础状态
        const subModules = [
            window.AppModules.generator_tasks,
            window.AppModules.generator_mentions,
            window.AppModules.generator_files,
            window.AppModules.generator_ui,
        ];

        let state = {
            promptText: '',
            attachments: [],
            // 后端注入的配置
            appSettings: window.appSettings || {},
            // 默认选中模型 key，与 conversation.js 保持一致风格
            selectedModel: 'seedance-2.0',
            models: {
                'seedance-2.0': {
                    id: 'doubao-seedance-2-0-260128',
                    name: 'Seedance 2.0',
                    available: true,
                    supports: ['text', 'first_frame', 'last_frame', 'reference_image', 'reference_video', 'reference_audio'],
                    ratios: ['16:9', '9:16', '1:1', '21:9', '4:3', '3:4'],
                    durations: [5, 10, 15],
                    has_audio: false,
                },
                'seedance-1.5-pro': {
                    id: 'doubao-seedance-1-5-pro-251215',
                    name: 'Seedance 1.5 Pro',
                    available: true,
                    supports: ['text', 'first_frame', 'last_frame'],
                    ratios: ['16:9', '9:16', '3:2', '2:3', '1:1', 'adaptive'],
                    durations: [5, 10],
                    has_audio: true,
                    resolutions: ['480p', '720p', '1080p'],
                },
                'seedance-lite': {
                    id: 'doubao-seedance-1-0-lite-i2v-250428',
                    name: 'Seedance Lite (参考图)',
                    available: true,
                    supports: ['text', 'reference_image'],
                    ratios: ['16:9', '9:16', '1:1'],
                    durations: [5, 10],
                    has_audio: false,
                },
            },
        };

        // 合并子模块 data
        subModules.forEach(m => {
            if (m && typeof m.data === 'function') {
                Object.assign(state, m.data());
            }
        });

        return state;
    },

    methods: {
        // 初始化
        async initGenerator() {
            // 调用 tasks 模块的容量查询轮询
            if (typeof this.startCapacityPolling === 'function') {
                this.startCapacityPolling();
            }

            // 初始化后对齐一次模型参数
            if (typeof this.normalizeParamsForModel === 'function') {
                this.normalizeParamsForModel(this.selectedModel);
            }

            // 预加载媒体库数据（后台异步，不阻塞 UI）
            if (typeof this.ensureMentionLibraryItems === 'function') {
                this.ensureMentionLibraryItems();
            }

            // 初始化缓存的可引用列表
            if (typeof this.updateCachedMentionableRefs === 'function') {
                this.updateCachedMentionableRefs();
            }
        },

        // 从子模块中挂载所有方法 (使用展开运算符时注意顺序，后定义的会覆盖前定义的)
        ...window.AppModules.generator_tasks?.methods,
        ...window.AppModules.generator_mentions?.methods,
        ...window.AppModules.generator_files?.methods,
        ...window.AppModules.generator_ui?.methods,

        // 覆盖/补充一些通用的 UI 辅助方法
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

    },
};
