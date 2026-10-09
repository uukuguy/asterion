# Task29：已确认动作之间的动态观察边界

用户已同意动态反馈方向并授权完成设计、实现；影响三层运行的直接相关缺陷可一并修复。本轮不启动新 BP35 冷测；按仓库合同完成打包验证。

## 问题与证据

Task28 L2七步计划到seq38滚屏后，下一seq39动作死亡；LLM直到整段结束才获得反馈。L6则有历史已见危险位置在滚屏后未正确复用。接口只有真实像素、state/progress等，没有玩家可见camera_offset或物理phase。不能使用内部engine.Camera作oracle，不能把当前两次死亡都归为简单漏看。

离线像素比较37→38提供dy+24候选，匹配约94.1%，zero约38.0%，次优约73.0%；182→183约94.9%，189→190约86.0%。这是录像统计，不是相机真值或新的通过率证据。

## 方案选择与三层定位

三种方案：固定每步返回增加LLM往返；仅模型手设检查点不能覆盖未预料的视窗变化；客观视图变化候选默认返回、允许模型关闭此软策略并手设检查点。选择第三种，稳定路径可批量执行，不注入危险语义。

Prime通用层沿用现有顺序工具调用、真实工具返回、控制admission、预算和记录机制，不新建runner或认知流程。P7研究层Solver负责计划语法及观察策略，将已确认动作结果交回模型；LLM自组织空间记忆、机制和后续行动。P7数据层只做有界真实像素平移统计，绝不推断具体关卡、颜色角色、相机真值或物理phase。

## 模型参数与语义

自主计划新增可选 `stop_on_view_change: bool`，缺省true；false仅关闭平移候选后的软yield。步骤新增可选 `observe_after: bool`，缺省false，模型可选择主动观察点。全计划所有字段严格校验后才能派发，bool不接受整数/字符串，legacy不接受新策略字段。

每个已知、已提交步骤，以此前及最新settled rawframe/ref比较；只在autonomous模式做新检测。检测到候选时将有界证据附于该步反馈，包含真实before/after refs、测量状态、位移与匹配统计及最多两个新露出区域。单步/最后一步也可附证据，帮助模型保持历史对应；只有还有未执行后缀时才yield。不能把`stop_on_view_change:false`理解为画面安全，不能把未检测到平移理解为无风险。

在`control.leave('action')`之后、已有hardstop处理之后：若步已确认提交、applied_count==1、stop_reason仍matched且suffix非空，检查observe_after或有效候选。返回`stop_reason='observation-boundary'`、有界`observation_boundary`（reason为actor-checkpoint/view-change-candidate）、实际执行数量、原有反馈、最新观察与ref、budget及未执行步骤。复用plan_id只读原记录；继续需新id和当前ref，无自动续执行、重放、退款、新授权。

检测器异常在动作try/except之外隔离：以`observation-boundary`/`observation-analysis-unavailable`停止剩余步骤，真实结果仍known，不调用_processing_failure或把环境变unknown。对真实观察损坏的既有异常处理保持。模糊/平坦/无平移/超数据cap只报告测量不可用或无候选，不作为危险，也不强迫每步暂停；显式分析异常才安全停止后缀。stop_on_view_change:false时分析异常不建立额外动作限制，但需保留有界不可用反馈。

## 纯数据检测器

新`view_change(before,after)`无外部依赖，同shape最多4096pixels；仅搜索零位移及两轴±32pixels以内的整数位移，最多129候选，最多528384pixelpairs/O(N)memory。更大frame/不同shape返回显式unsupported，不做无界搜索；不掩码特定颜色或坐标。统计两帧联合众数仅用于忽略无信息背景，颜色仍原样比较。

在重叠区统计非背景信息位置的exactmatch、informative数量和支持空间范围；候选要求至少128informative、匹配率>=0.85、相对zero提升>=0.15、比所有其它有效候选差距>=0.05；支持跨两维至少各半屏，重叠informative覆盖全帧informative至少0.5。所有阈值为数据一致性标准，不是危险或行动风险阈值；在文档/输出明确候选解释。重复/平坦/局部角色移动不得报可信滚屏；模糊保留unknown。非零位移表示before像素坐标加(dx,dy)对应after，新区域按此返回半开窗，含边界裁剪事实。输出≤2KiB，不返回图像副本。

P7只读研究API新增`r.view_change(before_sequence, after_sequence=None)`，通过既有bridge一次解析refs、读真实历史像素、返回同样测量及真实序号；不派发动作，不产生世界坐标或自动地图。注册工具保持3个，TS仍须同步闭合参数和描述、资源与allowlist测试。

## 一并修复的执行边界

实际发现Broker预测失配优先于RESET，自主Solver允许忽略native prediction-mismatch时可继续RESET后缀。Solver在收到已确认结果后独立按实际WIN/GAME_OVER、level advance、已执行RESET决定hardstop，优先于软失配和yield，任何stop_on_mismatch/view_change开关不得绕过。legacy同样优先保留实际终局/RESET原因，失配差异仍记录、不伪装匹配。不改Broker交易/未知执行保护或重放器。

## 验收与边界

测试先RED再实现：纯数据真平移、静态、flat、重复纹理、局部运动、歧义、unsupported、bounds与输入不变；真实Solver在变化之后但下一危险步骤之前return、prefix计费/suffix未派发、同id重复只读/newid继续、actorcheckpoint/optout、invalidwholeplan无派发、RESET加错误expect及false不得续行、终局优先、未知执行不走policy、policy异常不污染certainty、模型投影/历史瘦身保留事件与ref、只读API历史一致。

TS→Python→lint/docs→promotion→冻结提交→实际打包r11lL1验证。观察点/检测器特性可用同版本installed provider-free probe覆盖；自然模型不调用可选API不得算能力失败。没有新BP35通过率或速度声明，后续实测需另有用户指令。不能中断一次SDK动作内部，不检测所有场景转换/物理phase，不保证任何危险可避免，也不解决所有历史增长或动作缓存问题。
