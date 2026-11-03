# 完整Qwen推理、NPU算存、中断与中文设备控制实验

本轮直接使用保留的 Demo V6 实板，完成真实模型新请求、三组冷/暖前缀配对及固定中文控制测试。复用既有完整局部API、异常回归和原生Fabric波形，不新增CPU Cache/BTB/SRAM消融，不重跑PDS或整网RTL。各组证据和版本分别绑定。

实际新增完整模型请求 18 次；中文控制完成 10 条。严格预登记的意图/提交条件匹配 8/10。冷/暖配对三组均为相同输入、相同24-token上限、相同输出ID、相同EOS；板内首token平均下降 52.289%。

## 1. 完整模型真实推理（实板）

模型为完整24层 Qwen2.5-0.5B-Instruct 的既有 W8 部署，实际模型SHA256 `f55c1a1efd0188a3b792e695fb9f404080f0ffd10cae44d1831b595af6b37f71`。V6源码CID `3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a`；CPU/CE125MHz、UART115200、同次配置与同次认证模型。每次请求均实际执行生产Prefill/Decode，原协议检查器验收、CE调用>0、CPU/fallback调用=0，未调用主机回复缓存。

三条固定输入为“请只回答：你好。”“请只回答：欢迎。”“请只回答：收到。”，各执行冷、暖两臂。每组冷臂前仅用`:prefix 1`失效KV；暖臂只复用已计算的21-token系统前缀，仍执行余下prompt及全部新decode。相同问题重复是新模型计算，不是回复播放。输出分别为“你好。”“欢迎”“收到”，生成数含EOS，均未达到24-token上限。

| 指标 | 冷前缀 n=3，均值 [最小, 最大] | 暖前缀 n=3，均值 [最小, 最大] |
|---|---:|---:|
|板内首token / s|68.262892 [68.261579, 68.264329]|32.568672 [32.568188, 32.569370]|
|主机可见首字 / s|68.302171 [68.300434, 68.303745]|32.606535 [32.604501, 32.610361]|
|Prefill / s|68.203802 [68.202502, 68.205222]|32.510577 [32.510102, 32.511166]|
|Decode / step·s⁻¹|0.278465 [0.277707, 0.278844]|0.278455 [0.277711, 0.278828]|
|请求至READY / s|73.697606 [72.480947, 76.129385]|38.003704 [36.786817, 40.436334]|

本轮全部完整请求中，实测最低板内TTFT 32.568188s、最低主机可见首字 32.604501s、最短请求至READY 36.786817s；这些是各指标的最好单样本，不能拼接成一条不存在的请求。组均值和所有样本保留于[INFERENCE.csv](../../evidence/FINAL_EXPERIMENTS/20261103-v1/INFERENCE.csv)。

Decode定义为`(generated−1)×125000000/decode_ticks`，计入生成EOS的那次后续forward，不计由Prefill产生的首token；不能把generated直接除decode时间。短回答只有1–2个后续decode步，不代表长上下文稳态吞吐。可见首字由原生产解码器首次可见preview的UART接收时间确定，起点为本次write前的主机单调时钟；不含浏览器绘制时间。整请求时间至完整READY，包含UART、统计输出及协议尾部；未混用板内计数和主机时钟。

![完整模型推理性能](../../evidence/FINAL_EXPERIMENTS/20261103-v1/figures/04-full-model.png)

中文控灯请求同样执行完整模型，采用固定生产控制system prompt（65-token可复用前缀）及原128-token上限，条件不同，逐条列出，不与普通文本冷/暖组混算。

## 2. NPU与分层存储（复用成对RTL完整局部API）

| 完整局部API | 原版周期 | 五项合入周期 | 周期下降 |
|---|---:|---:|---:|
|att-len33|6,336,397|5,407,804|14.654906%|
|att-len45|8,037,745|7,115,333|11.476005%|
|att-m4-past29|23,275,971|19,570,751|15.918648%|
|swiglu-m1-n896|2,588,144|2,515,137|2.820824%|
|swiglu-m4-n896|12,768,955|8,704,845|31.828055%|

![NPU算存优化](../../evidence/FINAL_EXPERIMENTS/20261103-v1/figures/03-npu-memory.png)

