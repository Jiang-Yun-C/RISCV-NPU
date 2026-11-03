# OPT13 M4 因果预填充合同

`variants/opt13` 依次叠加冻结 B、OPT08、OPT09、OPT10；不合并 OPT07/11/12 数学/SFU开关，统一集成由 OPT16 负责。所有进程内结构的消费者重编译；CE描述符、completion、FP32 KV、group64量化与恢复顺序不变。独立 runner 为 `make opt13-transport`、`make opt13-runtime`、`make opt13-host`、`make opt13-numeric`；各次必须新 run-id。

会话容量为 M4；`nx_set_prefill_rows` 选择1或4，变化时 reset 撤销前缀/量化/logits。`nx_forward_block_v3` 同步消费1至所选宽度行，past 必须等于已提交长度，且 past+rows≤512。next为空时不执行 final norm/head；非空时只处理本块最后一行并返回原greedy结果。每层先按行写 K/V，RoPE 使用 past+r，attention 仅访问 [0,past+r]；14Q头按每7头映射一个KV头。成功后整个块提交有效长度；任何失败撤销 session/view/前缀，不发布部分输出，不承诺回滚物理字节。`nx_cache_view` 的有效长度是唯一合法读跨度，旧后缀不参与注意力。

`nxr_set_prefill_block` 在 idle/stopped 时设置同步回调和1/4行宽度；prefill按剩余行数处理尾块，只有末块请求head；decode继续调用单token forward。busy/active不能改配置。每个成功块推进相同数量的 prefilled/kv_length，超时检查覆盖完整调用；超时、取消和错误清空输出、时间戳并reset模型。旧无block回调路径保留。`NX_OPT13_M4=0` 编译回退到旧逐token调度，`NX_PREFILL_HEAD_SKIP=0` 保留每token完整诊断head。板端 `:verify` 显式关闭block回调，普通请求重新恢复设置。公开 `nx_forward` 仍提供调用者拥有的所有行完整logits；session内部只留一行。`nx_generate` 同样执行512总上下文上限：511输入至多1输出，512输入0输出，stop=3为总上下文停止，EOS优先级不变。

前缀prepare按所选宽度分块但不求head；restore沿用OPT09五类摘要及全部IDs，恢复绝对past与逻辑有效区，撤销量化借用/logits。长度相同但没有后缀的请求仍冷算最后head；改变执行配置须重新配置身份并prepare。准备、restore、首次冷费用分别计账。

## 生产内存布局

| 区域 | 地址 | 字节/容量 |
|---|---:|---:|
| 静态state（应用DDR BSS） | 链接器分配，16B对齐 | 32768；初始化按实际sizeof复核 |
| 原FP32 KV | a8000000 | 15728640，原640容量；请求仍上限512 |
| M4中间张量＋单行内部logits | ac000000 | 835072 |
| 独立诊断logits行 | ac0cc000 | 607744 |
| FP32 input staging | ba100000 | 77824，4×4864×4 |
| output staging | ba120000 | 607744；足够4×4864及单行完整head |
| Aq | ba1c0000 | 19456 |
| Sa | ba1c5000 | 1216 |

work 为 `4*(5*896+2*4864)*4+151936*4`；相对M1增加170496字节，避免四行完整词表缓冲。staging各自不重叠，prefix不分配第二份KV。state在DDR，不占SRAM栈。CPU函数的局部norm/attention/量化scratch按调用链计峰值，生产56KiB栈预算须随ELF复核。所有DMA依旧执行uncached/staging、fence、ACK和owner协议。

## 输出打包与物理端口

`M4_OUTPUT_PACK` 独立控制。M>1、无audit、输出stride为16字节倍数时，每个token累积相邻4列到一个128位寄存器，四个token缓冲共64字节；按token依次写回。短列尾仅写有效32位，非对齐stride和audit走原标量路径；M1保留原打包。跨M块不混用寄存器；submit/reset/drain丢弃未发出的暂存，已接受DMA仍按原流程排空。输出只在完整成功、1024周期native drain、completion acquire/ACK及owner释放后有效。

scratch仍是单个128位同步RAM物理端口。DMA写与控制器访问互斥，不能启用DMA/计算重叠；“重叠开”必须拒绝或明确退回同一串行执行。时间模型按load+compute+write+other求和，restore为嵌套观察。没有虚构双银行或使用max(compute,transfer)。输出寄存器不会增加scratch端口。新增寄存器/控制的集成资源、PDS时序/CDC由OPT16验收，本卡不据此提高频率。

## 数值与证据边界

完整IDs和独立逐token golden先于候选运行冻结。真实CPU小整网保持两层完整图和14:2 GQA，完整K896/K4864生产驱动/CE64/guard/native另分层验证；完整0.5B主机累计不冒充整网RTL。未来位置/KV偏移负例必须被独立oracle检出。各层保存XML、检查数、source/fixture/tool/VPI身份、seed1/7/19及1复跑、代表波形和实际失败；零测试/缺XML/坏golden/持续复位拒绝。比较M1/M4、prefix冷/热、pack开/关；decode差异和未覆盖范围单列。125MHz仅为数字周期模型基准，整网TTFT/decode及用户可见TTFT未完整测量时保持null。实物/JTAG/UART/SD/烧录统一后置OPT17。
