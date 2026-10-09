---
title: "逆向复现学习指南：从 WeFlow 看一套完整的「本地客户端数据考古」方法论"
date: 2026-09-30
tags: ["逆向工程", "WeFlow", "macOS", "安全研究"]
toc: true
readTime: true
summary: "基于开源项目 WeFlow 整理的 6 个可独立复现的逆向学习课题：二进制字符串考古、FFI 绑定逆向、进程内存密钥提取、ISAAC64+XOR 流解密、SQLite 触发器数据保全、PoC 到产品的工程化。"
---

> 基于开源项目 WeFlow（微信 4.x 本地数据查看/导出工具）的源码与二进制资源，整理出 6 个可反复研读、可独立复现的逆向学习课题。
> 每个课题都遵循同一结构：**它解决了什么 → 证据在哪 → 怎么复现 → 学到什么通用能力**。
>
> ⚠️ 本文所有技术仅用于研究自己设备上、自己账号产生的数据。对他人数据或未授权系统的操作不在本文讨论范围内。

---

## 0. 先建立全局认知：这个项目的「攻击面选择」

WeFlow 的技术路线选择本身就是第一个值得学习的东西。面对「如何拿到朋友圈数据」这个问题，有三条路：

| 路线 | 做法 | 难点 | WeFlow 的选择 |
|------|------|------|--------------|
| 协议重放 | 逆向 mmtls + 伪造请求 | 证书校验、风控、封号 | ❌ |
| 内存/Hook 运行时 | 注入微信进程拦截渲染层 | 反调试、版本适配成本高 | ❌（仅提取密钥时用） |
| **本地落库读取** | 解密微信自己的本地数据库 | ① 拿到 SQLCipher 密钥 ② 数据在删 | ✅ |

**学习点**：逆向工程的第一课不是「怎么逆向」，而是「选哪个面」。客户端再复杂，只要它把数据写到了本地磁盘，你就拥有一个静态的、可离线分析的、不受反调试保护的攻击面。剩下的全部难题都收敛为两个：**密钥**和**数据生命周期**。后文 6 个课题正好对应这两条线。

整体数据流（每层都值得单独学习）：

```
微信进程（密钥仅存在于内存，瞬时出现）
   │ ① 密钥捕获：进程附加 + 特征码定位 + Hook（课题三）
   ▼
SQLCipher 加密的 sns.db / session.db
   │ ② FFI 打开：闭源 C++ 库 + koffi 绑定（课题二）
   ▼
SnsTimeLine 表（XML 元数据 + token/key）
   │ ③ 触发器防删除：RAISE(IGNORE)（课题五）
   ▼
微信 CDN（加密媒体流）
   │ ④ ISAAC64 XOR 解密（课题四）
   ▼
Electron worker → IPC → 前端（课题六）
```

---

## 课题一：二进制字符串考古 —— 不反汇编也能还原协议

### 解决什么问题

项目里最核心的 `libwcdb_api.dylib` 是**闭源二进制**（无源码、被 strip 过符号），但上层 TypeScript 代码却知道怎么调用它、它返回什么 JSON。逆向者的第一个问题：**不打开 IDA，能还原多少信息？**

答案是：出乎意料地多。

### 证据在哪

```bash
# macOS 自带工具即可开始
cd resources/wcdb/macos/universal/

# 1. 导出符号表：确认它暴露了哪些 C ABI 函数
nm -gU libwcdb_api.dylib | grep -i sns
#   _wcdb_get_sns_timeline
#   _wcdb_get_sns_usernames
#   _wcdb_get_sns_export_stats
#   _wcdb_install_sns_block_delete_trigger
#   ...

# 2. 字符串考古：把 .rodata 里的字符串按出现顺序读出来
strings libwcdb_api.dylib | sed -n '/^SnsTimeLine$/,/^like_user_list$/p'
```

`strings` 按地址顺序输出，C++ 编译器会把**拼接 SQL 用的相邻字符串字面量**放在一起，于是你能看到一段连续的「代码化石」：

