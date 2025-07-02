/**
 * TailExplorer 前端逻辑
 */

class TailExplorer {
    constructor() {
        this.ws = null;
        this.logs = [];
        this.filteredLogs = [];
        this.currentFilter = '';
        this.autoScroll = true;
        this.isAtBottom = true;
        this.currentSource = '';
        this.availableSources = {};

        this.initElements();
        this.bindEvents();
        this.loadSources();
    }
    
    initElements() {
        this.logDisplay = document.getElementById('log-display');
        this.sourceSelect = document.getElementById('source-select');
        this.autoScrollToggle = document.getElementById('auto-scroll-toggle');
        this.keywordFilter = document.getElementById('keyword-filter');
        this.clearFilterBtn = document.getElementById('clear-filter');
        this.clearLogsBtn = document.getElementById('clear-logs');
        this.logoutBtn = document.getElementById('logout-btn');
        this.connectionStatus = document.getElementById('connection-status');
        this.logCount = document.getElementById('log-count');
        this.sourceInfo = document.getElementById('source-info');
        this.autoScrollIndicator = document.getElementById('auto-scroll-indicator');
    }
    
    bindEvents() {
        // 日志源选择
        this.sourceSelect.addEventListener('change', (e) => {
            const sourceId = e.target.value;
            if (sourceId) {
                this.connectToSource(sourceId);
            }
        });

        // 自动滚动开关
        this.autoScrollToggle.addEventListener('change', (e) => {
            this.autoScroll = e.target.checked;
            this.updateAutoScrollIndicator();
            if (this.autoScroll) {
                // 勾选自动滚动时立即滚动到底部
                this.scrollToBottom();
            }
        });

        // 关键词过滤
        this.keywordFilter.addEventListener('input', (e) => {
            this.currentFilter = e.target.value.toLowerCase();
            this.applyFilter();
        });

        // 清除过滤器
        this.clearFilterBtn.addEventListener('click', () => {
            this.keywordFilter.value = '';
            this.currentFilter = '';
            this.applyFilter();
        });

        // 清空日志
        this.clearLogsBtn.addEventListener('click', () => {
            this.clearLogs();
        });

        // 登出
        this.logoutBtn.addEventListener('click', () => {
            this.handleLogout();
        });

        // 监听滚动事件
        this.logDisplay.addEventListener('scroll', () => {
            this.checkScrollPosition();
        });

        // 键盘快捷键
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case 'f':
                        e.preventDefault();
                        this.keywordFilter.focus();
                        break;
                    case 'l':
                        e.preventDefault();
                        this.clearLogs();
                        break;
                }
            }
        });
    }
    
    async loadSources() {
        try {
            const response = await fetch('/api/sources');
            if (response.status === 401) {
                // 未授权，跳转到登录页
                window.location.href = '/login';
                return;
            }
            if (response.ok) {
                this.availableSources = await response.json();
                this.updateSourceSelect();
            } else {
                console.error('加载日志源失败:', response.statusText);
                this.showError('加载日志源失败');
            }
        } catch (error) {
            console.error('加载日志源失败:', error);
            this.showError('加载日志源失败: ' + error.message);
        }
    }

    async handleLogout() {
        try {
            const response = await fetch('/api/logout', {
                method: 'POST'
            });

            if (response.ok) {
                // 登出成功，跳转到登录页
                window.location.href = '/login';
            } else {
                console.error('登出失败:', response.statusText);
            }
        } catch (error) {
            console.error('登出请求失败:', error);
            // 即使请求失败，也跳转到登录页
            window.location.href = '/login';
        }
    }

    async checkAuthStatus() {
        try {
            const response = await fetch('/api/sources');
            if (response.status === 401) {
                console.log('认证失效，跳转到登录页');
                window.location.href = '/login';
            }
        } catch (error) {
            console.error('检查认证状态失败:', error);
        }
    }

    updateSourceSelect() {
        // 清空现有选项
        this.sourceSelect.innerHTML = '';

        // 添加可用的日志源
        const sourceEntries = Object.entries(this.availableSources);
        for (const [sourceId, sourceInfo] of sourceEntries) {
            const option = document.createElement('option');
            option.value = sourceId;
            option.textContent = `${sourceInfo.name} (${sourceInfo.type})`;
            option.title = sourceInfo.description;
            this.sourceSelect.appendChild(option);
        }

        // 自动选择第一个日志源
        if (sourceEntries.length > 0 && !this.currentSource) {
            const firstSourceId = sourceEntries[0][0];
            this.sourceSelect.value = firstSourceId;
            this.connectToSource(firstSourceId);
        }
    }

    connectToSource(sourceId) {
        if (this.currentSource === sourceId && this.ws && this.ws.readyState === WebSocket.OPEN) {
            return; // 已经连接到此日志源
        }

        // 断开现有连接
        this.disconnect();

        this.currentSource = sourceId;
        this.clearLogs();

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${sourceId}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log(`WebSocket连接已建立: ${sourceId}`);
            this.updateConnectionStatus(true);
            this.updateSourceInfo();
            this.hideLoading();
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (error) {
                console.error('解析消息失败:', error);
            }
        };

        this.ws.onclose = (event) => {
            console.log(`WebSocket连接已关闭: ${sourceId}, 代码: ${event.code}`);
            this.updateConnectionStatus(false);

            // 检查是否是认证失败 (4001自定义码或1002/1003标准码)
            if (event.code === 4001 || event.code === 1002 || event.code === 1003) {
                console.log('WebSocket认证失败，跳转到登录页');
                window.location.href = '/login';
                return;
            }

            // 如果是意外断开，尝试重连
            if (this.currentSource === sourceId) {
                this.showReconnecting();
                setTimeout(() => {
                    if (this.currentSource === sourceId) {
                        this.connectToSource(sourceId);
                    }
                }, 5000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
            this.updateConnectionStatus(false);

            // WebSocket连接失败可能是认证问题，检查API访问
            this.checkAuthStatus();
        };
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.currentSource = '';
        this.updateConnectionStatus(false);
        this.updateSourceInfo();
    }
    
    handleMessage(data) {
        switch (data.type) {
            case 'initial_logs':
                this.loadInitialLogs(data.logs);
                break;
            case 'new_log':
                this.addNewLog(data.log);
                break;
            case 'error':
                this.showError(data.message);
                break;
        }
    }
    
    loadInitialLogs(logs) {
        this.logs = logs;
        this.applyFilter();
        this.scrollToBottom();
        this.updateLogCount();
    }
    
    addNewLog(log) {
        this.logs.push(log);
        
        // 限制日志数量，避免内存溢出
        if (this.logs.length > 10000) {
            this.logs = this.logs.slice(-5000);
        }
        
        if (this.matchesFilter(log)) {
            this.appendLogToDisplay(log);
            
            if (this.autoScroll && this.isAtBottom) {
                this.scrollToBottom();
            }
        }
        
        this.updateLogCount();
    }
    
    applyFilter() {
        this.filteredLogs = this.currentFilter 
            ? this.logs.filter(log => this.matchesFilter(log))
            : this.logs;
        
        this.renderLogs();
    }
    
    matchesFilter(log) {
        if (!this.currentFilter) return true;
        // 移除ANSI代码后再进行匹配
        const cleanLog = this.stripAnsiCodes(log);
        return cleanLog.toLowerCase().includes(this.currentFilter);
    }
    
    renderLogs() {
        const wasAtBottom = this.isAtBottom;
        
        this.logDisplay.innerHTML = '';
        
        this.filteredLogs.forEach(log => {
            this.appendLogToDisplay(log);
        });
        
        if (wasAtBottom) {
            this.scrollToBottom();
        }
    }
    
    appendLogToDisplay(log) {
        const logElement = document.createElement('div');
        logElement.className = 'log-line';

        // 转换ANSI颜色代码为HTML
        let processedLog = this.convertAnsiToHtml(this.escapeHtml(log));

        // 高亮关键词
        if (this.currentFilter) {
            // 先移除ANSI代码进行搜索
            const cleanLog = this.stripAnsiCodes(log);
            if (cleanLog.toLowerCase().includes(this.currentFilter)) {
                const regex = new RegExp(`(${this.escapeRegex(this.currentFilter)})`, 'gi');
                processedLog = processedLog.replace(regex, '<mark>$1</mark>');
                logElement.classList.add('highlight');
            }
        }

        logElement.innerHTML = processedLog;
        this.logDisplay.appendChild(logElement);
    }
    
    scrollToBottom() {
        this.logDisplay.scrollTop = this.logDisplay.scrollHeight;
        this.isAtBottom = true;
    }
    
    checkScrollPosition() {
        const { scrollTop, scrollHeight, clientHeight } = this.logDisplay;
        const wasAtBottom = this.isAtBottom;
        this.isAtBottom = scrollTop + clientHeight >= scrollHeight - 10;

        // 如果用户手动滚动离开底部，关闭自动滚动
        if (wasAtBottom && !this.isAtBottom && this.autoScroll) {
            this.autoScroll = false;
            this.updateAutoScrollIndicator();
        }
    }
    
    updateAutoScrollIndicator() {
        // 更新开关状态
        this.autoScrollToggle.checked = this.autoScroll;

        // 更新指示器显示
        if (this.autoScroll && this.isAtBottom) {
            this.autoScrollIndicator.classList.add('show');
        } else {
            this.autoScrollIndicator.classList.remove('show');
        }
    }
    
    clearLogs() {
        this.logs = [];
        this.filteredLogs = [];
        this.logDisplay.innerHTML = '';
        this.updateLogCount();
    }
    
    updateConnectionStatus(connected) {
        if (connected) {
            this.connectionStatus.textContent = '已连接';
            this.connectionStatus.className = 'status-connected';
        } else {
            this.connectionStatus.textContent = '未连接';
            this.connectionStatus.className = 'status-disconnected';
        }
    }
    
    updateLogCount() {
        this.logCount.textContent = `日志: ${this.logs.length}`;
    }

    updateSourceInfo() {
        if (this.currentSource && this.availableSources[this.currentSource]) {
            const sourceInfo = this.availableSources[this.currentSource];
            this.sourceInfo.textContent = `源: ${sourceInfo.name}`;
        } else {
            this.sourceInfo.textContent = '';
        }
    }
    
    hideLoading() {
        const loading = this.logDisplay.querySelector('.loading');
        if (loading) {
            loading.remove();
        }
    }
    
    showReconnecting() {
        this.logDisplay.innerHTML = `
            <div class="loading">
                <div class="spinner"></div>
                <p>连接断开，正在重连...</p>
            </div>
        `;
    }
    
    showError(message) {
        const errorElement = document.createElement('div');
        errorElement.className = 'log-line';
        errorElement.style.color = '#e74c3c';
        errorElement.style.fontWeight = 'bold';
        errorElement.textContent = `❌ 错误: ${message}`;
        this.logDisplay.appendChild(errorElement);
        this.scrollToBottom();
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    stripAnsiCodes(text) {
        // 移除ANSI颜色代码和控制字符
        return text.replace(/\x1b\[[0-9;]*m/g, '');
    }

    convertAnsiToHtml(text) {
        // 将ANSI颜色代码转换为HTML样式
        const ansiColors = {
            '30': 'color: #000000',  // 黑色
            '31': 'color: #cd3131',  // 红色
            '32': 'color: #0dbc79',  // 绿色
            '33': 'color: #e5e510',  // 黄色
            '34': 'color: #2472c8',  // 蓝色
            '35': 'color: #bc3fbc',  // 紫色
            '36': 'color: #11a8cd',  // 青色
            '37': 'color: #e5e5e5',  // 白色
            '90': 'color: #666666',  // 亮黑色（灰色）
            '91': 'color: #f14c4c',  // 亮红色
            '92': 'color: #23d18b',  // 亮绿色
            '93': 'color: #f5f543',  // 亮黄色
            '94': 'color: #3b8eea',  // 亮蓝色
            '95': 'color: #d670d6',  // 亮紫色
            '96': 'color: #29b8db',  // 亮青色
            '97': 'color: #e5e5e5',  // 亮白色
            '1': 'font-weight: bold', // 粗体
            '0': ''  // 重置
        };

        let result = text;
        let openTags = [];

        // 处理ANSI转义序列
        result = result.replace(/\x1b\[([0-9;]*)m/g, (_, codes) => {
            if (!codes) return '';

            const codeList = codes.split(';');
            let html = '';

            for (const code of codeList) {
                if (code === '0' || code === '') {
                    // 重置所有样式
                    while (openTags.length > 0) {
                        html += '</span>';
                        openTags.pop();
                    }
                } else if (ansiColors[code]) {
                    // 添加新样式
                    html += `<span style="${ansiColors[code]}">`;
                    openTags.push('span');
                }
            }

            return html;
        });

        // 关闭所有未关闭的标签
        while (openTags.length > 0) {
            result += '</span>';
            openTags.pop();
        }

        return result;
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    new TailExplorer();
});
