const state = { windowSeconds: 60, summary: null, refreshTimer: null };
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
    cell.colSpan = 5;
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
    badge.textContent = finding ? (finding.severity === 'high' ? '주의' : '관찰') : '정상';
    stateCell.appendChild(badge);
    row.appendChild(stateCell);
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
    const reasons = document.createElement('ul');
    (finding.reasons || []).forEach(reason => {
      const item = document.createElement('li');
      item.textContent = reason;
      reasons.appendChild(item);
    });
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
    ctx.strokeStyle = '#edf1f6';
    ctx.lineWidth = 1;
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillStyle = '#a0aaba';
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
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
  const labelEvery = Math.max(1, Math.ceil(points.length / 5));
  points.forEach((point, index) => {
    if (index % labelEvery !== 0 && index !== points.length - 1) return;
    const x = coords[index].x;
    ctx.fillStyle = '#a0aaba';
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
    cell.colSpan = 6;
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
  });
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
    await Promise.all([loadSummary(), loadHistory()]);
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
window.addEventListener('resize', () => { if (state.summary) renderSummary(state.summary); });
refreshAll();
state.refreshTimer = window.setInterval(() => loadSummary().catch(() => {}), 5000);
