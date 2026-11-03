# 选题一：参考程序与虚拟执行一致性及延迟记录

本工具为当前演示台补上可复查的严格参考程序诊断：固定输入、固定24例公开开发集、原始串口
记录、完整分母、条件状态对，以及独立的延迟统计。评价器不连接串口；可选采集器只在
显式 `--capture` 时连接指定 CP2102。两者均不执行 GPIO/PWM，不改写模型输出，也不
调用另一个模型担任裁判。

## 自动保存完整24例

```bash
python software/competition_semantics/evaluate.py plan --output /new/live-run
python software/competition_semantics/collect.py --run /new/live-run/run.json
python software/competition_semantics/collect.py --run /new/live-run/run.json \
  --capture --port /dev/ttyUSB0 --baud 115200
python software/competition_semantics/evaluate.py score \
  --run /new/live-run/run.json --output /new/live-run/report.json
```

Windows 将 `--port` 换为实际 COM 端口。默认第二条命令只检查计划，不打开串口。
采集要求支持 `text_max=1 identity=1` 的服务，使用同一控制台 parser，保留每个原始
接收 chunk、单请求 export 与进度 manifest。上一条文件落盘后才发送下一条，因此
不受 UI 只保留20条历史的限制。失败和未尝试案例仍留在24例分母里，已开始的 plan
不允许覆盖重跑。协议异常或断线立即保存部分记录并停止后续请求。

主机默认等待86460秒，保留原24小时板端期限并留串口余量；`--wait-seconds` 只改变
主机等待，不是板端取消。需要较短板端期限时先在演示台应用请求期限；主机超时后
断开不会取消正在执行的计算。采集会观测模型/tokenizer 身份，但不认证硬件来源。
详见 `docs/spec/t27-service-enhancements.md` 的计时、冷热前缀、取消与快照口径。

## 记录如何被检查

输入直接使用 `software/demo_console` 导出的 `nexusrv-demo-v1` JSON。
`parse_export.mjs` 导入原版 `T25Parser`，重新解析 `rawChunks` 中的 base64 原始字节，
校验分块序号、UTF-8、TEXTLEN、流式与最终文本、token、EOS/停止原因、METRICS 和 READY。
有原始分块时还核对它们与 `raw` 文本一致。每份导出只允许一个请求，command 必须等于
该固定案例的命令。导出对象自己声称的 `complete`、`metrics` 不作为判定依据。

协议一致性不能证明数据一定来自某块实物板。报告记录文件和字节流 SHA256，并分别标明
声明为 live、replay 或 fixture 的来源；模型/tokenizer 身份可能来自请求原文，也可能
来自演示台保存的启动身份。固件/位流身份需要在 `run.json` 中填写实际部署信息并另存
原始部署证据。工具不会把自报身份变成硬件认证。

语义判定使用现有 `firmware/application/application.c` 的真实解析器与执行器，通过
只在主机运行的桥接函数评估动作计划。这样保留 RANGE、UNSUPPORTED、DUPLICATE 等规则。
状态全部来自开发集中的整数温度/照度，带明确的 `PUBLIC_DEV_VIRTUAL_STATE` 标记。
这些是虚拟状态求值结果，不是传感器采样或实际执行结果。

全部任务还要求模型输出的完整 JSON 程序与标签一致。例如，恰好处于关灯分支时，
直接输出“关灯”不能冒充正确的条件语义。空白差异不影响 JSON AST 比较；代码围栏、
解释性前后缀、JSON 截取或自动修复均不采用。拒绝任务也必须保留标签指定的设备/整数，
得到指定的校验错误且没有动作/读数：要求PWM 101却输出PWM -2，即使同为RANGE也不通过。
所有成功语义结果还必须以 EOS 结束。这是**严格参考程序匹配＋虚拟执行一致性诊断**，
不是宽泛的自然语言等价程序准确率；另一种等价程序也可能因参考AST不匹配而判错。

## 实际采集流程

从 `source/` 目录执行，依赖 Python 3、Node.js 和 GCC，无额外 Python 包：

