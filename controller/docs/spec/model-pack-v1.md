# T10 模型包 v1

version=`model-pack-v1`；producer=T10；consumers=T11/T12/T14/T15/T18/T19。
数值保持 [T05](numeric-v1.md) 的 `w8a8-g64-fp32-v1`，输入为
[冻结适配模型与原始 tokenizer](application-v2-model-lock.json)。不使用未适配 base 权重。
物理包 `layout_id=0x1001`，区别于 [T08](backend-contract-v1.md) 的逻辑 view ID 1。
T08 原能力快照中的 `pack_layout_id=null` 保留原意：它未定义物理包；新消费者按本合同
及 [T10 配置](../../configs/t10-pack.json) 选择 adapter，不将该 null 当作包的物理 ID。

## 物理顺序与数值

单文件 `.nxpack`，所有多字节整数和 FP32 均小端。每个有效载荷起点及区域相对地址
按 64 bytes 对齐；间隙必须是零。文件中依次为：共享 embedding、每层 input norm、
Q/bias、K/bias、V/bias、O、post norm、gate、up、down、final norm、head 两个别名目录项、
metadata、按文件名字典顺序排列的原始 tokenizer 资产。

| kind | entry layout_id | 逻辑与物理存储 | 字节数 |
|---|---|---|---|
| 1 | `0x1001` | W8 逻辑 `[N,K]`；物理 `[N,ceil(K/64),64]`，末组零填充 | `N*ceil(K/64)*64` |
| 2 | `0x1002` | FP32 scale `[N,ceil(K/64)]`，行优先 | `N*ceil(K/64)*4` |
| 3 | `0x1003` | FP32 bias/norm `[N]`，无量化 | `N*4` |
| 4 | `0x1004` | 原始 UTF-8/JSON/文本 bytes，无字符串终止符 | 目录 length |

W8 行 stride=`ceil(K/64)*64`，组 stride=64，列 stride=1；scale 行 stride=`G*4`，组 stride=4。
T07 的 `row → group → token` 微内核能直接按此顺序读取本模型的 K=896/4864；不在板端转置、
整模型解量化或重排。M、N 分块不会改变包。T14/T15 以合法目录 view 构造 T08 逻辑张量，
按 `W_base+row*Kp+group*64` 和 `scale_base+(row*G+group)*4` 寻址；N 尾块按真实行数执行。
格式支持通用 K 尾组，但 T08 当前后端不支持 K=65，必须返回 `NX_EUNSUPPORTED`，不能
把小包解析通过当作该形状已经能在 Coral 上执行。

权重值范围 [-127,127]；scale 有限、非负，非零必须为正常 FP32；零组保存 +0，且该组 q
必须全零。K padding 为零。bias/norm 有限。量化与逐组 FP32 恢复遵守 T05，不允许修改容差。
embedding/head 仅保留一份 W8 和一份 scale；两项 head 目录显式指向 embedding，逐字节
一致，禁止其他名称别名、别名链、自环、部分重叠或未经声明的完全重叠。

## 固定文件头：160 bytes

| offset | 类型/长度 | 含义 |
|---|---|---|
| 0 | bytes[8] | `NXW8PK1\0` |
| 8 | u32 | version=1 |
| 12 | u32 | header_bytes=160 |
| 16 | u32 | endian marker=`0x01020304` |
| 20 | u32 | pack layout_id=`0x1001` |
| 24 | u32 | group_size=64 |
| 28 | u32 | alignment=64 |
| 32 | u32 | directory entry count，范围 1..4096 |
| 36 | u32 | entry_bytes=256 |
| 40 | u64 | directory_offset=192 |
| 48 | u64 | data_offset=`align64(192+count*256)` |
| 56 | u64 | 精确文件大小，包括末尾对齐；拒绝多余或缺少字节 |
| 64 | bytes[32] | 目录全部 count*256 bytes 的 SHA-256 |
| 96 | bytes[32] | `[data_offset,file_bytes)` 全部载荷和对齐的 SHA-256 |
| 128 | bytes[32] | 头部 `[0,128)` 的 SHA-256 |
| 160 | bytes[32] | 零 padding，非头部哈希的一部分，必须逐字节为零 |

SHA-256 均为原始 32 bytes，不是 ASCII hex；外部 manifest 采用 64 个十六进制字符。
整个文件另有 SHA-256，由发布 manifest 固定。内部 checksum 检出损坏，不提供签名认证；
T18 在封存之前必须核对预先接收的包 hash，而不能信任同一个未知文件自带的 checksum。

