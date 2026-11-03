(function() {
    var loadSource = 'static';

    function loadKnowledge() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/knowledge', true);
        xhr.timeout = 5000;
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 200) {
                    try {
                        var data = JSON.parse(xhr.responseText);
                        if (data.categories && Array.isArray(data.categories) && data.categories.length > 0) {
                            var staticCategories = window.ChatKnowledge || [];
                            var apiCategories = data.categories;
                            var existingCats = {};
                            staticCategories.forEach(function(c) { existingCats[c.category] = c; });
                            apiCategories.forEach(function(c) {
                                if (existingCats[c.category]) {
                                    var existingItems = existingCats[c.category].items;
                                    c.items.forEach(function(item) {
                                        var dup = existingItems.find(function(ei) { return ei.q === item.q; });
                                        if (!dup) existingItems.push(item);
                                    });
                                } else {
                                    staticCategories.push(c);
                                }
                            });
                            window.ChatKnowledge = staticCategories;
                            loadSource = 'api';
                        }
                    } catch (e) {
                        loadSource = 'static';
                    }
                } else {
                    loadSource = 'static';
                }
            }
        };
        xhr.onerror = function() { loadSource = 'static'; };
        xhr.ontimeout = function() { loadSource = 'static'; };
        xhr.send();
    }

    window.getKnowledgeLoadSource = function() { return loadSource; };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadKnowledge);
    } else {
        loadKnowledge();
    }
})();