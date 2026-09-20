# snowblog

Hugo + Typo 个人博客，保留羊皮纸配色。

## 预览与构建

```sh
hugo server -D
hugo --minify
```

GitHub Pages：推送 main 后由 .github/workflows/deploy.yml构建并部署；站点 baseURL 为 https://jlenoch1.github.io/snowblog/。本次本地修改不自动发布。

## 信息架构

- 顶部：博客 / 简介 / 关于。
- 博客左栏：系列 / 思考（无 series 的独立文章）/ 标签。
- 内容保留原 URL；posts、thoughts、notes、scripts 中的文章统一参与博客聚合。
- 桌面文章目录在右侧，移动端折叠区位于正文前。
- 简介：content/projects.md，维护项目链接、问题、方法、预期结果。
- 关于：content/about.md，维护自我介绍、研究兴趣与 Links。
- 文章 front matter 填写 tags，系列文章再填写 series。

历史事实与决策见 docs/DECISIONS.md。GitHub Pages 中发布的内容是公开静态文件；历史 README 所述 Cloudflare Access 不代表本站已启用。

## 验证

```sh
hugo --destination /tmp/snowblog-check
python3 scripts/verify_site.py /tmp/snowblog-check modified
```
