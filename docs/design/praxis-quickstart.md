---
全宗: DESIGN
案卷: guide
件号: 001
类型: 实现
日期: 2026-07-22
时间戳: 2026-07-22T19:00
作者: L3
关键词: [NOMOS, Praxis, quickstart, guide]
关联: [ARCHIVE-design-001]
债务: []
---

# NOMOS Praxis 快速启动指南

> 5 分钟从零到第一个意图执行。

## 前置条件

- Python 3.11+
- 本仓库已克隆到本地

## 启动

```bash
# 从项目根目录启动 Praxis GUI
python run.py --gui
```

等待 pywebview 窗口弹出（首次启动可能需几秒加载 Flask 后端）。

## 第一个意图

在窗口右侧 Chat 输入框中输入：

```
修改数据库连接配置
```

流程：
1. L3 引擎解析意图 → 识别领域 `app/config`
2. 路由到 Agent B（业务层）
3. 展示任务预览卡片，点击 **确认**
4. Agent B 执行：`read_file` → `grep_search` → `replace_string_in_file`
5. 左侧事务区生成任务卡片
6. 中间编辑器显示文件变更 Diff
7. 底部面板实时更新执行日志、门禁状态

## 验证

- 窗口标题栏显示 `内核在线`（绿色圆点）
- Agent 流条显示执行进度
- 底部状态栏显示 Agent 信誉分和 PID

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 窗口白屏 | Flask 后端未就绪 | 等待终端出现 `Running on 127.0.0.1:5007` |
| 解析失败 | L3 引擎未识别意图 | 尝试更明确的表达，如"把 config.py 的 debug 改为 true" |
| 执行被阻断 | GateChain G3 领地检查 | 确认 Agent 拥有目标文件所在领地权限 |
