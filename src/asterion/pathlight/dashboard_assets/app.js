"use strict";

const state = {
  snapshot: null,
  traceId: null,
  selectedNode: null,
  tab: "evaluations",
  filter: "",
};

const byId = (id) => document.getElementById(id);

function shortDigest(value, size = 12) {
  if (typeof value !== "string") return "—";
  return value.length > size ? `${value.slice(0, size)}…` : value;
}

function appendText(parent, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = String(text);
  if (className) element.className = className;
  parent.append(element);
  return element;
}

function traceStatus(trace) {
  const root = trace.events[0].span_id;
  for (let index = trace.events.length - 1; index >= 0; index -= 1) {
    const event = trace.events[index];
    if (event.span_id === root && event.status !== "started") return event.status;
  }
  return "missing";
}

function selectedFlow() {
  if (!state.snapshot || !state.traceId) return null;
  return state.snapshot.flows.find((flow) => flow.trace_id === state.traceId) || null;
}

function renderSummary() {
  const summary = state.snapshot.summary;
  byId("count-traces").textContent = summary.trace_count;
  byId("count-models").textContent = summary.model_call_count;
  byId("count-tools").textContent = summary.tool_call_count;
  byId("count-evaluations").textContent = summary.evaluation_count;
  byId("count-gaps").textContent = summary.evidence_gap_count;
  byId("snapshot-digest").textContent = `snapshot ${shortDigest(state.snapshot.snapshot_sha256, 18)}`;
  byId("snapshot-status").textContent = "安全快照已验证 · 页面只显示摘要与不可逆标识";
}

function renderTraceList() {
  const list = byId("trace-list");
  list.replaceChildren();
  const visible = state.snapshot.traces.filter((trace) =>
    trace.trace_id.includes(state.filter),
  );
  byId("visible-run-count").textContent = visible.length;
  if (!visible.length) {
    appendText(list, "p", "没有匹配的运行。", "empty-copy");
    return;
  }
  visible.forEach((trace) => {
    const status = traceStatus(trace);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trace-button";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(trace.trace_id === state.traceId));
    button.addEventListener("click", () => {
      state.traceId = trace.trace_id;
      state.selectedNode = null;
      render();
    });
    appendText(button, "span", "", `status-dot ${status}`);
    appendText(button, "span", shortDigest(trace.trace_id, 18), "trace-id");
    appendText(button, "span", status, "trace-meta");
    list.append(button);
  });
}

function renderFlow() {
  const flow = selectedFlow();
  const list = byId("flow-list");
  list.replaceChildren();
  const badge = byId("flow-status");
  if (!flow) {
    badge.textContent = "未选择";
    badge.className = "status-badge status-missing";
    byId("flow-description").textContent = "选择一个运行，沿 ContextFrame → 模型调用 → 工具调用观察输入输出边界。";
    return;
  }
  const trace = state.snapshot.traces.find((item) => item.trace_id === flow.trace_id);
  const status = trace ? traceStatus(trace) : "missing";
  badge.textContent = status;
  badge.className = `status-badge status-${status}`;
  byId("flow-description").textContent = `Trace ${shortDigest(flow.trace_id, 20)} · ${flow.nodes.length} 个主线节点`;
  if (!flow.nodes.length) {
    const gap = document.createElement("li");
    gap.className = "evidence-gap";
    gap.textContent = "证据缺口：该历史运行没有可验证的 ContextFrame / 模型调用主线。Pathlight 不会根据最终结果反推或伪造缺失节点。";
    list.append(gap);
    return;
  }
  flow.nodes.forEach((node) => {
    const item = document.createElement("li");
    item.className = "flow-node";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "node-button";
    button.setAttribute("aria-pressed", String(state.selectedNode === node.sequence));
    button.addEventListener("click", () => {
      state.selectedNode = node.sequence;
      renderFlow();
      renderInspector();
    });
    appendText(button, "span", node.sequence, "node-sequence");
    const label = document.createElement("span");
    appendText(label, "span", node.kind, "node-kind");
    appendText(
      label,
      "span",
      node.missing_evidence ? "边界证据不完整" : "结构化边界已观察",
      "node-caption",
    );
    button.append(label);
    appendText(button, "span", node.status, `status-badge status-${node.status}`);
    item.append(button);
    list.append(item);
  });
  if (flow.missing_evidence) {
    const gap = document.createElement("li");
    gap.className = "evidence-gap";
    gap.textContent = "证据缺口：主线中至少一个调用边界缺少结构化观察数据。";
    list.append(gap);
  }
}

