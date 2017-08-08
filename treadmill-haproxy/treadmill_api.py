"""Temporary solution to starting and stopping treadmill containers"""

import subprocess

def start_container(app, manifest):
    """Starts a container through the command line"""
    cmd = ['treadmill', 'admin', 'master', 'app', 'schedule', '-m', manifest,
           '--env', 'prod', '--proid', 'treadmld', app]
    subprocess.call(cmd)

def stop_container(app, instance):
    """Stops a container through the command line"""
    cmd = ['treadmill', 'admin', 'master', 'app', 'delete', app + '#' + instance]
    subprocess.call(cmd)

def stop_containers(app):
    """Stops all containers and deletes the app through the command line"""
    cmd = ['treadmill', 'admin', 'master', 'app', 'delete', app]
    subprocess.call(cmd)

def discover_container(app, instance=None):
    """Performs discovery of a containers endpoints. Filters based on instance
    if parameter specified. Formats results into a dict keyed by instance and
    then by name of endpoint.
    """
    # Give more specific appname to discovery
    if instance:
        app += '#' + instance
    cmd = ['treadmill', 'admin', 'discovery', app]
    # Popen to allow access to results
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    # Decode to utf-8 to make working with results easier
    # Strip to remove trailing new line
    # Split by new line to separate results
    endpoints = proc.communicate()[0].decode('utf-8').strip().split('\n')
    endpoints_fmt = {}
    for endpoint in endpoints:
        if endpoint:
            name, address = endpoint.split(' ')
            app, _, name = name.split(':')
            instance = app.split('#')[1]
            endpoints_fmt.setdefault(instance, {})
            endpoints_fmt[instance][name] = address
        else:
            return None
    return endpoints_fmt
