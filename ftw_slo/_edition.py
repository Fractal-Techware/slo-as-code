"""This copy of ftw-slo is the Free edition (3 SLI templates, rule output).

The paid editions add 18 more SLI templates and further outputs; see README.md.
"""
EDITION = "free"
ALL_TEMPLATES = {
    "blackbox-probe": "pro",
    "envoy-availability": "pro",
    "generic-error-ratio": "pro",
    "generic-ratio": "free",
    "grpc-availability": "starter",
    "histogram-latency-classic": "pro",
    "histogram-latency-native": "pro",
    "http-availability": "free",
    "http-latency": "free",
    "ingress-nginx-availability": "starter",
    "istio-availability": "pro",
    "istio-latency": "pro",
    "k8s-cronjob-freshness": "pro",
    "kafka-consumer-freshness": "pro",
    "linkerd-availability": "pro",
    "otel-spanmetrics-availability": "pro",
    "otel-spanmetrics-latency": "pro",
    "postgres-availability": "pro",
    "queue-processing": "pro",
    "traefik-availability": "pro",
    "traefik-latency": "pro",
}
