# eBPF 수집기 도입 전 검증

작성일: 2026-10-27

## 결론

- **현재 트래픽 분석 파이프라인에 네트워크 흐름 데이터를 보태려면 Hubble을 우선 검토**한다. 단, Hubble은 Cilium 네트워킹을 기반으로 하므로 현재 Docker Desktop Kubernetes에 바로 설치하는 작업으로 취급하면 안 된다.
- **Falco는 두 번째 목적의 도구**다. HTTP 요청량·응답시간을 수집하는 용도보다는 컨테이너에서 실행된 명령, 파일 접근, 권한 변경 같은 런타임 보안 이벤트 탐지에 적합하다.
- 현재 앱의 HTTP 요청 로그와 Prometheus `/metrics`가 이미 존재한다. eBPF 수집기를 추가해도 이 데이터 경로를 대체하기보다 별도 이벤트 원천으로 추가해야 한다.
- 저장소 구성과 실행 중인 Kubernetes 리소스를 읽기 전용으로 확인했다. 샌드박스 안에서는 Docker named pipe 접근이 거부됐지만, 호스트 권한으로 확인했을 때 Docker Desktop과 Kubernetes는 정상 동작했다. eBPF 프로그램 로딩 자체는 아직 검증하지 않았다.

## 확인한 현재 구성

| 항목 | 확인 내용 | eBPF 도입에 미치는 점 |
|---|---|---|
| 앱 수집 | `app-testing/app.py`의 FastAPI middleware가 HTTP 요청, 상태 코드, 처리 시간, IP, 경로를 PostgreSQL `request_logs`에 저장 | 앱 계층의 요청별 상세 로그가 이미 있음 |
| 메트릭 | 앱과 analyzer가 `/metrics`를 노출하고 ServiceMonitor가 15초 간격으로 수집 | Prometheus는 기존 운영 지표 수집 경로로 유지 가능 |
| 서비스 구성 | test app Service의 HTTP 포트는 80→8000, analyzer는 9000 | Hubble은 서비스 간 네트워크 흐름 보강에 적합 |
| 정책 | `smart-traffic`에 ingress 및 모니터링 NetworkPolicy가 있음 | 실제 CNI가 NetworkPolicy를 지원하고 적용하는지 클러스터에서 확인 필요 |
| Docker/Kubernetes | Docker Engine 29.9.2, Kubernetes v1.34.1; `docker-desktop` 노드 Ready | 클러스터 조회 가능 |
| 노드 커널 | `6.6.87.2-microsoft-standard-WSL2` | Cilium의 문서상 Linux 5.10+ 최소 버전은 충족. BPF 기능·권한의 실제 사용 가능 여부는 별도 확인 필요 |
| CNI 흔적 | `kube-system`에 `kube-proxy` DaemonSet이 1/1 Ready, Cilium DaemonSet/Pod와 Cilium CRD는 조회되지 않음 | 현재 클러스터는 Cilium 기반이 아니므로 Hubble 활성화는 CNI 도입을 포함 |
| 서비스 상태 | app 2개, analyzer, DB, ingress-nginx, Prometheus/Grafana 모두 Running | 현재 앱 구성과 모니터링은 실행 중 |
| NetworkPolicy | `smart-traffic`에 앱 Ingress 및 Prometheus 스크레이프 정책 존재 | 실제 정책 집행은 현재 CNI 동작과 함께 보존 여부를 별도 검증해야 함 |

## Hubble 적합성 검증

Hubble은 Cilium의 관측 계층이며, Cilium이 수집한 Kubernetes 네트워크 흐름을 보여준다. 따라서 현 환경에서 Hubble만 Helm으로 추가해 기존 CNI를 그대로 둔 채 관측을 시작하는 방식은 적합하지 않다. 현재 클러스터는 앞선 점검에서 `kube-proxy`를 사용하고 Cilium은 설치되지 않은 상태였다. 기존 CNI에서 Cilium으로 바꾸는 것은 네트워크 구성 변경이므로, Docker Desktop의 주 개발 클러스터가 아니라 폐기 가능한 별도 테스트 클러스터에서 검증하는 편이 안전하다.

기본 Hubble 흐름은 L3/L4 수준의 연결·방향·포트 관측이다. HTTP 메서드와 URL 같은 L7 세부 정보가 필요하면 Cilium의 L7 proxy/policy 설정도 필요하다. 공식 문서는 L7 가시성 규칙이 정책 허용/차단 동작과 연결될 수 있고, HTTP URL/query/header 등 민감 정보가 흐름에 포함될 수 있다고 경고한다. 따라서 첫 검증은 L3/L4 흐름만 대상으로 하고, L7은 개인정보 제거와 정책 영향 검토 후 별도 단계로 둔다.

