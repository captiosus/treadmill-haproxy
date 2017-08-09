"""Treadmill orchestrator for HAProxy"""

import collections
import logging
import time

import treadmill_api

HISTORY_QUEUE = 10
_LOGGER = logging.getLogger(__name__)


def find_max(num, history):
    """Finds the max number in a list after appending the current number"""
    # Only keep a specified amount of history
    if len(history) > HISTORY_QUEUE:
        history.popleft()
    history.append(num)
    return max(history)


class Orchestrator(object):
    """Orchestrates treadmill containers"""
    def __init__(self, service_name, service, haproxy):
        """Setup necessary globals and registers cleanup for exit"""
        self._service_name = service_name
        self._haproxy = haproxy.backend(service_name)
        service['elasticity']['history'] = collections.deque([])
        service['elasticity']['conn_history'] = collections.deque([])

        self._elasticity = service['elasticity']
        self._treadmill = service['treadmill']

        self._elasticity['target'] = self._elasticity['min_servers']
        self._elasticity['pending'] = 0
        self._elasticity['healthy'] = None

        # If hold_conns is specified, the frontend is needed so connections
        # can be restricted and the backend of the proxy is needed to know
        # number of incoming connections before the reach the real backend.
        # After connections are opened, the real backend stats would be
        # equivalent to the proxy backend.
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self._haproxy_front = haproxy.frontend(service_name)
            self._haproxy_proxy = haproxy.backend(service_name + '_proxy')

    def add_server(self):
        """Starts a treadmill container"""
        _LOGGER.info('Add pending server')
        treadmill_api.start_container(self._treadmill['appname'],
                                      self._treadmill['manifest'])

    def delete_server(self, instance):
        """Deletes a treadmill container"""
        _LOGGER.info('Delete server')
        treadmill_api.stop_container(self._treadmill['appname'], instance)

    def healthy_servers(self):
        """Checks for all servers considered healthy"""
        healthy = []
        for server in self._haproxy.servers():
            # Status can be in the midway point between DOWN and UP. Just can't
            # be down.
            if server.status != 'DOWN':
                healthy.append(server)
        return healthy

    def adjust_servers(self):
        """Adjusts servers based on the elasticity configuration.
        Uses the largest value stored in queue for calculations to avoid
        random dips. Requires continuous levels of low activity to drop servers.
        """
        if self._elasticity['method'] == 'conn_rate':
            measure = int(self._haproxy.metric('rate'))
        elif self._elasticity['method'] == 'queue':
            measure = int(self._haproxy.metric('qtime'))
        elif self._elasticity['method'] == 'response':
            measure = int(self._haproxy.metric('rtime'))
        max_measure = find_max(measure, self._elasticity['history'])

        if 'steps' in self._elasticity:
            self.server_steps(max_measure)
        elif 'breakpoint' in self._elasticity:
            self.breakpoint(measure, max_measure)
        elif 'scale' in self._elasticity:
            self.scale(max_measure)

    def server_steps(self, max_measure):
        """Adjusts servers based on a list of steps indicating when to add a
        servers.

        Example:
        steps = [100, 300]

        When measure reach over 100, add a server
        When over 300, add another server
        When measure dips below 300, remove a server
        """
        _LOGGER.debug('Max Measure: %d', max_measure)
        # Reset to minimum number of servers
        self._elasticity['target'] = self._elasticity['min_servers']
        # Finds amount of numbers in steps that is lower than the current max
        # measure
        for measure in self._elasticity['steps']:
            if max_measure > measure:
                self._elasticity['target'] += 1

    def scale(self, max_measure):
        """Adjusts servers based on a growing scale.

        Example:
        scale: 100

        At 100 connections, a server is added
        At 200, another server is added
        At 199, that server is removed
        """

        _LOGGER.debug('Max Measure: %d', max_measure)

        # Every scale amount of servers, a server is added. The target is the
        # amount of scales in the max measure.
        self._elasticity['target'] = int(max_measure /
                                         self._elasticity['scale'])
        # Account for min servers
        self._elasticity['target'] += self._elasticity['min_servers']

    def breakpoint(self, curr_measure, max_measure):
        """Adjusts servers based on a breakpoint number. Suited for
        measurements where adding more servers reduces the measurements.

        Example:
        breakpoint: 10

        When queue time for one connection is 20, another server is added
        Another connection has a queue time of 11, another server is added
        If the historically high queue time drops below 10, a server is removed
        """

        _LOGGER.debug('Max Measure: %d', max_measure)
        _LOGGER.debug('Curr Measure: %d', curr_measure)
        # Uses the current measure instead of the historically largest measure
        # to avoid continuously adding servers
        if curr_measure > self._elasticity['breakpoint']:
            # If there is no configured max number of servers or the target
            # number of servers is below the max, a server can be added
            self._elasticity['target'] += 1
        # If the historical largest measure is lower than the breakpoint,
        # remove a server
        if max_measure < self._elasticity['breakpoint']:
            self._elasticity['target'] -= 1

    def hold_conns(self):
        """Closes connections for a service until there is a connection waiting.

        Uses two listen blocks. First listen block is for pointing at potential
        servers. The second points at the first listen block. The first is
        named after the service and the second has "_proxy" appended.

        The container stays alive for a configurable amount of time (cooldown).

        Blocks connections to the service backend by setting max connections
        to 0. For now, it will reset the maxconn to 2000 which is the default
        global max.
        """

        # If cooldown time has passed or first run (shutdown_time defaults to 0)
        if self._elasticity['shutoff_time'] < time.time():
            new_conns = int(self._haproxy_proxy.metric('scur'))
            _LOGGER.debug('New Conns: %d', new_conns)

            # If there are more than 0 connections
            if new_conns:
                # Raise min_servers to avoid conflict with adjust_servers
                self._elasticity['min_servers'] += 1
                self._elasticity['target'] += 1

                # Set new shutoff_time
                new_time = time.time() + self._elasticity['cooldown']
                self._elasticity['shutoff_time'] = new_time
            elif self._elasticity['target'] > 0:
                # Lower min_servers to avoid conflict with adjust_servers
                self._elasticity['min_servers'] -= 1
                self._elasticity['target'] -= 1

            # Set max connections to 0 if there are no healthy_servers
            if self._elasticity['healthy']:
                self._haproxy_front.setmaxconn(2000)
            else:
                self._haproxy_front.setmaxconn(0)

    def keep_target(self):
        """Adds and removes servers to keep number of healthy servers level
        with the target number of servers

        Keeps track of pending servers because treadmill containers do not
        start and stop instantly

        Pending deleted servers are counted as negative because they account
        for healthy servers that do not count

        Pending added servers are counted as positive because they accounted
        for healthy servers that should count
        """
        # Make sure target is above minimum and below maximum
        self._elasticity['target'] = max(self._elasticity['min_servers'],
                                         self._elasticity['target'])
        if self._elasticity['max_servers']:
            self._elasticity['target'] = min(self._elasticity['max_servers'],
                                             self._elasticity['target'])

        _LOGGER.debug('Target %d', self._elasticity['target'])

        new_healthy = self.healthy_servers()

        # Can be empty list, but None specifically means initial loop
        if self._elasticity['healthy'] != None:
            # Resolves pending servers. Servers that change between loops were
            # accounted for in the pending count. If there are new healthy
            # servers, the pending added servers have resolved. Pending is
            # subtracted. If there are fewer healthy servers, then
            # pending deleted servers have resolved. Pending is added.
            self._elasticity['pending'] -= (len(new_healthy) -
                                            len(self._elasticity['healthy']))

        self._elasticity['healthy'] = new_healthy

        _LOGGER.debug('Pending: %d', self._elasticity['pending'])
        _LOGGER.debug('Healthy: %d', len(self._elasticity['healthy']))

        # Difference between the target and number of available servers + the
        # pending number of added and deleted servers
        diff = (self._elasticity['target'] - len(self._elasticity['healthy']) -
                self._elasticity['pending'])
        _LOGGER.debug('Diff: %d', + diff)

        # If there are more healthy + pending, delete servers and adjust
        if diff < 0:
            # Prevent attempting deletion of pending servers that can't
            # be deleted yet.
            diff = min(abs(diff), len(self._elasticity['healthy']))
            for idx in range(diff):
                self.delete_server(self._elasticity['healthy'][idx].name)
                self._elasticity['pending'] -= 1
        else:
            for _ in range(abs(diff)):
                self.add_server()
                self._elasticity['pending'] += 1

    def loop(self):
        """Main loop. Runs adjust server if method is configured. Holds
        connections if configured. Always tries to keep target"""
        _LOGGER.info('Starting orchestrator loop for %s', self._service_name)
        if 'method' in self._elasticity:
            self.adjust_servers()
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self.hold_conns()
        self.keep_target()