数据为历史CID85c45c…与c8a62f…在公共夹具、相同合成输入/权重、seed1/max_delay3、原native1024下的完整局部API，含CPU量化、驱动、提交、供数、完成和ACK。实际CPU输出逐位检查通过。最大31.828055%只属于N896/M4 SwiGLU→down；普通M1 linear另有0.70–1.47%回退，全部11对见[原始性能表](../../evidence/FINAL_EXPERIMENTS/20261103-v1/NPU_REUSED.json)。不相加五项百分比，不推算完整请求加速。

该历史五项候选的125MHz PDS时序未通过（Setup/Slow−6.927ns），因此这里报告RTL周期收益。当前实板V6是后续不同CID，其最终PDS通过结果见第5节；不能用当前实现签核替换历史候选时序，也不能将历史局部百分比当成本轮实板前后对照。

## 3. 异常与完整中断路径（复用RTL及实板Fabric）

| 检查项 | 已验收结果 | 证据 |
|---|---|---|
| 机器CSR、WARL、64位计数/inhibit | 定向RTL PASS | csr-r1、csr-WARL-r2/CHECKS |
| 同步异常、精确store错误、MRET | 17实例，cause0/1/2/3/4/5/6/7/11，PC/MTVAL/不退休检查PASS | CPU_EXCEPTION_EXTENDED_CHECKS、CPU_W_EARLY_CHECKS |
| 同步异常优先；MEI>MSI>MTI；WFI唤醒 | CPU输入级RTL PASS | CPU_EXCEPTION_EXTENDED_CHECKS；SoC MSIP仍绑0 |
| 成功store与中断竞争 | B→退休→IRQ，无重复副作用，MRET续行PASS | cpu-success-store-IRQ-r1/CHECKS |
| NPU完成→ISR登记→主流程消费→completion ACK→owner释放 | 同次实板原生Fabric窗口PASS | npu.txt/vcd；WAVEFORM_VALIDATION |
| UART取消→ABORT→REQUEST_END→READY→下一真实请求 | 原实板UART/Fabric证据及本轮新采样分别绑定 | 旧cancel窗口与本轮原始UART |

![实板NPU中断波形](../../evidence/FINAL_EXPERIMENTS/20261103-v1/figures/05-native-interrupt.png)

图中取自真实1024×260bit原生PDS采集：pending样本256、ISR事件0x101样本319、主消费0x201样本550、ACK地址0x10003028的AW/B样本557/558、owner释放560。TU4导致样本非等间隔，横轴只能是存储样本号；原VCD的100ns不是实际时间。pending W1C清除未在窗口出现、共享ACK WDATA未布探针，完整物理ISR时延仍UNKNOWN。CPU的三类机器中断优先级不能误写成实板三源同时pending。

## 4. 中文工业设备控制（实板新请求）

下表测试前已固定，使用`:actm 45 <中文>`直接进入生产模型，未走主机快捷开关或缓存工具包。完整EOS→JSON全程序校验→CPU提交→状态读回；掩码45对应LED0/2/3/5。正常指令须正确JSON、一次store及正确读回，未知目标须明确reject且零store。否定句采用更严格的“保持状态、不提交新动作”标准，冗余同值store单独暴露。

| 编号 | 中文输入 | 模型完整输出 | CPU回执/写次数 | 严格符合预期 |
|---|---|---|---|---|
|C01|打开灯|`[["led",1]]`|OK / 1|是|
|C02|把灯打开|`[["led",1]]`|OK / 1|是|
|C03|关闭灯|`[["led",0]]`|OK / 1|是|
|C04|把灯关掉|`[["led",0]]`|OK / 1|是|
|C05|请打开LED灯|`[["led",1]]`|OK / 1|是|
|C06|关闭LED灯|`[["led",0]]`|OK / 1|是|
|C07|打开不存在的设备|`[["reject","UNSUPPORTED"]]`|UNSUPPORTED / 0|是|
|C08|打开电机|`[["reject","UNSUPPORTED"]]`|UNSUPPORTED / 0|是|
|C09|不要开灯|`[["led",0]]`|OK / 1|否|
|C10|不要关灯|`[["led",0]]`|OK / 1|否|

