<script>
export default {
  onLaunch() {
    const token = uni.getStorageSync('access_token')
    uni.reLaunch({ url: token ? '/pages/home/index' : '/pages/login/index' })
  },
}
</script>

<style lang="scss">
@import '@/uni.scss';

page,
body,
uni-page-body {
  // Capacitor 打包的 Android WebView 不会提供 uni-app 的状态栏变量，
  // 以 88rpx 作为刘海/灵动岛机型兜底，并优先使用系统提供的安全区。
  --app-safe-top: max(var(--status-bar-height, 0px), env(safe-area-inset-top, 0px), 88rpx);
}

page {
  min-height: 100%;
  background: $app-bg;
  color: $text-main;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

view,
text,
input,
button,
textarea,
scroll-view {
  box-sizing: border-box;
}

button::after {
  border: 0;
}
</style>
