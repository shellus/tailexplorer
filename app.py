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
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Set, Dict, Optional
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn


class AuthManager:
    """认证管理器"""

    def __init__(self, config: dict):
        self.security_config = config.get("security", {})
        self.password = self.security_config.get("password")
        self.session_expire_hours = self.security_config.get("session_expire_hours", 24)
        self.active_sessions = {}  # session_token -> expire_time

        if not self.password:
            print("错误: 配置文件中未设置密码 (security.password)")
            exit(1)

    def generate_session_token(self) -> str:
        """生成会话令牌"""
        return secrets.token_urlsafe(32)

    def verify_password(self, password: str) -> bool:
        """验证密码"""
        return password == self.password

    def create_session(self) -> str:
        """创建会话"""
        token = self.generate_session_token()
        expire_time = datetime.now() + timedelta(hours=self.session_expire_hours)
        self.active_sessions[token] = expire_time
        return token

    def verify_session(self, token: str) -> bool:
        """验证会话"""
        if not token or token not in self.active_sessions:
            return False

        expire_time = self.active_sessions[token]
        if datetime.now() > expire_time:
            # 会话过期，删除
            del self.active_sessions[token]
            return False

        return True

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        now = datetime.now()
        expired_tokens = [token for token, expire_time in self.active_sessions.items() if now > expire_time]
        for token in expired_tokens:
            del self.active_sessions[token]


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
            print(f"错误: 配置文件 {self.config_path} 不存在")
            print("请使用 config.example.yaml 创建配置文件")
            exit(1)
        except Exception as e:
            print(f"错误: 加载配置文件失败: {e}")
            exit(1)



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
        if disconnected:
            for connection in disconnected:
                self.active_connections[source_id].discard(connection)

            # 如果没有连接了，删除整个源
            if not self.active_connections[source_id]:
                del self.active_connections[source_id]

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
            print(f"[{self.source_id}] 日志读取器已在运行，跳过启动")
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

            print(f"[{self.source_id}] 启动日志读取: {command} (工作目录: {working_dir})")

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
            timeout_count = 0
            max_timeouts = 3  # 最多等待3次超时

            # 先读取现有的日志
            while line_count < max_initial_lines and timeout_count < max_timeouts:
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
                    timeout_count += 1

            # 发送初始日志
            await connection_manager.broadcast_to_source(self.source_id, json.dumps({
                "type": "initial_logs",
                "logs": initial_logs,
                "source_id": self.source_id
            }))

            if initial_logs:
                print(f"[{self.source_id}] 发送 {len(initial_logs)} 条初始日志")

            # 持续读取新日志
            log_counter = 0

            while self.running:
                try:
                    # 检查进程状态
                    if self.process.returncode is not None:
                        print(f"[{self.source_id}] 进程已退出，返回码: {self.process.returncode}")
                        break

                    line = await self.process.stdout.readline()
                    if not line:
                        break

                    log_line = line.decode('utf-8', errors='ignore').strip()
                    if log_line:
                        self.logs.append(log_line)
                        log_counter += 1

                        # 限制内存使用
                        if len(self.logs) > self.max_lines:
                            self.logs = self.logs[-self.cleanup_threshold:]

                        await connection_manager.broadcast_to_source(self.source_id, json.dumps({
                            "type": "new_log",
                            "log": log_line,
                            "source_id": self.source_id
                        }))

                except Exception as e:
                    print(f"[{self.source_id}] 读取日志时出错: {e}")
                    break

        except Exception as e:
            print(f"[{self.source_id}] 启动日志读取失败: {e}")
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

    async def check_process_status(self):
        """检查进程状态"""
        if not self.process:
            return "未启动"

        if self.process.returncode is None:
            return "运行中"
        else:
            return f"已退出 (返回码: {self.process.returncode})"

    def get_recent_logs(self, count: int = 100) -> list:
        """获取最近的日志"""
        return self.logs[-count:] if self.logs else []


# 创建FastAPI应用
app = FastAPI(title="TailExplorer", description="实时多源日志查看器")

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 全局变量
log_source_manager = LogSourceManager()
auth_manager = AuthManager(log_source_manager.config)
connection_manager = ConnectionManager()
active_readers: Dict[str, LogReader] = {}


async def cleanup_reader_later(source_id: str, delay: int = 30):
    """延迟清理日志读取器"""
    await asyncio.sleep(delay)
    if (source_id in active_readers and
        connection_manager.get_connection_count(source_id) == 0 and
        not active_readers[source_id].running):
        del active_readers[source_id]


# 认证依赖
async def verify_auth(request: Request, session_token: Optional[str] = Cookie(None)):
    """验证认证状态"""
    if not session_token or not auth_manager.verify_session(session_token):
        # 如果是API请求，返回401
        if request.url.path.startswith("/api/") or request.url.path.startswith("/ws/"):
            raise HTTPException(status_code=401, detail="未授权访问")
        # 如果是页面请求，重定向到登录页
        return RedirectResponse(url="/login", status_code=302)
    return session_token