**판정:** 네트워크 토폴로지나 서비스 간 연결 실패를 대시보드에 보여주는 목표에는 적합하다. 현재 Isolation Forest의 HTTP 요청 집계 개선만이 목적이라면 즉시 도입할 필요는 낮다. Hubble flow를 `request_logs`에 섞지 않고 `network_flows` 같은 별도 저장/수집 경로로 넣는 설계가 적절하다.

## Falco 적합성 검증

Falco의 기본 syscall 이벤트 원천은 Linux 커널 드라이버를 통해 시스템 호출을 관측한다. Modern eBPF 드라이버는 커널 BTF와 ring buffer 등 기능, eBPF 로딩 권한 및 런타임 capability가 필요하다. 현재 클러스터의 커널 버전만으로 이 요구 사항을 충족한다고 단정할 수 없고, Docker Desktop/WSL2에서 DaemonSet이 필요한 권한과 호스트 경로를 사용할 수 있는지도 실제 구동 확인이 필요하다.

**판정:** 컨테이너에서 의심스러운 프로세스 실행·파일 변경·권한 사용을 보안 경보로 보여주려는 목표에는 유용하다. 네트워크 트래픽의 요청량/지연시간을 수집해 현재 분석기에 넣는 목적과는 다르므로 Hubble과 같은 데이터 모델이나 탐지 결과로 취급하지 않는다. 나중에 도입한다면 `security_events`로 별도 보관하는 편이 좋다.

## 다음 검증 절차와 통과 조건

현재 개발 클러스터의 기본 정보는 읽기 전용으로 조회했다. 다음 단계는 아래 항목을 계속 **읽기 전용으로 확인**하는 것이다. 여기서는 설치·CNI 변경을 하지 않는다.

```powershell
kubectl get nodes -o wide
kubectl get pods -n kube-system -o wide
kubectl get daemonsets -n kube-system
kubectl get configmap -n kube-system
docker info
```

그 다음 폐기 가능한 별도 클러스터에서만 아래를 확인한다.

1. Cilium 설치 전후 `test-web-app`과 analyzer 간 HTTP 연결, Ingress 접속, DNS, 기존 NetworkPolicy 동작을 기록한다.
2. Hubble L3/L4에서 test app↔analyzer/DB 흐름의 source, destination, verdict가 보이는지 확인한다.
3. 원래 클러스터의 기능과 테스트 클러스터를 비교하고, Hubble 이벤트를 기존 HTTP 로그와 구분해 저장할 필드를 정한다.
4. Falco는 별도 보안 목표가 확정된 경우에만 modern eBPF 시작 가능 여부와 테스트 프로세스 경보를 확인한다.

Hubble 검증 통과 조건은 **서비스 통신과 NetworkPolicy가 유지되고, 관측 흐름이 식별되며, 기존 분석 DB의 HTTP 로그와 혼합되지 않는 것**이다. 이 조건을 만족하기 전에는 현재 개발 클러스터의 CNI를 교체하지 않는다.

## 격리 클러스터 실행 결과 (2026-10-28)

기존 `docker-desktop` 컨텍스트는 유지하고, kind로 `cilium-validation`이라는 별도 클러스터를 만들었다. 테스트 설정은 [kind-config.yaml](../k8s/ebpf-validation/kind-config.yaml)에 있으며, 기본 CNI를 끄고 Cilium이 네트워크 플러그인을 맡게 했다. Kubernetes 1.36.4와 WSL2 kernel `6.6.87.2-microsoft-standard-WSL2`에서 검증했다.

Helm으로 Cilium 1.20.4와 Hubble Relay/UI를 설치했다. Cilium agent 1/1, Hubble Relay 1/1, Hubble UI 2/2, CoreDNS 2/2가 Running/Ready가 됐고 Kubernetes 노드도 Ready 상태다. 1노드 클러스터에서 Cilium Operator 기본 replica 2개 중 하나가 스케줄되지 않아 테스트 클러스터만 1개로 조정했다.

[traffic.yaml](../k8s/ebpf-validation/traffic.yaml)의 격리된 HTTP 서버/클라이언트가 Service DNS로 2초 간격 요청을 보냈다. Hubble Relay에 연결한 CLI 결과는 `Healthcheck: Ok`, `Connected Nodes: 1/1`, 약 `12.8 flows/s`였고, `flow-client → flow-server:8080`의 TCP SYN/ACK, 데이터 전송 및 종료 흐름과 CoreDNS 질의를 관측했다. 따라서 **현재 WSL2/Docker Desktop 기반 로컬 커널에서 Cilium eBPF 기반 L3/L4 flow 수집과 Hubble 조회가 동작함을 확인**했다.

