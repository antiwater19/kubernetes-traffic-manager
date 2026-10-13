import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  scenarios: {
    normal_traffic: {
      executor: 'constant-vus',
      exec: 'normalTraffic',
      vus: 2,
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
  },
};

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
  sleep(0.5);
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
