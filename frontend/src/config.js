// 外部系统集成入口
// 网络学习小伴侣（demo1）：独立的 Node.js 教学系统，本地默认 8081 端口。
// 部署到其他地址时用 VITE_DEMO1_URL 覆盖，如 VITE_DEMO1_URL=http://124.70.107.64:8090
export const DEMO1_URL = import.meta.env.VITE_DEMO1_URL || 'http://127.0.0.1:8081'
