from kubernetes import client, config
import logging

NAMESPACE = "smart-traffic"
POLICY_NAME = "allow-only-from-nginx-ingress"
TARGET_APP_LABEL = "test-web-app"
INGRESS_NAMESPACE = "ingress-nginx"


def load_k8s_config():

    # Kubernetes 클러스터 내부에서 실행될 때는 incluster config 사용.
    # 로컬 테스트 시에는 kubeconfig 사용.
    
    try:
        config.load_incluster_config()
        logging.info("[BLOCKER] Loaded in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        logging.info("[BLOCKER] Loaded local kubeconfig")


def create_or_update_network_policy():
    # test-web-app Pod에 대해 nginx-ingress namespace에서 오는 트래픽만 허용하는 NetworkPolicy 생성/수정
    load_k8s_config()

    api = client.NetworkingV1Api()

    network_policy = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=POLICY_NAME,
            namespace=NAMESPACE
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(
                match_labels={
                    "app": TARGET_APP_LABEL
                }
            ),
            policy_types=["Ingress"],
            ingress=[
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={
                                    "kubernetes.io/metadata.name": INGRESS_NAMESPACE
                                }
                            )
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(
                            protocol="TCP",
                            port=8000
                        )
                    ]
                )
            ]
        )
    )

    try:
        # 기존 NetworkPolicy가 있으면 수정
        api.patch_namespaced_network_policy(
            name=POLICY_NAME,
            namespace=NAMESPACE,
            body=network_policy
        )

        logging.info(f"[BLOCKER] Updated NetworkPolicy: {POLICY_NAME}")

        return {
            "status": "updated",
            "policy": POLICY_NAME
        }

    except client.exceptions.ApiException as e:
        # 없으면 새로 생성
        if e.status == 404:
            api.create_namespaced_network_policy(
                namespace=NAMESPACE,
                body=network_policy
            )

            logging.info(f"[BLOCKER] Created NetworkPolicy: {POLICY_NAME}")

            return {
                "status": "created",
                "policy": POLICY_NAME
            }

        logging.error(f"[BLOCKER] Failed to apply NetworkPolicy: {e}")

        return {
            "status": "error",
            "message": str(e)
        }