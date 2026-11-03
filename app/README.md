# 智课平台 App

该目录是只面向 Android / iOS 安装包的 uni-app 工程，不提供 H5 启动或构建脚本。

## 已实现

- 登录、注册与 JWT 自动刷新
- 教师 / 学生工作台
- 课程与班级邀请码
- 章节讲解、章节 AI 助教、相关资料
- 消息中心与已读状态
- 个人资料与入班前完整性提醒

## 构建

```bash
npm install
npm run build:app
```

编译产物在 `dist/build/app` 。生成 Android APK 时，用 HBuilderX 导入本目录，先在 `manifest.json` 获取 DCloud AppID，再选择「发行 -> 原生 App-云打包」。

真机默认连接 `http://39.105.44.181:8005`。
