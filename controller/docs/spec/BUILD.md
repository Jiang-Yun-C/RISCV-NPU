# 构建与证据合同 v1（T01）

## 入口与复跑

在工程根目录执行 `make smoke`。默认配置 `configs/t01-smoke.json`，工具锁 `docs/spec/toolchain-lock.json`，Python 全量版本锁 `docs/spec/python-requirements.lock.txt`，第三方锁 `third_party/lock.json`。
全部路径以脚本位置解析，Python 入口也支持从其他工作目录调用。无需重新安装或构建用户级环境。

每次自动生成 UTC 时间与随机后缀组成的 run-id。构建目录 `build/T01/<run-id>/` 必须是新目录；证据目录 `evidence/T01/<run-id>/` 不覆盖。
指定已存在的 `--run-id` 会失败。`make clean` 仅删除根目录下的 `build/`，拒绝指向其他位置的 build 符号链接，保留证据和模型。

`npu-python scripts/run_smoke.py --config <json> --seed <n> --run-id <id>` 可选择配置、种子和标识。种子范围为 0–2147483647，进入 C 数据、RTL plusarg 与 VCS 随机种子。配置完整复制到证据中。
RV32IM/ILP32 与当前样例入口属于 T01 测试配置；样例的 0x10000 地址不定义最终系统地址图。

## 返回码和超时

| Python 入口返回码 | 含义 |
|---|---|
| 0 | 所有必需检查通过 |
| 1 | 命令失败、内容不符、环境漂移或运行器异常 |
| 2 | CLI 错误、目录冲突，无法建立新证据目录 |
| 124 | 子命令超时，已终止进程组 |
| 127 | 子命令无法启动 |
| 130 | 用户中断 |

GNU Make 将 recipe 的非零返回转换为自己的失败码（通常为 2）；精确结果以 manifest、exit-status.txt 和 commands.json 为准。
进程非零不是唯一失败条件：主机结果、ELF、仿真标志和波形均另做内容检查。
配置默认 probe/run/check 各 30 秒、每条编译命令 180 秒。超时杀掉整个子进程组，避免 VCS 的编译器或仿真子进程残留。
日志在子进程启动前打开，步骤状态在启动前保存；失败、中断和超时均写入最终清单。SIGKILL/掉电无法执行收尾时，已有 RUNNING 清单和日志表示未验收，不得视为通过。

## 结果目录

- `manifest.json`：状态、时间、原始调用、平台、环境白名单、身份、资格边界、工具实测和产物哈希。
- `config.json`：包括 seed 在内的有效配置；配置哈希针对这份完整快照。
- `commands.json`：每步 argv、cwd、timeout、起止时间、原始子进程返回值、归一化退出码、stdout/stderr 路径。
- `logs/*.stdout.log`、`logs/*.stderr.log`：原始命令输出，含编译器版本、readelf、objdump、独立 checker 与回归报告。
- `checks.json`：命令与内容检查的 PASS/FAIL；`exit-status.txt` 为运行器返回码，失败时另有 `failure.txt`。
- `source.tar.gz`：本次参与构建的源码、配置、检查器和锁文件快照；无需 Git 提交也能识别输入。
- `historical/`：全局环境 manifest 和原有 smoke 日志副本，明确仅作来源证据。
- `artifacts/`：小型 ELF/BIN、link map、VCD、主机 JSON、tensor 和工具报告；VCS 编译缓存和可执行程序留在 build。

## 身份与锁定

source.files 记录 Makefile、忽略规则、第三方锁和 configs/scripts/tests/smoke/docs/spec/rtl/firmware/software/model_tools 下各输入文件的 SHA-256（排除 Python 缓存）。
source.sha256 是该相对路径→文件哈希字典按键排序、紧凑 JSON 编码后的 SHA-256。运行结束再次比较输入，文件在途中改变则失败。
任务状态、报告、历史日志和生成物不进入源码身份，因此更新验收状态不会改变测试输入。source.tar.gz 的压缩时间戳不是源码身份。

firmware.sha256 是当前链接出的 ELF；另列 `execution=NOT_TESTED_T03`。model 明确为 NOT_APPLICABLE，revision/hash 为 null；本卡没有模型输入。checker 单独记录 SHA-256，seed 单独列出。
ELF 调试路径归一化到工程相对路径，汇编 `.file` 固定源文件名，避免随机临时对象名进入符号表；两次干净构建要求 ELF SHA-256 一致。
以后涉及模型或实际固件执行的任务必须用真实输入身份替代这些状态，不能继承 T01 的空值作验收。

工具检查比对入口文件/可执行文件哈希、实际版本、Python 全量包版本和关键环境文件哈希；VCS 版本从本次成功编译日志核对。
保留原安装包摘要作为历史来源，不重新下载它们；不复制专有工具或许可证。
VexRiscv 锁定外部 checkout 的 commit，检查已跟踪文件无修改；T01 不使用其生成物，也不重建 sbt 项目。sbt 启动器 1.10.7 与 VexRiscv 项目 sbt 1.6.0 分开记录。
工具升级或迁移时审阅实际版本和来源、更新相关锁文件，再跑 smoke；运行器不自动接受漂移。

## 验收覆盖

| 项目 | 当前测试 |
|---|---|
| 工具存在 | 入口文件、版本、身份与 Python 包版本检查 |
| 主机 C/Python | GCC 编译运行；NumPy int64 独立校验 16 元素整数 dot；Safetensors 往返 |
| RV32 ELF | 显式 RV32IM/ILP32 编译链接；readelf/objdump/BIN；独立 ELF32、RISC-V、ABI、入口、段范围和符号校验 |
| VCS 实际执行 | SystemVerilog 编译与运行；时钟/复位/8 拍计数；退出码和 seed 对应的通过标志 |
| 波形可读 | VCD 头、信号、时间单调、复位、时钟及每拍计数的独立解析；未验收 Verdi GUI/FSDB |
| CPU 执行固件 | NOT_TESTED_T03 |
| 完整模型/后端/板卡 | 未验收 |
| PDS | 历史 manifest 记录未安装；本次记录 PATH 探测，非 T01 前置条件 |

T01 的小型波形读取器仅接受该 fixture 的 VCD 子集；后续复杂 RTL 按其测试合同选择适当检查器。
`tests/smoke/test_evidence.py` 验证非零/超时/缺工具留痕、进程组清理、不覆盖、路径限制和错误内容拒绝；每次 smoke 内执行。
`make acceptance` 额外执行两次 `make smoke`（各自先清理 build），核对源码/配置/checker/ELF 身份一致、产物哈希完好；真实入口的非法配置须返回 1，强制编译超时须返回 124，并保留 FAIL manifest 和原始日志。另用成功产物的损坏副本验证 ELF/VCD 检查器会拒绝错误。
验收驱动自身保存 `T01_ACCEPTANCE_DRIVER` 清单，列出成功及预期失败 run 的路径；预期 FAIL 不应删除或改成 PASS。

## 向下游交接

后续任务使用 `scripts/evidence.py` 创建独立 task-id/run-id，填写自身输入身份与覆盖边界。
遵守 [HANDOFF](../plan/HANDOFF.md) 的每卡最小证据要求；不能把工具存在、RTL 编译、RTL 执行、CPU 执行固件、板级验证合并成一个通过结论。
