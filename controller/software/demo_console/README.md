# NexusRV 676 板端推理演示台 · 流式候选

本地演示台接收板端真实生成的正文，支持浏览器 USB 串口和 Python 串口桥。模型、tokenizer、推理均在板端执行；页面只解帧、显示和保存记录。本候选将现有 OPT06 流式协议接入生产服务，并保留旧固件与历史记录解析。新固件应与本包更新后的演示台配套使用：原版旧演示台要求每步 STEP，不能兼容本候选省略 STEP 的普通服务。

## 启动与连接

在项目根目录运行（Python 3.10+，页面无 npm/CDN 依赖）：

```sh
python3 software/demo_console/server.py --open
```

浏览器打开 <http://localhost:8765>。也可使用 `make demo-console` 或工具目录中的系统启动脚本。推荐 Chrome / Edge 的浏览器串口直连。选择目标 CP2102（VID `10c4` / PID `ea60`），串口参数默认为 **115200 baud、8N1、无流控**，与本包当前生产配置一致。只有实际运行的固件配置为历史 500000 baud 时，才切换该选项；选择高波特率不会改变板端设置。

Python 串口桥另需安装：

```sh
python3 -m pip install -r software/demo_console/requirements.txt
```

Python 列出服务所在系统的串口，只连接 `serial 0001` 的目标 CP2102。Web Serial 由用户在系统设备选择器中选择目标。打开端口时设置 DTR/RTS 为 false。连接已运行的板端服务，只发送空行等待 READY；工具不执行位流下载、重载或 SD 写入。

## 实时演示

1. 等待“板端服务就绪”。新固件发送 `T25 CAPABILITIES stream=1 text_max=1`，页面据此启用生成长度和流式开关。
2. 输入中文或英文单行文字。新服务使用 `:text MAX_NEW TEXT`，可设 1–128 tokens；页面默认 32，仅限制后续回复长度，不会降低首个 token 的模型计算量。旧服务继续发送原始文字，固件固定上限 128。Token 模式继续使用 `:ids MAX_NEW ...`。
3. 点击运行或按 Ctrl+Enter。生成的正文一旦到达，页面立即更新；不添加打字动画、虚构回复或人为等待。第一个完整 UTF-8 字符可在 TEXT 帧的换行到达前显示。
4. 结果生成期间标为“正在生成 · 预览”。收到 END、最终 IDS、按字节计数的正文、METRICS、READY，且最终正文/token 与预览一致后，才标为成功、保存成功记录并开放下一次请求。
5. 流式开关在空闲时发送 `:stream 0/1`。关闭后仍解析最终按长度封装的正文，便于同源 A/B 对比。首次打开流式候选固件时默认开启；重新附着已有服务时，如需明确模式，请切换到所需状态并等待 READY。

新普通服务不再逐步打印 STEP。页面依靠真实 TOKEN 事件显示已生成 token 数，不伪造 prefill 层内百分比。诊断 `:verify` 保留 STEP，但演示台不向用户暴露该诊断命令。

正文中的换行、CR、`T25 READY` 或 `T25 METRICS` 字样都属于正文，按 `TEXTLEN` 指定的 UTF-8 字节数消费，不能解锁新请求。分裂中文字、四字节 Unicode、BOM、空/special token 均按解码状态处理。协议错误、超时、ABORT 或断连将预览标为不完整，不会把部分内容当成功结果。

断开串口不会取消板端计算。刷新页面后重新接入尚在运行的 Python 连接时，页面保留收到的原始 chunk，但舍弃无法补齐的旧结果；等服务实际返回 READY 后再允许新请求，不将中途附着误判成完整结果。

## 首字指标与记录

页面同时呈现以下不同边界：

