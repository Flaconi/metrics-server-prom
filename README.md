# Kubernetes Metrics Server Prometheus Adapter

**[Motivation](#motivation)** |
**[Metrics transformation](#metrics-transformation)** |
**[License](#license)**

[![release](https://img.shields.io/github/tag/Flaconi/metrics-server-prom.svg)](https://github.com/cFlaconi/metrics-server-prom/releases)

<a target="_blank" title="DockerHub" href="https://hub.docker.com/r/flaconi/metrics-server-prom/"><img src="https://dockeri.co/image/flaconi/metrics-server-prom" /></a>

## Motivation

### What is provided

A Docker image on which [Prometheus](https://github.com/prometheus/prometheus) can scrape Kubernetes metrics provided by **[metrics-server](https://github.com/kubernetes-incubator/metrics-server)**. The image can run directly in a k8s cluster where Prometheus can use it as a target.

### Why is it needed

metrics-server seems to be the [successor of heapster](https://github.com/kubernetes/heapster) for Kubernetes monitoring. However, metrics-server currently only provides its metrics in JSON format via the Kubernetes API server.

Prometheus on the other hand expects a special [text-based format](https://prometheus.io/docs/instrumenting/exposition_formats/#comments-help-text-and-type-information).
So in order for Prometheus to scrape those metrics, they must be transparently transformed from JSON to its own format on every request.

### Differences

Other than metrics-server itself, this Docker container provides additional metrics metadata that are
retrieved via `python kubernetes client` API calls and included in the Prometheus output.

### How does it work

1. Prometheus scrapes the Docker container on `:9100/metrics`
2. Inside the Docker container [uwsgi](https://github.com/unbit/uwsgi) is proxying the request to [kube proxy](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/)
3. The Python kubernetes client will be created and requests the k8s API
4. The API replies with JSON formatted metrics provided by metrics-server
5. uwsgi calls [transform.py](data/src/transform.py)
6. transform.py rewrites the JSON into Prometheus readable output and hands the result back to uwsgi
8. uwsgi sends the final response back


## Usage

### Run metrics-server-prom

Simply run the Docker image in a cluster with a mounted token for a ServiceAccount in `/var/run/secrets/kubernetes.io/serviceaccount/token` (needs access to call the API)

### Configure Prometheus

`prometheus.yml`:
```yml
scrape_configs:
  - job_name: 'kubernetes'
    scrape_interval: '15s'
    metrics_path: '/metrics'
    static_configs:
      - targets:
        - <DOCKER_IP_ADDRESS>:9100
```

## Metrics transformation

metrics-server provices metrics in the following format:
```json
{
  "kind": "PodMetricsList",
  "apiVersion": "metrics.k8s.io/v1beta1",
  "metadata": {
    "selfLink": "/apis/metrics.k8s.io/v1beta1/pods"
  },
  "items": [
    {
      "metadata": {
        "name": "etcd-server-events-abc",
        "namespace": "kube-system",
        "selfLink": "/apis/metrics.k8s.io/v1beta1/namespaces/kube-system/pods/etcd-server-events-ip-10-30-78-99.eu-central-1.compute.internal",
        "creationTimestamp": "2018-08-20T03:19:05Z"
      },
      "timestamp": "2018-08-20T03:19:00Z",
      "window": "1m0s",
      "containers": [
        {
          "name": "etcd-container",
          "usage": {
            "cpu": "7m",
            "memory": "125448Ki"
          }
        }
      ]
    },

  ]
}
```

metrics-server-prom transforms it to the following format:

**Note:** Additional metadata (`node` and `ip`) have been added.
```
# HELP kube_metrics_server_pod_cpu The CPU time of a pod in seconds.
# TYPE kube_metrics_server_pod_cpu gauge
kube_metrics_server_pod_cpu{node="ip-10-30-78-99.eu-central-1.compute.internal",pod="etcd-server-events-abc",ip="10.30.62.138",container="etcd-container",namespace="kube-system"} 420
# HELP kube_metrics_server_pod_mem The memory of a pod in KiloBytes.
# TYPE kube_metrics_server_pod_mem gauge
kube_metrics_server_pod_mem{node="ip-10-30-78-99.eu-central-1.compute.internal",pod="etcd-server-events-abc",ip="10.30.62.138",container="etcd-container",namespace="kube-system"} 128475136
```

## License

[MIT License](LICENSE)

Copyright (c) 2018 [cytopia](https://github.com/cytopia)
