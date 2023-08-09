# -*- coding: utf-8 -*-
'''
Auther:  cytopia
License: MIT

Transformer for kubernetes-incubator/metrics-server from json
into Prometheus readable format.
'''

import os
import json
import re
import datetime
import subprocess
import kubernetes.client
from kubernetes import client, config
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from flask import Flask
from flask import Response

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

'''
Globals that specify at which url metrics for nodes and pods can be found
'''

with open('/var/run/secrets/kubernetes.io/serviceaccount/token','r') as saFile:
    saToken = saFile.read()

API = 'https://kubernetes.default.svc'
URL_NODES = API + '/apis/metrics.k8s.io/v1beta1/nodes'
URL_PODS = API + '/apis/metrics.k8s.io/v1beta1/pods'
HEADERS = {"Authorization": "Bearer "+saToken}

# create ApiClient
cConfiguration = client.Configuration()
cConfiguration.host = API
cConfiguration.verify_ssl = False
cConfiguration.api_key = {"authorization": "Bearer " + saToken}
cApiClient = client.ApiClient(cConfiguration)
v1 = client.CoreV1Api(cApiClient)

def json2dict(data):
    '''
    Safely convert a potential JSON string into a dict

    Args:
        data (str): Valid or invalid JSON string.
    Returns:
        dict: Returns dict of string or empty dict in case of invalid JSON input.
    '''
    json_object = dict()
    try:
        json_object = json.loads(data)
    except ValueError:
        pass
    return json_object


def val2base(string):
    '''
    Transforms an arbitrary string value into a prometheus valid base (int|float) type by best guess:
    https://prometheus.io/docs/instrumenting/exposition_formats/#comments-help-text-and-type-information
    https://golang.org/pkg/strconv/#ParseFloat
    https://golang.org/pkg/strconv/#ParseInt

    Currently able to handle values of:
      15Ki
      15Mi
      15Gi
      1m0s
      5m

    Args:
        string (str): metrics-server metrics value
    Returns:
        int|float|string: transformed value or initial value if no transformation regex was found.
    '''

    # Transform KiloByte into Bytes
    val = re.search('^([0-9]+)Ki$', string, re.IGNORECASE)
    if val and val.group(1):
        return int(val.group(1)) * 1024
    # Transform Megabytes into Bytes
    val = re.search('^([0-9]+)Mi$', string, re.IGNORECASE)
    if val and val.group(1):
        return int(val.group(1)) * (1024*1024)
    # Transform Gigabytes into Bytes
    val = re.search('^([0-9]+)Gi$', string, re.IGNORECASE)
    if val and val.group(1):
        return int(val.group(1)) * (1024*1024*1024)
    # Transform Terrabytes into Bytes
    val = re.search('^([0-9]+)Ti$', string, re.IGNORECASE)
    if val and val.group(1):
        return int(val.group(1)) * (1024*1024*1024*1024)

    # Convert cpu nanocores into cores
    val = re.search('^([0-9]+)n$', string, re.IGNORECASE)
    if val and val.group(1):
        return float(val.group(1)) / 1000000000
    # Convert cpu millicores into cores
    val = re.search('^([0-9]+)m$', string, re.IGNORECASE)
    if val and val.group(1):
        return float(val.group(1)) / 1000

    # Otherwise return value as it came in
    return string


