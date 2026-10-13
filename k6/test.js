import http from 'k6/http';
import { sleep } from 'k6';

const allScenarios = {
  normal_traffic: {
    executor: 'constant-vus',
    exec: 'normalTraffic',
    vus: 1,
    duration: '30s',
    tags: { traffic_scenario: 'normal' },
  },
  burst_traffic: {
    executor: 'constant-arrival-rate',
    exec: 'burstTraffic',
    rate: 8,
    timeUnit: '1s',
    duration: '10s',
    preAllocatedVUs: 4,
    maxVUs: 8,
    startTime: '5s',
    tags: { traffic_scenario: 'burst' },
  },
  slow_traffic: {
    executor: 'constant-vus',
    exec: 'slowTraffic',
    vus: 2,
    duration: '20s',
    startTime: '5s',
    tags: { traffic_scenario: 'slow' },
  },
  error_spike: {
    executor: 'constant-vus',
    exec: 'errorTraffic',
    vus: 2,
    duration: '20s',
    startTime: '10s',
    tags: { traffic_scenario: 'error' },
  },
};

const profile = (__ENV.RUN_PROFILE || 'all').toLowerCase();
let selectedScenarios;

if (profile === 'all') {
  selectedScenarios = allScenarios;
} else if (profile === 'normal') {
  selectedScenarios = {
    normal_traffic: { ...allScenarios.normal_traffic, duration: '21m' },
  };
} else if (profile === 'burst') {
  const { startTime, ...scenario } = allScenarios.burst_traffic;
  selectedScenarios = { burst_traffic: scenario };
} else if (profile === 'slow') {
  const { startTime, ...scenario } = allScenarios.slow_traffic;
  selectedScenarios = { slow_traffic: scenario };
} else if (profile === 'error') {
  const { startTime, ...scenario } = allScenarios.error_spike;
  selectedScenarios = { error_spike: scenario };
} else {
  throw new Error(`Unknown RUN_PROFILE "${profile}". Use all, normal, burst, slow, or error.`);
}

export const options = { scenarios: selectedScenarios };

const BASE_URL = __ENV.TARGET_URL ||
  'http://ingress-nginx-controller.ingress-nginx.svc.cluster.local';

function send(path, scenario) {
  return http.get(`${BASE_URL}${path}`, {
    headers: {
      Host: 'test.local',
      'X-Traffic-Scenario': scenario,
    },
    tags: { endpoint: path, traffic_scenario: scenario },
  });
}

export function normalTraffic() {
  send('/api', 'normal');
  sleep(5);
}

export function burstTraffic() {
  send('/burst', 'burst');
}

export function slowTraffic() {
  send('/slow', 'slow');
}

export function errorTraffic() {
  send('/error', 'error');
  sleep(0.5);
}

export function teardown() {
  if (__ENV.ANALYZE_AFTER_RUN !== 'true') return;

  const analyzerUrl = __ENV.ANALYZER_URL ||
    'http://traffic-analyzer-service.smart-traffic.svc.cluster.local:9000/analyze?window_seconds=60';
  const response = http.post(analyzerUrl);
  if (response.status < 200 || response.status >= 300) {
    console.log(`[ANALYZER] request failed: HTTP ${response.status} ${response.body}`);
    return;
  }

  const result = response.json();
  const model = result.detector_metadata || {};
  console.log(
    `[ANALYZER] saved id=${result.id} requests=${result.total_requests} ` +
    `findings=${(result.findings || []).length} model=${model.status} ` +
    `training_samples=${model.training_samples} anomalies=${model.anomalies || 0}`,
  );
}
