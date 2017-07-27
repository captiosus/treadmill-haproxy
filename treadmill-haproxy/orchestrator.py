import sys

from haproxyadmin import haproxy
from twisted.internet import task
from twisted.internet import reactor
from twisted.python import log

import haproxy_config
import pool

class Orchestrator(object):
    """Launches watchers and starts event loop"""
    def __init__(self, socket, config_file, haproxy_file):
        self._loop = None
        self._watchers = []
        config_parser = haproxy_config.ConfParse(config_file, haproxy_file)
        services = config_parser.parse_config()
        config_parser.config_write()
        hap = haproxy.HAProxy(socket_dir=socket)
        for service in services:
            self._watchers.append(
                pool.Pool(service, services[service], hap.backend(service),
                          config_parser))

    def monitor_loop(self):
        """Loop through watchers and run the monitor loop for each"""
        for watcher in self._watchers:
            watcher.monitor_loop()

    def monitor(self):
        """Begin monitor loop"""
        log.startLogging(sys.stdout)
        self._loop = task.LoopingCall(self.monitor_loop)
        self._loop.start(2)
        reactor.run()
