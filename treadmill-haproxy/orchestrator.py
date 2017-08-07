import sys

from haproxyadmin import haproxy
from twisted.internet import task
from twisted.internet import reactor
from twisted.python import log

import haproxy_config
import haproxy_control
import pool
import watcher

class Orchestrator(object):
    """Launches watchers and starts event loop"""
    def __init__(self, socket, config_file, haproxy_file):
        self._loop = None
        self._watchers = []
        self._pools = []

        config_parser = haproxy_config.ConfParse(config_file, haproxy_file)
        services = config_parser.parse_config()
        config_parser.config_write()

        if haproxy_control.is_running():
            haproxy_control.restart_haproxy()
        else:
            haproxy_control.start_haproxy()

        haproxy_sock = haproxy.HAProxy(socket_dir=socket)

        for service_name, service in services.items():
            self._watchers.append(
                watcher.Watcher(service_name, service, config_parser))

            if 'elasticity' in service:
                self._pools.append(
                    pool.Pool(service_name, service, haproxy_sock,
                              config_parser))

    def loop(self):
        """Loop through watchers and run the monitor loop for each"""
        for service_watcher in self._watchers:
            service_watcher.loop()

        for service_pool in self._pools:
            service_pool.loop()

    def monitor(self):
        """Begin monitor loop"""
        log.startLogging(sys.stdout)
        self._loop = task.LoopingCall(self.loop)
        self._loop.start(5)
        reactor.run()
