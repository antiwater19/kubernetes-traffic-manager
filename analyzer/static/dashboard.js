const state = { windowSeconds: 60, summary: null, policies: [], refreshTimer: null };
const numberFormat = new Intl.NumberFormat('ko-KR');
const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const shortTimeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit' });

function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2800);
}

function formatMs(value) {
  return `${Number(value || 0).toLocaleString('ko-KR', { maximumFractionDigits: 1 })} ms`;
}

function setCell(row, value, className) {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  cell.textContent = value;
  row.appendChild(cell);
  return cell;
}

function getDetectionDetails(item) {
  const reasons = Array.isArray(item.reasons) ? item.reasons : [];
  const modelReasons = reasons.filter(reason => reason.includes('Isolation Forest'));
  const ruleReasons = Array.isArray(item.rule_reasons)
    ? item.rule_reasons
    : reasons.filter(reason => !reason.includes('Isolation Forest'));
  const sources = Array.isArray(item.detection_sources) ? item.detection_sources : [];
  return {
    ruleReasons,
    modelReasons,
    rules: sources.includes('rules') || ruleReasons.length > 0,
    model: sources.includes('isolation_forest') || item.isolation_forest?.is_anomaly === true || modelReasons.length > 0,
  };
}

function getDetectionCounts(record) {
  const metadata = record.detector_metadata || {};
  const findings = record.findings || [];
  const ruleCount = Number.isFinite(Number(metadata.rule_findings))
    ? Number(metadata.rule_findings)
    : findings.filter(item => getDetectionDetails(item).rules).length;
  const modelCount = Number.isFinite(Number(metadata.isolation_forest_findings))
    ? Number(metadata.isolation_forest_findings)
    : Number.isFinite(Number(metadata.anomalies))
      ? Number(metadata.anomalies)
      : findings.filter(item => getDetectionDetails(item).model).length;
  return { ruleCount, modelCount };
}

function renderSummary(data) {
  state.summary = data;
  const model = data.detector_metadata || {};
  const modelStatus = model.status === 'ready'
    ? `Isolation Forest 준비됨 · 기준 ${numberFormat.format(model.training_samples || 0)}구간`
    : `Isolation Forest 기준 수집 중 · ${numberFormat.format(model.training_samples || 0)}/${numberFormat.format(model.minimum_training_samples || 20)}구간`;
  document.querySelector('.analyzer-status small').textContent = modelStatus;
  document.getElementById('kpi-requests').textContent = numberFormat.format(data.total_requests || 0);
  document.getElementById('kpi-findings').textContent = numberFormat.format((data.findings || []).length);
  document.getElementById('finding-note').textContent = `${numberFormat.format(data.unique_clients || 0)}개 클라이언트 중 탐지`;
  document.getElementById('kpi-errors').textContent = `${((data.error_rate || 0) * 100).toFixed(1)}%`;
  document.getElementById('error-note').textContent = `오류 응답 ${numberFormat.format(data.error_requests || 0)}건`;
  document.getElementById('kpi-latency').textContent = formatMs(data.average_latency_ms);
  document.getElementById('p95-note').textContent = `95백분위 ${formatMs(data.p95_latency_ms)}`;
  document.getElementById('client-count').textContent = `${numberFormat.format((data.client_summaries || []).length)} clients`;
  const detectionCounts = getDetectionCounts(data);
  document.getElementById('rules-detected-count').textContent = `${numberFormat.format(detectionCounts.ruleCount)}개 클라이언트`;
  document.getElementById('model-detected-count').textContent = `${numberFormat.format(detectionCounts.modelCount)}개 클라이언트`;
  const minimumSamples = model.minimum_training_samples || 20;
  const trainingSamples = model.training_samples || 0;
  document.getElementById('model-training-note').textContent = model.status === 'ready'
    ? `기준선 ${numberFormat.format(trainingSamples)}/${numberFormat.format(minimumSamples)}구간 · 평가 ${numberFormat.format(model.scored_clients || 0)} IP`
    : `기준선 ${numberFormat.format(trainingSamples)}/${numberFormat.format(minimumSamples)}구간 · 규칙 탐지는 동작 중`;

  const updated = new Date(data.window_ended_at);
  document.getElementById('last-updated').textContent = `갱신 ${timeFormat.format(updated)}`;
  renderClients(data);
  renderFindings(data);
  renderChart('requests-chart', 'request_count', data.timeline || [], '#6488f4', '건', 'request-chart-empty');
  renderChart('latency-chart', 'average_latency_ms', data.timeline || [], '#8970e8', 'ms', 'latency-chart-empty');
}

