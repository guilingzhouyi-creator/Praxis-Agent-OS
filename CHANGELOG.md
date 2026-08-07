# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增
- 脚本 `scripts/push-both.sh`:双远程推送(origin GitCode + github CI 镜像),防止漏推导致 CI 静默跳过
- 脚本 `scripts/bump-version.py`:原子契约版本升级(pyproject.toml + AGENTS.md 头 + docs/ SOC 引用一次提交完成)
- CHANGELOG.md 本文件

### 变更
- `tools/migrate_api_v2.py` 一次性迁移工具归档至 `docs/design/archive/`

## [0.4.1] - 2026-08-07

代号 "Aether"。契约版本化治理落地(API v2 前缀统一、端点 manifest 为唯一事实源),
性能优化与跨层基础设施扩展。

### 新增
- **CI 审查模块**:card 触发的 CI 审查守护进程、ErrorBus 错误捕获与结构化错误响应、
  管道加固(门禁匹配器、AutoTest 缓存、rerun、webhook)、每 cell/agent 作用域的控制平面
- **技能系统**:内置技能目录泛化至 18 个技能、受众路由(按领域动态供给)、
  Matt-Pocock 式调用模型(disable-model-invocation)、技能演化(Lean 用例自动泛化、
  SKILL.md 持久化、Cell 绑定、R4/R5 关联)、内置技能只读 + 宪法门禁 + 默认会话激活
- **LSP 工具面**:server-backed definition/references 握手、5 个可用 LSP 工具、
  代码自动格式化模块(format_file/format_project + 写入路径钩子)
- **L3A 会话系统**:agents-md 项目手册管道(AGENTS.md)、语言无关客户端契约、
  user_id 接入会话提示与 cardwrite
- **模型/推理**:按 provider 的 reasoning effort 分层归一化、xhigh/max 推理档位、
  scout 与 L3A 子代理按任务切换策略、策略包运行时切换、模型规格概览 + caps API
- **基础设施端口**:auth/websocket/rpc/fs 端口抽象、RPC server + FilesystemPort 适配器、
  事件链与 hook 发射、双通道网关认证、启动预热、ws 端口契约
- **运行时空档模式**:governed/semi/minimal 门禁矩阵、harness 模式运行时切换(API + L2 Shell)
- **图数据库边**:edge_mode 控制 API + 端点 manifest 分类
- **其他**:用户画像侧信道(typed per-user model)、系统提示注入开关、
  自动测试门(卡片后后台测试回归 + 卡片反馈)

### 修复
- 非 daemon 线程挂起与终端卡片执行链
- `_UNLIMITED` NameError(steps-exhausted 路径)+ UTF-8 BOM 清理
- 内置技能契约测试、Lean 用例技能持久化到 SKILL.md
- 门禁链 G5 停滞回调(L1 不再导入 L3)、重复/未接线端口常量清理
- API 网关 `{param}` 匹配 + 尾斜杠劫持、query 参数不可覆盖路径资源 id、
  SSE v2 路径同步、7 工作域分类
- i18n 未知 /lang 回退 'en'、deepseek 默认 API URL 修正
- CI 门禁修复(lint、pre-commit、全量套件、Windows L1)、pytest-mock 加入 test extras、
  L2 shell 单例按测试重置(并行顺序污染)
- ReferenceChannel flusher 线程停止 + 按测试路径隔离、构建检测器测试隔离

### 性能
- 移除 token-store 泄漏、防抖 checkpoint 持久化、HTTP 连接池

### 文档
- 架构文档同步(并行协作门禁强化、契约版本化、分支/协作工作流)
- 技能系统架构、配置总览、SOC 引用更新

## [0.4.0] - 2026-07

首个契约里程碑版本。五层架构(L1 kernel → L5 user CLI)成型,Agent OS 核心可引导运行。

> 注:0.4.0 之前的变更历史待补充(仓库早期迭代未记录 changelog)。
