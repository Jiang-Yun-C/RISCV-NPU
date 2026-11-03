# PDS 全局调用与任务交接

2026-10-12最新：**PDS2024.2/build178169已独立注册为全局EDA**，安装 `/software/eda/pango/PDS_2024.2`，版本入口 `pds2024` / `pds2024_shell` / `pds2024-doctor` / `pds2024-run`，可选模块 `pds/2024.2`。开跑执行 `make pds2024-check ARGS=--synthesize`，绑定[新版全局合同](pds-toolchain-2024.2-global.json)与本卡新PASS收据；精确PG2L200H/FBB676/-6 ADS/map另有独立检查。许可证按用户授权在专用虚拟MAC空间自动校验/首次重建，工具以调用者原账号执行。rc3默认 `current`、旧入口与历史合同保留。完整用法、PnR/网表/下载差异及范围见[PDS2024/T23经验](pds2024-t23-lessons.md)；[全局注册证据](../../evidence/PDS_GLOBAL/registration-20261012-v1/manifest.json)。

T23当前适配器已在项目候选2024安装完成真实校准、1GiB/32byte masks、3999.985秒零错误和六项持续带宽，八项正式门禁PASS；原绑定安装/合同/证据原样保留。全局副本工具资格与原镜像资格分别登记。下文2022入口和升级准备按其日期/rc3范围理解；T24 CPU/Coral竞争与T30完整PHY/IO保持OPEN。

2026-10-10项目内新路径：[原生200H/HMIC1.10已生成源码在rc3重建](../reports/ddr-native110-rc3-20261010.md)，实板通过校准、1GiB/32byte masks及3664.812秒零错误工作负载。全局安装/许可未改；该结果不改变安装1.3生成器对200H的实际拒绝记录，不关闭完整PHY时序或官方新版生成流程资格。

2026-10-10最新[安装及DDR选择核验](../reports/pds-install-ddr-selection-20261010.md)：47,847个安装文件与原始tar全部一致，六个原始分卷hash通过。原包本身的IP目录写1.7、实际HMIC生成器为1.3；本次相同参数再次复现100H成功、200H退出104拒绝。安装完整性与200H DDR配套问题已区分。当前默认入口继续保留rc3；下文升级准备是历史记录，不能据此自动切换全局版本。

2026-10-08 已在 `EDA-RHEL8` 完成系统级安装：**PDS 2022.2-rc3，build 113398**。Jiang、root、admin 均已验证许可证与 Tcl 执行；WSLg 图形主窗口和独立计数器的 ADS 综合也已通过。后续任务复用本安装，先检查，再建立各自工程。

标准 **MES2L676-200HP（200Pro+）V1.2** 当前采用[已验证工程路径](200pro-verified-pds-path.md)：保留rc3，项目内复用原厂原生200H/HMIC1.10生成源，从源重建并独立验收。官方HMIC_S V1.14的最低SP1.2要求仍作为官方版本边界，不能仅凭shell/ADS通过宣布DDR合格；当前项目校准/1GiB/掩码/一小时已有实际证据，完整PHY/一般适配器仍OPEN。来源及本机IP清单差异见[板卡资料交接](pds-board-references.md)与[板卡合同](../../board/mes2l676-200hp/board-contract.json)。

本版十条命令帮助已实际采集：[帮助记录](../../evidence/PDS_BOARD_DOCS/20261009-v1/pds-command-help.log)。帮助显示参数不等于各综合后端已验证，ADS继续采用本合同已通过形式。`add_constraint`本版帮助只列文件参数及`-copy`，不照搬旧教程的`-logic -sdc`；后续版本重新采集帮助并保留对应证据。

## 历史升级准备（2026-10-09）

以下保留当时升级候选与普通逻辑探针范围；其中“DDR必须准备新版”和待安装状态已被项目内原生1.10源码路径取代。独立新版对照仍可另行准备，默认入口保留rc3。

用户最新要求是 **rc3能完成所需任务就不升级**。已在现有rc3上完成PG2L200H/FBB676/-6的编译、ADS综合、映射、布局布线、时序报告和位流生成；Windows通过CMSIS-DAP HID连续三次读取`0x10603899`，与厂商BSDL中的200H IDCODE匹配（屏蔽器件版本高4位）。[本次预检查证据](../../evidence/T22_PRECHECK/windows-rc3-20261009-v1/manifest.json)记录全部阶段和边界。普通逻辑保持rc3及当前独立JSON合同，DDR的追加结果与所需准备如下。

这次离线工程仅含8位计数器，使用25MHz沙箱时钟及自动分配IO；生成位流**未用于板端下载**。其route后报告为setup WNS 27.023ns、最小hold slack 0.200ns、TNS/THS为0，时序模型为本版Pre-silicon。结果证明普通逻辑工具流程可运行，不能代替匹配PCB的引脚/电压合同、板上功能或200H HMIC_S支持。

