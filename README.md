# Warp2Api

基于 Python 的桥接服务，为 Warp AI 服务提供 OpenAI Chat Completions API 兼容性，通过利用 Warp 的 protobuf 基础架构，实现与 OpenAI 兼容应用程序的无缝集成。

## 🚀 特性

- **OpenAI API 兼容性**: 完全支持 OpenAI Chat Completions API 格式
- **Warp 集成**: 使用 protobuf 通信与 Warp AI 服务无缝桥接
- **双服务器架构**:
  - 用于 Warp 通信的 Protobuf 编解码服务器
  - 用于客户端应用程序的 OpenAI 兼容 API 服务器
- **智能账户轮换**: 多账户自动轮换，配额用尽时自动切换到下一个可用账户
- **配额管理**: 实时配额监控和智能刷新，避免服务中断
- **状态管理**: 自动跟踪账户状态（可用/配额用尽/刷新失败/token无效）
- **JWT 认证**: Warp 服务的自动令牌管理和刷新
- **流式支持**: 与 OpenAI SSE 格式兼容的实时流式响应
- **WebSocket 监控**: 内置监控和调试功能
- **消息重排序**: 针对 Anthropic 风格对话的智能消息处理

## 📋 系统要求

- Python 3.13+
- Warp AI 服务访问权限（需要 JWT 令牌）

## 🛠️ 安装

1. **克隆仓库:**
   ```bash
   git clone <repository-url>
   cd Warp2Api
   ```

2. **使用 uv 安装依赖 (推荐):**
   ```bash
   uv sync
   ```

   或使用 pip:
   ```bash
   pip install -e .
   ```

3. **配置匿名JWT TOKEN:**
   这一步可以什么都不做，程序会自行请求匿名JWT TOKEN

   当然你也可以创建一个包含您的 Warp 凭证的 `.env` 文件，用自己的订阅额度，不过这并不推荐:
   ```env
   WARP_JWT=your_jwt_token_here
   WARP_REFRESH_TOKEN=your_refresh_token_here
   ```

## 🎯 使用方法

### 快速开始

1. **启动 Protobuf 桥接服务器:**
   ```bash
   python server.py
   ```
   默认地址: `http://localhost:8000`

2. **启动 OpenAI 兼容 API 服务器:**
   ```bash
   python openai_compat.py
   ```
   默认地址: `http://localhost:8010`

### Docker 部署

使用 Docker 进行部署时，需要挂载数据卷以实现账户状态持久化：

1. **创建数据目录:**
   ```bash
   sudo mkdir -p /opt/warp2api/data/accounts
   sudo chown -R $USER:$USER /opt/warp2api/data
   ```

2. **运行 Docker 容器:**
   ```bash
   docker run -d \
     --name warp2api \
     -p 8000:8000 \
     -p 8010:8010 \
     -v /opt/warp2api/data:/app/data \
     -e WARP_JWT=your_jwt_token_here \
     -e WARP_REFRESH_TOKEN=your_refresh_token_here \
     your-image-name
   ```

3. **使用 docker-compose (推荐):**
   ```yaml
   version: '3.8'
   services:
     warp2api:
       image: your-image-name
       ports:
         - "8000:8000"
         - "8010:8010"
       volumes:
         - /opt/warp2api/data:/app/data
       environment:
         - WARP_JWT=your_jwt_token_here
         - WARP_REFRESH_TOKEN=your_refresh_token_here
   ```

**注意**: Docker 部署时账户文件会自动保存到 `/opt/warp2api/data/accounts/warp_accounts_simple.json`，确保该目录有适当的读写权限。

### 使用 API

两个服务器都运行后，您可以使用任何 OpenAI 兼容的客户端:

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8010/v1",
    api_key="dummy"  # 不是必需的，但某些客户端需要
)