function displayValue(value) {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}=${displayValue(item)}`)
      .join(" · ");
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  return value === null || value === undefined ? "—" : String(value);
}

function renderInspector() {
  const fields = byId("inspector-fields");
  fields.replaceChildren();
  const flow = selectedFlow();
  const node = flow?.nodes.find((item) => item.sequence === state.selectedNode);
  byId("inspector-empty").hidden = Boolean(node);
  if (!node) return;
  const entries = [
    ["sequence", node.sequence],
    ["kind", node.kind],
    ["status", node.status],
    ["parent", node.parent_sequence],
    ["caused by", node.caused_by_sequences],
    ["consumed by", node.consumed_by_sequences],
    ["produced by", node.produced_by_sequences],
    ["missing evidence", node.missing_evidence],
    ...Object.entries(node.attributes).map(([key, value]) => [key, value]),
  ];
  entries.forEach(([label, value]) => {
    appendText(fields, "dt", label);
    appendText(fields, "dd", displayValue(value));
  });
}

function renderEvaluations(container) {
  const contracts = new Map();
  const records = [];
  state.snapshot.evaluations.forEach((bundle) => {
    bundle.metric_contracts.forEach((contract) => contracts.set(contract.metric_contract_sha256, contract));
    records.push(...bundle.evaluations);
  });
  state.snapshot.experiments.forEach((bundle) => records.push(...bundle.evaluations));
  if (!records.length) {
    appendText(container, "p", "当前快照没有评估记录。", "empty-copy");
    return;
  }
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["指标", "得分", "覆盖", "证据状态", "Evaluation"].forEach((label) => appendText(headRow, "th", label));
  head.append(headRow);
  table.append(head);
  const body = document.createElement("tbody");
  const seen = new Set();
  records.forEach((record) => {
    if (seen.has(record.evaluation_sha256)) return;
    seen.add(record.evaluation_sha256);
    const contract = contracts.get(record.metric_contract_sha256);
    const row = document.createElement("tr");
    appendText(row, "td", contract?.metric_name || shortDigest(record.metric_contract_sha256));
    appendText(row, "td", record.value_microunits === null ? "missing" : (record.value_microunits / 1000000).toFixed(4));
    appendText(row, "td", `${record.selected_count}/${record.total_count}`);
    appendText(row, "td", record.status);
    const identity = appendText(row, "td", "");
    appendText(identity, "code", shortDigest(record.evaluation_sha256, 16));
    body.append(row);
  });
  table.append(body);
  container.append(table);
}

function renderExperiments(container) {
  if (!state.snapshot.experiments.length) {
    appendText(container, "p", "当前快照没有实验记录。", "empty-copy");
    return;
  }
  const stack = document.createElement("div");
  stack.className = "record-stack";
  state.snapshot.experiments.forEach((bundle) => {
    bundle.plans.forEach((plan) => {
      const record = document.createElement("article");
      record.className = "record";
      appendText(record, "h3", `experiment ${shortDigest(plan.experiment_plan_sha256, 16)}`);
      const trialCount = bundle.trials.filter((trial) => trial.experiment_plan_sha256 === plan.experiment_plan_sha256).length;
      appendText(record, "p", `${trialCount} trials · ${plan.candidate_variant_sha256s.length + 1} variants · scope ${shortDigest(plan.scope_sha256)}`);
      stack.append(record);
    });
  });
  container.append(stack);
}

function renderDiagnoses(container) {
  const findings = state.snapshot.diagnoses.flatMap((bundle) => bundle.findings);
  if (!findings.length) {
    appendText(container, "p", "当前快照没有诊断记录。", "empty-copy");
    return;
  }
  const stack = document.createElement("div");
  stack.className = "record-stack";
  findings.forEach((finding) => {
    const record = document.createElement("article");
    record.className = "record";
    appendText(record, "h3", finding.category);
    appendText(record, "p", `confidence ${finding.confidence} · evidence ${finding.evidence_sha256s.length} · subject ${shortDigest(finding.subject_sha256)}`);
    stack.append(record);
  });
  container.append(stack);
}

function optimizationTrials(snapshot) {
  return snapshot.optimizations.flatMap((bundle) => bundle.trials);
}

function traceForDigest(trace_sha256) {
  return state.snapshot.traces.find((trace) => trace.trace_sha256 === trace_sha256);
}

function appendTraceLink(parent, trial) {
  if (trial.status !== "completed" || !trial.trace_sha256) {
    appendText(parent, "span", trial.status, "trace-meta");
    return;
  }
  const trace = traceForDigest(trial.trace_sha256);
  if (!trace) {
    appendText(parent, "span", "trace unavailable", "trace-meta");
    return;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "trace-link";
  button.addEventListener("click", () => {
    state.traceId = trace.trace_id;
    state.selectedNode = null;
    window.location.hash = "workflow-main";
    render();
  });
  appendText(button, "code", shortDigest(trial.trace_sha256, 16));
  parent.append(button);
}

function renderOptimizationTrials(container, history) {
  const trials = optimizationTrials(state.snapshot);
  const trialIds = new Set([
    ...history.baseline_optimization_trial_sha256s,
    ...history.candidate_optimization_trial_sha256s,
  ]);
  const paired = new Map();
  trials.filter((trial) => trialIds.has(trial.optimization_trial_sha256)).forEach((trial) => {
    const pair = paired.get(trial.dataset_item_sha256) || {};
    pair[trial.variant_role] = trial;
    paired.set(trial.dataset_item_sha256, pair);
  });
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  ["Dataset item", "Baseline", "Candidate", "Trace flow"].forEach((label) => appendText(row, "th", label));
  head.append(row);
  table.append(head);
  const body = document.createElement("tbody");
  [...paired.entries()].sort(([left], [right]) => left.localeCompare(right)).forEach(([dataset, pair]) => {
    const item = document.createElement("tr");
    appendText(item, "td", shortDigest(dataset, 16));
    appendText(item, "td", pair.baseline ? `${pair.baseline.status} · ${pair.baseline.agent_cost_microusd}μ$` : "missing");
    appendText(item, "td", pair.candidate ? `${pair.candidate.status} · ${pair.candidate.agent_cost_microusd}μ$` : "missing");
    const links = document.createElement("td");
    if (pair.baseline) appendTraceLink(links, pair.baseline);
    if (pair.candidate) appendTraceLink(links, pair.candidate);
    item.append(links);
    body.append(item);
  });
  table.append(body);
  container.append(table);
}

function renderOptimizations(container) {
  if (!state.snapshot.optimizations.length) {
    appendText(container, "p", "当前快照没有优化决策。", "empty-copy");
    return;
  }
  state.snapshot.optimizations.forEach((bundle) => {
    bundle.decisions.forEach((decision) => {
      const record = document.createElement("article");
      record.className = `record decision-${decision.result}`;
      appendText(record, "h3", `Optimization decision · ${decision.result}`);
      appendText(record, "p", `reason ${decision.reason} · decision ${shortDigest(decision.decision_sha256, 16)}`);
      const history = bundle.histories.find((item) => item.trial_history_sha256 === decision.trial_history_sha256);
      if (!history) return;
      appendText(record, "p", `evidence ${history.evidence_state} · mean gain ${history.mean_gain_microunits ?? "missing"}μ · cost ${history.cost_increase_microunits ?? "missing"}μ · time ${history.time_increase_microunits ?? "missing"}μ`);
      appendText(record, "p", `thresholds: gain ≥ ${decision.minimum_mean_gain_microunits}μ · cost ≤ ${decision.maximum_cost_increase_microunits}μ · time ≤ ${decision.maximum_time_increase_microunits}μ`);
      if (history.evidence_state !== "complete") appendText(record, "p", "证据不完整：不会把该历史解释为接受或拒绝。", "evidence-gap");
      renderOptimizationTrials(record, history);
      container.append(record);
    });
  });
}

function renderAnalysis() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.tab === state.tab));
  });
  const container = byId("analysis-content");
  container.replaceChildren();
  if (state.tab === "evaluations") renderEvaluations(container);
  if (state.tab === "experiments") renderExperiments(container);
  if (state.tab === "diagnoses") renderDiagnoses(container);
  if (state.tab === "optimizations") renderOptimizations(container);
}

function render() {
  if (!state.snapshot) return;
  renderSummary();
  renderTraceList();
  renderFlow();
  renderInspector();
  renderAnalysis();
}

async function loadSnapshot() {
  try {
    const response = await fetch("/api/pathlight/v1/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error("snapshot-unavailable");
    state.snapshot = await response.json();
    state.traceId = state.snapshot.traces[0]?.trace_id || null;
    render();
  } catch (_error) {
    byId("snapshot-status").textContent = "安全快照不可用";
    byId("snapshot-status").classList.add("status-failed");
  }
}

byId("trace-filter").addEventListener("input", (event) => {
  state.filter = event.target.value.trim().toLowerCase();
  renderTraceList();
});

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    state.tab = button.dataset.tab;
    renderAnalysis();
  });
});

loadSnapshot();
