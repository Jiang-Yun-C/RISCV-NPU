# SpyGlass 静态验证

此入口借鉴 `/home/Jiang/BSI/bridge_meta/harness/adapters/spyglass.sh`、
`harness/bin/synopsys-license-probe` 以及
`scripts/qualify_p29_predictor_static.py` 的本地运行、FlexNet 探测和报告验收方式。
运行时不依赖 BSI 目录，也不继承其检查结果、RTL 参数或豁免。

## 运行

```bash
make spyglass-doctor  # 探测 lint/CDC/RDC 各自的 feature；不执行设计分析
make spyglass-lint    # 默认检查项目内 8 个模块
make spyglass-cdc
make spyglass-rdc
make spyglass-all     # 分别记录三类检查；即使某一项失败，仍收集其他项
make spyglass-test    # 无许可证依赖的解析器负例与包装编译检查

# 单模块检查；可重复 --scope
make spyglass-lint ARGS='--scope nx_accel_guard'

# 显式纳入生成 CPU 的 soft/hard/nopredict 等目录；不自动选择历史 build
make spyglass-all ARGS='--cpu-build build/T09/sim-v1-20261008-v1'

# 纳入实际生成的 Coral 后端（保留文件列表顺序和 include 文件）
make spyglass-lint ARGS='--coral-rtl build/T19/sim-v1-20261008-v1/compiled/rtl --scope coral'
```

默认配置为 `configs/spyglass.json`，使用已安装的 SpyGlass X-2025.06。
可通过 `ARGS='--config /absolute/path/config.json'` 选择配置。
`SPYGLASS_HOME` 和 `SPYGLASS_LMUTIL` 可覆盖安装路径；许可依次采用
`SNPSLMD_LICENSE_FILE`、`LM_LICENSE_FILE`、配置中的 `license_server`，
并把同一选项同时用于预检和工具执行。工具版本不符合配置则拒绝通过。
默认每次工具分析超时 1800 秒；超时会终止进程组并保留日志。

`--cpu-build` 必须包含 `generated/<profile>/T09Cpu.v`；多个目录可重复指定，
重名 profile 拒绝，避免悄悄选择不同生成物。读取 RTL 和初始化文件后保存源码快照。
生成核采用 `SYNTHESIS`，排除仿真用枚举字符串等代码；精确宏和文件列表保存在项目文件。
`--coral-rtl` 读取指定目录的 `filelist.f`，保留 `USE_GENERIC`、`VLEN_128`、
`ZVE32F_ON` 等设计选项，移除仿真断言宏 `TB_SUPPORT` 并加入 `SYNTHESIS`。
原始文件列表、有效宏及变化均归档；不加载 DPI/C++ 行为代码。
配置的 `mthresh=4194304` 和 `handle_large_bus=yes` 用于展开实际缓存/大数组，
避免默认 4096-bit 限制导致未综合黑盒；它们不改变错误/告警验收阈值。

## 检查范围与约束

默认范围：`t03_uart_tx`、`t17_uart`、`t17_uart_router`、`t18_spi`、
`nx_accel_bridge`、`nx_accel_guard`、`nx_shared_memory_arbiter`、`nx_stream_counters`。
依赖的 `axi4_if` 和 `nx_accel_map` 按需加入。

AXI 接口包装从实际 RTL 接口生成：CPU 32-bit/ID1、Coral 128-bit/ID6；
所有输入接到包装顶层输入，所有输出对外可见。被动计数器的两侧通道均为观察输入。
包装不提供刺激、不把 AXI 输入绑成常量、不用 blackbox 替代被检查模块。

SGDC 使用当前仿真的 10ns 主时钟和模块实际复位名称/极性/类型。
项目模块按实际 posedge-only 敏感列表标记同步复位；生成 CPU 与 Coral
按实际异步复位敏感列表标记异步复位，不将两种复位混用。
同步的总线/控制输入通过 `abstract_port` 关联到主时钟。
UART `rx` 和 SPI `miso` 分别关联到独立的保守虚拟外部域：
`clock -tag external_* -period 10 -domain external_*`（不指定 `-name`），
不套用与主时钟同步的输入假设。这些模型的语法已由实际工具验证；
外部速率/相位、SPI 可变分频 SCK 与卡响应/采样时序合同仍待补充，
即使工具返回干净报告，这两个模块也不能获得 CDC/RDC 通过结论。
CPU 单模块约束假定输入总线和中断同步，不能用于板端异步中断签核。

