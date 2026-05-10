# 트래픽 이상 여부를 판단하는 모듈

THRESHOLD = 20  # 테스트 기준: 요청 수 20회 초과 시 이상 트래픽으로 판단


def detect_abnormal_traffic(stats_data):
    result = []

    requests = stats_data.get("requests", {})

    for ip, count in requests.items():
        if count > THRESHOLD:
            result.append({
                "ip": ip,
                "count": count,
                "status": "abnormal"
            })

    return result