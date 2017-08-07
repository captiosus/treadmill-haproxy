"""Treadmill based watcher for HAProxy"""

import atexit
import collections
import logging
import time

import treadmill_api
import haproxy_control

HISTORY_QUEUE = 15


class Pool(object):
    """Maintains pool of treadmill containers"""
    def __init__(self, service_name, service, haproxy, haproxy_parser):
        self._service_name = service_name
        self._haproxy = haproxy.backend(service_name)
        self._haproxy_parser = haproxy_parser
        service['elasticity']['history'] = collections.deque([])
        service['elasticity']['conn_history'] = collections.deque([])

        self._elasticity = service['elasticity']
        self._treadmill = service['treadmill']
        self._haproxy_conf = service['haproxy']

        self._target = self._elasticity['min_servers']
        self._pending = 0
        self._healthy = None

        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self._haproxy_front = haproxy.frontend(service_name)
            self._haproxy_proxy = haproxy.backend(service_name + '_proxy')

        atexit.register(self._cleanup)

    def _cleanup(self):
        haproxy_control.stop_haproxy()
        treadmill_api.stop_containers(self._treadmill['appname'])

    def add_server(self):
        logging.info("Add pending server")
        treadmill_api.start_container(self._treadmill['appname'],
                                      self._treadmill['manifest'])

    def delete_server(self, instance):
        logging.info("Delete server")
        treadmill_api.stop_container(self._treadmill['appname'], instance)

    def healthy_servers(self):
        healthy = []
        for server in self._haproxy.servers():
            if server.status != 'DOWN':
                healthy.append(server)
        return healthy

    def find_max(self, num, history):
        if len(history) > HISTORY_QUEUE:
            history.popleft()
        history.append(num)
        return max(history)

    def adjust_servers(self):
        curr_conns = int(self._haproxy.metric('scur'))
        max_conns = self.find_max(curr_conns, self._elasticity['conn_history'])

        if max_conns == 0:
            self._target = self._elasticity['min_servers']

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
        for step, measure in enumerate(self._elasticity['steps']):
            if max_measure >= measure:
                self._target = self._elasticity['min_servers'] + step

    def breakpoint(self, curr_measure, max_measure):
        min_servers = self._elasticity['min_servers']
        max_servers = self._elasticity['max_servers']

        if curr_measure > self._elasticity['breakpoint']:
            if not max_servers or self._target < max_servers:
                self._target += 1
        if max_measure < self._elasticity['breakpoint']:
            if self._target > min_servers:
                self._target -= 1

    def hold_conns(self):
        if self._elasticity['shutoff_time'] < time.time():
            new_conns = int(self._haproxy_proxy.metric('scur'))
            logging.debug("New Conns: %d", new_conns)

            if new_conns:
                self._elasticity['min_servers'] += 1
                self._target += 1

                new_time = time.time() + self._elasticity['cooldown']
                self._elasticity['shutoff_time'] = new_time
            elif self._target > 0:
                self._elasticity['min_servers'] -= 1
                self._target -= 1

            if self._healthy:
                self._haproxy_front.setmaxconn(2000)
            else:
                self._haproxy_front.setmaxconn(0)

    def keep_target(self):
        logging.debug("Target %d", self._target)

        new_healthy = self.healthy_servers()

        # Can be empty list, but None specifically means initial loop
        if self._healthy != None:
            self._pending -= (len(new_healthy) - len(self._healthy))

        self._healthy = new_healthy

        logging.debug("Pending: %d", self._pending)
        logging.debug("Healthy: %d", len(self._healthy))

        diff = len(self._healthy) + self._pending - self._target
        logging.debug("Diff: %d", + diff)

        if diff > 0:
            for idx in range(abs(diff)):
                self.delete_server(self._healthy[idx].name)
                self._pending -= 1
        else:
            for _ in range(abs(diff)):
                self.add_server()
                self._pending += 1

    def loop(self):
        logging.info('Starting pool loop for %s', self._service_name)
        if 'method' in self._elasticity:
            self.adjust_servers()
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self.hold_conns()
        self.keep_target()
