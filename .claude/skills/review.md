# Review Skill

生成 flomo 笔记回顾。**按频率轮转,低频、稳定、无评分。**

## 机制

```
flomo review-push     # 清理笔记内容(去 HTML/去标签) → 推送到 D1
```

- Worker(`memo.example.com`)每次请求返回 `served_count` **最小**的卡片
- 推过一次 `served_count +1`,卡片被轮转,不会连续重复
- 没有到期时间、没有评分、没有 LLM 介入
- 复习频率 = 你的访问频率。想看就看,每张卡均匀轮转

## 内容

卡片内容 = **你的笔记原文**(纯整理版):

- 去掉 HTML 标签,按行展示
- 去掉 `#标签`(基于 `memo_tags` 精确剥离,不误删正文)
- 保留你的原话逐字,不改写

**不是 AI 生成的点评。** 复习的是你自己记下的东西。

## 操作

```bash
flomo sync            # 同步最新笔记到本地
flomo review-push     # 清理内容推送到 D1(重建表)
```

每次同步后跑一次 `review-push`,卡片库保持最新。

## 部署(一次性)

```bash
cd worker
npx wrangler secret put REVIEW_KEY   # 访问密钥
npx wrangler secret put FLOMO_TOKEN  # flomo 同步用(worker 未来可能用)
npx wrangler deploy
```

---

> 旧机制(间隔重复 / 评分 / 钩子)已废弃移除。需要历史时见 git。
