"""Treadmill based watcher for HAProxy"""

import atexit
import collections
import logging
import time

import treadmill_api
import haproxy_control

HISTORY_QUEUE = 15
_LOGGER = logging.getLogger(__name__)


class Pool(object):
    """Maintains pool of treadmill containers"""
    def __init__(self, service_name, service, haproxy):
        """Setup necessary globals and registers cleanup for exit"""
        self._service_name = service_name
        self._haproxy = haproxy.backend(service_name)
        service['elasticity']['history'] = collections.deque([])
        service['elasticity']['conn_history'] = collections.deque([])

        self._elasticity = service['elasticity']
        self._treadmill = service['treadmill']

        self._target = self._elasticity['min_servers']
        self._pending = 0
        self._healthy = None

        # If hold_conns is specified, the frontend is needed so connections
        # can be restricted and the backend of the proxy is needed to know
        # number of incoming connections before the reach the real backend.
        # After connections are opened, the real backend stats would be
        # equivalent to the proxy backend.
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self._haproxy_front = haproxy.frontend(service_name)
            self._haproxy = haproxy.backend(service_name + '_proxy')

        # Run self._cleanup on exit
        atexit.register(self._cleanup)

    def _cleanup(self):
        """Ran on exit. Stops treadmill containers"""
        treadmill_api.stop_containers(self._treadmill['appname'])

    def add_server(self):
        """Starts a treadmill container"""
        _LOGGER.info("Add pending server")
        treadmill_api.start_container(self._treadmill['appname'],
                                      self._treadmill['manifest'])

    def delete_server(self, instance):
        """Deletes a treadmill container"""
        _LOGGER.info("Delete server")
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

    def find_max(self, num, history):
        """Finds the max number in a list after appending the current number"""
        # Only keep a specified amount of history
        if len(history) > HISTORY_QUEUE:
            history.popleft()
        history.append(num)
        return max(history)

    def adjust_servers(self):
        """Adjusts servers based on the elasticity configuration.
        Uses the largest value stored in queue for calculations to avoid
        random dips. Requires continuous levels of low activity to drop servers.
        """
        # curr_conns = int(self._haproxy.metric('scur'))
        # max_conns = self.find_max(curr_conns, self._elasticity['conn_history'])
        #
        # # Reset to minimum if there have not been any connections
        # if max_conns == 0:
        #     self._target = self._elasticity['min_servers']

        if self._elasticity['method'] == 'conn_rate':
            curr_rate = int(self._haproxy.metric('rate'))
            max_rate = self.find_max(curr_rate, self._elasticity['history'])
            self.server_steps(max_rate)
        elif self._elasticity['method'] == 'queue':
            queue = int(self._haproxy.metric('qtime'))
            max_queue = self.find_max(queue, self._elasticity['history'])
            self.breakpoint(queue, max_queue)
        elif self._elasticity['method'] == 'response':
            response = int(self._haproxy.metric('rtime'))
            max_resp = self.find_max(response, self._elasticity['history'])
            self.breakpoint(response, max_resp)

    def server_steps(self, max_measure):
        """Adjusts servers based on a list of steps indicating when to add a
        servers.

        Example:
        steps = [100, 300]

        When measure reach over 100, add a server
        When over 300, add another server
        When measure dips below 300, remove a server
        """
        for step, measure in enumerate(self._elasticity['steps']):
            if max_measure >= measure:
                self._target = self._elasticity['min_servers'] + step

    def breakpoint(self, curr_measure, max_measure):
        """Adjusts servers based on a breakpoint number. Suited for
        measurements where adding more servers reduces the measurements.

        Example:
        breakpoint: 10

        When queue time for one connection is 20, another server is added
        Another connection has a queue time of 11, another server is added
        If the historically high queue time drops below 10, a server is removed
        """

        # Uses the current measure instead of the historically largest measure
        # to avoid continuously adding servers
        if curr_measure > self._elasticity['breakpoint']:
            # If there is no configured max number of servers or the target
            # number of servers is below the max, a server can be added
            if (not self._elasticity['max_servers'] or
                    self._target < self._elasticity['max_servers']):
                self._target += 1
        # If the historical largest measure is lower than the breakpoint,
        # remove a server
        if max_measure < self._elasticity['breakpoint']:
            if self._target > self._elasticity['min_servers']:
                self._target -= 1

    def scale(self, max_measure):
        """Adjusts servers based on a growing scale.

        Example:
        scale: 100

        At 100 connections, a server is added
        At 200, another server is added
        At 199, that server is removed
        """
        if max_measure > self._target * self._elasticity['scale']:
            if (not self._elasticity['max_servers'] or
                    self._target < self._elasticity['max_servers']):
                self._target += 1
        elif self._target > self._elasticity['min_servers']:
            self._target -= 1

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
            new_conns = int(self._haproxy.metric('scur'))
            _LOGGER.debug("New Conns: %d", new_conns)

            # If there are more than 0 connections
            if new_conns:
                # Raise min_servers to avoid conflict with adjust_servers
                self._elasticity['min_servers'] += 1
                self._target += 1

                # Set new shutoff_time
                new_time = time.time() + self._elasticity['cooldown']
                self._elasticity['shutoff_time'] = new_time
            elif self._target > 0:
                # Lower min_servers to avoid conflict with adjust_servers
                self._elasticity['min_servers'] -= 1
                self._target -= 1

            # Set max connections to 0 if there are no healthy_servers
            if self._healthy:
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
        _LOGGER.debug("Target %d", self._target)

        new_healthy = self.healthy_servers()

        # Can be empty list, but None specifically means initial loop
        if self._healthy != None:
            # Resolves pending servers. Servers that change between loops were
            # accounted for in the pending count. If there are new healthy
            # servers, the pending added servers have resolved. Pending is
            # subtracted. If there are fewer healthy servers, then
            # pending deleted servers have resolved. Pending is added.
            self._pending -= (len(new_healthy) - len(self._healthy))

        self._healthy = new_healthy

        _LOGGER.debug("Pending: %d", self._pending)
        _LOGGER.debug("Healthy: %d", len(self._healthy))

        # Difference between the target and number of available servers + the
        # pending number of added and deleted servers
        diff = len(self._healthy) + self._pending - self._target
        _LOGGER.debug("Diff: %d", + diff)

        # If there are more healthy + pending, delete servers and adjust
        if diff > 0:
            # Prevent attempting deletion of pending servers that can't
            # be deleted yet.
            diff = min(abs(diff), len(self._healthy))
            for idx in range(diff):
                self.delete_server(self._healthy[idx].name)
                self._pending -= 1
        else:
            for _ in range(abs(diff)):
                self.add_server()
                self._pending += 1

    def loop(self):
        """Main loop. Runs adjust server if method is configured. Holds
        connections if configured. Always tries to keep target"""
        _LOGGER.info('Starting pool loop for %s', self._service_name)
        if 'method' in self._elasticity:
            self.adjust_servers()
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self.hold_conns()
        self.keep_target()