@app.get("/")
async def read_root(session_token: str = Depends(verify_auth)):
    """返回主页面"""
    return FileResponse("static/index.html")


@app.get("/login")
async def login_page():
    """返回登录页面"""
    return FileResponse("static/login.html")


@app.post("/api/login")
async def login(request: Request):
    """处理登录请求"""
    try:
        data = await request.json()
        password = data.get("password", "")

        if auth_manager.verify_password(password):
            session_token = auth_manager.create_session()
            response = JSONResponse({"success": True, "message": "登录成功"})
            response.set_cookie(
                key="session_token",
                value=session_token,
                max_age=auth_manager.session_expire_hours * 3600,
                httponly=True,
                secure=False,  # 在生产环境中应设为True（需要HTTPS）
                samesite="lax"
            )
            return response
        else:
            return JSONResponse(
                {"success": False, "message": "密码错误"},
                status_code=401
            )
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": "请求格式错误"},
            status_code=400
        )


@app.post("/api/logout")
async def logout(session_token: Optional[str] = Cookie(None)):
    """处理登出请求"""
    if session_token and session_token in auth_manager.active_sessions:
        del auth_manager.active_sessions[session_token]

    response = JSONResponse({"success": True, "message": "已登出"})
    response.delete_cookie("session_token")
    return response


@app.get("/api/sources")
async def list_log_sources(session_token: str = Depends(verify_auth)):
    """获取所有可用的日志源"""
    return JSONResponse(log_source_manager.list_sources())


@app.get("/api/sources/{source_id}")
async def get_source_info(source_id: str, session_token: str = Depends(verify_auth)):
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
async def get_recent_logs(source_id: str, count: int = 100, session_token: str = Depends(verify_auth)):
    """获取指定日志源的最近日志"""
    if source_id not in active_readers:
        raise HTTPException(status_code=404, detail="日志源未激活")

    logs = active_readers[source_id].get_recent_logs(count)
    return JSONResponse({
        "source_id": source_id,
        "logs": logs,
        "count": len(logs)
    })


@app.get("/api/sources/{source_id}/status")
async def get_source_status(source_id: str, session_token: str = Depends(verify_auth)):
    """获取指定日志源的详细状态"""
    if source_id not in active_readers:
        return JSONResponse({
            "source_id": source_id,
            "status": "未激活",
            "process_status": "未启动",
            "log_count": 0,
            "connections": connection_manager.get_connection_count(source_id)
        })

    reader = active_readers[source_id]
    process_status = await reader.check_process_status()

    return JSONResponse({
        "source_id": source_id,
        "status": "运行中" if reader.running else "已停止",
        "process_status": process_status,
        "log_count": len(reader.logs),
        "connections": connection_manager.get_connection_count(source_id),
        "max_lines": reader.max_lines,
        "cleanup_threshold": reader.cleanup_threshold
    })


@app.websocket("/ws/{source_id}")
async def websocket_endpoint(websocket: WebSocket, source_id: str):
    """WebSocket端点 - 连接到指定的日志源"""
    client_ip = websocket.client.host if websocket.client else "unknown"

    # 验证认证
    session_token = None
    for cookie in websocket.headers.get("cookie", "").split(";"):
        if "session_token=" in cookie:
            session_token = cookie.split("session_token=")[1].strip()
            break

    if not session_token or not auth_manager.verify_session(session_token):
        await websocket.close(code=4001, reason="未授权访问")
        return

    # 检查日志源是否存在
    source_config = log_source_manager.get_source_config(source_id)
    if not source_config:
        await websocket.close(code=4004, reason="日志源不存在")
        return

    # 连接到连接管理器
    await connection_manager.connect(websocket, source_id)
    connection_count = connection_manager.get_connection_count(source_id)
    print(f"[{source_id}] WebSocket连接 #{connection_count} from {client_ip}")

    # 确保日志读取器存在并运行
    if source_id not in active_readers:
        active_readers[source_id] = LogReader(source_id, source_config, log_source_manager)

    reader = active_readers[source_id]
    if not reader.running:
        asyncio.create_task(reader.start_reading(connection_manager))
    else:
        # 发送现有日志给新连接
        recent_logs = reader.get_recent_logs(100)
        if recent_logs:
            await websocket.send_text(json.dumps({
                "type": "initial_logs",
                "logs": recent_logs,
                "source_id": source_id
            }))

    try:
        while True:
            # 保持连接活跃，处理客户端消息
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[{source_id}] WebSocket错误: {e}")
    finally:
        # 清理连接
        connection_manager.disconnect(websocket, source_id)
        remaining_connections = connection_manager.get_connection_count(source_id)

        if remaining_connections == 0:
            # 停止日志读取器并延迟清理
            if source_id in active_readers:
                active_readers[source_id].stop_reading()
                asyncio.create_task(cleanup_reader_later(source_id))


if __name__ == "__main__":
    server_config = log_source_manager.config.get("server", {})
    uvicorn.run(
        "app:app",
        host=server_config.get("host", "0.0.0.0"),
        port=server_config.get("port", 8000),
        reload=server_config.get("reload", True),
        log_level=server_config.get("log_level", "info")
    )