固定矩阵严格匹配 **8/10**。不删除不符合项，不用CPU校验通过代替模型意图正确；JSON合法性、安全门禁、语义和实体观察分别记录。逐条时间、session、原始程序、action值见[CONTROL_RESULTS.json](../../evidence/FINAL_EXPERIMENTS/20261103-v1/CONTROL_RESULTS.json)。

![系统闭环实测记录](../../evidence/FINAL_EXPERIMENTS/20261103-v1/figures/06-control-loop.png)

实体LED观察见USER_OBSERVATIONS.json；未取得观察答复的场景仍标NOT_OBSERVED。图6为真实测量记录的排版，不是板卡照片，未生成或伪造实体图像。若未另附现场照片，原建议的“实体照片”一项仍缺失。

## 5. 最终FPGA资源与时序（当前部署V6）

| 项目 | 最终PDS结果 |
|---|---:|
|LUT|72,889|
|FF|50,068|
|DRM|137个物理site|
|APM|43|
|顶层IO|87|
|Fabric|260通道×1024样本|
|系统/CPU/CE目标|125MHz / 8ns|
|Setup/Slow WNS|0.000ns（报告精度）|
|Hold/Slow / Hold/Fast|+0.062 / +0.041ns|
|Slow/Fast共十张时序表|全部PASS|
|最终route未布通/过用|0 / 0|

PDS2024.2/build178169，PG2L200H/FBB676/−6，同一已部署sbit SHA256 `c4b5c641860d91f6c9aecb16392cc996428a63d26a5bc6d544b36a98f34ff41e`。DRM按实际物理site报告，不与ADS的36K等效混用。原约束覆盖仍有36个no_input_delay、81个no_output_delay；本表不扩展为全面PHY/CDC/DRC或生产GO。完整十表摘要见[FPGA_SUMMARY.json](../../evidence/FINAL_EXPERIMENTS/20261103-v1/FPGA_SUMMARY.json)。

## 范围、失败及复验

CPU正式CoreMark和既有CPU波形原样保留；本轮无新增CPU消融、综合/PnR/位流、CRAM、模型装载、SD/Flash/NVM写或FPGA reset/reload。历史主配置累计完成10/尝试11、模型触发9不变。T27正式OPEN、production_GO=false的整体范围保持。

首条样本后的主机校验因PATH无Node停止，原失败日志保留；改用已固定Node后验收原样本并只续行未执行的暖臂，无重发。最初展示台空闲接管返回HTTP503，但事后核实owner已清除、串口锁已释放，本轮独占打开成功；不据此重发模型、重配或重置。其余失败/原件见FAILURES.md。最终UART句柄和板锁必须由FINAL_STATE.json确认关闭。

数据目录：[本轮完整证据](../../evidence/FINAL_EXPERIMENTS/20261103-v1/)。只读入口：`make final-experiments-verify`。验证不打开硬件、不重启任何历史或本轮执行器。

现场观察：用户在开灯与关灯检查时分别回复“等都没问题放心吧继续测就可以”“灯没问题不需要再文了”，登记为人工报告灯正常；没有据此推断未观察的后续用例或光学时延。

本轮并发补测：先由CPU定时器启动250ms翻转的灯效，期间完整真实模型请求以EOS结束；随后匹配session执行prefill取消，完整CONTROL accepted/ABORT/REQUEST_END/READY通过。取消后的第一条UART命令就是新真实推理，READY至该命令主机间隔 0.428762s，新请求完整EOS/CE执行/零fallback通过。之后停止灯效并确认OFF/owned45/遥测0x307；未reset FPGA或重新装载模型。

计数口径：cpu_calls=0是该后端统计字段，不表示CPU没有执行工作；分词、CPU算法段、驱动、IRQ及设备控制仍由CPU承担。主机任务文件曾在写完前被工作器读到，第二条控灯后采集器在下一查询TX前退出；原件保留，后续新会话改为原子发布并仅执行未完成项，未重发任何模型请求。

正确率分组：正常开关灯6/6、未知设备拒绝2/2、严格否定无动作0/2。“不要开灯”实际写off一次，最终电平仍符合保持关闭；“不要关灯”在预置ON后实际写off一次，是明确语义/状态错误。CPU准确执行了合法JSON，但没有纠正模型的否定意图错误。不能写“10条全部正确”或把主机快捷路径的否定过滤成绩替换这轮真实模型结果。
