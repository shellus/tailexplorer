# TailExplorer

一个基于Python的实时多源日志查看器，支持Docker Compose、文件、系统日志等多种日志源，提供Web界面和WebSocket实时更新功能。

## 功能特性

- 🔍 **多源日志支持**: Docker Compose、文件tail、系统journalctl等
- 🌐 **Web界面访问**: 现代化的响应式Web界面
- 🔌 **WebSocket实时推送**: 实时接收新日志，无需刷新页面
- 🔎 **关键词过滤**: 支持实时关键词过滤和高亮显示
- 📜 **智能自动滚动**: 当在底部时自动跟踪新日志
- 🎯 **一键操作**: 滚动到底部、清空日志等便捷功能
- ⚙️ **配置化管理**: 通过YAML配置文件管理多个日志源
- 📱 **响应式设计**: 支持桌面和移动设备访问

## 技术栈

- **后端**: Python 3, FastAPI, WebSocket, PyYAML
- **前端**: HTML5, JavaScript ES6+, CSS3
- **日志源**: Docker Compose, 文件系统, 系统日志

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置日志源

编辑 `config.yaml` 文件，配置您的日志源：

```yaml
log_sources:
  my-app:
    name: "我的应用日志"
    type: "docker-compose"
    command: "docker-compose logs -f --tail=100"
    working_dir: "/path/to/your/compose/project"
    description: "应用的Docker Compose日志"
```

### 3. 运行服务

```bash
python app.py
```

### 4. 访问界面

打开浏览器访问 http://localhost:8000

## 项目结构

```
tailexplorer/
├── app.py              # 主应用程序
├── config.yaml         # 日志源配置文件
├── static/             # 静态文件
│   ├── index.html     # 主页面
│   ├── style.css      # 样式文件
│   └── script.js      # 前端逻辑
├── requirements.txt    # Python依赖
├── test_*.html        # 功能测试页面
├── test_websocket.py  # WebSocket测试脚本
└── README.md          # 项目说明
```

## 使用说明

### 基本操作

1. **选择日志源**: 在下拉菜单中选择要查看的日志源
2. **关键词过滤**: 在过滤框中输入关键词，实时筛选日志
3. **自动滚动**: 当滚动条在底部时，新日志会自动滚动显示
4. **手动控制**: 使用"滚动到底部"按钮快速定位到最新日志

### 配置日志源

支持以下类型的日志源：

- **docker-compose**: Docker Compose服务日志
- **file**: 文件tail命令
- **system**: 系统journalctl日志

### API接口

- `GET /api/sources` - 获取所有日志源列表
- `GET /api/sources/{source_id}` - 获取指定日志源信息
- `GET /api/sources/{source_id}/recent` - 获取最近日志
- `WebSocket /ws/{source_id}` - 连接到指定日志源的实时推送

## 开发和测试

### 开发模式

项目使用FastAPI框架，支持热重载开发模式：

```bash
# 开发模式启动（自动重载）
python app.py
```

### 功能测试

项目包含多个测试页面：

- `test_filter.html` - 关键词过滤功能测试
- `test_scroll.html` - 自动滚动功能测试
- `test_websocket.py` - WebSocket连接测试

### 配置说明

`config.yaml` 配置文件结构：

```yaml
log_sources:
  source_id:
    name: "显示名称"
    type: "日志源类型"
    command: "执行命令"
    working_dir: "工作目录"
    description: "描述信息"

server:
  host: "0.0.0.0"
  port: 8000
  reload: true
  log_level: "info"

logging:
  max_lines_per_source: 10000
  cleanup_threshold: 5000
```