```
SnsTimeLine          ← 表名
userName             ← 查询列
, content,
 FROM SnsTimeLine WHERE 1=1
 IN (
 SQL(base):
 OFFSET
 SQL(page):
TimelineObject       ← content 列里存的是这种 XML
contentDesc
ContentObject
media
LocalExtraInfo
like_user_list        ← XML 的层级结构直接暴露
user_comment
comment_user_list
"tid":"
"id":"
"nickname":"
"createTime":        ← 输出 JSON 的字段名顺序
"media":[
thumb
"url":"
"token":"
"key":"
enc_idx
<LivePhoto>
LivePhoto
liveMedia
"livePhoto":{
...
```

这一段字符串连起来读，等于**同时还原了三样东西**：

1. **SQL 语句**：`SELECT tid, userName, createTime, content FROM SnsTimeLine WHERE 1=1 ... IN (...) ... LIMIT ? OFFSET ?`（`1=1` 是动态拼接 WHERE 条件的经典痕迹）
2. **存储格式**：`content` 列是 `TimelineObject` XML，层级为 `TimelineObject > ContentObject/media + LocalExtraInfo/like_user_list + comment_user_list/user_comment`
3. **输出协议**：函数返回的 JSON 字段序列 `"tid": "id": "nickname": "createTime": "contentDesc": "media": [...]`

再看触发器相关的字符串，还能还原出完整 DDL：

```
CREATE TRIGGER IF NOT EXISTS block_delete_SnsTimeLine
BEFORE DELETE ON SnsTimeLine BEGIN SELECT RAISE(IGNORE); END
DELETE FROM SnsTimeLine WHERE tid = '
SELECT COUNT(*) FROM SnsTimeLine WHERE tid = '
```

### 怎么复现（这是最值得反复练的基本功）

1. 随便找一个闭源 dylib/dll/so，先 `nm` 看导出符号 → 得到**API 面**；
2. `strings` 全量导出，重点看：**SQL 关键字**（SELECT/FROM/WHERE）、**表名字符串**、**JSON 字段名**（带引号的 `"xxx":` 模式）、**错误信息模板**（`"%s failed: ..."`）；
3. 用 `sed -n '/^A$/,/^B$/p'` 或 grep 的 `-B/-A` 上下文，按地址相邻关系重建「编译前相邻的字符串常量」；
4. 交叉验证：把还原出的协议和上层绑定代码（下个课题）对照，互相印证。

### 通用能力沉淀

- **C++ 程序的字符串常量是按编译单元聚集的**——同一个函数里用到的 SQL 片段大概率物理相邻，这是「不需要反汇编的协议重建」的物理基础。
- 错误信息是最好的免费文档：`sns.db not found in ...` 一句话就告诉你它会去找 `sns.db`，且路径是搜索出来的。
- JSON 输出字段名直接暴露了数据模型，等于免费拿到了结构体定义。

---

## 课题二：FFI 绑定逆向 —— 从 TS 类型声明反推 C ABI

### 解决什么问题

