import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  vus: 5,
  duration: '30s',
};

const BASE_URL = __ENV.TARGET_URL ||
  'http://ingress-nginx-controller.ingress-nginx.svc.cluster.local';
const PATHS = ['/api', '/api', '/api', '/slow', '/burst', '/error'];

export default function () {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)];
  http.get(`${BASE_URL}${path}`, {
    headers: { Host: 'test.local' },
    tags: { endpoint: path },
  });
  sleep(0.25);
}
