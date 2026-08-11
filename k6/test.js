import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
    vus: 10,
    duration: '30s',
};

export default function () {
    http.get('http://YOUR-SERVICE-URL/');
    sleep(0.1);
}


// 실행 할때는 bash에 k6 run k6/test.js 을 입력
// 이거는 외부에서 사용하는 k6로 트래픽을 발생시키는 테스트 코드임.