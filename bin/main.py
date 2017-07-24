"""Main launcher for HAProxy watcher."""

import logging

import click
from haproxyadmin import haproxy
import twisted.internet

import haproxy_config
import pool

_LOGGER = logging.getLogger(__name__)

class Orchestrator(object):
    """Launches watchers and starts event loop"""
    def __init__(self, socket, config_file, haproxy_file):
        self._haproxy = haproxy.HAProxy(socket_dir=socket)
        self._loop = None
        self._watchers = []
        config_parser = haproxy_config.ConfParse(config_file, haproxy_file)
        services = config_parser.load_services()
        config_parser.config_write()

        for service in services:
            self._watchers.append(
                pool.Pool(services[service], self._haproxy))

    def monitor_loop(self):
        """Loop through watchers and run the monitor loop for each"""
        for watcher in self._watchers:
            watcher.monitor_loop()

    def monitor(self):
        """Begin monitor loop"""
        self._loop = twisted.internet.task.LoopingCall(self.monitor_loop)
        self._loop.start(2)
        twisted.internet.reactor.run()

@click.command()
@click.option('--socket', default='/run/haproxy', help='HAProxy socket')
@click.option('--config', 'config_file',
              default='../config/treadmill-haproxy.json',
              help="Configuration file")
@click.option('--haproxy-config', 'haproxy_file',
              default='../config/haproxy.conf')
def main(socket, config_file, haproxy_file):
    """Configure logging and start monitering"""
    logging.basicConfig(level=logging.INFO)
    _LOGGER.setLevel(logging.INFO)
    logging.getLogger('requests').setLevel(logging.CRITICAL)
    orch = Orchestrator(socket, config_file, haproxy_file)
    orch.monitor()
