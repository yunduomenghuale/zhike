<script>
export default {
  onLaunch: function () {
    // 未登录直接进入登录页（pages.json 第一项即登录页，这里处理已登录场景）
    const token = uni.getStorageSync('access_token')
    if (token) {
      uni.reLaunch({ url: '/pages/home/index' })
    }
  },
}
</script>

<style>
/* 全局基础样式：与 Web 端 main.css 对齐 */
page {
  background: #f8fafc;
  color: #1e293b;
  font-family: 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont, 'Segoe UI',
    Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
</style>