function renderClients(data) {
  const body = document.getElementById('client-rows');
  body.replaceChildren();
  const clients = data.client_summaries || [];
  if (!clients.length) {
    const row = body.insertRow();
    const cell = setCell(row, '선택한 시간 구간에 요청이 없습니다.', 'empty-cell');
    cell.colSpan = 6;
    return;
  }
  const findings = new Map((data.findings || []).map(item => [item.client_ip, item]));
  clients.slice(0, 12).forEach(client => {
    const row = body.insertRow();
    setCell(row, client.client_ip, 'ip-cell');
    setCell(row, numberFormat.format(client.request_count), 'number-cell');
    setCell(row, `${(client.error_rate * 100).toFixed(1)}%`, 'number-cell');
    setCell(row, formatMs(client.average_latency_ms), 'number-cell');
    const stateCell = document.createElement('td');
    const badge = document.createElement('span');
    const finding = findings.get(client.client_ip);
    badge.className = `state-badge ${finding ? finding.severity : 'normal'}`;
    const detection = getDetectionDetails(finding || client);
    badge.textContent = detection.rules && detection.model
      ? '규칙 + 모델'
      : detection.model ? '모델' : detection.rules ? '규칙' : '정상';
    stateCell.appendChild(badge);
    row.appendChild(stateCell);
    const policy = state.policies.find(item => item.client_ip === client.client_ip);
    const actions = document.createElement('td');
    actions.className = 'policy-actions';
    actions.appendChild(makeActionButton(policy?.is_blocked ? '차단 해제' : '차단', policy?.is_blocked ? 'unblock' : 'block', client.client_ip));
    actions.appendChild(makeActionButton(policy?.rate_limit_max_requests ? '제한 변경' : '요청 제한', 'set-limit', client.client_ip));
    row.appendChild(actions);
  });
}

function makeActionButton(label, action, clientIp) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `small-action ${action === 'unblock' ? 'secondary' : ''}`;
  button.dataset.action = action;
  button.dataset.ip = clientIp;
  button.textContent = label;
  return button;
}

function renderPolicies() {
  const body = document.getElementById('policy-rows');
  body.replaceChildren();
  document.getElementById('policy-count').textContent = `${numberFormat.format(state.policies.length)} policies`;
  if (!state.policies.length) {
    const row = body.insertRow();
    const cell = setCell(row, '등록된 IP 정책이 없습니다. 클라이언트 분석에서 IP를 선택해 설정하세요.', 'empty-cell');
    cell.colSpan = 5;
    return;
  }
  state.policies.forEach(policy => {
    const row = body.insertRow();
    setCell(row, policy.client_ip, 'ip-cell');
    const status = setCell(row, policy.is_blocked ? '차단됨' : '허용', 'policy-status');
    status.classList.add(policy.is_blocked ? 'blocked' : 'allowed');
    const limit = policy.rate_limit_max_requests
      ? `${numberFormat.format(policy.rate_limit_max_requests)}회 / ${formatWindow(policy.rate_limit_window_seconds)}`
      : '제한 없음';
    setCell(row, limit, 'number-cell');
    setCell(row, policy.block_reason || '—');
    const actions = document.createElement('td');
    actions.className = 'policy-actions';
    actions.appendChild(makeActionButton(policy.is_blocked ? '차단 해제' : '차단', policy.is_blocked ? 'unblock' : 'block', policy.client_ip));
    actions.appendChild(makeActionButton(policy.rate_limit_max_requests ? '제한 해제' : '요청 제한', policy.rate_limit_max_requests ? 'clear-limit' : 'set-limit', policy.client_ip));
    row.appendChild(actions);
  });
}