## 目录项：256 bytes

| entry offset | 类型/长度 | 含义 |
|---|---|---|
| 0 | bytes[128] | ASCII 名称，1..127 bytes，后接 NUL，余下全零 |
| 128 | u32 | kind=1/2/3/4 |
| 132 | u32 | 对应 entry layout_id |
| 136 | u32 | rank：W8/scale=2，FP32=1，blob=0 |
| 140 | u32 | flags：0 正常存储，1 显式别名，其他拒绝 |
| 144 | u32[4] | 逻辑 shape；未使用维度必须为零，有效维度必须为正 |
| 160 | u64 | 文件绝对 offset |
| 168 | u64 | 精确有效 length，不含尾 padding |
| 176 | u32 | region：1=weights，2=tokenizer |
| 180 | u32 | alias_of：非别名=`0xffffffff`，否则为更早的目录项索引 |
| 184 | u64 | region_offset，区别于文件 offset |
| 192 | bytes[32] | 本项有效载荷 SHA-256，不含 padding；别名与目标相同 |
| 224 | bytes[32] | 保留，全零 |

名字允许 `[A-Za-z0-9_./-]`，不允许 `..`、绝对路径、重复名字；不把名字当作主机路径执行。
矩阵名称沿用 checkpoint；scale 的名字是矩阵名加 `.scale`。共享关系仅允许
`lm_head.weight → model.embed_tokens.weight` 和对应 `.scale`；二者必须同时出现。
full profile 必须有全部 290 个源张量、169 个 scale、两个别名、metadata 和五个 tokenizer
文件，共 467 项。独立 full 检查同时逐块比较全部源参数，不仅检查文件 hash。

正常项按目录顺序紧凑存储，下一项 offset 为上一项末尾 align64；两个目标区域分别
维护同样的 cursor。别名不推进任何 cursor、不增加存储字节。禁止未声明的洞或载荷。
以至少 u64 计算 shape 乘积、length、offset+length，再检查 32-bit SoC 地址溢出和分区上限。

## 装载和 metadata

地址从 [T08 memory-map-v1](memory-map-v1.json) 取得：weights base=`0x80000000`，
tokenizer base=`0xB8000000`。SoC 地址=`region_base+region_offset`，不是 `base+file_offset`。
Coral 读取模型权重使用同一 SoC DDR 地址，包没有 Coral TCM 本地地址。
`metadata.json` 属于 weights 区，最大 1MiB；`tokenizer/*` 仅能装入 tokenizer 区。

metadata 的 UTF-8 JSON 拒绝重复 key、非有限 JSON 数字；包含 format、profile、numeric_version、
group_size。完整模型另含模型 revision、模型锁/算子清单/数值门槛/地址图 hash、结构尺寸、
原配置、原始 tokenizer 文件清单与哈希、RMS epsilon、RoPE theta 和**显式生成策略**。
固定 EOS=151645、BOS/PAD=151643、输入≤512、新 token≤128、KV≥640、greedy/beam1、
repetition_penalty=1、use_model_defaults=false。不得回填 checkpoint 的采样默认值。

保留 tokenizer 原始 config.json、tokenizer.json、tokenizer_config.json、vocab.json、merges.txt；
聊天模板和 added/special tokens 使用原 tokenizer_config 的内容，不使用合并导出时改写的 tokenizer。
`fixture-v1` 是合法的小张量集合，显式不是可运行的完整网络，不能冒充完整模型 profile。

T18 必须先检查头/目录/区间，再用有界缓冲流式写入最终区域并验证 checksum；失败后
保持模型未就绪且不可被后端访问，重装必须重新验证。所有别名仅引用已有存储。
整包校验、预期 hash 核对和 loader 封存后才发布只读 view。禁止一次存整包再复制到第二份
模型区。PRELOAD 和 PROTOCOL_BOOT 分开；后者模型目的区初始不得预置。

## 独立读取器和错误

[export.py](../../model_tools/export.py) 复用 T05 NumPy 数值参考，按 256 行分块导出。
[verify_pack.py](../../model_tools/verify_pack.py) 不导入导出器或数值参考，独立解码结构、
检查所有文件/地址区间、哈希、别名和数值合法性，再提供有界的 `rows`/`blob` 读取接口。
调用者须在验证后保持文件/内存不可变；改变载荷必须重新验证。
[check_full.py](../../tests/model_pack/check_full.py) 用 T05 独立 Torch 量化器重算全部 24 层，
逐位核对 W8、scale、bias/norm，还读取封存的 T05 八类矩阵向量验证一致性。

