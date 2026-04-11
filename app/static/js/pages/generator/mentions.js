window.AppModules = window.AppModules || {};
window.AppModules.generator_mentions = {
    data() {
        return {
            mentionMenuVisible: false,
            mentionMenuItems: [],
            mentionMenuActiveIndex: 0,
            mentionQuery: '',
            mentionLibraryItems: [],
            mentionLibraryLoading: false,
            mentionLibraryLoadedAt: 0,
            // 缓存的可引用媒体列表（避免模板重复计算）
            cachedMentionableRefs: [],
            // 防抖定时器
            _mentionDebounceTimer: null,
        };
    },
    methods: {
        async ensureMentionLibraryItems(force = false) {
            if (!this.user?.id) return;
            const now = Date.now();
            // 缓存 60 秒（从原来的 10 秒提升），除非强制刷新
            const CACHE_TTL = 60_000;
            if (!force && this.mentionLibraryItems.length > 0 && (now - this.mentionLibraryLoadedAt < CACHE_TTL)) return;
            // 如果已在加载中，不重复发请求
            if (this.mentionLibraryLoading) return;

            this.mentionLibraryLoading = true;
            try {
                const resp = await fetch(`/api/media/library/mentions?user_id=${this.user.id}&limit=10`);
                if (!resp.ok) return;
                const data = await resp.json();
                this.mentionLibraryItems = Array.isArray(data.items) ? data.items.map(item => ({
                    ...item,
                    role: item.file_type === 'video' ? 'reference_video' : item.file_type === 'audio' ? 'reference_audio' : 'reference_image',
                })) : [];
                this.mentionLibraryLoadedAt = Date.now();
            } catch (e) {
                console.error('加载提及媒体库失败:', e);
            } finally {
                this.mentionLibraryLoading = false;
                // 加载完后刷新 @ 下拉菜单（不影响底部快捷区）
                this.refreshMentionMenu();
            }
        },

        getCurrentComposerReferenceDrafts() {
            const list = [];
            if (this.enableFrames && this.firstFrame) {
                list.push({ uid: 'sys_first_frame', type: 'image', role: 'first_frame', preview: this.firstFrame.preview, name: '当前首帧 (First Frame)' });
            }
            if (this.enableFrames && this.lastFrame) {
                list.push({ uid: 'sys_last_frame', type: 'image', role: 'last_frame', preview: this.lastFrame.preview, name: '当前尾帧 (Last Frame)' });
            }
            this.attachments.forEach(att => {
                if (att.role === 'reference_image' || att.role === 'reference_video' || att.role === 'reference_audio') {
                    const roleLabel = att.role === 'reference_image' ? '参考图' : att.role === 'reference_video' ? '参考视频' : '参考音频';
                    list.push({
                        uid: att.id,
                        type: att.type,
                        role: att.role,
                        preview: att.preview,
                        name: `上传：${roleLabel}`,
                        isProcessing: att.isProcessing,
                        progress: att.progress,
                        storage_path: att.storage_path || null,
                    });
                }
            });
            return list;
        },

        getMentionCandidateList() {
            const list = [];
            const composerItems = this.getCurrentComposerReferenceDrafts();

            let counters = { image: 0, video: 0, audio: 0 };
            
            const addToList = (item, source) => {
                const effectiveType = item.type === 'video' || item.file_type === 'video' ? 'video' : 
                                      item.type === 'audio' || item.file_type === 'audio' ? 'audio' : 'image';
                
                counters[effectiveType]++;
                const num = counters[effectiveType];
                
                const typeText = effectiveType === 'video' ? '视频' : effectiveType === 'audio' ? '音频' : '图片';
                const token = `@参考${typeText}${num}`;
                
                list.push({
                    id: source === 'current' ? `composer-${num}` : `lib-${item.id}`,
                    name: item.name,
                    token: token,
                    label: token,
                    icon: effectiveType === 'video' ? 'movie' : effectiveType === 'audio' ? 'music_note' : 'image',
                    preview: item.preview || item.thumbnail_signed_url || item.signed_url,
                    type: effectiveType,
                    item_type: effectiveType,
                    role: item.role,
                    storage_path: item.storage_path,
                    source: source,
                    source_type: source,
                    display: item.name,
                    key: source === 'current' ? item.uid : `lib-${item.id}`,
                    isProcessing: item.isProcessing || false,
                    progress: item.progress || 0
                });
            };

            composerItems.forEach(item => addToList(item, 'current'));

            this._currentMentionCandidates = list;
            return list;
        },

        /**
         * 更新缓存的可引用列表 — 在 attachments 变化时调用
         * 只包含当前 composer 中的本地附件（首帧/尾帧/参考素材），
         * 媒体库内容仅在 @ 下拉菜单中出现，不在底部快捷区显示。
         */
        updateCachedMentionableRefs() {
            // 直接复用 getMentionCandidateList 中的类型计数逻辑，保证 Token 编号完全一致
            const allCandidates = this.getMentionCandidateList();
            this.cachedMentionableRefs = allCandidates.filter(item => item.source === 'current');
        },

        refreshMentionMenu() {
            if (!this.mentionMenuVisible) return;
            const candidates = this.getMentionCandidateList();
            if (this.mentionQuery) {
                const q = this.mentionQuery.toLowerCase();
                this.mentionMenuItems = candidates.filter(i => 
                    i.label.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)
                );
            } else {
                this.mentionMenuItems = candidates;
            }
            if (this.mentionMenuActiveIndex >= this.mentionMenuItems.length) {
                this.mentionMenuActiveIndex = 0;
            }
        },

        handlePromptInput(e) {
            const textarea = e?.target || this.$refs.promptInput;
            
            // Auto resize the textarea to remove internal scrollbars and sync fully with backdrop
            if (textarea) {
                textarea.style.height = 'auto';
                textarea.style.height = textarea.scrollHeight + 'px';
            }

            if (!textarea) return;
            const cursor = textarea.selectionStart;
            const text = textarea.value;
            const before = text.substring(0, cursor);
            const match = before.match(/@(\S*)$/);
            
            if (match) {
                const query = match[1];
                // 如果 @ 后面已经是已插入 token 的格式（如退格删除 token 时经过的状态），
                // 则不弹菜单，避免用户以为那是删除列表
                const isInsertedToken = /^参考(图片|视频|音频)\d+/.test(query);
                if (isInsertedToken) {
                    this.mentionMenuVisible = false;
                    this.mentionQuery = '';
                    clearTimeout(this._mentionDebounceTimer);
                    return;
                }

                this.mentionMenuVisible = true;
                this.mentionQuery = query;

                // 防抖：150ms 后才发起网络请求，避免快速输入时频繁调用 API
                clearTimeout(this._mentionDebounceTimer);
                this._mentionDebounceTimer = setTimeout(() => {
                    this.ensureMentionLibraryItems();
                }, 150);

                // 菜单内容先用缓存立即刷新（无网络延迟）
                this.refreshMentionMenu();
            } else {
                this.mentionMenuVisible = false;
                this.mentionQuery = '';
                clearTimeout(this._mentionDebounceTimer);
            }
        },

        handlePromptFocus() {
            // Placeholder for future logic
        },

        handlePromptBlur() {
            setTimeout(() => { this.mentionMenuVisible = false; }, 200);
        },

        handlePromptKeydown(e) {
            // Backspace：若光标前紧接着完整 @token，整体删除（无论菜单是否可见）
            if (e.key === 'Backspace') {
                const textarea = e.target || this.$refs.promptInput;
                if (textarea && textarea.selectionStart === textarea.selectionEnd) {
                    const cursor = textarea.selectionStart;
                    const before = textarea.value.substring(0, cursor);
                    // 匹配光标前的完整 @token（含可选的尾随空格）
                    const tokenMatch = before.match(/@参考(图片|视频|音频)\d+(_[^\s]+)?( ?)$/);
                    if (tokenMatch) {
                        e.preventDefault();
                        const matched = tokenMatch[0];
                        const newBefore = before.substring(0, before.length - matched.length);
                        const after = textarea.value.substring(cursor);
                        this.promptText = newBefore + after;
                        this.$nextTick(() => {
                            textarea.focus();
                            textarea.setSelectionRange(newBefore.length, newBefore.length);
                        });
                        return;
                    }
                }
            }

            if (!this.mentionMenuVisible) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.mentionMenuActiveIndex = (this.mentionMenuActiveIndex + 1) % this.mentionMenuItems.length;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.mentionMenuActiveIndex = (this.mentionMenuActiveIndex + this.mentionMenuItems.length - 1) % this.mentionMenuItems.length;
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                const item = this.mentionMenuItems[this.mentionMenuActiveIndex];
                if (item) this.insertMentionToken(item);
            } else if (e.key === 'Escape') {
                this.mentionMenuVisible = false;
            }
        },

        /**
         * @deprecated 用 cachedMentionableRefs 替代，避免模板频繁调用
         */
        getMentionableReferences() {
            return this.cachedMentionableRefs;
        },

        /**
         * 插入 mention token 到输入框
         * @param {object|string} itemOrToken - 候选对象或快捷标签字符串
         */
        insertMentionToken(itemOrToken) {
            const textarea = this.$refs.promptInput;
            if (!textarea) return;

            // 兼容传入对象或字符串
            const label = typeof itemOrToken === 'string' ? itemOrToken : (itemOrToken.label || itemOrToken.token);

            const cursor = textarea.selectionStart;
            const text = textarea.value;
            const before = text.substring(0, cursor);
            const after = text.substring(cursor);

            let newText;
            let newCursor;

            if (this.mentionMenuVisible) {
                // 从 @ 下拉菜单插入：替换 @query 为 token
                const atIndex = before.lastIndexOf('@');
                if (atIndex !== -1) {
                    newText = before.substring(0, atIndex) + label + ' ' + after;
                    newCursor = atIndex + label.length + 1;
                } else {
                    // 异常回退：在光标位置插入
                    const prefix = before.length > 0 && !before.endsWith(' ') && !before.endsWith('\n') ? ' ' : '';
                    newText = before + prefix + label + ' ' + after;
                    newCursor = before.length + prefix.length + label.length + 1;
                }
            } else {
                // 从底部快捷按钮插入：直接在光标位置插入
                const prefix = before.length > 0 && !before.endsWith(' ') && !before.endsWith('\n') ? ' ' : '';
                newText = before + prefix + label + ' ' + after;
                newCursor = before.length + prefix.length + label.length + 1;
            }

            this.promptText = newText;
            this.$nextTick(() => {
                textarea.focus();
                textarea.setSelectionRange(newCursor, newCursor);
            });
            this.mentionMenuVisible = false;
            // 插入 token 后更新缓存
            this.updateCachedMentionableRefs();
        },

        getHighlightedPrompt() {
            if (!this.promptText) return '';
            
            // 防 XSS: 创建一个安全的文本节点
            const div = document.createElement('div');
            div.innerText = this.promptText;
            let safeHTML = div.innerHTML;

            // 匹配格式: @参考类型数字_文件名扩展名，然后为它增加高亮标签
            const regex = /@参考(图片|视频|音频)(\d+)(_[^\s]+)?/g;
            safeHTML = safeHTML.replace(regex, (match) => {
                // 不能更改 match 的文本内容，且不能添加 padding 或 margin
                // 否则会导致高亮层的文字宽度被撑开，失去与 textarea 的光标 1:1 同步
                return `<span class="bg-indigo-500/30 text-indigo-300 rounded-sm">${match}</span>`;
            });

            // 修补因为连续换行导致的空白节点渲染高度丢失
            safeHTML = safeHTML.replace(/\n$/g, '\n<br/>');

            return safeHTML;
        },

        syncPromptTokensOnDeletion(deleteActionCallback) {
            // 立即关闭 @ 下拉菜单，防止删除过程中菜单残留导致用户误操作
            this.mentionMenuVisible = false;
            this.mentionQuery = '';
            clearTimeout(this._mentionDebounceTimer);

            // 捕获删除前所有的 Token 映射信息
            const oldList = this.getMentionCandidateList();
            
            // 执行实际删除动作（改变 attachments 数组结构）
            deleteActionCallback();
            
            // 获取删除后全新的 Token 映射
            const newList = this.getMentionCandidateList();
            
            // 辅助函数：提取 token 基础部分（如 "@参考图片1"），忽略可选的 _safeName 后缀
            const getBase = (token) => {
                const m = token.match(/^(@参考(?:图片|视频|音频)\d+)/);
                return m ? m[1] : token;
            };
            // 辅助函数：构建灵活匹配的正则（匹配 base + 可选 _suffix + 可选尾部空白）
            const buildFlexRegex = (token, withTrailingSpace) => {
                const base = getBase(token);
                const escaped = base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                return new RegExp(escaped + '(_[^\\s]*)?' + (withTrailingSpace ? '\\s*' : ''), 'g');
            };
            
            // 按需求更新输入框和发送的纯文本
            if (this.promptText) {
                let newText = this.promptText;
                
                // 1. 对于被彻底删除的项目，移除它们所在的标记文本
                const oldKeys = oldList.map(i => i.key);
                const newKeys = newList.map(i => i.key);
                const deletedKeys = oldKeys.filter(k => !newKeys.includes(k));
                
                deletedKeys.forEach(k => {
                    const delItem = oldList.find(i => i.key === k);
                    if (delItem) {
                        newText = newText.replace(buildFlexRegex(delItem.token, true), '');
                    }
                });
                
                // 2. 对于没有删除但受顺位影响的元素，更新它们的 Token 编号
                // 由于删除后序号只会减小，按原序 (从小到大) 逐个替换不会冲突
                oldList.forEach(oldItem => {
                    const newItem = newList.find(i => i.key === oldItem.key);
                    if (newItem) {
                        const oldBase = getBase(oldItem.token);
                        const newBase = getBase(newItem.token);
                        if (oldBase !== newBase) {
                            newText = newText.replace(buildFlexRegex(oldItem.token, false), (match, suffix) => {
                                return newBase + (suffix || '');
                            });
                        }
                    }
                });

                this.promptText = newText;
            }
            
            // 同步渲染列表
            this.updateCachedMentionableRefs();
        },
    },
};
