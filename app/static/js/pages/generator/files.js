window.AppModules = window.AppModules || {};
window.AppModules.generator_files = {
    data() {
        return {
            firstFrame: null,
            lastFrame: null,
            enableFrames: false,
            showMediaLibraryPicker: false,
            selectedLibraryItems: [],
        };
    },
    methods: {
        handleFileSelect(e) {
            this.processFiles(e.target.files);
        },

        handleDrop(e) {
            this.processFiles(e.dataTransfer.files);
        },

        handlePaste(e) {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            const files = [];
            for (let item of items) {
                if (item.kind === 'file') {
                    files.push(item.getAsFile());
                }
            }
            if (files.length > 0) this.processFiles(files);
        },

        generateVideoThumbnail(file) {
            return new Promise((resolve) => {
                const video = document.createElement('video');
                video.preload = 'auto';
                video.muted = true;
                video.playsInline = true;
                video.crossOrigin = 'anonymous';

                const url = URL.createObjectURL(file);
                let resolved = false;

                const cleanup = (objectUrl) => {
                    video.removeAttribute('src');
                    video.load();
                    if (objectUrl) URL.revokeObjectURL(objectUrl);
                };

                const captureFrame = () => {
                    if (resolved) return;
                    resolved = true;
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = video.videoWidth || 640;
                        canvas.height = video.videoHeight || 360;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                        const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
                        resolve(dataUrl);
                    } catch (e) {
                        resolve('/static/img/video_placeholder.png');
                    }
                    cleanup(url);
                };

                const timeoutId = setTimeout(() => {
                    if (!resolved) {
                        resolved = true;
                        resolve('/static/img/video_placeholder.png');
                        cleanup(url);
                    }
                }, 5000);

                video.onseeked = () => {
                    clearTimeout(timeoutId);
                    captureFrame();
                };

                // loadeddata 表示当前帧的数据已可用，可直接截帧或触发 seek
                video.onloadeddata = () => {
                    // 若 duration 足够长则 seek 到 0.5s，否则直接截取当前帧
                    if (video.duration && video.duration > 0.5) {
                        video.currentTime = 0.5;
                    } else {
                        // currentTime 已经是 0，onseeked 不会触发，直接截帧
                        clearTimeout(timeoutId);
                        captureFrame();
                    }
                };

                video.onerror = () => {
                    clearTimeout(timeoutId);
                    if (!resolved) {
                        resolved = true;
                        resolve('/static/img/video_placeholder.png');
                        cleanup(url);
                    }
                };

                video.src = url;
                video.load();
            });
        },

        async processFiles(files) {
            if (this.generating) return;

            let imgCount = this.attachments.filter(a => a.type === 'image').length;
            let vidCount = this.attachments.filter(a => a.type === 'video').length;
            let audCount = this.attachments.filter(a => a.type === 'audio').length;

            let imgAlerted = false;
            let vidAlerted = false;
            let audAlerted = false;

            for (let file of files) {
                const isVideo = file.type.startsWith('video/');
                const isAudio = file.type.startsWith('audio/');
                const isImage = file.type.startsWith('image/');

                if (isVideo || isAudio || isImage) {
                    if (isImage) {
                        if (imgCount >= 9) {
                            if (!imgAlerted) { alert('图片最多只能添加 9 张'); imgAlerted = true; }
                            continue;
                        }
                        imgCount++;
                    } else if (isVideo) {
                        if (vidCount >= 3) {
                            if (!vidAlerted) { alert('视频最多只能添加 3 个'); vidAlerted = true; }
                            continue;
                        }
                        vidCount++;
                    } else if (isAudio) {
                        if (audCount >= 3) {
                            if (!audAlerted) { alert('音频最多只能添加 3 个'); audAlerted = true; }
                            continue;
                        }
                        audCount++;
                    }

                    // 避免在压缩期间用户重复拖拽同一个文件
                    if (this.attachments.some(a => a.name === file.name && a.file?.size === file.size && a.isProcessing)) {
                        console.info('文件正在处理中，请勿重复添加:', file.name);
                        continue;
                    }

                    let role = isImage ? 'reference_image' : isVideo ? 'reference_video' : 'reference_audio';
                    let attachmentObj = {
                        id: 'att_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                        file: file,
                        type: isImage ? 'image' : isVideo ? 'video' : 'audio',
                        preview: isImage ? '' : (isVideo ? '/static/img/video_placeholder.png' : '/static/img/audio_placeholder.png'),
                        role: role,
                        name: file.name,
                        isProcessing: isVideo && !!window.processVideoIfOversized,
                        progress: 0
                    };
                    
                    // 尽早将其推入数组，以触发视图渲染转圈动画
                    this.attachments.push(attachmentObj);
                    if (typeof this.updateCachedMentionableRefs === 'function') {
                        this.updateCachedMentionableRefs();
                    }

                    if (isVideo) {
                        try {
                            if (window.processVideoIfOversized) {
                                if (this.statusText) this.statusText = "转码压缩中...";
                                
                                attachmentObj.file = await window.processVideoIfOversized(file, 921600, (prog) => {
                                    attachmentObj.progress = Math.round(prog * 100);
                                    if (typeof this.updateCachedMentionableRefs === 'function') {
                                        this.updateCachedMentionableRefs();
                                    }
                                });
                                
                                if (this.statusText === "转码压缩中...") this.statusText = "";
                            }
                            // 处理完毕，生成真实的缩略图
                            attachmentObj.isProcessing = false;
                            attachmentObj.preview = await this.generateVideoThumbnail(attachmentObj.file);
                        } catch (e) {
                            console.error("Video processing/thumbnail generation error:", e);
                            attachmentObj.isProcessing = false;
                            attachmentObj.preview = '/static/img/video_placeholder.png';
                        }
                    } else if (isAudio) {
                        attachmentObj.preview = '/static/img/audio_placeholder.png';
                        attachmentObj.isProcessing = false;
                    } else if (isImage) {
                        const preview = await new Promise(resolve => {
                            const reader = new FileReader();
                            reader.onload = e => resolve(e.target.result);
                            reader.readAsDataURL(file);
                        });
                        attachmentObj.preview = preview;
                        attachmentObj.isProcessing = false;
                    }

                    if (typeof this.updateCachedMentionableRefs === 'function') {
                        this.updateCachedMentionableRefs();
                    }
                }
            }
        },

        handleFirstFrameSelect(e) {
            const file = e.target.files[0];
            if (file && !this.generating) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.firstFrame = { id: 'sys_first_frame', file, preview: e.target.result };
                    if (typeof this.updateCachedMentionableRefs === 'function') {
                        this.updateCachedMentionableRefs();
                    }
                };
                reader.readAsDataURL(file);
            }
        },

        handleLastFrameSelect(e) {
            const file = e.target.files[0];
            if (file && !this.generating) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.lastFrame = { id: 'sys_last_frame', file, preview: e.target.result };
                    if (typeof this.updateCachedMentionableRefs === 'function') {
                        this.updateCachedMentionableRefs();
                    }
                };
                reader.readAsDataURL(file);
            }
        },

        removeFirstFrame() {
            if (typeof this.syncPromptTokensOnDeletion === 'function') {
                this.syncPromptTokensOnDeletion(() => {
                    this.firstFrame = null;
                    if (this.$refs.firstFrameInput) this.$refs.firstFrameInput.value = '';
                });
            } else {
                this.firstFrame = null;
                if (this.$refs.firstFrameInput) this.$refs.firstFrameInput.value = '';
                this.updateCachedMentionableRefs();
            }
        },

        removeLastFrame() {
            if (typeof this.syncPromptTokensOnDeletion === 'function') {
                this.syncPromptTokensOnDeletion(() => {
                    this.lastFrame = null;
                    if (this.$refs.lastFrameInput) this.$refs.lastFrameInput.value = '';
                });
            } else {
                this.lastFrame = null;
                if (this.$refs.lastFrameInput) this.$refs.lastFrameInput.value = '';
                this.updateCachedMentionableRefs();
            }
        },
        
        removeAttachment(index) {
            if (typeof this.syncPromptTokensOnDeletion === 'function') {
                this.syncPromptTokensOnDeletion(() => {
                    this.attachments.splice(index, 1);
                });
            } else {
                this.attachments.splice(index, 1);
                this.updateCachedMentionableRefs();
            }
        },

        removeReference(ref) {
            if (ref.key === 'sys_first_frame') {
                this.removeFirstFrame();
            } else if (ref.key === 'sys_last_frame') {
                this.removeLastFrame();
            } else {
                const idx = this.attachments.findIndex(a => a.id === ref.key || `composer-${a.id}` === ref.key);
                if (idx !== -1) {
                    this.removeAttachment(idx);
                }
            }
        },

        openMediaLibraryPicker() {
            this.showMediaLibraryPicker = true;
            this.selectedLibraryItemIds = [];
            if (typeof this.loadMediaLibrary === 'function' && !this.mediaLibraryLoaded) {
                this.loadMediaLibrary();
            }
        },

        toggleLibraryItemSelection(item) {
            const idx = this.selectedLibraryItems.findIndex(i => i.id === item.id);
            if (idx === -1) {
                this.selectedLibraryItems.push(item);
            } else {
                this.selectedLibraryItems.splice(idx, 1);
            }
        },

        addSelectedReferencesFromLibrary() {
            if (this.selectedLibraryItems.length === 0) return;
            
            let imgCount = this.attachments.filter(a => a.type === 'image').length;
            let vidCount = this.attachments.filter(a => a.type === 'video').length;
            let audCount = this.attachments.filter(a => a.type === 'audio').length;
            
            let imgAlerted = false;
            let vidAlerted = false;
            let audAlerted = false;

            this.selectedLibraryItems.forEach(libItem => {
                let type = libItem.file_type || (libItem.role === 'reference_video' ? 'video' : 'image');
                let role = type === 'video' ? 'reference_video' : type === 'audio' ? 'reference_audio' : 'reference_image';
                
                if (type === 'image') {
                    if (imgCount >= 9) {
                        if (!imgAlerted) { alert('图片最多只能添加 9 张'); imgAlerted = true; }
                        return;
                    }
                    imgCount++;
                } else if (type === 'video') {
                    if (vidCount >= 3) {
                        if (!vidAlerted) { alert('视频最多只能添加 3 个'); vidAlerted = true; }
                        return;
                    }
                    vidCount++;
                } else if (type === 'audio') {
                    if (audCount >= 3) {
                        if (!audAlerted) { alert('音频最多只能添加 3 个'); audAlerted = true; }
                        return;
                    }
                    audCount++;
                }

                this.attachments.push({
                    id: 'lib_' + libItem.id + '_' + Date.now().toString(36).substr(4),
                    file: null,
                    type: type,
                    preview: libItem.thumbnail_signed_url || libItem.signed_url,
                    role: role,
                    storage_path: libItem.storage_path,
                    name: libItem.name
                });
            });

            if (typeof this.updateCachedMentionableRefs === 'function') {
                this.updateCachedMentionableRefs();
            }
            this.showMediaLibraryPicker = false;
            this.selectedLibraryItems = [];
        },


        async uploadToStorage(file) {
            if (!file) return null;
            const ts = Date.now();
            // 某些存储服务（如 Supabase 所用的 S3 后端）在特定环境下对非 ASCII（如中文字符）的文件名支持较差，
            // 容易导致签名、下载或检索时出现 "Invalid key" 错误。
            // 这里我们对 storage 路径下的文件名进行简单的脱敏处理（仅保留 ASCII 可打印字符），
            // 具体的展示名称可以在媒体库记录中使用原始名称。
            const safeName = file.name.replace(/[^\x00-\x7F]/g, '_');
            const fileName = `${this.user.id}/upload/${ts}_${safeName}`;
            
            const formData = new FormData();
            formData.append('file', file);
            formData.append('file_path', fileName);
            
            const res = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            if (!res.ok) throw new Error("Upload failed");
            const data = await res.json();
            return data.path;
        },

        resolveReferenceInputsByMentions(prompt, uploadedReferencesMap = {}, candidates = null) {
            const results = [];
            const mentionRegex = /@参考(图片|视频|音频)(\d+)(_[^\s]+)?/g;
            let match;
            
            const officialCandidates = candidates || (typeof this.getMentionCandidateList === 'function' ? this.getMentionCandidateList() : []);

            while ((match = mentionRegex.exec(prompt)) !== null) {
                const baseToken = `@参考${match[1]}${match[2]}`;
                const officialItem = officialCandidates.find(c => {
                    const cBase = c.token ? c.token.match(/(@参考(?:图片|视频|音频)\d+)/) : null;
                    return cBase && cBase[1] === baseToken;
                });

                if (officialItem) {
                    let storage_path = officialItem.storage_path || null;
                    if (officialItem.source === 'current') {
                        // 优先从上传结果 map 中查（新上传的文件会在这里）
                        // 找不到时兜底使用候选项本身的 storage_path（重试/复用历史附件的场景）
                        storage_path = uploadedReferencesMap[officialItem.key] || officialItem.storage_path || null;
                    }

                    if (storage_path) {
                        results.push({
                            role: officialItem.role,
                            storage_path: storage_path,
                            url: officialItem.preview || null,
                            type: officialItem.item_type || 'image',
                        });
                    }
                }
            }
            return results;
        },
    },
};
