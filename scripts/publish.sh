#!/bin/bash
# publish.sh — 一键构建并发布到 Cloudflare Pages
set -e

BLOG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BLOG_DIR"

echo "🔍 本地构建检查..."
hugo --environment production --minify 2>&1

echo ""
echo "✅ 构建成功，准备发布..."

# 检查是否有变更
if git diff --quiet && git diff --cached --quiet; then
    echo "📝 没有新的变更"
else
    git add -A
    echo "📋 变更内容："
    git diff --cached --stat
    git commit -m "update: $(date +%Y-%m-%d %H:%M)"
fi

echo ""
echo "🚀 推送到远程仓库..."
git push origin main

echo ""
echo "✅ 发布完成！Cloudflare Pages 正在构建（约 30 秒）"
echo "   公开站点: https://atum.li"
echo "   私密内容需通过 Cloudflare Access 认证访问"
