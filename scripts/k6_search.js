import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    http_req_duration: ['p(95)<250']
  }
};

const base = __ENV.BASE_URL || 'http://localhost:18000';

export default function () {
  const trace = Math.random().toString(16).slice(2);
  const res = http.get(`${base}/search?q=smoke`, { headers: { 'x-trace-id': trace }});
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(0.2);
}