def trans_node_metrics(string):
    '''
    Transforms metrics-server node metrics (in the form of a JSON string) into Prometheus
    readable metrics format (text-based).
    https://prometheus.io/docs/instrumenting/exposition_formats/
    https://en.wikipedia.org/wiki/Extended_Backus%E2%80%93Naur_form

    Args:
        string (str): Valid or invalid JSON string.
    Returns:
        str: Returns newline separated node metrics ready for Prometheus to pull.
    '''
    data = json2dict(string)
    cpu = []
    mem = []

    cpu.append('# HELP kube_metrics_server_node_cpu The CPU cores')
    cpu.append('# TYPE kube_metrics_server_node_cpu gauge')
    mem.append('# HELP kube_metrics_server_node_mem The memory of a node in Bytes.')
    mem.append('# TYPE kube_metrics_server_node_mem gauge')

    tpl = 'kube_metrics_server_node_{}{{node="{}", nodegroup="{}", zone="{}", instancetype="{}", capacitytype="{}"}} {}'

    for node in data.get('items', []):
        lbl = {
            'node': node.get('metadata', []).get('name', ''),
            'nodegr': node.get('metadata', []).get('labels', []).get('eks.amazonaws.com/nodegroup', ''),
            'zone': node.get('metadata', []).get('labels', []).get('topology.kubernetes.io/zone', ''),
            'instancetype': node.get('metadata', []).get('labels', []).get('beta.kubernetes.io/instance-type', ''),
            'capacitytype': node.get('metadata', []).get('labels', []).get('eks.amazonaws.com/capacityType', '')
        }
        val = {
            'cpu': node.get('usage', []).get('cpu', ''),
            'mem': node.get('usage', []).get('memory', '')
        }
        cpu.append(tpl.format(
          'cpu',
          lbl['node'],
          lbl['nodegr'],
          lbl['zone'],
          lbl['instancetype'],
          lbl['capacitytype'],
          val2base(val['cpu'])
        ))
        mem.append(tpl.format(
          'mem',
          lbl['node'],
          lbl['nodegr'],
          lbl['zone'],
          lbl['instancetype'],
          lbl['capacitytype'],
          val2base(val['mem'])
        ))
    return '\n'.join(cpu + mem)


def trans_pod_metrics(string):
    '''
    Transforms metrics-server pod metrics (in the form of a JSON string) into Prometheus
    readable metrics format (text-based).
    https://prometheus.io/docs/instrumenting/exposition_formats/
    https://en.wikipedia.org/wiki/Extended_Backus%E2%80%93Naur_form

    Args:
        string (str): Valid or invalid JSON string.
    Returns:
        str: Returns newline separated node metrics ready for Prometheus to pull.
    '''
    data = json2dict(string)
    more = get_pod_metrics_from_cli()
    cpu = []
    mem = []
    age = []

    cpu.append('# HELP kube_metrics_server_pod_cpu The CPU cores of a pod.')
    cpu.append('# TYPE kube_metrics_server_pod_cpu gauge')
    mem.append('# HELP kube_metrics_server_pod_mem The memory of a pod in Bytes.')
    mem.append('# TYPE kube_metrics_server_pod_mem gauge')
    age.append('# HELP kube_metrics_server_pod_age The age of a pod in seconds.')
    age.append('# TYPE kube_metrics_server_pod_age gauge')

    tpl = 'kube_metrics_server_pod_{}{{node="{}", pod="{}", ip="{}",container="{}", namespace="{}", age="{}", age_seconds="{}", restarts={} }} {}'

    for pod in data.get('items', []):
        lbl = {
            'pod': pod.get('metadata', []).get('name', ''),
            'ns': pod.get('metadata', []).get('namespace', '')
        }
        # Loop over defined container in each pod
        for container in pod.get('containers', []):
            lbl['cont'] = container.get('name', '')
            val = {
                'cpu': container.get('usage', []).get('cpu', ''),
                'mem': container.get('usage', []).get('memory', '')
            }
            cpu.append(tpl.format(
                'cpu',
                more[lbl['pod']]['node'],
                lbl['pod'],
                more[lbl['pod']]['ip'],
                lbl['cont'],
                lbl['ns'],
                more[lbl['pod']]['age'],
                more[lbl['pod']]['age_seconds'],
                more[lbl['pod']]['restarts'],
                val2base(val['cpu'])
            ))
            mem.append(tpl.format(
                'mem',
                more[lbl['pod']]['node'],
                lbl['pod'],
                more[lbl['pod']]['ip'],
                lbl['cont'],
                lbl['ns'],
                more[lbl['pod']]['age'],
                more[lbl['pod']]['age_seconds'],
                more[lbl['pod']]['restarts'],
                val2base(val['mem'])
            ))
            age.append(tpl.format(
                'age',
                more[lbl['pod']]['node'],
                lbl['pod'],
                more[lbl['pod']]['ip'],
                lbl['cont'],
                lbl['ns'],
                more[lbl['pod']]['age'],
                more[lbl['pod']]['age_seconds'],
                more[lbl['pod']]['restarts'],
                more[lbl['pod']]['age_seconds']
            ))
    return '\n'.join(cpu + mem + age)