```bash
python software/competition_semantics/evaluate.py plan --output /new/semantic-run
```

生成：

- `run.json`：24例固定分母、模型/tokenizer/时钟合同、导出文件位置、实际部署身份填写处。
- `COPY_PROMPTS.txt`：逐例可复制的单行提示。
- `requests.jsonl`：相同提示、实际 `commandFor()` 生成的命令、生成上限。
- `exports/`：保存每个请求的当前演示台导出 JSON。

在当前演示台选择**文本输入、生成上限128**，复制每例提示行提交；每次收到结果或失败后
立即导出，按 `sem-01.json` 至 `sem-24.json` 存入 `exports/`。演示台历史最多保留20条，
不要等跑完24例才统一导出。`COPY_PROMPTS.txt` 中的提示已经包含固定程序接口说明和
虚拟状态；这是一套新的公开开发测评，不替代原 T02/T20/T31 的冻结prompt或保留集。

若超时/断连而没有导出文件，将该项 `attempt_status` 改为 `timeout` 或 `disconnected`，
保留案例，不删除记录。若重新测试，应建立新的完整run，保留第一次失败；不要从多个
试次挑选每题最佳输出拼成一轮成绩。

```bash
python software/competition_semantics/evaluate.py score \
  --run /new/semantic-run/run.json \
  --output /new/semantic-run/report.json
```

当前包没有真实模型生成头/权重、板端串口或新部署，本次提供的是采集与评价能力。
空run会输出 `NO_CAPTURE_DATA`、模型准确率 `null`，不会制造板端成绩。

## 报告口径

| 字段 | 含义 |
|---|---|
| `protocol` | 原始字节通过当前协议检查的请求数 / 固定24例 |
| `diagnostic_semantic_agreement` | 所有导出记录的严格参考AST/虚拟执行一致数；缺失、失败仍占分母；fixture也可能在这里匹配，但不是模型成绩 |
| `declared_live_model_semantics` | 声明为live、非fixture、有精确分块、身份匹配的成功数 / 固定24例；没有live尝试时准确率为null |
| `paired_virtual_states` | 相同指令两种阈值边界状态都通过才通过一对；共5对；不等于真实传感器成对测试 |
| `latency_by_declared_source` | live/replay/fixture分别统计，避免混合历史、合成与现场记录 |
| `physical_evidence` | 传感器、GPIO/PWM动作、显示设备始终标为未由本工具验证 |

延迟由重解析的板端 `mcycle` 统计与声明匹配的125MHz合同换算，分别保留内部首token、
prefill、decode和runtime total。正文首个可见字符从解析器真实preview事件所在原始chunk
重新定位，只在同一时钟域相减：Python `time.monotonic_ns` 对 Python write_start；浏览器
`performance.now` 对浏览器 write_start。没有对应起点、原始chunk或正确时钟名就留空。
不会以另一个时钟域、DOM更新时间、墙钟、回放播放速度补齐。数据来源自报的CLOCK仍须
由板端时钟/部署记录确认。统计包括所有协议完整请求，即使其语义错误；缺失延迟不记0。

24例公开开发诊断不足以宣称泛化准确率。它适合快速显示“能正确理解什么、在什么条件
失败”，并帮助为完整、独立保留的正式集准备同样的采集方法。现有冻结集和阈值未改。

## 完整自测示例

以下故意根据标签生成假记录，仅检查评价链路。每份记录包含 `source=fixture` 和
`fixture=true`；即使24例全部语义匹配，报告的模型准确率仍为null：

```bash
python tests/competition_semantics/make_fixture.py --output /new/semantic-fixture
python software/competition_semantics/evaluate.py score \
  --run /new/semantic-fixture/run.json \
  --output /new/semantic-fixture/FIXTURE_ONLY_REPORT.json
python -m unittest discover -s tests/competition_semantics -p 'test_*.py' -v
```

测试覆盖原始分块不一致/丢失、缺少READY、假complete、错误命令、非EOS、重复导出路径、
篡改数据集身份、多请求混合、条件作弊、同错误码但整数错误、缺失/超时分母、身份缺失与时钟混用等。
