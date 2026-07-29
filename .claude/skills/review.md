# Review Skill

当用户要求生成复习内容时使用此 Skill。

## 原理

从本地笔记中通过 4 种关联策略找到相关笔记组（2-4 条），Claude 为每组写 1-2 句口语化复习。

## 操作

```
1. 确保本地 DB 是最新的：flomo sync
2. 生成分组 JSON：flomo review -n 50 > /tmp/groups.json
3. 写复习内容（手动或 subagent）
4. 推送到 D1：flomo review --push --json /tmp/reviews.json
```

## 复习格式要求

每条复习内容：
- 1-2 句话，口语化，像发微信
- 串联几条笔记，加上简短感受或理解
- 不要用分号，不要写长句，不要说教
- 可以俏皮、可以温暖、可以有态度

## 4 种关联策略

| 策略 | 方法 |
|------|------|
| 同标签 | 同一标签下的笔记 |
| 同书 | 同一本微信读书的划线 |
| 近时间 | 同一天写的笔记 |
| 双标签 | 两个标签同时出现的笔记 |

## 推送到 D1

```
flomo review --push --json reviews.json
```

## Cloudflare Worker

部署在 memo.example.com，唯一端点：
```
GET /?key=<64位hex密钥>
→ 返回 JSON { content, date, id }
→ served_count 最少优先（均匀分发）
```

部署命令：
```bash
cd worker && npx wrangler secret put REVIEW_KEY && npx wrangler secret put FLOMO_TOKEN && npx wrangler deploy
```
