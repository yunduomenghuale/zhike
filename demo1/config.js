var SiteConfig = {
    SITE_NAME: '网络学习小伴侣',
    SITE_SUBTITLE: '洛阳理工学院计算机学院',
    HOST: '127.0.0.1',
    PORT: 8081,
    getBaseUrl: function() {
        return 'http://' + this.HOST + (this.PORT === 80 ? '' : ':' + this.PORT);
    }
};