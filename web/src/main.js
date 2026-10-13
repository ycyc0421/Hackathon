import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import { initTheme } from './state/theme.js'
import './design-tokens.css'
import './styles.css'

// 主题要在挂载前定下来，避免先按浅色画一帧再跳成暗色。
// index.html 里的内联脚本已做过一次同样的判断（更早、防闪烁），
// 这里是兜底：内联脚本被 CSP 拦掉时仍能生效。
initTheme()

createApp(App).use(router).mount('#app')
