"""Orchestrates the pool and watcher for every configured service"""

import atexit
import logging
import sys

from haproxyadmin import haproxy
from twisted.internet import task
from twisted.internet import reactor
from twisted.python import log

import haproxy_config
import haproxy_control
import pool
import watcher

LOOP_TIME = 7


class Orchestrator(object):
    """Launches watchers and starts event loop"""
    def __init__(self, socket, config_file, haproxy_file):
        """Parse the config file and create corresponding watchers and pools"""
        self._watchers = []
        self._pools = []

        # Config parser
        self._haproxy_parser = haproxy_config.ConfParse(socket, config_file,
                                                        haproxy_file)

        # Get list of services and their configs
        services = self._haproxy_parser.parse_config()

        # Write the initial configuration to file
        self._haproxy_parser.config_write()

        # If there is an existing HAProxy running that is using the same
        # pid file, take over the existing to avoid conflicts
        if haproxy_control.is_running():
            haproxy_control.restart_haproxy()
        else:
            haproxy_control.start_haproxy()

        # Instantiate initial connection to haproxy socket only once
        haproxy_sock = haproxy.HAProxy(socket_dir=socket)

        # Share the single instance of haproxy socket and config parser for
        # efficiency
        for service_name, service in services.items():
            self._watchers.append(
                watcher.Watcher(service_name, service, self._haproxy_parser))

            # Only create pools when the config is present
            if 'elasticity' in service:
                self._pools.append(
                    pool.Pool(service_name, service, haproxy_sock))

        # Run self._cleanup on exit
        atexit.register(self._cleanup)

    def _cleanup(self):
        """Ran on exit. Stops haproxy"""
        haproxy_control.stop_haproxy()

    def loop(self):
        """Loop through watchers and run the monitor loop for each"""
        # Track if any of the services have changes that need to be committed
        changes = False
        for service_watcher in self._watchers:
            # Check for the return value of the loop. Indicates whether each
            # individual watcher has changes that need to be comitted to the
            # haproxy config
            if service_watcher.loop():
                changes = True

        if changes:
            # Commit once after all services have been processed for efficiency
            logging.debug("Write to config and restart")
            self._haproxy_parser.config_write()
            haproxy_control.restart_haproxy()

        # Pool processed after watcher. Pre-existing containers need to be
        # processed by watcher first. If not processed, pool will create more
        # servers thinking that there are not enough.
        for service_pool in self._pools:
            service_pool.loop()

    def monitor(self):
        """Begin monitor loop"""
        log.startLogging(sys.stdout)
        loop = task.LoopingCall(self.loop)
        loop.start(LOOP_TIME)
        reactor.run()
