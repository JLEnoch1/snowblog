#!/bin/bash
# obsidian-setup.sh — 将项目目录链接为 Obsidian Vault
set -e

BLOG_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "📂 博客目录: $BLOG_DIR"
echo ""

# 创建 Obsidian 配置目录（如果不存在）
if [ ! -d "$BLOG_DIR/.obsidian" ]; then
    mkdir -p "$BLOG_DIR/.obsidian"
    echo '{}' > "$BLOG_DIR/.obsidian/app.json"
    echo '{}' > "$BLOG_DIR/.obsidian/appearance.json"
    echo '{}' > "$BLOG_DIR/.obsidian/core-plugins.json"

    # 配置模板目录
    cat > "$BLOG_DIR/.obsidian/templates.json" << 'EOF'
{
  "folder": "templates",
  "dateFormat": "YYYY-MM-DD",
  "timeFormat": "HH:mm"
}
EOF

    # 配置核心插件
    cat > "$BLOG_DIR/.obsidian/core-plugins.json" << 'EOF'
["file-explorer","global-search","switcher","graph","templates","note-composer","command-palette","markdown-importer","outline","tags"]
EOF

    echo "✅ Obsidian 配置已创建"
else
    echo "ℹ️  Obsidian 配置已存在，跳过"
fi

echo ""
echo "🎯 下一步："
echo "   1. 打开 Obsidian"
echo "   2. 选择 'Open folder as vault'"
echo "   3. 选择目录: $BLOG_DIR"
echo "   4. 在模板设置中确认模板目录为 templates/"
echo ""
echo "📝 使用模板："
echo "   - Cmd/Ctrl+T → 插入博客文章/视频脚本/思考笔记/技术笔记模板"