TypeScript 侧不能直接调 C++，必须有 FFI 桥。WeFlow 用 [koffi](https://koffi.dev/)（一个现代 Node FFI 库），而**绑定声明本身就 是对闭源库 ABI 的完整文档**。学会读它，你就学会了「怎么给一个没有头文件的库写绑定」——这同时也是逆向技能：写绑定的过程就是验证你对 ABI 理解的过程。

### 证据在哪

`electron/services/wcdbCore.ts:1095-1117`：

```typescript
// wcdb_status wcdb_get_sns_timeline(wcdb_handle handle, int32_t limit, int32_t offset,
//   const char* username, const char* keyword, int32_t start_time, int32_t end_time, char** out_json)
this.wcdbGetSnsTimeline = this.lib.func(
  'int32 wcdb_get_sns_timeline(int64 handle, int32 limit, int32 offset, const char* username, const char* keyword, int32 startTime, int32 endTime, _Out_ void** outJson)'
)
```

注意几个细节，每个都是 ABI 层面的知识点：

1. **注释先于绑定存在**：作者把 C 函数原型写成注释放在上面——这是逆向工作的标准姿势：先从文档/反汇编/字符串推断原型，再翻译成绑定。原型推断的依据链：函数名（`wcdb_get_sns_timeline`）+ 字符串考古（课题一）+ 调用点行为。
2. **句柄模式**：第一个参数永远是 `int64 handle`。C ABI 里 OOP 的标准做法——`wcdb_open_account` 返回不透明句柄，后续所有函数传回。读到这个模式就应立刻明白：库内部维护每账号状态（打开的 db 连接、密钥）。
3. **`_Out_ void** outJson` 输出参数模式**：C 函数没有多返回值，复杂结果通过「调用方传指针、被调方 malloc 并写入」返回。**配套必然存在 `wcdb_free_string`**——在 `wcdbCore.ts:47` 确实有 `private wcdbFreeString`。谁分配谁释放，跨 FFI 边界时这是内存泄漏/崩溃的高发区，也 是逆向时判断「返回值需要不需要 free」的直接线索。
4. **错误码约定**：`int32` 返回值，`0 = 成功`；`installSnsBlockDeleteTrigger` 里 `status === 1` 被解释为 `alreadyInstalled`——错误码语义要从调用方处理逻辑里反推（`wcdbCore.ts:4492-4497`）。
5. **防御式绑定**：核心函数（timeline）必须存在，否则报「不支持」；可选函数（`wcdb_get_emoticon_caption`）用 try-catch 包住 `lib.func()`，置 null 后运行时降级——**这是对「闭源库版本会变、符号可能缺失」的现实工程应对**，`getSnsTimeline` 里那句 `'当前数据服务版本不支持获取朋友圈'` 就是这条防线的产物。

### 怎么复现

```bash
# 验证绑定声明的真实性：nm 看到的符号应该与 lib.func() 的名字一一对应
nm -gU libwcdb_api.dylib | grep _wcdb_get_sns_timeline
# 然后写一个 20 行的 Node 脚本，用 koffi 加载 dylib 并调用一个无参函数
```

进阶复现：自己挑一个系统库或任意开源 C 库，不看头文件，只用「函数名 + 字符串 + 猜测原型」写出 koffi 绑定并调通——这就是完整的 ABI 逆向闭环。

### 通用能力沉淀

- 看到 `_Out_` / `**` 输出参数 → 找配套 free 函数；
- 看到句柄 → 理解库的状态管理边界；
- 看到 int32 返回 + 调用方 if-else → 还原错误码语义表；
- **绑定代码是 ABI 的可执行文档**，比反汇编轻量一个数量级。

---

## 课题三：密钥提取 —— 全项目技术含量最高的部分

### 解决什么问题

SQLCipher 数据库的密钥**从不落盘**，只在微信进程内存里瞬时出现（登录/打开 db 时）。要解密，必须在正确的时机从活着的进程内存里把它抠出来。这是整个项目真正「逆向」的部分，其余更接近「工程集成」。

### 证据在哪（三层证据链，值得反复咀嚼）

**第一层：helper 的日志关键字暴露了完整技术流程**。`electron/services/keyServiceMac.ts:474-493` 的日志解析代码：

```typescript
if (line.includes('strict hit=') || line.includes('sink matched by strict semantic signature')) {
    onStatus?.('已定位到目标函数，正在安装 Hook...', 0)      // ← 特征码定位
}
if (line.includes('hook installed @')) {
    onStatus?.('Hook 已安装，等待微信触发密钥调用...', 0)    // ← 断点注入
}
if (line.includes('[MASTER] hex64=')) {
    onStatus?.('检测到密钥回调，正在回填...', 0)              // ← 捕获 64 字节主密钥
}
```

这些字符串是作者**为了给用户显示进度**而写的，却完整泄露了实现原理，把流程串起来就是：

```
task_for_pid(微信 PID)                    → 附加进程
  → 扫描内存模块，按「语义特征码」匹配目标函数   （"sink pattern"）
  → 在函数入口 patch 断点（硬件断点/陷阱）      （"hook installed"）
  → 等待微信自己调用该函数                    （被动等待，不是主动搜索）
  → 断点命中时从寄存器/栈上读走 64 字节密钥     （"[MASTER] hex64="）
```

**第二层：错误码体系暴露了对抗环境的边界**。`keyServiceMac.ts:332-343`：

```typescript
if (raw.includes('Sink pattern not found'))  → SCAN_FAILED    // 微信版本变了，特征码没适配
if (raw.includes('patch_breakpoint_failed')) → HOOK_FAILED    // 断点注入被拦截
if (raw.includes('task_for_pid:5'))          → ATTACH_FAILED  // Mach 进程附加被系统拒绝
```

`docs/MAC-KEY-FAQ.md` 进一步揭示了现实约束：SIP 与 entitlements 限制（`task_for_pid` 需要调试权限，ad-hoc 签名的开发版 Electron 拿不到）、需要降级到适配过的微信版本、失败后要重启清状态。**这份 FAQ 本身就是「macOS 上做进程内存分析的权限与系统防线」的实战教材**，比任何博客都具体。

**第三层：一个完整可编译的 helper 源码**。`resources/key/macos/source/image_scan_helper.c` 是全项目唯一开放的 C 源码——它展示了规范的 helper 模式：

```c
typedef const char* (*ScanMemoryForImageKeyFn)(int pid, const char* ciphertext);
ScanMemoryForImageKeyFn scan_fn = (ScanMemoryForImageKeyFn)dlsym(handle, "ScanMemoryForImageKey");
const char* result = scan_fn(pid, ciphertext_hex);
// 返回 "ERROR..." 开头视为失败，否则就是 key；配套 FreeString 释放
```

学到的模式：**主程序（Electron）与特权操作（进程附加）通过独立 helper 进程隔离**——helper 拿到的是干净的最小权限，主程序通过 `spawn` + 解析 stderr 进度行 + 解析 stdout 最后一行 JSON 通信（`keyServiceMac.ts:454-552` 的完整子进程协议实现值得精读：行缓冲、超时 kill、残留进程 pkill 清理）。

**附加彩蛋：密钥用途不止 SQLCipher**。注意 `ScanMemoryForImageKey(pid, ciphertext_hex)` 的签名——它传入一段**密文**，在内存里扫描出能解密这段密文的 AES key（本地图片缓存的独立密钥体系）。**「已知明文/密文，在内存里搜能匹配它的密钥」**是一个可复用的通用技巧，比盲搜「长得像 key 的 32 字节」可靠得多。

### 怎么复现（阶梯式）

1. **读**：精读 `keyServiceMac.ts` 的 helper 协议实现与错误分类，画出状态机；
2. **跑**：对自己设备上的微信（自己的账号）执行一次 WeFlow 密钥获取，观察各阶段日志；
3. **写**：写一个最小 task_for_pid demo（Xcode 工程里 `#include <mach/mach.h>`，读目标进程的一个 VM region），体验 entitlements 拒绝；
4. **研究 Frida**：`hook installed @` 等价于 Frida 的 `Interceptor.attach`，用 Frida 对自己的测试程序复现「断点 → 读寄存器 → 捕获瞬时数据」全流程。

### 通用能力沉淀

- **瞬时秘密的捕获思路**：密钥不存储、只在调用瞬间存在 → 不能静态搜内存，必须 hook 调用点等它自投罗网；
- **特征码定位 vs 固定偏移**：`Sink pattern not found` 说明用的是语义特征匹配而非硬编码地址——版本适配成本的根源与解法；
- **进程隔离的特权边界设计**：Electron 主程序不碰 Mach API，helper 进程拿最小权限，JSON+日志行作为 IPC 协议；
- 顺带理解 macOS 安全模型：SIP、`task_for_pid` 的 entitlements 门槛、签名链。

---

## 课题四：ISAAC64 + XOR —— CDN 媒体流解密

### 解决什么问题

朋友圈的图片/视频不在本地库里，`SnsTimeLine.content` XML 里只有 CDN URL + token + `<enc key="2105122989">`。下载回来的是**加密流**，需要用 enc key 生成密钥流逐字节 XOR。

### 证据在哪

这个课题的妙处在于：**纯 TS 实现 + WASM 加速 + 魔数校验**三件套完整可读。

**① 算法本体**：`electron/services/isaac64.ts`（127 行，全文值得逐行读）。ISAAC 是 Bob Jenkins 的快速密码学 PRNG，微信用它生成对称密钥流。三个学习要点：

```typescript
// 要点 1：种子放置方式 —— 整个 randrsl 清零，key 只放第一个槽位
this.randrsl.fill(0n)
this.randrsl[0] = seedBig
this.init(true)

// 要点 2：初始化混合 —— 黄金分割常数 0x9e3779b97f4a7c15 起手，8 变量 mix
a = b = ... = h = 0x9e3779b97f4a7c15n

// 要点 3：输出字节序 —— 大端写入，注释直说了这是逆向得出的微信行为
// "This matches WeChat's behavior (Reverse index order + byte reversal)"
public generateKeystreamBE(size: number): Buffer { ... }
```

`generateKeystreamBE` 的存在本身就是逆向叙事：标准 ISAAC 参考实现是小端/顺序输出，微信的实现却有「反序 + 字节反转」的魔改，作者显然是对着已知明文（JPEG 头 `FF D8 FF`）暴力试出了正确的字节序组合。**这就是「已知明文攻击定标格式」的微型案例**。

**② WASM 加速 + 优雅降级**：`snsService.ts:2016-2024`：

```typescript
try {
    const wasmService = WasmService.getInstance()
    keystream = await wasmService.getKeystream(keyText, 131072)   // WASM 版（BigInt 模拟 64 位运算极慢）
} catch (wasmErr) {
    const isaac = new Isaac64(keyText)                            // 纯 TS 回退
    keystream = isaac.generateKeystreamBE(131072)
}
```

BigInt 逐位模拟 64 位运算是性能灾难，所以有 `electron/assets/wasm/wasm_video_decode.wasm`。**「纯 TS 参考实现作为正确性基准 + WASM 作为性能路径 + 失败自动回退」**这个三件套是跨语言密码学代码的标准工程范式。

**③ 视频只解头部**：`snsService.ts:2018` 注释 `// 只需要前 128KB (131072 bytes) 用于解密头部`——视频只需解密 ftyp/moov 头就能播放，流式跳过剩余部分。密码学上这意味着**微信的 XOR 流加密一旦丢同步就是灾难，但对「前缀解密」极其友好**。

**④ 魔数校验闭环**：`detectImageMime`（`snsService.ts:160-205`）用魔数检查解密结果——JPEG `FF D8 FF`、PNG、GIF87a/89a、RIFF/WEBP、ISO-BMFF 家族里区分 AVIF/HEIC/MP4。解密成功与否**不靠异常，靠「解出来像不像合法图片」**。这是所有「无认证标签的 XOR 解密」唯一的正确性判据，写任何此类工具都必须有。

### 怎么复现

```bash
# 最小闭环实验（不碰微信也能做）：
# 1. 自己实现/复制 isaac64.ts
# 2. 用已知 key 生成 keystream，XOR 一个 PNG 文件 → 观察变成乱码
# 3. 再 XOR 同一段 keystream → 还原（验证 XOR 对称性）
# 4. 故意用错误 key → 用魔数检测「解密失败」
# 进阶：对照 Bob Jenkins 的 ISAAC 官方 C 版本逐函数核对
```

### 通用能力沉淀

- 识别「XOR 流加密」特征：密钥流 PRNG + 逐字节异或 + 需要外部魔数校验；
- 已知明文定标：用 JPEG/PNG 头暴力对齐字节序/对齐偏移的思路可迁移到任何自定义格式；
- 参考实现/优化实现/回退路径的三层结构。

---

## 课题五：SQLite 触发器 —— 数据生命周期劫持

### 解决什么问题

微信会清理本地库：删帖、三天可见过期、防撤回失效。这些都是物理 `DELETE`。WeFlow 的解法是往**微信自己的数据库**里注入触发器，让删除静默失败。

### 证据在哪（两个同构案例，对照学习价值极高）

**案例 A：朋友圈防删除**（课题一已还原的 DDL）：

```sql
CREATE TRIGGER IF NOT EXISTS block_delete_SnsTimeLine
BEFORE DELETE ON SnsTimeLine
BEGIN SELECT RAISE(IGNORE); END
```

`RAISE(IGNORE)` 是 SQLite 触发器里的特殊语句：**放弃当前这一行操作，且不报错**。效果 = 对这张表的 DELETE 全部变成 no-op，微信毫无感知，数据永久冻结。

**案例 B：消息防撤回**（从 strings 还原，展示了更进阶的影子表模式）：

```sql
CREATE TABLE IF NOT EXISTS _weflow_anti_revoke_deleted_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tbl TEXT NOT NULL, local_id INTEGER, server_id INTEGER, ...,
  deleted_at INTEGER
)
-- BEFORE DELETE 触发器里：把 OLD.* 整行搬进影子表
INSERT INTO _weflow_anti_revoke_deleted_cache (...) VALUES (OLD.local_id, OLD.server_id, ...)
-- 之后还能 INSERT 回原表恢复消息（strings 里有完整的 INSERT ... SELECT ... FROM cache 语句）
```

两个案例是同一思想的两种强度：

| | 案例A（朋友圈） | 案例B（防撤回） |
|---|---|---|
| 策略 | 直接拒绝删除（RAISE IGNORE） | 允许删除但先快照到影子表 |
| 副作用 | 微信的清理逻辑可能积累不一致 | 占额外空间，需维护 cache |
| 通用名 | **拦截器模式** | **影子表/软删除模式** |

工程细节也值得学：`_weflow_anti_revoke_pending` 表记录「哪些会话装了触发器」（`REPLACE INTO ... VALUES`），`checkSnsBlockDeleteTrigger` 通过查 `sqlite_master` 判断触发器是否已安装——**在别人的数据库里做持久化状态管理，命名前缀 `_weflow_` 是避免与宿主 schema 冲突的规范做法**。

### 怎么复现（5 分钟，零风险）

```bash
sqlite3 /tmp/demo.db <<'EOF'
CREATE TABLE msg(id INTEGER PRIMARY KEY, text TEXT);
INSERT INTO msg VALUES (1, 'hello'), (2, 'world');
CREATE TRIGGER block_del BEFORE DELETE ON msg
BEGIN SELECT RAISE(IGNORE); END;
DELETE FROM msg WHERE id = 1;
SELECT COUNT(*) FROM msg;   -- 仍然是 2！删除被静默吞掉
EOF
```

再练影子表版：把 `RAISE(IGNORE)` 换成 `INSERT INTO shadow SELECT OLD.*` 然后允许删除继续。这两个实验做完，你对「应用与本地数据库的信任边界」的理解会上一个台阶：**任何把 SQLite 当私有缓存的客户端应用，其数据生命周期都控制不住，因为数据库本身是可编程的**。

### 通用能力沉淀

- 审计思路：看到「本地 SQLite 缓存了有价值但会消失的数据」→ 触发器是最廉价的数据保全方案；
- `RAISE(IGNORE)` vs 影子表两种强度的取舍；
- 在宿主数据库注入持久对象时的命名空间纪律。

---

## 课题六：工程架构 —— 逆向成果如何变成产品

### 解决什么问题

逆向拿到数据只是 20%，剩下 80% 是把「能跑的 PoC」变成不卡 UI、可测试、可对外暴露的软件。这层没有秘密但全是经验。

### 值得学的四个决策

**① FFI 全部隔离进 worker 线程**。`wcdbWorker.ts` 用 `worker_threads` 把所有 koffi 调用移出主进程，`wcdbService.callWorker('getSnsTimeline', {...})` 以消息协议转发。原因：koffi 同步调用会阻塞 Electron 主进程 → UI 冻结 + 窗口无法响应。**逆向工具的典型形态：FFI 阻塞调用 + GUI 线程模型天然冲突**，worker 隔离是标准解。

**② 三层 API 暴露**。同一份 `snsService` 能力被暴露了三次：`ipcMain.handle('sns:*')`（渲染进程用）→ `preload.ts:530` 的 `window.electronAPI.sns.*`（contextBridge 安全暴露）→ `httpService.ts` 的 `GET /api/v1/sns/timeline`（外部集成）。**一次实现、三个面**，这是本地工具做生态的标准姿势。`docs/HTTP-API.md` 里 curl 示例齐全，可直接当接口文档模板。

**③ 游标分页而非 offset 分页**。`SnsPage.tsx:1087`：加载更旧内容时 `endTs = 最后一条 createTime - 1`，加载更新时 `startTime = 首条 + 1`。**本地库在导出/删除操作下数据会变，OFFSET 分页会跳条或重复，时间戳游标不会**。同时 `exportTimeline` 里用的却是 offset 循环（`offset += pageSize`）——两处对比正好展示两种分页的适用差异（导出是快照语义，浏览是增量语义）。

**④ 端到端的降级与容错设计**，几乎每个环节都有备用路径，这 是长期维护「逆向目标会变版本」的软件的核心生存技能：

```
wcdb_get_sns_usernames 返回空 → 回退到 timeline 分页扫表收集  (snsService.ts:902)
DLL 返回的评论缺表情     → 从 rawXml 用正则重新解析          (snsService.ts:1228)
WASM 不可用              → 纯 TS ISAAC64                     (snsService.ts:2021)
统计查询返回 0           → 缓存兜底 + timeline 全表统计回退   (snsService.ts:988)
```

### 怎么复现

给自己的逆向 PoC 加一层壳：worker 化 → IPC → 小 HTTP API → curl 可调用。做完这一个循环，你对「PoC 到产品」的距离会有具体体感。

---

## 总结：一张学习路线图

| 课题 | 核心技能 | 难度 | 可独立复现 | 反复研读的回报 |
|------|---------|------|-----------|--------------|
| 一、字符串考古 | nm/strings/协议重建 | ★☆☆ | ✅ 完全 | 每次遇到新二进制都用 |
| 二、FFI 绑定 | ABI 推断与验证 | ★★☆ | ✅ 完全 | koffi/ctypes/frida 通用 |
| 三、密钥提取 | 进程内存 + Hook | ★★★★ | ⚠️ 需自己设备 | 理解所有「瞬时秘密」类问题 |
| 四、ISAAC64+XOR | 流密码识别与定标 | ★★★ | ✅ 完全 | 已知明文攻击的肌肉记忆 |
| 五、SQLite 触发器 | 数据生命周期劫持 | ★★☆ | ✅ 完全（5分钟） | 本地数据保全通用解 |
| 六、工程化 | worker/IPC/API/降级 | ★★☆ | ✅ | PoC→产品的模板 |

**建议的研读顺序**：五（动手最快，建立信心）→ 一（建立方法论）→ 二（打通调用链）→ 四（算法层）→ 六（工程视野）→ 三（最后攻 hardest，需要较多前置知识）。

这个项目最值得反复回味的，是它在每个环节都展示了同一种思维：**不硬碰硬（不伪造协议、不破解加密算法本身、不重写客户端），而是找到系统里「已经存在的薄弱环节」——密钥会出现在内存里、数据会落盘、删除会经过 SQL、媒体解密只需前 128KB——然后精确介入**。逆向工程的高手过招，从来不在算力，而在对目标系统数据流的完整理解。

---

*文档基于 WeFlow 开源仓库（GitHub: hicccc77/WeFlow）源码与其自带二进制资源分析产出。引用的文件路径与行号均对应该仓库。*
