import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

/* Element Plus 只在题库页用到：不在此全局注册，
 * 由题库组件按需 import（保持首屏轻量，见 qbank/*.vue）。 */
createApp(App).use(router).mount('#app')
