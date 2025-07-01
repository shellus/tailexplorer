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
        this.refreshSourcesBtn = document.getElementById('refresh-sources');
        this.keywordFilter = document.getElementById('keyword-filter');
        this.clearFilterBtn = document.getElementById('clear-filter');
        this.scrollToBottomBtn = document.getElementById('scroll-to-bottom');
        this.clearLogsBtn = document.getElementById('clear-logs');
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
            } else {
                this.disconnect();
            }
        });

        // 刷新日志源
        this.refreshSourcesBtn.addEventListener('click', () => {
            this.loadSources();
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

        // 滚动到底部
        this.scrollToBottomBtn.addEventListener('click', () => {
            this.scrollToBottom();
        });

        // 清空日志
        this.clearLogsBtn.addEventListener('click', () => {
            this.clearLogs();
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
                    case 'End':
                        e.preventDefault();
                        this.scrollToBottom();
                        break;
                }
            }
        });
    }
    
    async loadSources() {
        try {
            const response = await fetch('/api/sources');
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

    updateSourceSelect() {
        // 清空现有选项
        this.sourceSelect.innerHTML = '<option value="">选择日志源...</option>';

        // 添加可用的日志源
        for (const [sourceId, sourceInfo] of Object.entries(this.availableSources)) {
            const option = document.createElement('option');
            option.value = sourceId;
            option.textContent = `${sourceInfo.name} (${sourceInfo.type})`;
            option.title = sourceInfo.description;
            this.sourceSelect.appendChild(option);
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

        this.ws.onclose = () => {
            console.log(`WebSocket连接已关闭: ${sourceId}`);
            this.updateConnectionStatus(false);

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
        return log.toLowerCase().includes(this.currentFilter);
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
        
        // 高亮关键词
        if (this.currentFilter) {
            const regex = new RegExp(`(${this.escapeRegex(this.currentFilter)})`, 'gi');
            logElement.innerHTML = this.escapeHtml(log).replace(regex, '<mark>$1</mark>');
            logElement.classList.add('highlight');
        } else {
            logElement.textContent = log;
        }
        
        this.logDisplay.appendChild(logElement);
    }
    
    scrollToBottom() {
        this.logDisplay.scrollTop = this.logDisplay.scrollHeight;
        this.isAtBottom = true;
        this.updateAutoScrollIndicator();
    }
    
    checkScrollPosition() {
        const { scrollTop, scrollHeight, clientHeight } = this.logDisplay;
        this.isAtBottom = scrollTop + clientHeight >= scrollHeight - 10;
        this.updateAutoScrollIndicator();
    }
    
    updateAutoScrollIndicator() {
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
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    new TailExplorer();
});
