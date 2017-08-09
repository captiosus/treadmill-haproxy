"""Starts and runs the orchestrator and watcher for every configured service"""

import atexit
import logging
import sys

from haproxyadmin import haproxy
from twisted.internet import task
from twisted.internet import reactor
from twisted.python import log

import configurator
import haproxy_cmd
import orchestrator
import watcher

LOOP_TIME = 7


class Conductor(object):
    """Launches orchestrators and watchers and starts event loop"""
    def __init__(self, socket, config_file, haproxy_file):
        """Parse the config file and create corresponding watchers and pools"""
        self._watchers = []
        self._orchestrators = []

        # Config parser
        self._configurator = configurator.Configurator(socket, config_file,
                                                       haproxy_file)

        # Get list of services and their configs
        services = self._configurator.parse_config()

        # Write the initial configuration to file
        self._configurator.config_write()

        # If there is an existing HAProxy running that is using the same
        # pid file, take over the existing to avoid conflicts
        if haproxy_cmd.haproxy_proc():
            haproxy_cmd.restart_haproxy()
        else:
            haproxy_cmd.start_haproxy()

        # Instantiate initial connection to haproxy socket only once
        haproxy_sock = haproxy.HAProxy(socket_dir=socket)

        # Share the single instance of haproxy socket and config parser for
        # efficiency
        for service_name, service in services.items():
            self._watchers.append(
                watcher.Watcher(service_name, service, self._configurator))

            # Only create orchestrators when the config is present
            if 'elasticity' in service:
                self._orchestrators.append(
                    orchestrator.Orchestrator(service_name, service,
                                              haproxy_sock))

        # Run self._cleanup on exit
        atexit.register(self._cleanup)

    def _cleanup(self):
        """Ran on exit. Stops haproxy"""
        haproxy_cmd.stop_haproxy()

    def loop(self):
        """Loop through watchers and run the monitor loop for each"""
        # Track if any of the services have changes that need to be committed
        changes = False
        for watch in self._watchers:
            # Check for the return value of the loop. Indicates whether each
            # individual watcher has changes that need to be comitted to the
            # haproxy config
            if watch.loop():
                changes = True

        if changes:
            # Commit once after all services have been processed for efficiency
            logging.debug("Write to config and restart")
            self._configurator.config_write()
            haproxy_cmd.restart_haproxy()

        # Orchestrator processed after watcher. Pre-existing containers need to
        # be processed by watcher first. If not processed, orchestrator will
        # create more servers thinking that there are not enough.
        for orch in self._orchestrators:
            orch.loop()

    def monitor(self):
        """Begin monitor loop"""
        log.startLogging(sys.stdout)
        loop = task.LoopingCall(self.loop)
        loop.start(LOOP_TIME)
        reactor.run()
