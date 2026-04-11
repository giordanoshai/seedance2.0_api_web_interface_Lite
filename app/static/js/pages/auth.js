/**
 * auth.js — 无认证模式（开源版）
 * 直接以本地用户身份初始化，无需登录，打开即用
 */
window.AppModules = window.AppModules || {};

window.AppModules.auth = {
    data() {
        return {
            // 固定本地用户，无需认证
            user: { id: 'local_user', email: 'local@localhost' },
            userProfile: { display_name: '本地用户' },
            // 保留字段（兼容模板中的 x-show="user" 判断）
            showProfileModal: false,
            profileDisplayName: '',
            profileSaving: false,
            profileError: '',
        };
    },

    methods: {
        async initAuth() {
            // 无认证模式：直接触发登录后的初始化逻辑
            await this.onUserLoggedIn();
        },

        async onUserLoggedIn() {
            if (typeof this.loadConversations === 'function') {
                await this.loadConversations();
                if (this.conversations && this.conversations.length > 0) {
                    await this.switchConversation(this.conversations[0]);
                }
            }
        },

        onUserLoggedOut() {
            // 本地模式无需登出操作
        },

        // 以下方法保留空实现以兼容模板中的调用
        openProfileModal() {},
        closeProfileModal() { this.showProfileModal = false; },
        async saveProfile() {},
    },
};
