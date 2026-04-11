window.AppModules = window.AppModules || {};

window.AppModules.history = {
    data() {
        return {
            taskList: [],
        };
    },

    methods: {
        async loadTasks() {
            if (!this.user) return;
            try {
                const resp = await fetch(`/api/tasks?user_id=${this.user.id}`);
                const data = await resp.json();
                this.taskList = data.tasks || [];
            } catch (e) {
                console.error('加载任务列表失败:', e);
            }
        },

        async playVideo(task) {
            try {
                const resp = await fetch(`/api/video/${task.id}`);
                const data = await resp.json();
                this.playInCurrentVideo(data.signed_video_url);
            } catch (e) {
                console.error('获取视频失败:', e);
            }
        },

        async deleteTask(taskId) {
            try {
                await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
                this.taskList = this.taskList.filter(t => t.id !== taskId);
            } catch (e) {
                console.error('删除任务失败:', e);
            }
        },
    },
};
