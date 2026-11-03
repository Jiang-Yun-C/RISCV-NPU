# 标准200Pro+已验证工程路径与下游复用约定

2026-10-12工具接续：全局PDS2024.2/build178169已并行注册，后续新实现采用 `make pds2024-check` 及独立合同/收据；rc3默认和T23原项目候选绑定均保留。新版PnR参数、split报告、同版模型/网表、100kHz CRAM和连续UART验收经验已写入[T24–T33交接规则](pds2024-t23-lessons.md)。下文v7/rc3经验继续作为冻结基线复跑路径。

2026-10-12最新：**T23 DONE**；当前新适配器镜像实测1GiB、32字节掩码、3999.985秒零错误压力及六种独立带宽通过。实际CPU/Coral竞争按用户范围交T24联验，完整PHY/板外时序交T30；以下较早状态按记录日期理解。 [验收报告](../reports/T23.md)。

2026-10-12最新：**T22平台范围DONE**；正式验收10项PASS。当前v7下载及COM10 1GiB/32byte masks新增8轮通过，组件82,817检查通过。沿用rc3，当前保留v7；完整PHY/板外DDR时序交T30，T23新适配器及T24政策保持各自范围。[T22结果](../reports/T22.md)。后文旧ACTIVE、COM10缺失、暂缓及“当前最小镜像”按历史日期理解。

2026-10-12 最新重试：冻结 native110-v7 大镜像以 100kHz CRAM 下载成功，533.156 秒；原生 DONE 比对和后续只读均为 DONE1、STATUS=`0x81ffca0`。30 次 SAMPLE 显示 INIT/CPD/PLL 高、错误指示低、心跳翻转。当前保留 v7，Flash 未写。COM10 缺失，本次没有新的 UART 容量/压力计数；完整 PHY/板外 DDR 时序仍 OPEN，T22 ACTIVE。[本轮报告](../reports/jtag-large-retry-20261012.md)。后文“当前最小镜像”及暂缓描述属于相应历史日期；恢复范围仅为本次 T22 v7 重试。

2026-10-11：T23 离线适配器、10组 VCS+cocotb/9,994,302检查、native控制器及综合网表联测和 PDS ADS 通过。T23 ACTIVE，T22 实物/完整PHY与新适配器实板容量/压力/独立带宽仍 OPEN；当前板测暂缓有效。见 [T23报告](../reports/T23.md)。

2026-10-11 更新：[T22 本轮报告](../reports/T22.md) 记录组件/最小工程重建、当前配置复验和时序覆盖审计。当前板上是已通过的最小镜像；最新 v7 重放未进入 DONE，完整 PHY/IO 时序仍 OPEN。用户报告杜邦线 JTAG，待短线对照；板载 UART 不能直接下载位流。下列 v7/一小时结果是 2026-10-10 冻结窗口。未知丝印按用户要求保留既有记录。

2026-10-10，适用于 **MES2L676-200HP（200Pro+）V1.2，Logos2 / PG2L200H / FBB676 / -6**。T22–T33从本页接收已经实现的工程经验；逐卡工作和正式验收仍以任务卡及[登记表](../plan/tasks.json)为准。

## 原厂200H资料位置