| 错误码 | 检出内容 |
|---|---|
| E_MAGIC / E_VERSION / E_ENDIAN / E_LAYOUT | magic、版本/结构长度、端序、布局或 group 不支持 |
| E_CHECKSUM | 头、目录、载荷、单项或预期整包 hash 不符 |
| E_BOUNDS / E_OVERFLOW | 截断/多余字节、越界/非规范间隙、尺寸/地址运算溢出 |
| E_ALIGNMENT / E_RESERVED | 错对齐、非零保留字节或 padding |
| E_SHAPE / E_DUPLICATE | rank/shape/length/scale 配对错误、重名 |
| E_ALIAS / E_OVERLAP | 非法/不完整别名，文件或 SoC 地址重叠 |
| E_NUMERIC / E_METADATA | 非法整数/scale/FP32，metadata/全模型身份不符合合同 |
| E_IO | 主机文件访问失败 |

错误优先顺序为固定头支持性与校验 → 目录校验/逐项结构 → 重叠/紧凑性/载荷校验 → metadata
与数值 → 完整 profile 身份；多重损坏只保证拒绝，fixture 通过修复无关 checksum 隔离特定错误。
测试工具的 E_SOURCE/E_REFERENCE/E_EVIDENCE 是来源、数值对照或证据错误，不是硬件 ABI 状态码。
T18 的固件状态映射由其任务定义，必须保留这里的分类，不提前声称固件已实现。

## 容量和运行时约束

[pack_budget.py](../../model_tools/pack_budget.py) 从实际目录 span 计算两个模型区域占用，并
列出有地址的分配：全 24 层 640-token FP32 KV=15,728,640 bytes，M≤8 的激活、完整 logits、
group dot、两份最大 padded reduction 缓冲、CPU 程序/堆/固定栈、BPE 索引、文本、传输/装载
双缓冲与最大目录。所有缓冲保守地同时计入，不凭生命周期猜测减免。

容量上界更保守：实际 weights span＋T08 **全部非 weights 分区的完整预留**（包括未使用的
arena 和不可映射的 64MiB）。因此没有漏算 tokenizer、固件或 loader 工作区。
实际文件大小、逐区分配、精确余量在每次证据的 `budget.json`。
程序≤8MiB、堆≤8MiB、文本≤1MiB、BPE 索引≤`vocab*16+200000*16` 是接收方须执行的限额，
不是已测得的固件峰值。T12 仍须实现/实测分配和越界拒绝，T23 仍须核实实物 DDR；
本卡不将预算通过表述为已经在板上运行。

## 复跑与下游 fixtures

```bash
make t10
make t10-test
npu-python model_tools/export.py models/model-pack-v1/new-run/model.nxpack
npu-python model_tools/verify_pack.py models/model-pack-v1/new-run/model.nxpack --sha256 <published-hash>
npu-python scripts/run_t10.py --verify-archive evidence/T10/<run-id>
```

输出路径必须不存在，失败文件/证据不覆盖。完整包及第二次重建均在受管理、源码忽略的
`models/model-pack-v1/<run-id>/`；evidence 保存小 manifest/结果/源码快照与 fixtures。

[fixture manifest](../../tests/cocotb/fixtures/model_pack/manifest.json) 包含三个合法包：
M4/N129/K896（输出行尾块）、M4/N129/K65（格式尾组，Coral 应拒绝）、M1/N3/K4864。
固定 seeds=1/7/19，均含量化舍入边界、零组、极值、bias、norm、共享 head 和 tokenizer。
另有 21 个坏包：截断、坏版本/校验、地址/文件溢出越界、非法别名、重名/重叠、错布局/端序/
对齐，以及 reseal 后的非法整数/scale。manifest 固定输入/golden hash、shape/dtype/stride/
端序、group、物理 layout 与逻辑 view、文件偏移/SoC 地址、生成器/checker 身份、错误码和消费者。

T14 验证真实搬运字节、行尾块与反压；T15 验证逐组整数与 FP32 完整输出；T18 验证 SD 协议
装载及所有坏包在进入 ready 前被拒绝。桌面检查器以 Python scalar round/任意精度点积
重算 golden，并保存每个坏包 CLI 的原始 FAIL/exit=1。T10 的 producer PASS **不计为 RTL
消费 PASS**，实际消费 hash 与波形由各卡回填，完整 W8 应用质量由 T11 验收。