response = client.chat.completions.create(
    model="claude-3-sonnet",  # 模型名称会被传递
    messages=[
        {"role": "user", "content": "你好，你好吗？"}
    ],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 可用端点

#### Protobuf 桥接服务器 (`http://localhost:8000`)
- `GET /healthz` - 健康检查
- `POST /encode` - 将 JSON 编码为 protobuf
- `POST /decode` - 将 protobuf 解码为 JSON
- `WebSocket /ws` - 实时监控

#### OpenAI API 服务器 (`http://localhost:8010`)
- `GET /` - 服务状态
- `GET /healthz` - 健康检查
- `POST /v1/chat/completions` - OpenAI Chat Completions 兼容端点

## 🏗️ 架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    客户端应用     │───▶│  OpenAI API     │───▶│   Protobuf      │
│  (OpenAI SDK)   │    │     服务器      │    │    桥接服务器    │
└─────────────────┘    │  (端口 8010)    │    │  (端口 8000)    │
                       └─────────────────┘    └─────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │    Warp AI      │
                                              │      服务       │
                                              └─────────────────┘
```

### 核心组件

- **`protobuf2openai/`**: OpenAI API 兼容层
  - 消息格式转换
  - 流式响应处理
  - 错误映射和验证

- **`warp2protobuf/`**: Warp protobuf 通信层
  - JWT 认证管理
  - Protobuf 编解码
  - WebSocket 监控
  - 请求路由和验证

## 🔧 配置

### 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `WARP_JWT` | Warp 认证 JWT 令牌 | 必需 |
| `WARP_REFRESH_TOKEN` | JWT 刷新令牌 | 必需 |
| `LOCAL_JWT_FILEPATH` | 多账户JSON文件路径（可选） | 未设置 |
| `WARP_QUOTA_REFRESH_THRESHOLD` | 配额刷新阈值（0=禁用检查） | `0` |
| `HOST` | 服务器主机地址 | `127.0.0.1` |
| `WARP_SERVER_PORT` | Protobuf 桥接服务器端口 | `8000` |
| `OPENAI_SERVER_PORT` | OpenAI API 服务器端口 | `8010` |
| `WARP_BRIDGE_URL` | Protobuf 桥接服务器 URL | `http://localhost:8000` |

### 多账户配置

系统支持智能账户轮换功能，通过配置 `LOCAL_JWT_FILEPATH` 环境变量启用：

1. **创建账户文件:**
   ```bash
   # 创建账户配置文件
   mkdir -p tmp
   ```

2. **配置账户文件格式 (JSON):**
   ```json
   [
     {
       "email": "account1@example.com",
       "refresh_token": "your_refresh_token_1",
       "account_status": "available"
     },
     {
       "email": "account2@example.com",
       "refresh_token": "your_refresh_token_2",
       "account_status": "available"
     }
   ]
   ```

3. **设置环境变量:**
   ```env
   LOCAL_JWT_FILEPATH=tmp/warp_accounts_simple.json
   ```

**账户状态说明:**
- `available` - 账户可用
- `quota_exhausted` - 配额已用尽
- `refresh_failed` - 刷新失败
- `invalid_token` - Token无效

系统会自动管理账户状态，配额不足时自动切换到下一个可用账户。

### 项目脚本

在 `pyproject.toml` 中定义:

```bash
# 启动 protobuf 桥接服务器
warp-server

# 启动 OpenAI API 服务器  
warp-test
```

## 🔐 认证

服务会自动处理 Warp 认证:

1. **JWT 管理**: 自动令牌验证和刷新
2. **智能账户轮换**: 配额不足时自动切换到下一个可用账户
3. **状态跟踪**: 实时监控每个账户的配额和状态
4. **匿名访问**: 在需要时回退到匿名令牌
5. **令牌持久化**: 安全的令牌存储和重用

### 账户轮换工作原理

1. **启动检查**: 系统启动时自动初始化账户状态
2. **配额监控**: 实时监控当前账户的配额使用情况
3. **智能切换**: 配额不足时立即标记当前账户并切换到下一个可用账户
4. **状态管理**: 自动更新账户状态，避免重复使用已耗尽的账户
5. **持久化存储**: 账户状态信息持久化保存，重启后保持状态

## 🧪 开发

### 项目结构

```
Warp2Api/
├── protobuf2openai/          # OpenAI API 兼容层
│   ├── app.py               # FastAPI 应用程序
│   ├── router.py            # API 路由
│   ├── models.py            # Pydantic 模型
│   ├── bridge.py            # 桥接初始化
│   └── sse_transform.py     # 服务器发送事件
├── warp2protobuf/           # Warp protobuf 层
│   ├── api/                 # API 路由
│   ├── core/                # 核心功能
│   │   ├── auth.py          # 认证
│   │   ├── protobuf_utils.py # Protobuf 工具
│   │   └── logging.py       # 日志设置
│   ├── config/              # 配置
│   └── warp/                # Warp 特定代码
├── server.py                # Protobuf 桥接服务器
├── openai_compat.py         # OpenAI API 服务器
└── pyproject.toml           # 项目配置
```

### 依赖项

主要依赖项包括:
- **FastAPI**: 现代、快速的 Web 框架
- **Uvicorn**: ASGI 服务器实现
- **HTTPx**: 支持 HTTP/2 的异步 HTTP 客户端
- **Protobuf**: Protocol buffer 支持
- **WebSockets**: WebSocket 通信
- **OpenAI**: 用于类型兼容性

## 🐛 故障排除

### 常见问题

1. **JWT 令牌过期**
   - 服务会自动刷新令牌
   - 检查日志中的认证错误
   - 验证 `WARP_REFRESH_TOKEN` 是否有效

2. **桥接服务器未就绪**
   - 确保首先运行 protobuf 桥接服务器
   - 检查 `BRIDGE_BASE_URL` 配置
   - 验证端口可用性

3. **连接错误**
   - 检查到 Warp 服务的网络连接
   - 验证防火墙设置
   - 如适用，检查代理配置

### 日志记录

两个服务器都提供详细的日志记录:
- 认证状态和令牌刷新
- 请求/响应处理
- 错误详情和堆栈跟踪
- 性能指标

## 📄 许可证

该项目配置为内部使用。请与项目维护者联系了解许可条款。

## 🤝 贡献

1. Fork 仓库
2. 创建功能分支
3. 进行更改
4. 如适用，添加测试
5. 提交 pull request

## 📞 支持

如有问题和疑问:
1. 查看故障排除部分
2. 查看服务器日志获取错误详情
3. 创建包含重现步骤的 issue