# 部署到 GitHub Pages

| 项 | 值 |
|---|---|
| GitHub 账号 | `LQ19488-maker` |
| 新仓库名 | `bj-house-insight` |
| 仓库地址 | https://github.com/LQ19488-maker/bj-house-insight |
| 站点地址 | https://lq19488-maker.github.io/bj-house-insight/ |
| 旧仓库 | `vue-login-demo`（**保留不动**，与本项目无关） |

> 为什么新建仓库而不是复用旧的 `vue-login-demo`：
> ① 推进去会覆盖旧站；② 之前被你开过修改权限的人会连带拿到新项目权限；
> ③ 仓库名和"北京二手房"不搭，给老师的链接会让人困惑。

---

## 一、第一次推送（只需做一次）

本地已经准备好了：`git init` 已完成、`.gitignore` 已配、首次提交已创建、远程 `origin` 已关联。
**你只需要把提交推上去。**

### 方式 A（推荐）：双击运行

在项目目录里双击 **`push-to-github.cmd`**。

它会自动：显示远程地址 → 显示待推送的提交 → 执行 `git push` → 失败时自动用 OpenSSL 后端重试 → 最后告诉你下一步做什么。

第一次可能会弹出一个 GitHub 登录窗口，按提示授权即可（和你当初推 `vue-login-demo` 时一样）。

### 方式 B：手动敲命令

```bat
cd C:\Users\LTQ\work\可视化\bj-house-insight
git push -u origin main
```

如果报 `schannel: AcquireCredentialsHandle failed`（Windows 证书栈问题），改用：

```bat
git -c http.sslBackend=openssl push -u origin main
```

---

## 二、开启 Pages（推送成功后做一次）

1. 打开 https://github.com/LQ19488-maker/bj-house-insight/settings/pages
2. **Source** 选择 **GitHub Actions**（不要选 Deploy from a branch）
3. 保存

之后每次 `git push` 到 `main`，Actions 会自动 `npm run build` 并部署，约 2 分钟。

---

## 三、每次修改后的更新流程

```bat
cd C:\Users\LTQ\work\可视化\bj-house-insight
git add -A
git commit -m "feat: 说明这次改了什么"
git push
```

`push-to-github.cmd` 也可以直接用（它会连推送一起做）。

---

## 四、为什么 GitHub Pages 上跑不了后端

GitHub Pages **只能托管静态文件**，不能运行 Python。所以公网站点采用**静态数据模式**：

```
本地完整系统                               GitHub Pages 只读站
http://127.0.0.1:8080                     https://lq19488-maker.github.io/bj-house-insight/
        │                                           │
  数据层 httpSource                       数据层 staticSource
  （调 /api/v1/*）                          （读 public/data/*.json）
        └──────── 同一套页面组件与业务逻辑 ────────┘
                 靠 VITE_DATA_SOURCE 切换
```

| 页面 | Pages 上是否可用 | 说明 |
|---|---|---|
| P1 市场概览 | ✅ 真数据 | KPI、区均价、分布直方图 |
| P2 房源检索 | ✅ 真数据 | 2890 条在浏览器内存里筛选 |
| P3 房源详情 | ✅ 真数据 | 单价分位、相似房源 |
| P4 房源对比 | ✅ 真数据 | 属性矩阵 + 雷达 |
| P5 分析看板 | ✅ 真数据 | 聚合结果预生成成 JSON |
| P6 小区画像 | ✅ 真数据 | 分位 + 街道排行 |
| P7 估价参考 | ✅ 真数据 | 加权均价在浏览器算，结果与后端一致 |
| P8 数据管理 | ⚠️ 只读 | 质量报告可看，不可点"导入" |
| 注册/登录/收藏 | ❌ 隐藏 | 静态站没有服务端状态 |

数据体积参考：2890 条 × 15 列打成 JSON 后 **85 KB（gzip）**，比一张手机照片还小。

---

## 五、三个必须记住的坑

| 坑 | 症状 | 解法（已在本项目配好） |
|---|---|---|
| `vite base` 没设 | 打开**白屏**、控制台一片 404 | `base` 从 `VITE_BASE` 环境变量读，Pages 构建时注入 `/bj-house-insight/` |
| history 路由 | 刷新 `/analytics` → GitHub 404 页 | 用 **hash 路由**（`/#/analytics`），和你旧站一致 |
| API 地址硬编码 | 线上全打到 `127.0.0.1` | 相对路径 `/api/v1` + `VITE_DATA_SOURCE=static` |

---

## 六、常见问题

**Q：推送时报 `unable to get password from user` / 弹不出登录窗？**
先确认 `Git Credential Manager` 可用：在 cmd 里执行 `git credential-manager configure`，
再 `git push`。或改用 GitHub Desktop 推送一次，凭据会被记住。

**Q：`github.io` 打不开 / 很慢？**
国内访问 GitHub Pages 时通时不通，属正常现象。不影响课程使用，因为有更好的主通道：
**答辩现场直接跑本机 `http://127.0.0.1:8080`**，无网络依赖、无关网、无冷启动。

**Q：想要国内稳定访问的公网链接？**
把 `frontend/dist/` 整个目录上传到 **腾讯云 CloudBase 静态托管**（有免费额度）或
**阿里云 OSS**（几块钱/月），换托管方零改动。

**Q：仓库是公开的，会不会有问题？**
课程项目通常没问题。若不想公开代码，可改用 **Cloudflare Pages**（支持私有仓库免费部署），
`dist` 产物是同一份，换托管方零改动。注意：`JWT_SECRET` 等敏感值始终只走环境变量，不入库、不进 git。

**Q：旧仓库 `vue-login-demo` 要删吗？**
**不要删。** 删了旧的 Pages 站会一起消失。如果不想让别人继续改，去
`vue-login-demo` → Settings → Collaborators 把对方改成 **Read** 或 **Remove** 即可。

---

## 七、未来可选：单容器全栈（一个 URL 跑完整系统）

如果以后想让公网也能用真后端（登录、收藏、导入），可以做成单个 Docker 容器：

```
node:24 构建前端 dist  →  python:3.14-slim 运行后端（同时托管 dist）
```

后端已经具备部署条件：`PORT` / `HOST` / `DB_PATH` / `READONLY` 环境变量、
`/health` 健康检查、日志到 stdout、SPA 回退（不需要 Nginx）、零运行时依赖。
还需要补：幂等 seed 脚本、多阶段 Dockerfile、`.dockerignore`、部署文档。

托管平台：Render / Koyeb（免费但 15 分钟无访问会休眠，冷启动 30–60 秒）。
