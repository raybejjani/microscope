import time
import argparse
import sys
from multiprocessing import Process, Queue
from typing import List

from kubernetes import config
from kubernetes.client import Configuration
from kubernetes.client.apis import core_v1_api
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream



def connect_monitor(pod_name: str, namespace: str, queue: Queue,
                    close_queue: Queue, api: core_v1_api.CoreV1Api,
                    endpoint: int):
    try:
        resp = api.read_namespaced_pod(name=pod_name,
                                       namespace=namespace)
    except ApiException as e:
        if e.status != 404:
            print("Unknown error: %s" % e)
            exit(1)


# calling exec and wait for response.
    exec_command = [
        'cilium',
        'monitor',
        '-v']

    if endpoint:
        exec_command.append("--related-to")
        exec_command.append(str(endpoint))

    resp = stream(api.connect_get_namespaced_pod_exec, pod_name, namespace,
                  command=exec_command,
                  stderr=True, stdin=True,
                  stdout=True, tty=False,
                  _preload_content=False)

    while resp.is_open():
        resp.update(timeout=1)
        if resp.peek_stdout():
            queue.put({"name": pod_name,  "output": resp.read_stdout()})
        if resp.peek_stderr():
            queue.put({"name": pod_name,  "output": resp.read_stderr()})
        if not close_queue.empty():
            break

    resp.close()

def run_monitors(endpoint: int, queue: Queue,
                 close_queue: Queue) -> List[Process]:

    config.load_kube_config()
    c = Configuration()
    c.assert_hostname = False
    Configuration.set_default(c)
    api = core_v1_api.CoreV1Api()
    namespace = 'kube-system'

    try:
        pods = api.list_namespaced_pod(namespace,
                                       label_selector="k8s-app=cilium")
    except APIException as e:
        print("could not list Cilium pods: %s\n" % e)
        sys.exit(1)

    names = [pod.metadata.name for pod in pods.items]

    processes = [Process(target=connect_monitor,
                         args=(name, namespace, queue, close_queue, api,
                               endpoint))
                 for name in names]
    for p in processes:
        p.start()

    return processes

def close_monitors(close_queue: Queue, procs: List[Process]):
    print("closing")
    close_queue.put("close")
    for p in processes:
        p.join()

def wait_for_output(queue: Queue):
    while True:
        print(q.get())
        time.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoint', type=int, help="endpoint id", default=0)
    args = parser.parse_args()

    q = Queue()
    close_queue = Queue()
    processes = run_monitors(args.endpoint, q, close_queue)

    try:
        wait_for_output(q)
    except KeyboardInterrupt:
        pass
    finally:
        close_monitors(close_queue, processes)