function renderFindings(data) {
  const container = document.getElementById('findings-list');
  const findings = data.findings || [];
  const status = document.getElementById('overall-status');
  status.className = `status-pill ${findings.length ? 'high' : 'normal'}`;
  status.textContent = findings.length ? `${findings.length}건 탐지` : '정상';
  container.replaceChildren();
  if (!findings.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = '현재 구간에서 탐지된 이상 징후가 없습니다.';
    container.appendChild(empty);
    return;
  }
  findings.forEach(finding => {
    const card = document.createElement('div');
    card.className = `finding-card ${finding.severity}`;
    const head = document.createElement('div');
    head.className = 'finding-head';
    const ip = document.createElement('span');
    ip.className = 'finding-ip';
    ip.textContent = finding.client_ip;
    const badge = document.createElement('span');
    badge.className = `state-badge ${finding.severity}`;
    badge.textContent = finding.severity === 'high' ? '높음' : '관찰';
    head.append(ip, badge);
    card.appendChild(head);
    const detection = getDetectionDetails(finding);
    const sources = document.createElement('div');
    sources.className = 'detection-sources';
    if (detection.rules) {
      const tag = document.createElement('span');
      tag.className = 'source-tag rules-source';
      tag.textContent = '규칙 기반';
      sources.appendChild(tag);
    }
    if (detection.model) {
      const tag = document.createElement('span');
      tag.className = 'source-tag model-source';
      tag.textContent = 'Isolation Forest';
      sources.appendChild(tag);
    }
    if (sources.childElementCount) card.appendChild(sources);
    const reasons = document.createElement('ul');
    const appendReasons = (label, items) => items.forEach(reason => {
      const item = document.createElement('li');
      const source = document.createElement('strong');
      source.className = 'reason-source';
      source.textContent = `${label} · `;
      item.append(source, document.createTextNode(reason));
      reasons.appendChild(item);
    });
    appendReasons('규칙', detection.ruleReasons);
    appendReasons('모델', detection.modelReasons);
    card.appendChild(reasons);
    container.appendChild(card);
  });
}

