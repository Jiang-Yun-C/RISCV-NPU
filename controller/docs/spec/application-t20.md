# T20 控制执行合同 v1

producer=T20，consumers=T21/T26/T31。语义沿用 T02 application-v2；模型锁、W8 包与
T12 `nxr_*` 请求/停止合同不变。接口扩展原因为状态新鲜度、重复防护及外设错误处理。

设备有限：LED 整数 0/1、PWM 整数 0–100%，temperature 整数摄氏度 -40–125、light
整数 lux 0–100000。JSON 根为程序数组，每级 ≤8 节点、深度 ≤2、总节点 ≤32、最终动作
≤8；完整文本 ≤4096 bytes。`if` 支持 >/< />=/<=，阈值整数 -100000–100000；两分支均先
校验。reject/不支持设备返回 UNSUPPORTED；未知操作、类型/缺字段/多字段/JSON 错误为
FORMAT；动作越界为 RANGE。拒绝节点在任意分支出现均拒绝整条程序。空程序合法。
选中路径中重复相同设备和值返回 DUPLICATE；LED 1→0 等不同值的顺序动作合法。
CPU 先解析并完整校验，再读取一次一致传感器包，构建完整暂存动作，成功后才逐项提交。
任一解析、状态或动作计划错误均无 GPIO/PWM 写入；错误请求后可立即接受新请求。

模型负责中文→程序；CPU 不读中文来纠正语义。显示模板只格式化结果。模型把四分之一
错误生成 40% 时，固件不能改成 25%；模型质量评分与执行器忠实执行分别记录。
未知中文应由模型生成 reject；CPU 不能知道语法合法程序是否误解了中文。开发集沿用
合法 ≥90%、拒绝 ≥95%、全部成对状态通过的冻结门槛；不读取/调参 T31 保留集。

桌面编译器 `software/application_v2/compiler.py` 首先使用原 T02 冻结提示运行完整模型。
仅当输出为单个合法根 if 时，再用固定的双条件提示生成候选；候选若为温度和光照各一个
根 if 且阈值位于各传感器范围，再用固定的带 else 提示生成第三候选。全部调用均使用
相同中文与状态、相同完整 W8 模型和 greedy/EOS 请求。选择规则只比较生成 AST：第三
候选完整保留原 if 节点时选第三候选；或者第二候选保留原条件/then，原 else 恰等于
第二个独立条件的 then、两个候选 else 均空时选第二候选；其余保留原输出。完整规则
以归档源码为准。每次发布均为某次模型调用的完整原始 EOS 输出，不能合成节点、替换
阈值/动作或按文字、样例 ID、类别、期望答案选择。主机记录所有候选 prompt/messages/
token IDs/stop 及选择路线。这是 T20 的有限多候选模型编译接口，单请求最多三次完整
推理，不宣称单次模型调用。原单条件开发集重新全部验证；新增两个双条件表达各三种
状态必须全部通过。CPU 解析器与执行器不参与候选生成或语言解释。

开发集和新增双条件回放前，通过单独标为 CPU_STATE_PRECONDITION 的 UART 程序由
真实 CPU 设置快照中的 LED/PWM，独立 checker 在模型请求之前核对实际输出状态；
这些初始化动作不能记作模型生成。温度/光照由 I²C 包提供，CPU 仅可使用本次有效版本。
故障和短测为顺序会话，保留此前输出，拒绝不得产生任何新输出写入。条件程序只支持
温度/光照谓词，LED/PWM 是桌面模型上下文与可观察执行器状态，不新增 LED/PWM 条件。

UART 8N1 文本帧：`id epoch text_bytes intent_bytes\n`，随后 UTF-8 中文、换行、完整
模型 JSON 文本、换行。id 为严格递增的 1–0xfffffffe，包含拒绝请求也消费 ID；0、重复、
倒退及最大值返回 REQUEST_ID，输出无副作用。`END\n` 结束测试会话。固件返回一行
JSON（id/text/intent/intent_fnv32/temperature/light/epoch/sampled_at/validation/actions/readings）
及 `RESULT id status` 文本。原始模型输出 SHA-256、输入状态、token IDs、prompt、包/库
身份保存在主机记录；CPU FNV32 仅用于串口关联，不作为密码学真实性校验。

I²C 虚拟快照设备地址 0x48，单次读事务返回 16 bytes little-endian：i32 temperature、
u32 light、u32 epoch、u32 sampled_at。CPU bitbang 实现 START、0x91、ACK、16 bytes、
前15字节 ACK、最终 NACK、STOP，SDA/SCL 开漏与 clock stretch。10000 mcycle 拉高等待
上限返回 TIMEOUT；地址 NACK 返回 NACK。包 epoch 与模型请求快照不一致返回 STATE；
传感器越界同样 STATE。CPU 读取 mcycle 低32位，以模差检查样本年龄 ≤1000000 周期，
超过或未来时间返回 STALE；该窗口小于半计数空间，兼容正常低32位回绕。T26 要将此虚拟
聚合包适配为实际传感器，并保证版本和时间戳来自可信采集端。校验期间外部状态改变不
触发重新解释；本次动作基于该版本的一致快照，下次请求读取新版本。

MMIO：UART 0x10000000/04/08 沿用 T17 RTL；虚拟 LED/PWM/id 为 0x10001000/04/08，
I²C 输出/输入 0x10001100/04，测试结束 0x10001200。I²C bits=0 SCL、1 SDA，1表示释放。
PWM 100个10ns时钟周期一帧；执行器顺序写寄存器，独立监视实际 LED/PWM 引脚及每次
提交。T26 的物理 MMIO 与时钟由实板适配，本合同不是板级引脚或传感器型号声明。

范围是桌面完整 24层0.5B W8 C 推理＋UART 原始意图回放＋真实 VexRiscv CPU执行器＋
真实 UART RTL＋虚拟 I²C/GPIO/PWM。固件/ROM PRELOAD；没有 Coral 参与应用意图推理、
没有完整0.5B RTL推理、没有真实传感器/DDR/PDS/板级性能。T19 与 T25 的范围保持原合同。
