# atumblog

个人博客 — Hugo + Typo 主题 + 羊皮纸配色。

## 首次设置

### 1. 安装 Hugo

```bash
# macOS
brew install hugo

# 或通过 Hugo 官方安装
# https://gohugo.io/installation/
```

### 2. 本地预览

```bash
hugo server -D --buildDrafts
# 打开 http://localhost:1313
```

### 3. Obsidian 集成

```bash
bash scripts/obsidian-setup.sh
# 然后在 Obsidian 中打开此目录作为 Vault
```

### 4. 部署

```bash
# 一键发布
bash scripts/publish.sh
```

#### Cloudflare Pages 首次配置

1. 在 Cloudflare Dashboard 创建 Pages 项目
2. 在 GitHub 仓库 Settings → Secrets 添加：
   - `CLOUDFLARE_API_TOKEN` — Cloudflare API Token（Pages 编辑权限）
   - `CLOUDFLARE_ACCOUNT_ID` — Cloudflare Account ID
3. Push 到 main 分支，GitHub Actions 自动部署

#### Cloudflare Access（私密内容保护）

1. 在 Cloudflare Zero Trust Dashboard → Access → Applications
2. 添加规则：
   - 路径: `/thoughts/*` → 仅允许你的邮箱
   - 路径: `/notes/*` → 仅允许你的邮箱
3. 认证方式推荐: Email OTP（免密码）

## 内容结构

```
content/
├── posts/          公开博客文章
├── scripts/        视频脚本底稿
├── thoughts/       私密思考（Access 保护）
├── notes/          私密笔记（Access 保护）
└── about.md        关于页面

_drafts/            草稿区（不构建）
_templates/         Obsidian 模板
```

## 写新文章

1. Obsidian 中用模板创建 → 保存到 `_drafts/`
2. 写完后移到 `content/posts/` 或对应目录
3. `bash scripts/publish.sh` 发布