이번 초기 확인은 L3/L4 흐름 관측까지였다. Hubble에서 HTTP 메서드/URL 등 L7 필드가 나오는지와 L7 정책 영향은 검증하지 않았다. 따라서 현 개발 클러스터로 CNI를 옮길 근거가 아니라, 별도 클러스터에서 기본 기능이 동작한다는 검증이다.

## 실제 test app 흐름 시연 구성 (2026-11-11)

주 개발 클러스터의 CNI를 변경하지 않고, 같은 `kind-cilium-validation` 클러스터에 프로젝트의 `test-web-app:v8`과 PostgreSQL을 별도 `smart-traffic` 네임스페이스로 배포했다. `smart-traffic-demo-client`는 2초 간격으로 `/api`를 호출한다. app 2개, PostgreSQL 1개, demo client 1개가 모두 Ready가 됐고, 앱 로그에 HTTP 200 응답과 `[TRAFFIC]` DB 저장 기록이 남는 것을 확인했다. 따라서 시연 트래픽 경로는 `demo client → test-web-app → PostgreSQL`이다.

Hubble UI 포트포워딩은 `http://localhost:12000`에서 HTTP 200을 반환하는 것을 확인했다. 이번 단계에서는 브라우저 UI의 flow 목록을 직접 캡처하거나 Hubble CLI의 flow 레코드를 별도로 저장하지 않았다. L7 HTTP 메서드/URL 가시성도 아직 검증 범위에 포함하지 않는다.

실행 명령은 [README의 Hubble 실제 앱 흐름 시연 절차](../README.md)를 참고한다. 시연 후에는 `kubectl --context kind-cilium-validation delete -f k8s/ebpf-validation/smart-traffic-demo.yaml`로 반복 요청을 중단할 수 있다.

### 재현 명령

프로젝트 루트의 PowerShell에서 아래처럼 다시 만들 수 있다. Helm 설치에는 `operator.replicas=1`을 지정해 단일 노드에서 불필요한 Pending replica를 만들지 않는다.

```powershell
kind create cluster --name cilium-validation --config k8s/ebpf-validation/kind-config.yaml --wait 5m
$kc = "$env:TEMP\kind-cilium-validation-kubeconfig"
kind export kubeconfig --name cilium-validation --kubeconfig $kc
helm repo add cilium https://helm.cilium.io/
helm repo update cilium
helm --kubeconfig $kc upgrade --install cilium cilium/cilium `
  --version 1.20.4 --namespace kube-system `
  --set kubeProxyReplacement=false --set operator.replicas=1 `
  --set hubble.enabled=true --set hubble.relay.enabled=true --set hubble.ui.enabled=true `
  --wait --timeout 8m
kubectl --kubeconfig $kc apply -f k8s/ebpf-validation/traffic.yaml
kubectl --kubeconfig $kc rollout status deployment/flow-server -n hubble-validation
kubectl --kubeconfig $kc rollout status deployment/flow-client -n hubble-validation
```

### 임시 검증 화면 접속

PowerShell에서 다음 명령으로 Hubble UI를 로컬에만 포트포워딩한다. 이때 `kubectl`이 기본 `docker-desktop`이 아니라 테스트용 kubeconfig를 사용하도록 먼저 설정한다.

```powershell
$env:KUBECONFIG = "$env:TEMP\kind-cilium-validation-kubeconfig"
kubectl port-forward -n kube-system svc/hubble-ui 12000:80
```

브라우저 주소는 <http://localhost:12000>이다. 흐름 조회용 Hubble CLI는 공식 Windows CLI를 설치한 뒤 Relay를 포트포워딩해 확인할 수 있다.

```powershell
kubectl port-forward -n kube-system svc/hubble-relay 4245:80
hubble status --server localhost:4245
hubble observe --server localhost:4245 --namespace hubble-validation --last 20 --output compact
```

검증용 클러스터를 더 이상 사용할 필요가 없으면 이름을 확인한 뒤 다음 명령으로 이 테스트 클러스터만 삭제한다.

```powershell
kind delete cluster --name cilium-validation
```

## 공식 문서

- [Cilium 시스템 요구 사항](https://docs.cilium.io/en/stable/operations/system_requirements/)
- [Hubble 설정](https://docs.cilium.io/en/stable/observability/hubble/setup/)
- [Cilium L7 가시성 및 보안 주의사항](https://docs.cilium.io/en/stable/observability/visibility/)
- [기존 클러스터에서 Cilium으로 마이그레이션](https://docs.cilium.io/en/stable/installation/k8s-install-migration/)
- [Falco 이벤트 원천](https://falco.org/docs/concepts/event-sources/)
- [Falco 커널 이벤트와 Modern eBPF 요구 사항](https://falco.org/docs/concepts/event-sources/kernel/)