| 指标 | 含义 |
|---|---|
| 板内首 token | 固件内部接受第一个生成 ID 的时刻；不是正文首字。零输出 token 时显示 `—`。 |
| 正文首字到达 | 浏览器直连使用 `performance.now()` 的串口写入开始到 read 返回；Python 桥使用同一主机 `time.monotonic_ns()` 的 write_start 到收到包含首个完整可显示字符的 chunk。 |
| 首字写入页面 | 浏览器提交请求到实际设置正文 DOM 的时刻，使用浏览器同一单调时钟。Python 路径包含 HTTP 传递。 |
| 下个帧回调 | 首字 DOM 更新之后的 requestAnimationFrame 回调；仅为浏览器调度证据，不是像素显示时间。 |

空白、控制/格式字符、单独的组合符号以及替代符不算首个可显示字符。只生成 EOS 或无正文时没有首字值。回放不会生成现场首字测量。

导出的 JSON 保留原始文本、**逐 chunk 的 base64 原始字节与单调时间**、请求、模型身份、板端 TIME/METRICS、预览完整性结论以及 DOM/帧回调时间。Python 路径还保留串口 `write_start`、`write_return`、`flush_end`；Web Serial 没有物理发送排空时间接口，`flush_end` 明确为空。浏览器和 Python 时钟分别记录、分别相减，不跨时钟域推算延迟。

Python 桥保持“先等 1 字节，再读取已到达数据”的方式，不使用 readline。页面改为有数据立即唤醒的长轮询，去掉旧版固定 180 ms 轮询间隔。20 秒只是无数据时长轮询的最长等待，字节到达即返回。每个 chunk 有递增序号，缓冲溢出或序号缺失时拒绝完整结果。

板内 `total_ticks`、流式 `complete`、主机首字和 DOM 更新的边界不同。Decode 计算速度仍按 `(generated-1)*125000000/decode_ticks`，**不含串口输出与前端开销**，不作为端到端流式吞吐。PROFILE CUMULATIVE 仍是平台启动以来累积值。

## 验证

离线协议/UTF-8/旧回放测试（Node.js）：

```sh
node software/demo_console/tests/test_stream_protocol.mjs
```

串口桥与 HTTP 测试（只用假串口，不访问板卡）：

```sh
python3 -m unittest software.demo_console.tests.test_server -v
```

本次上述 Node **72 项断言**和 Python **12 项测试**通过。覆盖首个中文字在帧换行前显示、任意 chunk 切分、错误 UTF-8、BOM、空文本、正文中的控制行字样、缺失/乱序事件、END 后 ABORT、预览/最终不一致、旧记录兼容、按数据唤醒、发送/接收时钟与连接恢复状态。另由根目录集成测试把实际生产 main 的流式输出送入本解析器验证；具体范围见候选验证报告。

浏览器渲染、真实 Web Serial 设备选择、录屏和摄像头授权须在用户环境验证。当前运行环境没有可用的 Chromium，浏览器截图/实际 DOM 渲染 QA 未执行；不能将 Node 解析通过宣称为像素显示或真实实板 TTFT 通过。保留的 `tests/browser_smoke.py` 可在配有 Playwright/Chromium 的环境执行。

## 历史记录与部署边界

内置回放是既有实板串口记录，保留原始内容与来源；播放动画仅按事件顺序，不代表真实逐行耗时。中文样例、COM10 同步/内存读取、单 token 输出 `er`、507 次后端调用等均为 **2026-10-17 的旧版本历史证据**，不是本次流式候选上板结果。本次修改没有访问实际 UART、写 SD、下载位流，也没有新增完整模型实板性能结论。

新固件需要重新编译并按项目既有应用/loader 信任链部署。仅打开新页面不会让旧固件提前发出 token；旧 ROM 对新应用的信任绑定也不能由界面绕过。部署步骤与原件关系见候选根目录的交付说明。

工具仅绑定 localhost，串口 API 使用本地凭据和窗口所有权，服务退出时释放串口。历史记录保存在当前浏览器，导出可保存当前请求；导入始终重新解析原始内容，不信任导入 JSON 自报的成功状态。
