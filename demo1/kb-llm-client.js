var http = require('http');
var https = require('https');
var dataStore = require('./kb-data-store');
var cryptoUtil = require('./kb-crypto-util');

var DEFAULT_TIMEOUT = 60000;
var PROVIDERS = {
    openai: {
        name: 'OpenAI',
        baseUrl: 'https://api.openai.com/v1/chat/completions',
        models: ['gpt-3.5-turbo', 'gpt-4', 'gpt-4o', 'gpt-4o-mini'],
        defaultModel: 'gpt-4o-mini'
    },
    deepseek: {
        name: 'DeepSeek',
        baseUrl: 'https://api.deepseek.com/v1/chat/completions',
        models: ['deepseek-chat', 'deepseek-reasoner'],
        defaultModel: 'deepseek-chat'
    }
};

var DEFAULT_PROMPT = '你是一个计算机网络课程的知识库助手。请根据以下主题，生成5个常见的问答对（Q&A），每个答案要详细、准确、适合大学生学习。请严格按照以下JSON格式输出，不要添加其他内容：\n[{"q":"问题","a":"答案"}]\n\n主题：';

function getProviderConfig(providerId) {
    var llmConfig = dataStore.loadLlmConfig();
    var provider = llmConfig.providers.find(function(p) { return p.id === providerId; });
    return provider || null;
}

function buildRequestBody(providerId, topic, customPrompt) {
    var providerMeta = PROVIDERS[providerId];
    if (!providerMeta) throw new Error('Unknown provider: ' + providerId);

    var providerConfig = getProviderConfig(providerId);
    if (!providerConfig || !providerConfig.apiKey) throw new Error('Provider ' + providerId + ' not configured or missing API key');

    var model = providerConfig.model || providerMeta.defaultModel;
    var prompt = customPrompt || DEFAULT_PROMPT;

    return {
        url: providerConfig.baseUrl || providerMeta.baseUrl,
        apiKey: cryptoUtil.decrypt(providerConfig.apiKey),
        model: model,
        body: {
            model: model,
            messages: [
                { role: 'user', content: prompt + topic }
            ],
            temperature: 0.7,
            max_tokens: 4096
        }
    };
}

function callLlmApi(url, apiKey, body) {
    return new Promise(function(resolve, reject) {
        var urlObj = new URL(url);
        var client = urlObj.protocol === 'https:' ? https : http;
        var postData = JSON.stringify(body);

        var options = {
            hostname: urlObj.hostname,
            port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
            path: urlObj.pathname + urlObj.search,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + apiKey,
                'Content-Length': Buffer.byteLength(postData)
            },
            timeout: DEFAULT_TIMEOUT
        };

        var req = client.request(options, function(res) {
            var data = '';
            res.on('data', function(chunk) { data += chunk; });
            res.on('end', function() {
                if (res.statusCode >= 200 && res.statusCode < 300) {
                    try {
                        var result = JSON.parse(data);
                        resolve(result);
                    } catch (e) {
                        reject(new Error('Invalid JSON response from LLM API'));
                    }
                } else {
                    reject(new Error('LLM API returned status ' + res.statusCode + ': ' + data.substring(0, 200)));
                }
            });
        });

        req.on('error', function(e) { reject(e); });
        req.on('timeout', function() { req.destroy(); reject(new Error('LLM API request timeout')); });
        req.write(postData);
        req.end();
    });
}

function parseLlmResponse(response) {
    try {
        var content = response.choices[0].message.content.trim();
        var jsonMatch = content.match(/\[[\s\S]*\]/);
        if (!jsonMatch) throw new Error('No JSON array found in LLM response');

        var items = JSON.parse(jsonMatch[0]);
        if (!Array.isArray(items)) throw new Error('LLM response is not an array');

        var valid = [];
        var invalid = 0;
        items.forEach(function(item) {
            if (!item.q || typeof item.q !== 'string' || !item.a || typeof item.a !== 'string') {
                invalid++;
                return;
            }
            if (item.q.indexOf('<script') >= 0 || item.a.indexOf('<script') >= 0) {
                invalid++;
                return;
            }
            valid.push({
                q: item.q.trim(),
                a: item.a.trim(),
                tags: item.tags || [],
                source: 'llm'
            });
        });

        var usage = response.usage || {};
        return {
            items: valid,
            invalid: invalid,
            tokens: {
                prompt: usage.prompt_tokens || 0,
                completion: usage.completion_tokens || 0,
                total: usage.total_tokens || 0
            }
        };
    } catch (e) {
        throw new Error('Failed to parse LLM response: ' + e.message);
    }
}

