window.AppModules = window.AppModules || {};

window.AppModules.media = {
    data() {
        return {
            // 关闭媒体列表本地缓存，避免新生成媒体显示滞后。
            MEDIA_LIST_CACHE_TTL_MS: 0,
            SIGNED_URL_SKEW_SECONDS: 60,

            mediaLibrary: [],
            mediaLibraryAll: [],
            mediaLibraryLoaded: false,
            mediaStats: {
                total_items: 0,
                total_images: 0,
                total_videos: 0,
                total_audios: 0,
                total_size: 0,
                total_uploaded: 0,
                total_generated: 0,
            },
            filterMediaType: null,
            filterMediaSource: 'uploaded',
            hoveredMediaId: null,
            currentPage: 1,
            pageSize: 24,
            hasMore: true,
            _mediaLoadAbortController: null,
            _mediaLoadDebounceTimer: null,
        };
    },

    methods: {
        getMediaListCacheKey() {
            return `media_library_cache:${this.user?.id || 'anonymous'}`;
        },

        getSignedUrlCacheKey() {
            return `media_signed_url_cache_v3:${this.user?.id || 'anonymous'}`;
        },

        clearMediaCacheStorage() {
            try {
                localStorage.removeItem(this.getMediaListCacheKey());
                localStorage.removeItem(this.getSignedUrlCacheKey());
            } catch (e) {
                console.warn('清理媒体缓存失败:', e);
            }
        },

        isSignedUrlFresh(expiresAt) {
            if (!expiresAt) return true;
            const now = Math.floor(Date.now() / 1000);
            return Number(expiresAt) - this.SIGNED_URL_SKEW_SECONDS > now;
        },

        loadSignedUrlCache() {
            try {
                const raw = localStorage.getItem(this.getSignedUrlCacheKey());
                if (!raw) return {};
                const parsed = JSON.parse(raw);
                return parsed && typeof parsed === 'object' ? parsed : {};
            } catch (_) {
                return {};
            }
        },

        saveSignedUrlCache(cache) {
            try {
                localStorage.setItem(this.getSignedUrlCacheKey(), JSON.stringify(cache));
            } catch (e) {
                console.warn('保存签名 URL 缓存失败:', e);
            }
        },

        mergeSignedUrlCacheIntoItems(items) {
            const cache = this.loadSignedUrlCache();
            let cacheChanged = false;

            const upsertCache = (key, url, expiresAt) => {
                if (!key || !url) return;
                cache[key] = {
                    url,
                    expires_at: expiresAt || null,
                    updated_at: Date.now(),
                };
                cacheChanged = true;
            };

            for (const item of items) {
                const storageKey = item.storage_path ? `storage:${item.storage_path}` : null;
                const thumbnailKey = item.thumbnail_path ? `thumb:${item.thumbnail_path}` : null;

                if (storageKey) {
                    const cached = cache[storageKey];
                    if (cached?.url && this.isSignedUrlFresh(cached.expires_at)) {
                        item.signed_url = cached.url;
                        item.signed_url_expires_at = cached.expires_at;
                    } else if (item.signed_url) {
                        upsertCache(storageKey, item.signed_url, item.signed_url_expires_at || null);
                    }
                }

                if (thumbnailKey) {
                    const cachedThumb = cache[thumbnailKey];
                    if (cachedThumb?.url && this.isSignedUrlFresh(cachedThumb.expires_at)) {
                        item.thumbnail_signed_url = cachedThumb.url;
                        item.thumbnail_signed_url_expires_at = cachedThumb.expires_at;
                    } else if (item.thumbnail_signed_url) {
                        upsertCache(
                            thumbnailKey,
                            item.thumbnail_signed_url,
                            item.thumbnail_signed_url_expires_at || null,
                        );
                    }
                }
            }

            if (cacheChanged) {
                this.saveSignedUrlCache(cache);
            }

            return items;
        },

        saveMediaListCache(items) {
            if (this.MEDIA_LIST_CACHE_TTL_MS <= 0) return;
            try {
                const payload = {
                    cached_at: Date.now(),
                    items,
                };
                localStorage.setItem(this.getMediaListCacheKey(), JSON.stringify(payload));
            } catch (e) {
                console.warn('保存媒体列表缓存失败:', e);
            }
        },

        loadMediaListCache() {
            if (this.MEDIA_LIST_CACHE_TTL_MS <= 0) return null;
            try {
                const raw = localStorage.getItem(this.getMediaListCacheKey());
                if (!raw) return null;
                const parsed = JSON.parse(raw);
                if (!parsed?.cached_at || !Array.isArray(parsed?.items)) return null;

                if (Date.now() - parsed.cached_at > this.MEDIA_LIST_CACHE_TTL_MS) {
                    return null;
                }

                const hasExpiredSigned = parsed.items.some(item => {
                    const s1 = item?.signed_url_expires_at;
                    const s2 = item?.thumbnail_signed_url_expires_at;
                    return !this.isSignedUrlFresh(s1) || !this.isSignedUrlFresh(s2);
                });

                if (hasExpiredSigned) {
                    return null;
                }

                return parsed.items;
            } catch (_) {
                return null;
            }
        },

        changeMediaType(type) {
            this.filterMediaType = type;
            this.currentPage = 1;
            // 使用防抖处理，避免用户快速连续点击（特别是切换分类时）
            clearTimeout(this._mediaLoadDebounceTimer);
            this._mediaLoadDebounceTimer = setTimeout(() => {
                this.loadMediaLibrary(true);
            }, 250);
        },

        changeMediaSource(source) {
            this.filterMediaSource = source;
            this.currentPage = 1;
            clearTimeout(this._mediaLoadDebounceTimer);
            this._mediaLoadDebounceTimer = setTimeout(() => {
                this.loadMediaLibrary(true);
            }, 250);
        },

        nextPage() {
            if (this.hasMore) {
                this.currentPage++;
                this.loadMediaLibrary(true);
            }
        },

        prevPage() {
            if (this.currentPage > 1) {
                this.currentPage--;
                this.loadMediaLibrary(true);
            }
        },

        async loadMediaStats() {
            try {
                if (!this.user) return;
                const resp = await fetch(`/api/media/library/stats?user_id=${this.user.id}`);
                if (resp.ok) {
                    this.mediaStats = await resp.json();
                }
            } catch (e) {
                console.error('加载媒体统计失败:', e);
            }
        },

        async loadMediaLibrary(forceRefresh = false) {
            if (!this.user) return;

            // 取消上一个未完成的请求 (防止竞态条件导致筛选结果错乱)
            if (this._mediaLoadAbortController) {
                this._mediaLoadAbortController.abort();
            }
            this._mediaLoadAbortController = new AbortController();

            // 立即开启加载状态并清空当前列表，提供及时的交互反馈
            this.mediaLibraryLoaded = false;
            this.mediaLibrary = [];

            // 统计信息刷新逻辑
            if (this.mediaStats.total_items === 0 || forceRefresh === 'hard') {
                this.loadMediaStats();
            }

            try {
                const params = new URLSearchParams({
                    user_id: this.user.id,
                    limit: this.pageSize.toString(),
                    offset: ((this.currentPage - 1) * this.pageSize).toString(),
                });

                if (this.filterMediaType) {
                    params.append('file_type', this.filterMediaType);
                }
                if (this.filterMediaSource) {
                    params.append('source_type', this.filterMediaSource);
                }

                const resp = await fetch(`/api/media/library?${params.toString()}`, {
                    signal: this._mediaLoadAbortController.signal
                });

                const data = await resp.json();
                const items = this.mergeSignedUrlCacheIntoItems(data.media || []);

                this.mediaLibraryAll = items;
                this.mediaLibrary = items;
                this.mediaLibraryLoaded = true;

                this.hasMore = items.length === this.pageSize;

            } catch (e) {
                if (e.name === 'AbortError') {
                    // 这是预期的请求取消，不需要处理
                    return;
                }
                console.error('加载媒体库失败:', e);
                this.mediaLibraryLoaded = true;
            } finally {
                this._mediaLoadAbortController = null;
            }
        },

        async deleteMediaItem(itemId) {
            if (!confirm('确认删除？')) return;

            try {
                const resp = await fetch(`/api/media/${itemId}?user_id=${this.user.id}`, { method: 'DELETE' });
                if (resp.ok) {
                    this.mediaLibrary = this.mediaLibrary.filter(m => m.id !== itemId);
                    this.mediaLibraryAll = this.mediaLibrary;
                    this.loadMediaStats();
                }
            } catch (e) {
                console.error('删除媒体失败:', e);
            }
        },

        async downloadMediaItem(media) {
            if (!media || !media.signed_url) return;
            try {
                const resp = await fetch(media.signed_url);
                if (!resp.ok) throw new Error('下载失败');
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = media.name || `download_${Date.now()}`;
                a.style.display = 'none';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            } catch (e) {
                console.error('下载文件失败:', e);
                alert('下载失败，请稍后重试');
            }
        },

        playMediaVideo(media) {
            this.openVideoModal(media.signed_url);
        },

        playMediaAudio(media) {
            if (!media?.signed_url) return;
            const audio = new Audio(media.signed_url);
            audio.play().catch(err => {
                console.error('播放音频失败:', err);
            });
        },

        viewMedia(media) {
            this.openImageModal(media.signed_url || media.thumbnail_signed_url);
        },

        formatMediaDuration(media) {
            const seconds = Number(media?.duration || media?.metadata?.duration || 0);
            if (!seconds) return '--';
            return `${seconds}s`;
        },

        formatMediaResolution(media) {
            if (media?.width && media?.height) {
                return `${media.width}x${media.height}`;
            }
            if (media?.metadata?.resolution) {
                return media.metadata.resolution;
            }
            if (media?.metadata?.ratio) {
                return media.metadata.ratio;
            }
            return '未知';
        },

        formatMediaSize(media) {
            const bytes = Number(media?.file_size || 0);
            if (!bytes) return '--';
            if (bytes < 1024 * 1024) {
                return `${Math.max(1, Math.round(bytes / 1024))} KB`;
            }
            return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        },
    },
};