历史 `t03_soc`、行为内存、测试平台、集成 SoC、生成 Coral 后端、
板级 DDR/PLL/IO 不在默认范围。单模块静态结果不替代跨模块连接检查、
VCS/cocotb 功能验证或板级 CDC/RDC 签核。此次入口采用 `sandbox` 轨道，
不会修改冻结的 sim-v1/T21 验收记录。

显式提供 `--coral-rtl` 可执行 Coral lint。Coral 门控/派生时钟和复位重汇聚的
完整 SGDC 仍需审查；当前基础约束不会被当成 Coral CDC/RDC 签核模型。

## 判定

每个 goal 均要求对应 top 的 `consolidated_reports` 下真实
`spyglass.log` 和 `moresimple.rpt`。解析实际完成标志、工具版本、Fatal/Error/Warning，
并核对逐条诊断和汇总计数。CDC 两个 goal 都必须产生完整报告。

通过条件为：进程成功、全部分析报告完整、零 Fatal/Error/Warning、零 waived 和
overlimit 消息。新增 warning 默认失败；本入口没有自动基线、全局 suppression 或豁免。
保留告警的规则、文件、行号、消息及原报告，供后续修复或有依据的审查。

`scripts/audit_r01.py --evidence <完整静态证据目录> --reviews
configs/r01-warning-review.json --run-id <新身份>` 可重新解析归档原始 lint
报告并核对源码摘要，生成逐项告警 JSON/CSV。审查项绑定源文件 SHA、位置
与消息 SHA；陈旧或未匹配项拒绝。清单工具自身 PASS 只表示来源与审查匹配，
已审查但保留的 Warning 仍使设计零告警门禁 FAIL，不产生 waiver。

| 结果 | 含义 |
|---|---|
| `PASS` | 所选范围全部满足报告验收条件 |
| `FAIL` | RTL/约束诊断、未完成分析、缺报告、计数不符、超时或输入变化 |
| `BLOCKED_LICENSE` | 对应功能未就绪，或实际 checkout 被拒绝 |
| `EXECUTION_CONTEXT_BLOCKED` | FlexNet 连接被执行环境以 EPERM 等原因拒绝 |
| `BLOCKED_TOOL` | 工具或 methodology 缺失 |
| `READY` | 仅 doctor 的工具存在和 feature 就绪；不是设计通过 |

默认 feature：lint=`lint_func`、CDC=`cdc_adv_checker`、RDC=`rdc_adv_checker`。
lint 的可用许可不代表 CDC/RDC 也可用。报告规则目录中出现 `Ac_license01`
不是许可证失败，必须有实际诊断；无报告的计数保留为 null，不当作零。

## 证据

每次创建 `build/SPYGLASS/<run-id>/` 和 `evidence/SPYGLASS/<run-id>/`，
拒绝覆盖已有目录。证据包含：

- `summary.json`：总结果、逐 stage/scope/goal 结果及范围限制。
- `manifest.json`、`commands.json`、`checks.json`：输入/工具身份、命令、超时和状态。
- `sources/`、`source-manifest.json`：执行所读的 RTL、包装、初始化文件和脚本/配置快照。
- `*-license.json`、`logs/`：逐次同环境 FlexNet 检查和 SpyGlass 原始输出。
- `artifacts/<stage>-<scope>/`：`.prj`、`.sgdc`、报告、逐条诊断及 `result.json`。

源码/配置/报告 SHA-256 保存在清单中；工具直接读取保留的源码快照。
运行结束再次检查原输入文件，过程中变化则失败。构建数据库留在 `build/`，
必要报告复制到 `evidence/`，因此清理构建目录不删除历史验收证据。