function generateKnowledge(providerId, topic, category, customPrompt) {
    var reqConfig = buildRequestBody(providerId, topic, customPrompt);

    return callLlmApi(reqConfig.url, reqConfig.apiKey, reqConfig.body).then(function(response) {
        var parsed = parseLlmResponse(response);

        var pendingItems = parsed.items.map(function(item) {
            return {
                q: item.q,
                a: item.a,
                tags: item.tags,
                source: 'llm',
                category: category || topic,
                llmProvider: providerId,
                llmModel: reqConfig.model,
                tokens: parsed.tokens
            };
        });

        var addedCount = dataStore.addPendingItems(pendingItems);

        dataStore.appendUpdateLog({
            timestamp: new Date().toISOString(),
            type: 'llm',
            status: 'success',
            details: 'Generated ' + parsed.items.length + ' items via ' + providerId + ' on topic: ' + topic,
            provider: providerId,
            model: reqConfig.model,
            topic: topic,
            tokens: parsed.tokens,
            addedToPending: addedCount
        });

        return {
            provider: providerId,
            model: reqConfig.model,
            topic: topic,
            generatedItems: parsed.items.length,
            invalidItems: parsed.invalid,
            addedToPending: addedCount,
            tokens: parsed.tokens
        };
    }).catch(function(err) {
        dataStore.appendUpdateLog({
            timestamp: new Date().toISOString(),
            type: 'llm',
            status: 'failed',
            details: 'LLM generation failed: ' + err.message,
            provider: providerId,
            topic: topic
        });
        throw err;
    });
}

function testConnection(providerId) {
    var providerMeta = PROVIDERS[providerId];
    if (!providerMeta) return Promise.reject(new Error('Unknown provider: ' + providerId));

    var providerConfig = getProviderConfig(providerId);
    if (!providerConfig || !providerConfig.apiKey) return Promise.reject(new Error('Provider not configured or missing API key'));

    var apiKey = cryptoUtil.decrypt(providerConfig.apiKey);
    var model = providerConfig.model || providerMeta.defaultModel;
    var url = providerConfig.baseUrl || providerMeta.baseUrl;

    return callLlmApi(url, apiKey, {
        model: model,
        messages: [{ role: 'user', content: 'Hello' }],
        max_tokens: 5
    }).then(function() {
        return { success: true, provider: providerId, model: model };
    }).catch(function(err) {
        return { success: false, provider: providerId, model: model, error: err.message };
    });
}

function getAvailableProviders() {
    var llmConfig = dataStore.loadLlmConfig();
    return Object.keys(PROVIDERS).map(function(id) {
        var meta = PROVIDERS[id];
        var configured = llmConfig.providers.find(function(p) { return p.id === id; });
        return {
            id: id,
            name: meta.name,
            models: meta.models,
            defaultModel: meta.defaultModel,
            configured: !!(configured && configured.apiKey),
            model: configured ? (configured.model || meta.defaultModel) : meta.defaultModel
        };
    });
}

function saveProviderConfig(providerId, config) {
    var llmConfig = dataStore.loadLlmConfig();
    var idx = llmConfig.providers.findIndex(function(p) { return p.id === providerId; });

    var providerMeta = PROVIDERS[providerId];
    if (!providerMeta) throw new Error('Unknown provider: ' + providerId);

    var entry = {
        id: providerId,
        baseUrl: config.baseUrl || providerMeta.baseUrl,
        model: config.model || providerMeta.defaultModel,
        apiKey: config.apiKey ? cryptoUtil.encrypt(config.apiKey) : (idx >= 0 ? llmConfig.providers[idx].apiKey : ''),
        enabled: config.enabled !== undefined ? config.enabled : true
    };

    if (idx >= 0) {
        llmConfig.providers[idx] = entry;
    } else {
        llmConfig.providers.push(entry);
    }

    dataStore.saveLlmConfig(llmConfig);
    return { id: providerId, name: providerMeta.name, model: entry.model, configured: !!entry.apiKey, enabled: entry.enabled };
}

function autoGenerateForWeakCategories() {
    var knowledge = dataStore.loadKnowledge();
    var llmConfig = dataStore.loadLlmConfig();

    var enabledProviders = llmConfig.providers.filter(function(p) { return p.enabled && p.apiKey; });
    if (enabledProviders.length === 0) return Promise.resolve({ status: 'skipped', message: 'No enabled LLM providers' });

    var categoryStats = knowledge.map(function(cat) {
        return { category: cat.category, itemCount: cat.items.length };
    }).sort(function(a, b) { return a.itemCount - b.itemCount; });

    var target = categoryStats[0];
    if (!target) return Promise.resolve({ status: 'skipped', message: 'No categories found' });

    var provider = enabledProviders[0];
    return generateKnowledge(provider.id, target.category, target.category);
}

module.exports = {
    generateKnowledge: generateKnowledge,
    testConnection: testConnection,
    getAvailableProviders: getAvailableProviders,
    saveProviderConfig: saveProviderConfig,
    autoGenerateForWeakCategories: autoGenerateForWeakCategories,
    PROVIDERS: PROVIDERS
};