Windows识别到的实际适配器是`ATK-HS-V2-CMSIS-DAP`（USB `04d8:00df`、序列号`ATK 20210914`）。COM9是同一USB设备的CDC串口，实际JTAG访问走HID接口；已测得CMSIS-DAP 2.0.0、JTAG能力开启、1024字节packet。串口115200/8N1可打开，被动监听3秒未收到数据；未发送串口命令或执行系统复位。该适配器的原生Fabric Configuration下载兼容性尚未验证，不能把本次HID读IDCODE记成PDS下载通过。

后续[实际IP探针](../../evidence/T22_VERIFY/board-ip-20261009-v1/manifest.json)已确认当前HMIC_S 1.3拒绝PG2L200H/FBB676（退出104，IPCompiler 0006），而100H对照成功；200H PLL 1.3和单口RAM 1.5仅完成生成检查。因此普通逻辑继续复用rc3，DDR必须准备官方支持的PDS/SP及匹配IP。没有修改全局安装或独立JSON合同。

候选仍为 **PDS_2022.2-SP6.7.1-ads-CentOS7.3-x64**；[官方下载页](https://www.pangomicro.com/resources/software/pds/)列示更新日期2025-06-19、大小2413.26M。官网要求登录，安装包尚未取得。[此前升级准备证据](../../evidence/PDS_UPGRADE/preparation-20261009-v1/manifest.json)保留当时状态；当前DDR准备状态为`REQUIRED_FOR_DDR_AWAITING_INSTALLER_AND_IP`。接收安装包后按下述步骤在独立目录验证，普通逻辑的rc3通过记录继续保留。

确有升级需要并取得安装包后按顺序执行：

1. 保存来源、安装包SHA256、包内版本与安装说明；在独立版本目录安装，保留rc3。当前账号无权写入系统安装目录，可先在用户目录完成候选验证。
2. 按实测版本、二进制与有效许可证建立独立候选JSON合同；冻结合同格式与现有合同一致，但`home`、`resolved_home`及hash来自新安装。先核验运行库、shell/Tcl许可和ADS；旧版可用许可证是否适用于新版须实际检查。
3. 用明确的候选`PDS_HOME`和`PANGO_LICENSE_FILE`调用现有绝对入口，执行`python3 scripts/check_pds.py --contract /absolute/path/candidate.json --synthesize`。`--contract`只读取候选合同，不改默认合同或`current`；有效环境必须与候选合同相符。重新采集该版命令帮助。
4. 单独验证`Logos2 PG2L200H FBB676 -6`的工程/ADS，并用实际HMIC_S包生成该器件配置、编译示例及核验许可；记录IP版本、生成器、配置和生成物hash。100H工具探针与200H DDR资格分别交付。
5. 工具检查通过后更新入口和独立工具合同，再从默认入口复跑检查；200H/HMIC_S的未完成项继续留在T22。匹配PCB约束、时序/DRC、全容量DDR和实物下载仍按各任务验收。

## 固定入口

| 用途 | 命令或路径 |
|---|---|
| 图形界面 | `/usr/local/bin/pds`，交互终端可直接 `pds` |
| Tcl自动化 | `python3 scripts/pds/run_interactive.py SCRIPT --log LOG --cwd RUN --marker COMPLETE`，经`/usr/local/bin/pds_shell`输入`source` |
| 快速诊断 | `/usr/local/bin/pds-doctor` |
| 工程开跑前检查 | 在仓库根目录执行 `make pds-check` |
| 重新验证 ADS 综合 | `make pds-check ARGS=--synthesize` |
| 全局稳定路径 | `/software/eda/pango/current` → `PDS_2022.2-rc3` |
| 公共环境默认值 | `/software/eda/pango/env.sh` |
| 可选环境模块 | `module load pds/2022.2-rc3` |
| 当前版本与校验值 | [独立 PDS 工具合同](pds-toolchain.json) |

入口属于系统目录，其他 Linux 账号可调用；不依赖 Jiang 的安装缓存、安装包目录或 shell 启动脚本。自动化任务即使没有登录 shell，也应使用 `/usr/local/bin/` 下的绝对入口。Bash/csh 登录环境另有 `/etc/profile.d/pango-pds.*`。旧终端需要刷新变量时执行 `source /etc/profile.d/pango-pds.sh`。

## 后续任务怎么运行

```bash
cd /home/Jiang/RISCV+NPU
make pds-check
# 新环境、升级或综合问题时，额外验证 ADS：
make pds-check ARGS=--synthesize

# 各卡创建独立工程和日志目录，示例中的 run-id 每次须更换：
repo=/home/Jiang/RISCV+NPU
run_id=your-new-run-id
mkdir -p "$repo/build/T22/$run_id" "$repo/evidence/T22/$run_id/logs"
python3 "$repo/scripts/pds/run_interactive.py" "$repo/path/to/your/run.tcl" \
  --log "$repo/evidence/T22/$run_id/logs/pds.log" \
  --cwd "$repo/build/T22/$run_id" --marker YOUR_TASK_FLOW_COMPLETE
```

`path/to/your/run.tcl`和`YOUR_TASK_FLOW_COMPLETE`是本卡脚本及其真实完成标记的占位符，不能直接照抄运行。本机rc3的`-file`曾退出0却未执行；当前工程通过解释器`source`执行，具体DDR构建/压缩/导出/实板步骤见[复跑约定](200pro-verified-pds-path.md)。工程的相对输入路径按运行目录解析；脚本应明确输入、输出和目标器件。使用各卡的 task-id，遵循 [证据合同](../plan/HANDOFF.md)，保存脚本、RTL、IP、约束身份及真实报告。不要在全局安装目录运行工程。

`make pds-check` 会核对二进制、许可证 SHA256、实际版本/build、有效环境及已获许可的 Tcl 完成标记；每次产生新的 `evidence/PDS_TOOLCHAIN/<run-id>/`，打印 `PDS_CHECK=PASS` 和证据路径，失败返回非零。可用 `ARGS='--run-id unique-name --synthesize'` 指定新运行。任务卡应引用本次 PASS 的证据路径；缺少工具、身份漂移、许可失败或超时均须先处理。可用 `make pds-check PYTHON=/path/to/python3` 指定 Python 3.7+；默认使用工程现有 `npu-python`。

PDS 某些许可失败会返回退出码 0，因此各卡的脚本还要输出自己的最终成功标记，并核对新生成的网表/位流和报告。不能只凭退出码或旧输出判断成功。当前 ADS 命令用法是 `compile -top_module <top>` 后执行 `synthesize -ads`；不要把 `-top_module` 或 `-write_verilog` 加在 `synthesize` 上。可复跑的最小脚本见 [smoke.tcl](../../scripts/pds/smoke.tcl)。具体工程仍按安装版帮助和文档选参数。

## 许可证与环境

默认 `PANGO_LICENSE_FILE=/software/eda/pango/licenses/pds-2022.2-bundled.lic`，这是用户所提供安装包中 `ip/ip.lic` 的原样副本。相关记录为 `permanent uncounted HOSTID=ANY`，本次 shell/ADS 验证不依赖 WSL 网卡 MAC，也不需要启动许可证服务。二进制、许可证签名和 MAC 均未修改。

另行取得的 `new_pds_00155dbab2cf.lic` 保留在原位置和全局许可证目录；其格式无法被此旧版 FlexNet 解析，会报 `-77,4`，当前不使用它。入口会把最初误设的全局旧默认路径自动切回有效副本；其他显式 `PANGO_LICENSE_FILE` 覆盖仍被尊重。自定义许可证或 `PDS_HOME` 与冻结合同不一致时，工程检查会失败，须先核实，不能直接改校验值使检查通过。

包装入口仅在 PDS 子进程中清除 `LM_LICENSE_FILE` 并设置本版 Qt 插件路径，避免继承其他 EDA 工具的服务器和插件；调用者的环境及其他工具配置不受影响。升级时保留版本目录和原证据，在验证后更新 `current`、模块及独立 PDS 合同。

## 已验证范围与证据

- [全局安装及许可验收](/software/eda/pango/installation/20261008T194150Z-bundled-license/receipt.json)：多账户、WSLg、ADS 综合和库依赖。
- [固定入口配置及备份](/software/eda/pango/installation/20261008T195600Z-stable-entrypoints/receipt.json)：共享环境、旧默认迁移和修改前备份。
- [本仓库首次完整检查](../../evidence/PDS_TOOLCHAIN/20261008T195905.535719Z-3788e864/manifest.json)：版本/校验值、Tcl 许可、ADS checkout、8 个寄存器及非空映射网表全部 PASS。
- [会话与多账户检查](/software/eda/pango/installation/20261008T195600Z-stable-entrypoints/shell-and-users.json)：非登录/登录/csh、Jiang/root/admin、旧默认及其他 EDA 环境隔离均 PASS；自定义无效许可证被正确拒绝。
- 本仓库的当前检查记录：`evidence/PDS_TOOLCHAIN/<run-id>/`。安装失败尝试另行保留，未覆盖。

综合探针使用安装包示例器件 `Logos2 PG2L100H FBG676 -6`，产生 8 个寄存器的网表。它仅验证工具与 ADS 授权，未验收项目板型、DDR/IP、约束、布局布线、时序、位流或硬件下载；探针未约束 I/O 的警告保留。GUI 需要 WSLg/可用显示会话。

全局路径和配置已持久写入磁盘，普通新会话无需重装或重新设置 MAC；本次未实际关闭/重启 WSL，以免中断其他 EDA 作业。重启后先跑 `make pds-check`，图形界面另验显示连接。

[T01 工具锁](toolchain-lock.json) 与 sim-v1 归档是历史快照，其中 PDS 尚不可用的记录保留；当前 PDS 状态以本合同及新证据为准。T00–T21 继续无需 PDS，T22–T33 的状态仍按 [登记表](../plan/tasks.json) 与各自板级验收条件推进。
