"""Temporary solution to starting and stopping treadmill containers"""

import subprocess

def start_container(app, manifest):
    cmd = ['treadmill', 'admin', 'master', 'app', 'schedule', '-m', manifest,
           '--env', 'prod', '--proid', 'treadmld', app]
    subprocess.call(cmd)

def stop_container(app, instance):
    cmd = ['treadmill', 'admin', 'master', 'app', 'delete', app + '#' + instance]
    subprocess.call(cmd)

def stop_containers(app):
    cmd = ['treadmill', 'admin', 'master', 'app', 'delete', app]
    subprocess.call(cmd)

def discover_container(app, instance=None):
    if instance:
        app += '#' + instance
    cmd = ['treadmill', 'admin', 'discovery', app]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    containers = proc.communicate()[0].decode('utf-8').strip().split('\n')
    containers_fmt = {}
    for container in containers:
        if container:
            name, address = container.split(' ')
            app, _, name = name.split(':')
            instance = app.split('#')[1]
            containers_fmt[instance] = {'name': name,
                                        'address': address}
        else:
            return None
    return containers_fmt