[原始完整ZIP](../../盘古200Pro+开发板（MES2L676-200HP）配套资料.zip)位于工作区根目录；[已解压原件](../../build/T22_VENDOR/standard-200pro-20261010-v1/vendor/)位于`/home/Jiang/RISCV+NPU/build/T22_VENDOR/standard-200pro-20261010-v1/vendor`，按需提取563文件。原厂手册、DDR `.pds`/`.idf`/FDC/生成源、硬件SCH/PCB/点位及IP包的逐文件位置/hash见[资料清单](../sources/logicmatrix/standard-200hp-materials.json)，关键路径和逐卡对照顺序见[资料交接](pds-board-references.md#200h资料包位置与关键原件)。

原厂参考与本地通过镜像分别取原件目录和[v7冻结输入](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/inputs/build/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/)。新实验在独立目录进行；原件目录失效时核对ZIP SHA，按archive-import.json提取所需前缀并校验，不改旧原件或冻结证据。

## 已经实现的基线

保留全局 **PDS2022.2-rc3 / build113398** 和安装内实际 **HMIC_S1.3生成器**。项目内使用原厂SP6.4 / build146967生成的**原生200H / HMIC1.10源码**，在rc3重新编译、综合、布局布线和生成位流。这条路径已在2026-10-10实板窗口通过校准、数据、全容量和一小时测试。

| 可继承的结果 | 实测范围与证据 |
|---|---|
| 安装完整性 | 47,847个文件与原始tar完全一致，六分卷SHA通过；目录1.7与实际生成器1.3的差异来自原包。[安装审计](../../evidence/T22_INSTALL/rc3-hmic-selection-20261010-v1/manifest.json) |
| 器件和源码 | 92份原厂生成源中91份保持原字节；只更换example顶层，并加入项目BIST/UART/观测源。83个有效pad中73个DDR/参考时钟pad匹配。[源与引脚核查](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/source-pad-check.json) |
| 实现 | rc3从源构建完整通过；Slow/Fast各5类时序表通过。完整PHY覆盖仍OPEN。[时序门禁](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/timing-gate.json) |
| 配置和校准 | 原生优化压缩、100kHz JTAG写入易失CRAM，DONE1、INIT1、训练重试0，Flash未写。[v7冻结清单](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/manifest.json) |
| 容量和掩码 | **1,073,741,824字节（1GiB）**地址/互补全范围写读、32个单字节strobe及独立读回；初始150秒7轮、674个CRC正确帧、错误/重试/丢帧0。[独立评估](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/functional-summary.json) |
| 一小时 | 同一镜像独立窗口3664.812秒，新增192轮、16,467帧，错误/重试/CRC错误/丢帧0；结束12次只读ID/DONE复检通过。[压力冻结清单](../../evidence/T23_NATIVE/native110-full1g-stress-20261010-v1/manifest.json) |
| 当前测试负载速率 | 写请求payload **56.07MB/s**、读有效payload **56.25MB/s**；包含1024周期保守写后等待、遍历和掩码测试。[压力评估](../../evidence/T23_NATIVE/native110-full1g-stress-20261010-v1/functional-summary.json) |

速率采用十进制MB/s，只描述该BIST负载；峰值DDR、CPU/NPU并发和整网应用性能另测。T22保持ACTIVE，T23–T33保持DEFERRED。完整PHY/板外I/O时序、通用适配器、多ID、物理按键复位、掉电冷启动和实际DDR/Flash芯片丝印仍待验收；MS7210是资料中的HDMI发送芯片，不能用作DDR型号。

## 工具与IP选择经验

1. **延续rc3与项目内原生1.10源码。** 官方[HMIC_S V1.14](../sources/logicmatrix/hmic-s-guide-v1.14.pdf)的PG2L200H最低SP1.2要求保留为官方版本边界；本项目从已生成源码重建的实测结果单独登记。默认流程不强制升级、重装同一包或修改全局支持列表/许可证。
2. **从生成源码重建数据库。** rc3不能直接读取原厂SP6.4旧路由ADF，曾报DB-4001。干净构建不要求在rc3重新生成HMIC1.10；安装内1.3生成器原生拒绝200H（退出104/IPCompiler0006）。100H生成成功不能替代200H IP，旧1.3移植/v8容量候选不再作为下游基线。
3. **保留通过镜像的观测结构。** native110 v5能配置和校准，但首读失败；从成功v6后重放同一v5仍失败。加入观测的v6和继承它的v7通过，具体综合/布线/物理原因尚未隔离。[受控重放](../../evidence/T22_NATIVE_REPLAY/native110-v5-from-v6-20261010-v1/manifest.json)。不得把删除探针当成无影响清理；RTL/IP/FDC/探针/实现参数改变后，重新检查时序、校准、短数据、全范围/掩码及一小时。
4. **退出0之外检查执行和新产物。** 本机rc3的`-file`曾退出0却没有执行；使用[run_interactive.py](../../scripts/pds/run_interactive.py)向解释器输入`source`，同时核查所有阶段标记、错误日志及本轮报告/产物。完整调用合同见[pds-toolchain.md](pds-toolchain.md)。

## 从成功工程准备下一次实现

每轮建立新的`build/<task>/<run-id>/`与`evidence/<task>/<run-id>/`，失败轮次也保留。恢复源时从[v7冻结清单](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/manifest.json)校验hash，再取其中`inputs/build/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/`的`sources/`、三个项目`ddr_*.v`、`native110.fdc`和`flow.tcl`。重建目录只接收输入，生成旧数据库/报告不作为本轮输出。

把`flow.tcl`中的原工程绝对路径改为新目录，核查每个`add_design`与`add_constraint`；重新生成本轮输入清单和hash，记录父清单及差异，不能照搬旧`full-inputs.json`冒充新输入。标准源码基线有91份未改原厂文件，新顶层或适配器另列；FDC的有效最终属性按已验收pad表核对。v7执行的FDC有三处旧重复赋值及最终覆盖，规范化这些赋值也要保存差异并复验。

原生DDR工作点为27MHz参考、1000MT/s、core/reset125MHz，row15/column10/bank3/x32；D18参考、N3/N2时钟pad、DQ/DQS/DM映射及宏位置从冻结FDC和[板卡合同](../../board/mes2l676-200hp/board-contract.json)接收。不要沿用旧1.3实验的93.75MHz假设。接入SoC时先CPU+DDR，再加入Coral；初始化完成前禁止发用户事务，超时/训练失败向软件报告。

以下命令用于**已准备且路径核对的新test_ddr工程**。`PDS_RUN`、`PDS_EVIDENCE`、`PDS_STAGE`均需指定为本轮新建的绝对路径，前两者已存在，stage已建好；日志不得指向冻结目录。新SoC顶层须另建等效门禁，现有资格脚本含test_ddr、固定SBIT长度和BIST假设，不能直接验收任意工程。

```bash
make pds-check
python3 scripts/pds/run_interactive.py "$PDS_RUN/flow.tcl" \
  --log "$PDS_EVIDENCE/pds-flow.log" --cwd "$PDS_RUN" \
  --marker NATIVE110_FLOW_COMPLETE
python3 scripts/pds/qualify_native110_artifacts.py \
  "$PDS_RUN" "$PDS_EVIDENCE" --timing-only
python3 scripts/pds/prepare_native_compressed_bitstream.py \
  "$PDS_RUN" "$PDS_RUN/native-compressed" --top test_ddr
python3 scripts/pds/run_interactive.py "$PDS_RUN/native-compressed/flow.tcl" \
  --log "$PDS_EVIDENCE/native-bitstream.log" \
  --cwd "$PDS_RUN/native-compressed" --marker NATIVE_INPUT_ADF_BITSTREAM_COMPLETE
```

阶段顺序为`compile -top_module test_ddr` → `synthesize -ads` → `dev_map` → `pnr -fix_hold_violation_in_route TRUE` → `report_timing` → `gen_bit_stream`。检查COMPILE/ADS/MAP/PNR/TIMING/BITSTREAM/FLOW全部COMPLETE；保留资源、DRC、警告审查和覆盖缺项。Slow/Fast两角各Setup/Hold/Recovery/Removal/Minimum Pulse Width都要检查，不能只检查setup/hold。v7最小setup0.846ns、hold0.099ns、pulse0.035ns仅作旧结果参照。

具名DQS启动、IOL启动、DQS训练、CPD_RSTN四条复位网的8ns datapath上限，须绑定[实际复位/READ审计](../../evidence/T22_NATIVE_RESET/native110-125-20261010-v5/reset-windows-audit.json)和[实际CPD控制审计](../../evidence/T22_NATIVE_RESET/native110-cpd-20261010-v4/cpd-window-audit.json)；对象或逻辑改变后重新审计。DDC/WCLK至gopIOL/OSERDES传播、板外DDR I/O delay和pre-silicon模型覆盖仍OPEN。完整时序和CDC/RDC不能由实板零错误代替，也不能用整域false path/clock groups消除缺项。

## 压缩、SVF与上板记录

压缩输入必须是**本轮**`place_route/test_ddr_pnr.adf`，不是`.prr.db`或SP6.4旧ADF。[prepare_native_compressed_bitstream.py](../../scripts/pds/prepare_native_compressed_bitstream.py)使用原生`-compress_bitstream TRUE -optimize_compress TRUE`，并生成同路由未压缩参考。SVF由当前Fabric Configuration的`cdt_cfg_shell`解释器`source`导出；以实际执行的[v7 convert.tcl](../../evidence/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/inputs/build/T22_NATIVE_IMPL/rc3-native110-20261010-v7-full1g/native-compressed/convert.tcl)为模板，所有输入输出改为新目录：

```tcl
cfg_add_device -file {/absolute/new-run/native-compressed/optimized-candidate.sbit}
cfg_one_step_create_svf -device_index 0 -svf_property 40426 \
  -sbit {/absolute/new-run/native-compressed/optimized-candidate.sbit} \
  -svf_file_name {/absolute/new-run/native-compressed/native110.svf} \
  -jtag_chain 0 -not_create_pef TRUE -flatten TRUE
puts NATIVE110_SVF_COMPLETE
exit
```

Fabric运行需保留本机工具合同中的Qt离屏、动态库和许可证环境，输出保存为`native-svf.log`。然后执行门禁：

```bash
python3 scripts/pds/qualify_native110_artifacts.py "$PDS_RUN" "$PDS_EVIDENCE" \
  --artifacts "$PDS_RUN/native-compressed" --stage "$PDS_STAGE" \
  --data-diagnostic --requested-hz 100000 --test-window-bytes 1073741824
```

门禁核对同路由未压缩配置主体、压缩SBIT与SVF完整payload反位序、原生ID/CRC/JRST/DONE命令；只把`FREQUENCY 1E6 HZ`改为`1E5 HZ`。当前压缩镜像用100kHz通过；原厂未压缩镜像曾在1MHz通过，不能推广为所有1MHz下载均失败。SVF内频率会覆盖主机`--hz`，两者都须核对。

已通过v7的SBIT SHA256为`1245a1ea797bc89d8da69d67e6d61ff5520a694f4e548d280b926cee436d680d`，100kHz SVF SHA256为`7fe34dd1b9dc362a765c657fc799615d2d31ffbe57f0ad928b03384aec3c4a0f`。这对文件是DDR诊断恢复基线，不是应用演示镜像；泛用Windows stage文件名可能被后轮覆盖，恢复时只取冻结副本并核hash。

接续先用[windows_cmsis_jtag.py](../../scripts/pds/windows_cmsis_jtag.py)省略`--svf`只读核对ID/DONE；既有适配器为ATK20210914、IDCODE`0x10603899`。检查本轮要编程的文件身份后执行CRAM下载。UART采用COM10/CP2102、115200/8N1、DTR/RTS关闭、仅接收；COM9是JTAG适配器串口。C24/B24诊断UART和A20初始化灯已被使用，应用改用这些引脚前须明确诊断迁移方案。

新下载前启动[windows_ddr_uart.py](../../scripts/pds/windows_ddr_uart.py)：`--protocol d2d1 --await-boot --stop-on-test-failure --seconds 900 --after-first-frame 150`，等待CAPTURE_READY后才下载，核对新sequence0。同镜像继续一小时可省略`--await-boot`，使用`--seconds 3900 --after-first-frame 3665 --stop-on-test-failure`。保存完整命令、`uart.bin/json`、`board.json`和本轮`program-inputs.json`；capture退出0仅表示采集完成，需独立分析：

```bash
python3 scripts/pds/analyze_ddr_capacity.py \
  --capture "$PDS_EVIDENCE/uart.json" --raw "$PDS_EVIDENCE/uart.bin" \
  --board "$PDS_EVIDENCE/board.json" --inputs "$PDS_EVIDENCE/program-inputs.json" \
  --out "$PDS_EVIDENCE/functional-summary.json"
```

D2D1帧260字节，前256字节CRC32；word49=`0x00010001`才是v7布局，word47为完成轮数，word48的bit0/1/2为全范围/掩码/失败，word50为首错字地址。旧v6帧或原厂PLL标志不代替项目通过。分析核对真实编程hash、原始帧、时钟和连续计数；32位流量逐帧展开溢出，64位core周期连续；一小时以已通过状态后连续≥3600秒的零错误/重试/丢帧窗口登记。

## 用户口与下游执行边界

从[ddr-user-port.json](../../board/mes2l676-200hp/ddr-user-port.json)接收实际接口：256位数据/32bit strobe，28位**4字节字地址**，LEN+1；LEN15为16拍/512字节，LEN0为1拍/32字节。ROW[27:13]/BANK[12:10]/COL[9:0]，BIST从128字对齐位置发burst，不跨column边界。simplified AXI没有WVALID、B、RREADY，WREADY是请求数据；当前只验证ID0、单在途、WLAST/RLAST和1024周期写后等待。

T23/T24需显式实现字节地址换算、项目/Coral到256位的数据宽度转换、ID映射、burst拆分、strobe、反压/复位错误及Cache所有权。保守等待不是一般AXI写完成语义，必须证明“已写回且对下一接收者可见”，才能返回应用完成。非零ID、多个在途及CPU/NPU竞争不能从BIST推断。

T24负责最小CPU+DDR/Coral与T16同输入复现；T25复核1GiB预算、实物SD装载与完整模型；T26核接线并保留诊断；T27测应用真实带宽/瓶颈；T28每项优化保留回退并复验；T29测应用长稳/故障/冷启动；T30闭合最终时序/CDC/RDC及CPU评测；T31同身份正式质量/性能对照；T32干净重建并保留来源；T33冻结实演和恢复步骤。各卡已写入对应执行项和验收项。

长任务沿用工作区异步规则：空`write_stdin`等待≥180000ms，通常300000ms；`functions.wait`≥180000ms；外层`functions.exec`等待至少比最长嵌套等待多30000ms。非空交互输入不套长等待；不要仅为报告“仍运行”唤醒。结束只清理本轮拥有的进程，保存最终只读结果、原始日志和不可变清单。

相关入口：[新路径报告](../reports/ddr-native110-rc3-20261010.md)、[DDR资格报告](../reports/ddr-qualification.md)、[交接规范](../plan/HANDOFF.md)、[任务索引](../plan/TASK_INDEX.md)。
