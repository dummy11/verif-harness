# v3 安装、初始化和版本管理

每个 verif-harness 发布版本固定一份 nsim 版本及安装包摘要，关系见 `release.json`。
项目只选择 verif-harness 版本。安装新版本不会升级项目；已发布安装包不能替换。

## 用户级和系统级安装

从 GitHub Release 下载 `verif-harness-install.py` 并按 `SHA256SUMS` 校验。
安装器需要 Python 3.9+，默认另外安装发布清单要求的独立 Python 运行环境。
Codex/Kimi CLI 由用户安装和认证，个人凭据不进入发布包。

```bash
python3 verif-harness-install.py install 3.0.0 --user
export PATH="$HOME/.local/share/verif-harness/bin:$PATH"
```

管理员使用有目录写权限的账号执行系统安装；安装器不会自动提权：

```bash
python3 verif-harness-install.py install 3.0.0 --system
export PATH="/opt/verif-harness/bin:$PATH"
```

个人目录为 `~/.local/share/verif-harness` 和 `~/.local/share/nsim`；系统目录为
`/opt/verif-harness` 和 `/opt/nsim`。自定义位置使用 `--root` 和 `--nsim-root`。
相同版本和安装包摘要直接复用；不同摘要拒绝覆盖。个人安装可复用完全匹配的系统 nsim。
项目数据库、Dashboard 日志和 token 保存在项目或当前账号目录，不写入共享程序目录。

默认安装锁定的 Python、xverif 和 WavePeek，并核对配套 nsim。
`--python PATH` 可使用明确选择的 Python 3.11+ 创建隔离环境。
`--core-only` 只安装控制面和 nsim，适合无 Agent 的配置或分发测试；不表示分析工具就绪。
本地 wheel 使用 `--wheel`，配套 nsim 使用 `--nsim-wheel` 和 `--nsim-installer`，
Python 依赖可通过 `--wheelhouse` 提供。所有配套 nsim 文件仍须匹配发布清单的校验值。

已有 Python 3.11+ 的离线机器可以使用控制面离线包：

```bash
python3 verif-harness-install.py bundle create --wheel verif_harness-3.0.0-py3-none-any.whl \
  --nsim-wheel nsim-0.1.0-py3-none-any.whl --nsim-installer nsim-install.py \
  --wheelhouse wheelhouse --output core-offline.tar.gz
python3 verif-harness-install.py install --bundle core-offline.tar.gz \
  --python /path/to/python3 --core-only --user
```

wheelhouse 必须包含目标 Python/平台对应的 nsim 依赖 wheels；导入只使用包内依赖，
不访问包索引。离线包包含逐文件校验清单，并另外生成归档 `.sha256`，传输后需核对。
它不包含 Python 解释器、xverif、WavePeek 或 Agent CLI；完整分析环境仍需分别准备这些工具。

## 每个项目 bootstrap

```bash
verif-harness bootstrap
```

交互终端逐项询问 RTL 根目录、RTL filelist、DUT top、top file、验证资产目录、规格、
已有 testbench、参考模型和验证脚本，再确认 nsim 的可选 testbench filelist 与仿真输出目录。
每次只询问一项；可选项必须提供路径或填写 `skip`。最终汇总确认后才写入。
RTL filelist 与 RTL 根目录同为必填只读输入，不生成替代文件。

自动化可以明确提供参数：

```bash
verif-harness bootstrap --project-root /work/project \
  --runtime codex --rtl-root /work/design/rtl --rtl-filelist /work/design/rtl/rtl.f \
  --dut-top dut_top --dut-top-file /work/design/rtl/dut_top.sv \
  --verif-root verification --sim-output-root /data/simulation --dashboard
```

nsim 工程位于选定的验证资产目录，使用发布清单中的准确版本。本版本集成要求一个明确的
RTL 根目录；多个 RTL 输入通过工程 filelist 表达。现有 `.nsim` 配置先核对再复用，
路径或版本冲突不静默覆盖。submit、caselist 和 regression list 位置继续由 nsim TOML 管理。
继续采用 nsim 的命名规则：同一账号登记的验证目录名称必须唯一；多个项目可分别使用
`chip_a_verif`、`chip_b_verif`，不能都登记为 `verification`。重复名称会在初始化前报错。
没有 testbench filelist 时 nsim 创建待填写模板；模板及初始化成功不表示可以仿真。

`.verif-harness/toolchain.json` 保存软件选择，ProjectStore 仍是工作流状态的唯一事实源。
Agent 配置失败后可用相同输入重试，不重建已有控制状态。改变输入使用 `bootstrap --refresh`，
逐项确认。旧源码项目通过完整 refresh 参数登记发布版本，保留文档、审批和证据历史。
refresh 可将旧 setup 创建的 Skill 符号链接改为当前安装版本，并记录原路径；旧源码目录和
用户自行修改的 Agent 配置保留。普通 restart 不接管未登记的 Skill 入口。

## restart 继续工作

```bash
verif-harness restart
```

从项目根目录或任意子目录启动，找到最近项目，检查固定版本、Skill/MCP 和 Dashboard，
进入项目选择的 Codex 或 Kimi。Agent 读取持久化状态接续工作；不会凭空恢复消失的进程或
聊天历史。`restart --no-agent` 只准备 Dashboard。该操作保留工作流 revision、审批和证据，
不重新初始化或升级工具。

Dashboard 按账号、发布版本和程序身份分开运行。同版本项目可以共享服务，各项目的数据库、
访问和路由保持独立。远端服务就绪不表示本机 SSH 转发已经验证。

## 查询和切换版本

```bash
verif-harness versions
verif-harness version
verif-harness install 3.0.0
verif-harness switch 3.0.0
```

`versions` 查看当前安装目录中的版本；`version` 显示所选版本的发布清单。
目标版本必须已经安装且数据库 schema 兼容。本版本不自动迁移不兼容数据库。
已有 Agent、正在运行的 nsim、未结束或尚待核对的 VREG 执行会阻止切换。
切换保存一致的 SQLite 备份和原版本记录，不重建审批，不把旧证据当成新执行结果。
切换后使用 restart 更新 Agent 配置并准备相应 Dashboard。

中断后项目停止普通操作，恢复入口为：

```bash
verif-harness switch --recover
```

恢复原工具选择，不将旧数据库备份覆盖到新记录上。受管项目不能单独使用 `nsim switch`
改变版本；独立使用 nsim 的项目不受影响。历史报告保存创建版本；使用旧工具复现实验时，
在独立工作区选择对应的 verif-harness 版本。

## 开发和发布

源码 `scripts/setup` 保留为开发兼容入口。共享安装目录不能 git pull 或修改资源。
正式发布在干净提交上运行 `make release-check`，验证安装和版本切换；创建与发布清单一致的 tag：

```bash
python3 scripts/package_release.py --release --output /tmp/verif-harness-release
```

输出目录必须为空，包含 wheel、sdist、独立安装器、发布清单和 SHA256SUMS。
固定 nsim 安装包须先独立测试和发布。fake 仿真和临时系统安装目录测试不等于商业 EDA、
真实共享机器或 farm 验收。

GitHub 的 `Release` workflow 由人工选择已经创建的 tag 后启动，重新执行 release-check、
文档构建和真实安装测试，通过后才创建 Release；不会覆盖已发布版本。
