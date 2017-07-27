"""Treadmill based watcher for HAProxy"""

import collections
import time

import treadmill_api

HISTORY_QUEUE = 15


class Pool(object):
    """Maintains pool of treadmill containers"""
    def __init__(self, service_name, service, haproxy, haproxy_parser):
        self._service_name = service_name
        self._haproxy = haproxy
        self._haproxy_parser = haproxy_parser
        self._servers = haproxy.servers()
        service['elasticity']['down_servers'] = []
        service['elasticity']['history'] = collections.deque([])
        service['elasticity']['conn_history'] = collections.deque([])
        service['elasticity']['pending_servers'] = []
        service['elasticity']['curr_servers'] = []

        self._elasticity = service['elasticity']
        self._treadmill = service['treadmill']
        self._haproxy_conf = service['haproxy']

        for _ in range(self._elasticity['min_servers']):
            self.add_server()

    def server_alive(self, instance):
        status = self._servers[instance].status
        if status == 'UP':
            return True
        return False

    def add_server(self):
        instance = treadmill_api.start_container(self._treadmill['appname'],
                                                 self._treadmill['manifest'])
        props = self._haproxy_conf['server']
        self._elasticity['pending_servers'].append({'instance': instance,
                                                    'properties': props})

    def delete_server(self):
        if self._elasticity['curr_servers']:
            server = self._elasticity['curr_servers'].pop()
            self._haproxy_parser.delete_server(self._service_name,
                                               server['instance'])
            treadmill_api.stop_container(server['instance'])
            self._haproxy.haproxy_restart()

    def discover_server(self, server):
        endpoints = treadmill_api.discover_container(self._treadmill['appname'],
                                                     server['instance'])
        for endpoint in endpoints:
            if (endpoint['instance'] == server['instance'] and
                    endpoint['endpoint'] != 'ssh'):
                return '{}:{}'.format(endpoint['host'], endpoint['port'])
        return None

    def shutoff(self):
        treadmill_api.stop_app(self._treadmill['appname'])

    def adjust_servers(self):
        min_servers = self._elasticity['min_servers']
        curr_servers = self._elasticity['curr_servers']
        curr_conns = int(self._haproxy.metric('scur'))
        max_conns = self.find_max(curr_conns, self._elasticity['conn_history'])

        if max_conns == 0:
            for _ in range(min_servers, len(curr_servers)):
                self.delete_server()

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

    def find_max(self, num, history):
        if len(history) > HISTORY_QUEUE:
            history.popleft()
        history.append(num)
        return max(history)

    def server_steps(self, max_measure):
        min_servers = self._elasticity['min_servers']
        max_servers = self._elasticity['max_servers']
        curr_servers = len(self._elasticity['curr_servers'])
        pending_servers = len(self._elasticity['pending_servers'])
        total_servers = curr_servers + pending_servers

        for num, measure in enumerate(self._elasticity['steps']):
            if max_measure >= int(measure):
                if not (max_servers and total_servers > max_servers):
                    if total_servers > min_servers + num:
                        self.add_server()
            elif total_servers > min_servers + num:
                self.delete_server()

    def breakpoint(self, curr_measure, max_measure):
        min_servers = self._elasticity['min_servers']
        max_servers = self._elasticity['max_servers']
        curr_servers = len(self._elasticity['curr_servers'])
        pending_servers = len(self._elasticity['pending_servers'])
        total_servers = curr_servers + pending_servers

        if curr_measure > self._elasticity['breakpoint']:
            if not max_servers or total_servers < max_servers:
                self.add_server()
        if max_measure < self._elasticity['breakpoint']:
            if curr_servers > min_servers:
                self.delete_server()

    def check_health(self):
        curr_count = 0
        while curr_count < len(self._elasticity['curr_servers']):
            curr_server = (self._elasticity['curr_servers'][curr_count]
                           ['instance'])
            status = curr_server in self._servers

            if status != 0:
                curr_count += 1
                continue
            else:
                self.add_server()
                self._elasticity['down_servers'].append(
                    self._elasticity['curr_servers'].pop(curr_count))

        down_count = 0
        while down_count < len(self._elasticity['down_servers']):
            down_server = (self._elasticity['down_servers'][down_count]
                           ['instance'])
            status = self._servers[down_server].status

            if status:
                self._elasticity['curr_servers'].append(
                    self._elasticity['down_servers'].pop(down_count))
            else:
                down_count += 1
                continue

    def check_pending(self):
        pending_servers = self._elasticity['pending_servers']
        curr_servers = self._elasticity['curr_servers']
        for server in pending_servers:
            if 'address' not in server:
                addr = self.discover_server(server)
                if addr:
                    server['address'] = addr
                    self._haproxy_parser.add_server(self._service_name,
                                                    server['instance'],
                                                    server['address'],
                                                    server['properties'])
                    self._haproxy.haproxy_restart()
            else:
                status = self.server_alive(server['instance'])
                if status:
                    curr_servers.append(server)
                    pending_servers.remove(server)

    def hold_conns(self):
        if self._elasticity['shutoff_time'] < time.time():
            new_conns = int(self._haproxy.metric('scur'))

            if self._elasticity['shutoff_time'] != 0:
                self._elasticity['min_servers'] -= 1
                self.delete_server()
                self._elasticity['shutoff_time'] = 0

            if new_conns != 0:
                self._elasticity['min_servers'] += 1
                self.add_server()

                new_time = time.time() + self._elasticity['cooldown']
                self._elasticity['shutoff_time'] = new_time

    def monitor_loop(self):
        self.check_health()
        self.adjust_servers()
        self.check_pending()
        if 'hold_conns' in self._elasticity and self._elasticity['hold_conns']:
            self.hold_conns()