function renderChart(canvasId, key, points, color, unit, emptyId) {
  const canvas = document.getElementById(canvasId);
  const empty = document.getElementById(emptyId);
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext('2d');
  const themeStyles = getComputedStyle(document.documentElement);
  const gridColor = themeStyles.getPropertyValue('--chart-grid').trim() || '#edf1f6';
  const labelColor = themeStyles.getPropertyValue('--chart-label').trim() || '#a0aaba';
  const pointColor = themeStyles.getPropertyValue('--chart-point').trim() || '#fff';
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const values = points.map(point => Number(point[key] || 0));
  const hasTraffic = points.some(point => Number(point.request_count || 0) > 0);
  empty.classList.toggle('hidden', hasTraffic);
  if (!points.length) return;

  const pad = { top: 10, right: 10, bottom: 25, left: 40 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const maxValue = Math.max(...values, key === 'request_count' ? 1 : 10);
  const tickCount = 4;
  ctx.font = '9px "DM Sans", "Noto Sans KR", sans-serif';
  ctx.textBaseline = 'middle';
  for (let tick = 0; tick <= tickCount; tick++) {
    const y = pad.top + chartHeight * tick / tickCount;
    const value = maxValue * (tickCount - tick) / tickCount;
    ctx.beginPath();
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillStyle = labelColor;
    ctx.textAlign = 'right';
    ctx.fillText(key === 'request_count' ? Math.round(value).toString() : Math.round(value).toString(), pad.left - 7, y);
  }
  const coords = values.map((value, index) => ({
    x: pad.left + (points.length === 1 ? chartWidth / 2 : chartWidth * index / (points.length - 1)),
    y: pad.top + chartHeight * (1 - value / maxValue),
  }));
  if (key === 'request_count') {
    ctx.beginPath();
    coords.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
    ctx.lineTo(coords[coords.length - 1].x, pad.top + chartHeight);
    ctx.lineTo(coords[0].x, pad.top + chartHeight);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + chartHeight);
    gradient.addColorStop(0, '#6488f426');
    gradient.addColorStop(1, '#6488f402');
    ctx.fillStyle = gradient;
    ctx.fill();
  }
  ctx.beginPath();
  coords.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.stroke();
  coords.forEach(point => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = pointColor;
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
  const labelEvery = Math.max(1, Math.ceil(points.length / 5));
  points.forEach((point, index) => {
    if (index % labelEvery !== 0 && index !== points.length - 1) return;
    const x = coords[index].x;
    ctx.fillStyle = labelColor;
    ctx.textAlign = index === 0 ? 'left' : index === points.length - 1 ? 'right' : 'center';
    ctx.fillText(shortTimeFormat.format(new Date(point.timestamp)), x, height - 8);
  });
}

function formatWindow(seconds) {
  if (seconds < 60) return `${seconds}초`;
  if (seconds % 3600 === 0) return `${seconds / 3600}시간`;
  return `${seconds / 60}분`;
}

async function loadSummary() {
  const response = await fetch(`/traffic/summary?window_seconds=${state.windowSeconds}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`요약 조회 실패 (${response.status})`);
  renderSummary(await response.json());
}

async function loadHistory() {
  const response = await fetch('/analyses?limit=10', { cache: 'no-store' });
  if (!response.ok) throw new Error(`기록 조회 실패 (${response.status})`);
  const records = await response.json();
  const body = document.getElementById('history-rows');
  body.replaceChildren();
  if (!records.length) {
    const row = body.insertRow();
    const cell = setCell(row, '아직 저장된 분석이 없습니다. “지금 분석하기”를 눌러 첫 분석을 실행하세요.', 'empty-cell');
    cell.colSpan = 7;
    return;
  }
  records.forEach(record => {
    const row = body.insertRow();
    setCell(row, timeFormat.format(new Date(record.analyzed_at)));
    setCell(row, formatWindow(record.window_seconds));
    setCell(row, numberFormat.format(record.total_requests), 'number-cell');
    setCell(row, numberFormat.format(record.unique_clients), 'number-cell');
    const resultCell = document.createElement('td');
    const result = document.createElement('span');
    result.className = `history-result ${record.status}`;
    const dot = document.createElement('i');
    const text = document.createElement('span');
    text.textContent = record.status === 'abnormal' ? '이상 탐지' : '정상';
    result.append(dot, text);
    resultCell.appendChild(result);
    row.appendChild(resultCell);
    setCell(row, numberFormat.format((record.findings || []).length), 'number-cell');
    const detections = getDetectionCounts(record);
    setCell(row, `규칙 ${detections.ruleCount} · IF ${detections.modelCount}`, 'source-cell');
  });
}

async function loadPolicies() {
  const response = await fetch('/ip-policies', { cache: 'no-store' });
  if (!response.ok) throw new Error(`IP 정책 조회 실패 (${response.status})`);
  state.policies = await response.json();
  renderPolicies();
  if (state.summary) renderClients(state.summary);
}

async function savePolicy(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `정책 변경 실패 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  await loadPolicies();
  showToast('IP 정책을 저장했습니다.');
}

async function handlePolicyAction(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const clientIp = button.dataset.ip;
  try {
    if (button.dataset.action === 'block') {
      const reason = window.prompt(`${clientIp} 차단 사유`, '이상 트래픽 확인');
      if (reason === null) return;
      const hoursInput = window.prompt('차단 시간(시간)을 입력하세요. 비우면 수동 해제 전까지 차단합니다.', '1');
      if (hoursInput === null) return;
      const durationSeconds = hoursInput.trim() ? Number(hoursInput) * 3600 : null;
      if (durationSeconds !== null && (!Number.isInteger(durationSeconds) || durationSeconds < 3600 || durationSeconds > 2_592_000)) {
        throw new Error('차단 시간은 1시간에서 720시간 사이로 입력하세요.');
      }
      await savePolicy('/ip-policies/block', { client_ip: clientIp, reason, duration_seconds: durationSeconds });
    } else if (button.dataset.action === 'unblock') {
      if (!window.confirm(`${clientIp} 차단을 해제할까요?`)) return;
      await savePolicy('/ip-policies/unblock', { client_ip: clientIp });
    } else if (button.dataset.action === 'set-limit') {
      const maxInput = window.prompt(`${clientIp}의 구간당 최대 요청 수`, '30');
      if (maxInput === null) return;
      const windowInput = window.prompt('구간 길이(초)', '60');
      if (windowInput === null) return;
      const maxRequests = Number(maxInput);
      const windowSeconds = Number(windowInput);
      if (!Number.isInteger(maxRequests) || maxRequests < 1 || maxRequests > 100000 || !Number.isInteger(windowSeconds) || windowSeconds < 1 || windowSeconds > 86400) {
        throw new Error('요청 수는 1~100000, 구간은 1~86400초로 입력하세요.');
      }
      await savePolicy('/ip-policies/rate-limit', { client_ip: clientIp, max_requests: maxRequests, window_seconds: windowSeconds });
    } else if (button.dataset.action === 'clear-limit') {
      if (!window.confirm(`${clientIp}의 요청 제한을 해제할까요?`)) return;
      await savePolicy('/ip-policies/rate-limit/clear', { client_ip: clientIp });
    }
  } catch (error) {
    showToast(error.message || 'IP 정책을 변경하지 못했습니다.');
  }
}

async function runAnalysis() {
  const button = document.getElementById('analyze-button');
  button.disabled = true;
  button.querySelector('.button-label').textContent = '분석 중…';
  try {
    const response = await fetch(`/analyze?window_seconds=${state.windowSeconds}`, { method: 'POST' });
    if (!response.ok) throw new Error(`분석 실패 (${response.status})`);
    const result = await response.json();
    await Promise.all([loadSummary(), loadHistory()]);
    showToast(`분석 결과를 저장했습니다. ${result.findings.length}건 탐지`);
  } catch (error) {
    showToast(error.message || '분석 요청에 실패했습니다.');
  } finally {
    button.disabled = false;
    button.querySelector('.button-label').textContent = '지금 분석하기';
  }
}

async function refreshAll() {
  try {
    await Promise.all([loadSummary(), loadHistory(), loadPolicies()]);
  } catch (error) {
    showToast(error.message || '대시보드 데이터를 불러오지 못했습니다.');
  }
}

document.getElementById('window-select').addEventListener('change', event => {
  state.windowSeconds = Number(event.target.value);
  loadSummary().catch(error => showToast(error.message));
});
document.getElementById('analyze-button').addEventListener('click', runAnalysis);
document.getElementById('refresh-history').addEventListener('click', () => loadHistory().catch(error => showToast(error.message)));
document.getElementById('client-rows').addEventListener('click', handlePolicyAction);
document.getElementById('policy-rows').addEventListener('click', handlePolicyAction);
window.addEventListener('resize', () => { if (state.summary) renderSummary(state.summary); });
window.addEventListener('themechange', () => { if (state.summary) renderSummary(state.summary); });
refreshAll();
state.refreshTimer = window.setInterval(() => Promise.all([loadSummary(), loadPolicies()]).catch(() => {}), 5000);
