---
name: insight
description: 用本地 SQLite 笔记生成深度洞察。当用户要求「洞察」「分析笔记」时使用。Python 只打包 prompt；结论由 Claude 写。任何把洞察写入 D1/flomo/本地库的动作都必须先征得用户同意。
---

# Insight Skill

基于**本地 SQLite**（`data/flomo.db`）做洞察。数据可能过期，先 `flomo sync`。

## 硬性规则：LLM 产物写入前必须确认

洞察结论是 **LLM 产物**。下列动作**禁止自动执行**，必须先展示结果并等用户明确同意：

| 动作 | 命令 |
|------|------|
| 推到 D1 复习 | `flomo insight-push --type T --file f.md` |
| 写入 flomo | `flomo create` / `flomo update` |
| 改本地 SQLite | 任何直接写库 |

默认只在对话里给出洞察全文；用户说「推到复习 / 保存到 flomo」后再执行写入。

## 前置

```bash
flomo sync
```

## 洞察类型（11）

### 分析型

| Key | 含义 |
|-----|------|
| `topics` | 思维全景 |
| `stagnant` | 停滞检测 |
| `declining` | 兴趣消退 |
| `connections` | 跨界连接 |
| `draft` | 写作草稿 |

### 视角型

`default` / `value-clarification` / `inversion` / `second-order` / `cbt` / `mbti`

## 操作步骤

```bash
flomo perspectives
flomo insight topics
```

1. 运行 `flomo insight <type>`，读 prompt + 笔记  
2. 用中文写洞察：有判断、不客套  
3. **在对话中展示给用户**  
4. 仅当用户要求时，再写入文件并（可选）`insight-push`  

## 推荐组合

- 复盘：`topics` → `declining` → `stagnant`  
- 觉察：`cbt` → `value-clarification` → `inversion`  
- 网络：`connections` → `second-order` → `draft`  

## 注意

- 不要用统计脚本代替阅读原文  
- 每次一种类型  
- 数据来自本地库，不是实时 API  
