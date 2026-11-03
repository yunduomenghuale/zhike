(function() {
    var style = document.createElement('style');
    style.textContent =
        '#chat-fab{position:fixed;bottom:30px;right:30px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#4a90e2,#357abd);color:white;border:none;font-size:28px;cursor:pointer;box-shadow:0 4px 20px rgba(74,144,226,0.5);z-index:9998;transition:all 0.3s;display:flex;align-items:center;justify-content:center;}' +
        '#chat-fab:hover{transform:scale(1.1);box-shadow:0 6px 25px rgba(74,144,226,0.6);}' +
        '#chat-panel{position:fixed;bottom:100px;right:30px;width:400px;max-height:calc(100vh - 200px);background:white;border-radius:16px;box-shadow:0 10px 50px rgba(0,0,0,0.25);z-index:9998;display:none;flex-direction:column;overflow:hidden;font-family:"Microsoft YaHei",Arial,sans-serif;}' +
        '#chat-panel.open{display:flex;animation:chatSlideUp 0.3s ease;}' +
        '@keyframes chatSlideUp{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}' +
        '#chat-header{background:linear-gradient(135deg,#4a90e2,#357abd);color:white;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-radius:16px 16px 0 0;flex-shrink:0;}' +
        '#chat-header h3{font-size:16px;margin:0;}' +
        '#chat-close{background:none;border:none;color:white;font-size:22px;cursor:pointer;padding:0 4px;}' +
        '#chat-body{flex:1;overflow-y:auto;padding:16px;max-height:380px;min-height:300px;}' +
        '.chat-msg{margin-bottom:12px;display:flex;}' +
        '.chat-msg.bot{justify-content:flex-start;}' +
        '.chat-msg.user{justify-content:flex-end;}' +
        '.chat-bubble{max-width:85%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.7;white-space:pre-wrap;word-break:break-word;}' +
        '.chat-msg.bot .chat-bubble{background:#f0f4ff;color:#333;border-bottom-left-radius:4px;}' +
        '.chat-msg.user .chat-bubble{background:#4a90e2;color:white;border-bottom-right-radius:4px;}' +
        '.chat-category{margin:8px 0;}' +
        '.chat-cat-btn{display:inline-block;margin:3px;padding:5px 12px;background:#e8f4ff;color:#4a90e2;border:1px solid #b8daff;border-radius:15px;font-size:12px;cursor:pointer;transition:all 0.2s;}' +
        '.chat-cat-btn:hover{background:#4a90e2;color:white;}' +
        '#chat-input-area{display:flex;padding:12px;border-top:1px solid #eee;gap:8px;}' +
        '#chat-input{flex:1;padding:10px 14px;border:2px solid #e0e0e0;border-radius:20px;font-size:14px;outline:none;font-family:inherit;}' +
        '#chat-input:focus{border-color:#4a90e2;}' +
        '#chat-send{padding:10px 18px;background:#4a90e2;color:white;border:none;border-radius:20px;font-size:14px;cursor:pointer;transition:background 0.3s;}' +
        '#chat-send:hover{background:#357abd;}' +
        '#chat-suggestions{padding:0 16px 8px;display:flex;flex-wrap:wrap;gap:4px;}' +
        '.chat-sug-btn{padding:4px 10px;background:#f8f9fa;border:1px solid #e0e0e0;border-radius:12px;font-size:12px;color:#666;cursor:pointer;transition:all 0.2s;}' +
        '.chat-sug-btn:hover{background:#e8f4ff;color:#4a90e2;border-color:#b8daff;}';
    document.head.appendChild(style);

    var fab = document.createElement('button');
    fab.id = 'chat-fab';
    fab.innerHTML = '🎓';
    fab.title = '网络学习小伴侣';
    fab.onclick = function() { toggleChat(); };
    document.body.appendChild(fab);

    var panel = document.createElement('div');
    panel.id = 'chat-panel';
    panel.innerHTML =
        '<div id="chat-header"><h3>🎓 网络学习小伴侣</h3><button id="chat-close" onclick="toggleChatPanel()">✕</button></div>' +
        '<div id="chat-body"></div>' +
        '<div id="chat-suggestions"></div>' +
        '<div id="chat-input-area"><input type="text" id="chat-input" placeholder="输入问题，如：什么是TCP三次握手" onkeydown="if(event.key===\'Enter\')sendChat()"><button id="chat-send" onclick="sendChat()">发送</button></div>';
    document.body.appendChild(panel);

    var chatBody = document.getElementById('chat-body');
    var chatInput = document.getElementById('chat-input');
    var chatSuggestions = document.getElementById('chat-suggestions');

    window.toggleChatPanel = function() {
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) {
            chatInput.focus();
        }
    };

    function toggleChat() {
        panel.classList.toggle('open');
        if (panel.classList.contains('open')) {
            if (chatBody.children.length === 0) {
                showWelcome();
            }
            setTimeout(function() { chatInput.focus(); }, 100);
        }
    }

    function showWelcome() {
        addBotMessage('你好！我是网络学习小伴侣 🎓\n我可以回答关于计算机网络课程的问题，包括：\n\n• 计算机网络概述\n• 物理层（编码、复用、传输介质）\n• 数据链路层（以太网、VLAN、STP）\n• 网络层（IP、ARP、路由、NAT）\n• 传输层（TCP、UDP）\n• 应用层（DNS、DHCP、HTTP）\n• 实验操作（华为命令）\n• 华为ICT大赛（赛事介绍、历年真题、备赛指南）\n\n请输入你的问题，或点击下方分类浏览：');
        showCategories();
    }

    function showCategories() {
        var html = '';
        if (typeof ChatKnowledge !== 'undefined') {
            ChatKnowledge.forEach(function(cat) {
                html += '<span class="chat-cat-btn" onclick="selectCategory(\'' + cat.category.replace(/'/g, "\\'") + '\')">' + cat.category + '</span>';
            });
        }
        chatSuggestions.innerHTML = html;
    }

    window.selectCategory = function(category) {
        lastCategory = category;
        chatSuggestions.innerHTML = '';
        if (typeof ChatKnowledge === 'undefined') return;
        var cat = ChatKnowledge.find(function(c) { return c.category === category; });
        if (!cat) return;
        addUserMessage(category);
        var html = '【' + category + '】常见问题：\n\n';
        cat.items.forEach(function(item, idx) {
            html += (idx + 1) + '. ' + item.q + '\n';
        });
        html += '\n请输入问题编号或直接提问';
        addBotMessage(html);
        var sugHtml = '';
        cat.items.slice(0, 5).forEach(function(item) {
            sugHtml += '<span class="chat-sug-btn" onclick="sendChatText(\'' + item.q.replace(/'/g, "\\'") + '\')">' + item.q + '</span>';
        });
        chatSuggestions.innerHTML = sugHtml;
    };

    function addBotMessage(text) {
        var div = document.createElement('div');
        div.className = 'chat-msg bot';
        div.innerHTML = '<div class="chat-bubble">' + escapeHtml(text) + '</div>';
        chatBody.appendChild(div);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    function addUserMessage(text) {
        var div = document.createElement('div');
        div.className = 'chat-msg user';
        div.innerHTML = '<div class="chat-bubble">' + escapeHtml(text) + '</div>';
        chatBody.appendChild(div);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    window.sendChat = function() {
        var text = chatInput.value.trim();
        if (!text) return;
        chatInput.value = '';
        chatSuggestions.innerHTML = '';
        addUserMessage(text);
        setTimeout(function() {
            var numAnswer = tryNumberAnswer(text);
            if (numAnswer) {
                addBotMessage(numAnswer);
                showFollowUp(text);
            } else {
                var answer = findAnswer(text);
                addBotMessage(answer);
                showFollowUp(text);
            }
        }, 300);
    };

    var lastCategory = null;

    function tryNumberAnswer(text) {
        var num = parseInt(text, 10);
        if (isNaN(num) || num < 1) return null;
        if (typeof ChatKnowledge === 'undefined') return null;
        if (!lastCategory) return null;
        var cat = ChatKnowledge.find(function(c) { return c.category === lastCategory; });
        if (!cat || num > cat.items.length) return null;
        var item = cat.items[num - 1];
        return '【' + lastCategory + '】' + item.q + '\n\n' + item.a;
    }

    window.sendChatText = function(text) {
        chatInput.value = text;
        window.sendChat();
    };

    function findAnswer(query) {
        if (typeof ChatKnowledge === 'undefined') {
            return '知识库未加载，请刷新页面重试。';
        }

        var queryLower = query.toLowerCase().trim();
        var results = [];

        var synonyms = {
            'tcp三次握手': ['tcp连接', '三次握手', 'tcp握手', '建立连接'],
            'tcp四次挥手': ['tcp断开', '四次挥手', 'tcp挥手', '释放连接', '断开连接', '关闭连接'],
            'ip地址': ['ip', '网际协议地址', 'internet protocol'],
            'mac地址': ['mac', '物理地址', '硬件地址'],
            '子网掩码': ['掩码', '子网划分', 'subnet mask'],
            '路由协议': ['路由', 'routing'],
            'ospf': ['开放最短路径优先', '链路状态路由', 'open shortest path first'],
            'rip': ['路由信息协议', '距离向量路由', 'routing information protocol'],
            'bgp': ['边界网关协议', 'border gateway protocol'],
            'dns': ['域名系统', '域名解析', 'domain name system'],
            'dhcp': ['动态主机配置', '自动分配ip', 'dynamic host configuration'],
            'http': ['超文本传输', 'hypertext transfer'],
            'https': ['安全http', '加密http'],
            'arp': ['地址解析', 'ip转mac', 'address resolution'],
            'icmp': ['互联网控制报文', 'ping', 'internet control message'],
            'vlan': ['虚拟局域网', 'virtual lan'],
            'stp': ['生成树', 'spanning tree'],
            'nat': ['网络地址转换', 'network address translation'],
            'cdma': ['码分复用', '码分多址'],
            'csma': ['载波监听', 'carrier sense'],
            'cidr': ['无分类编址', '无类域间路由'],
            '曼彻斯特': ['manchester'],
            '以太网': ['ethernet', '局域网'],
            '交换机': ['switch', '二层交换'],
            '路由器': ['router', '三层设备'],
            '双绞线': ['twisted pair'],
            '光纤': ['fiber', 'optical', '光缆'],
            '帧': ['frame', '数据帧', 'mac帧'],
            '分组': ['packet', '数据包', 'ip数据报'],
            '报文': ['message', 'segment'],
            '套接字': ['socket'],
            '端口号': ['port', '端口'],
            '拥塞控制': ['congestion', '拥塞避免'],
            '流量控制': ['flow control', '滑动窗口'],
            '滑动窗口': ['sliding window', '流量控制'],
            'crc': ['循环冗余校验', '校验码', '帧校验'],
            '复用': ['multiplexing', '多路复用'],
            '编码': ['encoding', '信号编码'],
            '带宽': ['bandwidth', '频宽'],
            '时延': ['delay', '延迟', 'latency'],
            '吞吐量': ['throughput'],
            '华为': ['huawei', 'ensp', '交换机配置', '路由器配置'],
            'ict': ['信息通信技术', '大赛', '竞赛', '比赛'],
            '考研': ['408', '考研真题', '计算机考研', '研究生考试', '统考', '计算机统考'],
            '408': ['考研', '考研真题', '计算机考研', '研究生考试', '统考', '计算机统考'],
            '真题': ['考研', '408', '历年试题', '考试真题'],
            '研究生': ['考研', '408', '统考', '研究生入学']
        };

        var expandedTerms = [queryLower];
        Object.keys(synonyms).forEach(function(key) {
            var synList = synonyms[key];
            var allTerms = [key].concat(synList);
            var matched = false;
            allTerms.forEach(function(term) {
                if (queryLower.indexOf(term) >= 0 || term.indexOf(queryLower) >= 0) {
                    matched = true;
                }
            });
            if (matched) {
                allTerms.forEach(function(term) {
                    if (expandedTerms.indexOf(term) < 0) expandedTerms.push(term);
                });
            }
        });

        var queryKeywords = extractKeywords(queryLower);

        ChatKnowledge.forEach(function(cat) {
            cat.items.forEach(function(item) {
                var score = 0;
                var qLower = item.q.toLowerCase();
                var aLower = item.a.toLowerCase();

                if (qLower === queryLower) { score = 100; }
                else if (qLower.indexOf(queryLower) >= 0) { score = 85; }
                else if (queryLower.indexOf(qLower) >= 0) { score = 75; }

                expandedTerms.forEach(function(term) {
                    if (term === queryLower) return;
                    if (qLower.indexOf(term) >= 0) score += 25;
                    else if (aLower.indexOf(term) >= 0) score += 10;
                });

                queryKeywords.forEach(function(kw) {
                    if (kw.length < 2) return;
                    if (qLower.indexOf(kw) >= 0) score += 20;
                    else if (aLower.indexOf(kw) >= 0) score += 8;
                });

                if (item.tags && Array.isArray(item.tags)) {
                    item.tags.forEach(function(tag) {
                        var tagLower = tag.toLowerCase();
                        expandedTerms.forEach(function(term) {
                            if (tagLower.indexOf(term) >= 0 || term.indexOf(tagLower) >= 0) {
                                score += 15;
                            }
                        });
                        queryKeywords.forEach(function(kw) {
                            if (kw.length >= 2 && tagLower.indexOf(kw) >= 0) {
                                score += 15;
                            }
                        });
                    });
                }

                if (cat.category.toLowerCase().indexOf(queryLower) >= 0) {
                    score += 20;
                }

                if (score > 15) {
                    results.push({ item: item, score: score, category: cat.category });
                }
            });
        });

        results.sort(function(a, b) { return b.score - a.score; });

        var uniqueResults = [];
        var seenQ = {};
        results.forEach(function(r) {
            if (!seenQ[r.item.q]) {
                seenQ[r.item.q] = true;
                uniqueResults.push(r);
            }
        });
        results = uniqueResults;

        if (results.length === 0) {
            return '抱歉，我暂时没有找到与"' + query + '"相关的答案。\n\n你可以尝试：\n• 换个关键词提问（如：TCP、IP地址、VLAN）\n• 点击下方分类浏览\n• 输入"帮助"查看使用说明';
        }

        var best = results[0];
        if (best.score >= 50) {
            return '【' + best.category + '】' + best.item.q + '\n\n' + best.item.a;
        }

        var answer = '找到以下相关内容：\n\n';
        var shown = 0;
        results.forEach(function(r) {
            if (shown >= 3) return;
            answer += '📌 ' + r.item.q + '（相关度：' + Math.round(r.score) + '%）\n';
            shown++;
        });
        answer += '\n请输入具体问题获取详细解答';
        return answer;
    }

    function extractKeywords(text) {
        var stopWords = ['的', '了', '是', '在', '有', '和', '与', '或', '不', '也', '都', '什么', '怎么', '如何', '为什么', '哪', '哪些', '吗', '呢', '啊', '吧', '请', '能', '可以', '说', '讲', '介绍', '解释', '一下', '告诉', '问'];
        var keywords = [];
        text.split(/\s+/).forEach(function(w) {
            if (w.length >= 2 && stopWords.indexOf(w) < 0) keywords.push(w);
        });
        if (keywords.length === 0 && text.length >= 2) {
            keywords.push(text);
        }
        var bigrams = [];
        for (var i = 0; i < text.length - 1; i++) {
            var bi = text.substring(i, i + 2);
            if (stopWords.indexOf(bi) < 0 && keywords.indexOf(bi) < 0) {
                bigrams.push(bi);
            }
        }
        keywords = keywords.concat(bigrams);
        return keywords;
    }

    function showFollowUp(query) {
        if (typeof ChatKnowledge === 'undefined') return;
        var suggestions = [];
        var queryLower = query.toLowerCase();
        ChatKnowledge.forEach(function(cat) {
            cat.items.forEach(function(item) {
                if (item.q.toLowerCase() !== queryLower && suggestions.length < 4) {
                    var qChars = query.replace(/\s/g, '').split('');
                    var match = 0;
                    qChars.forEach(function(ch) {
                        if (item.q.toLowerCase().indexOf(ch) >= 0) match++;
                    });
                    if (match / qChars.length > 0.3) {
                        suggestions.push(item.q);
                    }
                }
            });
        });
        if (suggestions.length === 0) {
            showCategories();
            return;
        }
        var html = '';
        suggestions.forEach(function(s) {
            html += '<span class="chat-sug-btn" onclick="sendChatText(\'' + s.replace(/'/g, "\\'") + '\')">' + s + '</span>';
        });
        chatSuggestions.innerHTML = html;
    }
})();