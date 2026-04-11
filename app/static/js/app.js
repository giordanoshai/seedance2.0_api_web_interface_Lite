/**
 * Cinematic AI - Alpine 入口装配
 * 页面逻辑拆分到 /static/js/pages/*.js
 */

// Tailwind 配置
window.tailwind = window.tailwind || {};
window.tailwind.config = {
    darkMode: 'class',
    theme: {
        extend: {
            colors: {
                'on-background': '#dae2fd',
                'surface-container-highest': '#2d3449',
                'surface-tint': '#c0c1ff',
                'tertiary-fixed': '#ffdcc5',
                'secondary-container': '#3c4a5e',
                'inverse-on-surface': '#283044',
                'primary-fixed': '#e1e0ff',
                'surface-container-lowest': '#060e20',
                'tertiary-container': '#d97721',
                primary: '#c0c1ff',
                'on-surface-variant': '#c7c4d7',
                'on-tertiary-fixed': '#301400',
                'primary-fixed-dim': '#c0c1ff',
                tertiary: '#ffb783',
                outline: '#908fa0',
                'surface-variant': '#2d3449',
                'outline-variant': '#464554',
                'tertiary-fixed-dim': '#ffb783',
                'surface-dim': '#0b1326',
                'inverse-primary': '#494bd6',
                'on-surface': '#dae2fd',
                'secondary-fixed': '#d5e3fd',
                'on-error': '#690005',
                surface: '#0b1326',
                'on-tertiary-fixed-variant': '#703700',
                background: '#0b1326',
                'on-tertiary': '#4f2500',
                'primary-container': '#8083ff',
                'error-container': '#93000a',
                'on-primary-fixed': '#07006c',
                'on-secondary-fixed-variant': '#3a485c',
                'inverse-surface': '#dae2fd',
                'surface-container': '#171f33',
                'on-tertiary-container': '#452000',
                'secondary-fixed-dim': '#b9c7e0',
                error: '#ffb4ab',
                'surface-container-high': '#222a3d',
                'on-secondary-container': '#abb9d2',
                'surface-container-low': '#131b2e',
                'on-secondary-fixed': '#0d1c2f',
                'on-secondary': '#233144',
                'on-primary-container': '#0d0096',
                'on-primary': '#1000a9',
                'on-primary-fixed-variant': '#2f2ebe',
                secondary: '#b9c7e0',
                'on-error-container': '#ffdad6',
                'surface-bright': '#31394d',
            },
            fontFamily: {
                headline: ['Manrope'],
                body: ['Inter'],
                label: ['Space Grotesk'],
            },
            borderRadius: {
                DEFAULT: '0.125rem',
                lg: '0.25rem',
                xl: '0.5rem',
                full: '0.75rem',
            },
        },
    },
};

function applyModule(target, module) {
    if (!module) return;
    if (typeof module.data === 'function') {
        Object.assign(target, module.data());
    }
    if (module.methods && typeof module.methods === 'object') {
        Object.assign(target, module.methods);
    }
}

function appState() {
    const state = {
        get currentModelConfig() {
            return this.models[this.selectedModel];
        },
        get currentModelCapacity() {
            return (this.capacityInfo && this.capacityInfo[this.selectedModel])
                || { active: 0, limit: 0, available: true };
        },
    };

    const modules = window.AppModules || {};
    applyModule(state, modules.auth);
    applyModule(state, modules.conversation);
    applyModule(state, modules.generator);
    applyModule(state, modules.history);
    applyModule(state, modules.media);

    return state;
}
