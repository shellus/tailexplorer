#!/usr/bin/env python3
"""
TailExplorer - 实时日志查看器
支持多种日志源：Docker Compose、文件、系统日志等
"""

import asyncio
import json
import subprocess
import yaml
import os
from typing import Set, Dict, Optional
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn


class LogSourceManager:
    """日志源管理器"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self.load_config()
        self.log_sources = self.config.get("log_sources", {})

    def load_config(self) -> dict:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"配置文件 {self.config_path} 不存在，使用默认配置")
            return self.get_default_config()
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return self.get_default_config()

    def get_default_config(self) -> dict:
        """获取默认配置"""
        return {
            "log_sources": {
                "default": {
                    "name": "默认日志",
                    "type": "docker-compose",
                    "command": "docker-compose logs -f --tail=100",
                    "working_dir": "/data/compose/xhj-php",
                    "description": "默认 Docker Compose 日志"
                }
            },
            "server": {
                "host": "0.0.0.0",
                "port": 8000,
                "reload": True,
                "log_level": "info"
            },
            "logging": {
                "max_lines_per_source": 10000,
                "cleanup_threshold": 5000
            }
        }

    def get_source_config(self, source_id: str) -> Optional[dict]:
        """获取指定日志源的配置"""
        return self.log_sources.get(source_id)

    def list_sources(self) -> dict:
        """列出所有可用的日志源"""
        return {
            source_id: {
                "name": config["name"],
                "description": config.get("description", ""),
                "type": config["type"]
            }
            for source_id, config in self.log_sources.items()
        }


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}  # source_id -> connections

    async def connect(self, websocket: WebSocket, source_id: str):
        await websocket.accept()
        if source_id not in self.active_connections:
            self.active_connections[source_id] = set()
        self.active_connections[source_id].add(websocket)

    def disconnect(self, websocket: WebSocket, source_id: str):
        if source_id in self.active_connections:
            self.active_connections[source_id].discard(websocket)
            if not self.active_connections[source_id]:
                del self.active_connections[source_id]

    async def broadcast_to_source(self, source_id: str, message: str):
        """广播消息到指定日志源的所有连接客户端"""
        if source_id not in self.active_connections:
            return

        connections = self.active_connections[source_id].copy()
        disconnected = set()

        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.add(connection)

        # 清理断开的连接
        for connection in disconnected:
            self.active_connections[source_id].discard(connection)

    def get_connection_count(self, source_id: str) -> int:
        """获取指定日志源的连接数"""
        return len(self.active_connections.get(source_id, set()))


class LogReader:
    """通用日志读取器"""

    def __init__(self, source_id: str, source_config: dict, log_source_manager: LogSourceManager):
        self.source_id = source_id
        self.source_config = source_config
        self.log_source_manager = log_source_manager
        self.process = None
        self.running = False
        self.logs = []
        self.max_lines = log_source_manager.config.get("logging", {}).get("max_lines_per_source", 10000)
        self.cleanup_threshold = log_source_manager.config.get("logging", {}).get("cleanup_threshold", 5000)

    async def start_reading(self, connection_manager: ConnectionManager):
        """开始读取日志"""
        if self.running:
            return

        self.running = True
        command = self.source_config["command"]
        working_dir = self.source_config.get("working_dir", "/")

        try:
            # 解析命令
            if isinstance(command, str):
                command_parts = command.split()
            else:
                command_parts = command

            print(f"启动日志读取: {command} (工作目录: {working_dir})")

            # 启动进程
            self.process = await asyncio.create_subprocess_exec(
                *command_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )

            # 读取初始日志
            initial_logs = []
            line_count = 0
            max_initial_lines = 100  # 初始加载最多100行

            # 先读取现有的日志
            while line_count < max_initial_lines:
                try:
                    line = await asyncio.wait_for(
                        self.process.stdout.readline(), timeout=2.0
                    )
                    if not line:
                        break

                    log_line = line.decode('utf-8', errors='ignore').strip()
                    if log_line:
                        initial_logs.append(log_line)
                        self.logs.append(log_line)
                        line_count += 1
                except asyncio.TimeoutError:
                    break

            # 发送初始日志
            if initial_logs:
                await connection_manager.broadcast_to_source(self.source_id, json.dumps({
                    "type": "initial_logs",
                    "logs": initial_logs,
                    "source_id": self.source_id
                }))

            # 持续读取新日志
            while self.running and self.process.returncode is None:
                try:
                    line = await self.process.stdout.readline()
                    if not line:
                        break

                    log_line = line.decode('utf-8', errors='ignore').strip()
                    if log_line:
                        self.logs.append(log_line)

                        # 限制内存使用
                        if len(self.logs) > self.max_lines:
                            self.logs = self.logs[-self.cleanup_threshold:]

                        await connection_manager.broadcast_to_source(self.source_id, json.dumps({
                            "type": "new_log",
                            "log": log_line,
                            "source_id": self.source_id
                        }))

                except Exception as e:
                    print(f"读取日志时出错: {e}")
                    break

        except Exception as e:
            print(f"启动日志读取失败: {e}")
            await connection_manager.broadcast_to_source(self.source_id, json.dumps({
                "type": "error",
                "message": f"无法读取日志: {e}",
                "source_id": self.source_id
            }))
        finally:
            self.running = False
            if self.process:
                try:
                    self.process.terminate()
                    await self.process.wait()
                except:
                    pass

    def stop_reading(self):
        """停止读取日志"""
        self.running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

    def get_recent_logs(self, count: int = 100) -> list:
        """获取最近的日志"""
        return self.logs[-count:] if self.logs else []


# 创建FastAPI应用
app = FastAPI(title="TailExplorer", description="实时多源日志查看器")

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 全局变量
log_source_manager = LogSourceManager()
connection_manager = ConnectionManager()
active_readers: Dict[str, LogReader] = {}


@app.get("/")
async def read_root():
    """返回主页面"""
    return FileResponse("static/index.html")


@app.get("/api/sources")
async def list_log_sources():
    """获取所有可用的日志源"""
    return JSONResponse(log_source_manager.list_sources())


@app.get("/api/sources/{source_id}")
async def get_source_info(source_id: str):
    """获取指定日志源的详细信息"""
    source_config = log_source_manager.get_source_config(source_id)
    if not source_config:
        raise HTTPException(status_code=404, detail="日志源不存在")

    return JSONResponse({
        "id": source_id,
        "name": source_config["name"],
        "description": source_config.get("description", ""),
        "type": source_config["type"],
        "command": source_config["command"],
        "working_dir": source_config.get("working_dir", "/"),
        "active_connections": connection_manager.get_connection_count(source_id),
        "is_running": source_id in active_readers and active_readers[source_id].running
    })


@app.get("/api/sources/{source_id}/recent")
async def get_recent_logs(source_id: str, count: int = 100):
    """获取指定日志源的最近日志"""
    if source_id not in active_readers:
        raise HTTPException(status_code=404, detail="日志源未激活")

    logs = active_readers[source_id].get_recent_logs(count)
    return JSONResponse({
        "source_id": source_id,
        "logs": logs,
        "count": len(logs)
    })


@app.websocket("/ws/{source_id}")
async def websocket_endpoint(websocket: WebSocket, source_id: str):
    """WebSocket端点 - 连接到指定的日志源"""
    # 检查日志源是否存在
    source_config = log_source_manager.get_source_config(source_id)
    if not source_config:
        await websocket.close(code=4004, reason="日志源不存在")
        return

    await connection_manager.connect(websocket, source_id)

    # 如果是第一个连接到此日志源，开始读取日志
    if connection_manager.get_connection_count(source_id) == 1:
        if source_id not in active_readers:
            active_readers[source_id] = LogReader(source_id, source_config, log_source_manager)

        if not active_readers[source_id].running:
            asyncio.create_task(active_readers[source_id].start_reading(connection_manager))

    try:
        while True:
            # 保持连接活跃，可以接收客户端消息
            message = await websocket.receive_text()
            # 这里可以处理客户端发送的控制消息
            try:
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except:
                pass
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, source_id)

        # 如果没有活跃连接，停止读取日志
        if connection_manager.get_connection_count(source_id) == 0:
            if source_id in active_readers:
                active_readers[source_id].stop_reading()


if __name__ == "__main__":
    server_config = log_source_manager.config.get("server", {})
    uvicorn.run(
        "app:app",
        host=server_config.get("host", "0.0.0.0"),
        port=server_config.get("port", 8000),
        reload=server_config.get("reload", True),
        log_level=server_config.get("log_level", "info")
    )
