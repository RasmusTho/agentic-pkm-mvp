import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    http_req_duration: ['p(95)<250'],
    http_req_failed: ['rate==0'],
    checks: ['rate==1']
  }
};

const base = __ENV.BASE_URL;
if (!base) throw new Error('BASE_URL is required for the disposable search API');
const fixture = JSON.parse(open(__ENV.K6_FIXTURE_MANIFEST));
const uuidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
if (!uuidPattern.test(fixture.expected_uuid) || !fixture.expected_title || fixture.query !== 'smoke') {
  throw new Error('Invalid k6 fixture manifest');
}

function expectedResult(response) {
  if (response.status !== 200) return false;
  let payload;
  try {
    payload = response.json();
  } catch (_) {
    return false;
  }
  if (!payload || !Array.isArray(payload.results) || !payload.results.length || payload.results.length > 10) {
    return false;
  }
  if (!payload.results.every((result) => result && typeof result.uuid === 'string'
    && uuidPattern.test(result.uuid) && typeof result.title === 'string')) return false;
  return payload.results.filter((result) => result.uuid === fixture.expected_uuid
    && result.title === fixture.expected_title).length === 1;
}

function request(trace) {
  return http.get(`${base}/search?q=${encodeURIComponent(fixture.query)}`, {
    headers: { 'x-trace-id': trace }
  });
}

function verify(response) {
  return check(response, {
    'status 200': (r) => r.status === 200,
    'seeded canonical result': expectedResult
  });
}

export function setup() {
  if (!verify(request('warmup-k6-load'))) {
    throw new Error('Search warm-up did not return the expected seeded canonical result');
  }
}

export default function () {
  const trace = Math.random().toString(16).slice(2);
  verify(request(trace));
  sleep(0.2);
}