def get_pod_metrics_from_cli():
    '''
    Get pod metrics via CLI (allows to have node for enriching the data)

    Returns
        data: Dictionary of additional pod metrics
    '''

    data = dict()

    # 1:NS | 2:Name | 3:Ready | 4:Status | 5:Restarts | 6:Age | 7:IP | 8:Node | 9: NOMINATED NODE
    ret = v1.list_pod_for_all_namespaces(watch=False)
    for line in ret.items:

        data[line.metadata.name] = {
            'ns': line.metadata.namespace,
            'name': line.metadata.name,
            'ready': line.status.container_statuses[0].ready,
            'status': line.status.phase,
            'restarts': line.status.container_statuses[0].restart_count,
            'age': age(line.metadata.creation_timestamp, 'formatted'),
            'age_seconds': age(line.metadata.creation_timestamp, 'secs'),
            'ip': line.status.pod_ip,
            'node': line.spec.node_name
        }

    return data

def age(starttime, format):

    # calculate age in different formats
    now = datetime.datetime.now().astimezone()
    diff = now-starttime

    if format == 'formatted':
        days = diff.days
        hours, rest = divmod(diff.seconds, 3600)
        mins, secs = divmod(rest, 60)
        age = f"{days}d {hours}h {mins}m {secs}s"
    elif format == 'secs':
        age = diff.total_seconds()
    elif format == 'mins':
        age = diff.total_seconds()/60
    elif format == 'hours':
        age = diff.total_seconds()/60/60
    elif format == 'days':
        age = diff.total_seconds()/60/60/24

    return age

application = Flask(__name__) # pylint: disable=invalid-name

@application.route("/metrics")
def metrics():
    '''
    This function is the /metrics http entrypoint and will itself do the callback
    to gather node and pod metrics from specified kubernetes api urls.
    Current output is JSON and we must therefore transform both results
    into Prometheus readable format:
        https://prometheus.io/docs/instrumenting/exposition_formats/
        https://en.wikipedia.org/wiki/Extended_Backus%E2%80%93Naur_form
    '''
    # Get info from K8s API
    req = {
        'nodes': requests.get(URL_NODES, verify=False, headers=HEADERS),
        'pods': requests.get(URL_PODS, verify=False, headers=HEADERS)
    }

    # Object to JSON text
    json = {
        'nodes': req['nodes'].text,
        'pods': req['pods'].text
    }

    # Convert to Prometheus format
    prom = {
        'nodes': trans_node_metrics(json['nodes']),
        'pods': trans_pod_metrics(json['pods'])
    }
    get_pod_metrics_from_cli()
    # Return response
    return Response(prom['nodes'] + '\n' + prom['pods'], status=200, mimetype='text/plain')


@application.route("/healthz")
def healthz():
    '''
    This function is the /healthz http entrypoint and will itself do two callbacks
    in order to determine the health of node and pod metric endpoints.

    Returns:
        Response: Flask Response object that will handle returning http header and body.
                  If one of the pages (nodes or pods metrics by metrics-server) fails,
                  it will report an overall failure and respond with 503 (service unavailable).
                  If both a good, it will respond with 200.
    '''
    req = {
        'nodes': requests.get(URL_NODES, verify=False, headers=HEADERS),
        'pods': requests.get(URL_PODS, verify=False, headers=HEADERS)
    }
    health = 'ok'
    status = 200
    if req['nodes'].status_code != 200:
        health = 'failed'
        status = 503
    if req['pods'].status_code != 200:
        health = 'failed'
        status = 503

    return Response(health, status=status, mimetype='text/plain')


@application.route("/")
def index():
    '''
    This function is the / http entrypoint and will simply provide a link to
    the metrics and health page. This is done, because all metrics endpoints I have encountered
    so far also do it exactly this way.

    Returns:
        Response: Flask Response object that will handle returning http header and body.
                  Returns default Prometheus endpoint index page (http 200) with links
                  to /healthz and /metrics.
    '''
    return '''
        <html>
        <head><title>metrics-server-prom</title></head>
        <body>
            <h1>metrics-server-prom</h1>
	    <ul>
                <li><a href='/metrics'>metrics</a></li>
                <li><a href='/healthz'>healthz</a></li>
	    </ul>
        </body>
        </html>
    '''

if __name__ == "__main__":
    application.run(host='0.0.0.0')
