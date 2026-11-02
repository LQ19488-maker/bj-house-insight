import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import './styles/tokens.css'

// Element Plus 组件与样式由 unplugin-vue-components 按需注入（见 vite.config.js），
// 这里不再全量注册 —— 否则会把整套组件库（约 1 MB）打进包里。
const app = createApp(App)

app.use(createPinia())
app.use(router)
app.mount('#app')
