"""Treadmill based watcher for HAProxy"""

import collections
import time

import treadmill_connect


class Pool(object):
    """Maintains pool of treadmill containers"""
    def __init__(self, service, haproxy):
        self._haproxy = haproxy
        service['down_servers'] = []
        service['history'] = collections.deque([])
        service['conn_history'] = collections.deque([])
        service['pending_servers'] = []
        for _ in range(service['min_servers']):
            self.add_server()
        self._service = service

    def add_server(self):
        name = treadmill_connect.start_server()
        props = self._service['default_properties']
        self._service['pending_servers'].append({'name': name,
                                                 'properties': props})

    def delete_server(self):
        if len(self._service['curr_servers']) > 0:
            server = self._service['curr_servers'].pop()
            self._haproxy.server_delete(self._service, server['name'])
            treadmill_connect.stop_container(server['name'])
            self._haproxy.haproxy_restart()

    def discover_server(self, server):
        endpoints = treadmill_connect.discovery(self.service['appname'])
        for endpoint in endpoints:
            if (endpoint['instance'] == server['name'] and
                    endpoint['endpoint'] != 'ssh'):
                return '{}:{}'.format(endpoint['host'], endpoint['port'])
        return None

    def shutoff(self):
        treadmill_connect.stop_app(self._service['appname'])

    def adjust_servers(self):
        min_servers = self._service['min_servers']
        curr_servers = self._service['curr_servers']
        curr_conns = int(self._haproxy.backend_conn_num(self._service))
        max_conns = self.find_max(curr_conns, self._service['conn_history'])

        if max_conns == 0:
            for _ in range(min_servers, len(curr_servers)):
                self.delete_server()

        if self._service['method'] == 'conn_rate':
            curr_rate = int(self._haproxy.backend_conn_rate(self._service))
            max_rate = self.find_max(curr_rate, self._service['history'])
            self.server_steps(max_rate)
        elif self._service['method'] == 'queue':
            queue = int(self._haproxy.backend_queue_time(self._service))
            max_queue = self.find_max(queue, self._service['history'])
            self.breakpoint(queue, max_queue)
        elif self._service['method'] == 'response':
            response = int(self._haproxy.backend_response_time(self._service))
            max_resp = self.find_max(response, self._service['history'])
            self.breakpoint(response, max_resp)

    def find_max(self, num, history):
        if len(history) > self._history_count:
            history.popleft()
        history.append(num)
        return max(history)

    def server_steps(self, max_measure):
        min_servers = self._service['min_servers']
        max_servers = self._service['max_servers']
        curr_servers = len(self._service['curr_servers'])
        pending_servers = len(self._service['pending_servers'])
        total_servers = curr_servers + pending_servers

        for num, measure in enumerate(self._service['server_steps']):
            if max_measure >= int(measure):
                if total_servers < max_servers:
                    if total_servers > min_servers + num:
                        self.add_server()
            elif total_servers > min_servers + num:
                self.delete_server()

    def breakpoint(self, curr_measure, max_measure):
        min_servers = self._service['min_servers']
        max_servers = self._service['max_servers']
        curr_servers = len(self._service['curr_servers'])
        pending_servers = len(self._service['pending_servers'])
        total_servers = curr_servers + pending_servers

        if curr_measure > self._service['breakpoint']:
            if not max_servers or total_servers < max_servers:
                self.add_server()
        if max_measure < self._service['breakpoint']:
            if curr_servers > min_servers:
                self.delete_server()

    def check_health(self):
        curr_count = 0
        while curr_count < len(self._service['curr_servers']):
            curr_server = self._service['curr_servers'][curr_count]['name']
            status = self._haproxy.server_alive(self._service, curr_server)

            if status != 0:
                curr_count += 1
                continue
            else:
                self.add_server()
                self._service['down_servers'].append(
                    self._service['curr_servers'].pop(curr_count))

        down_count = 0
        while down_count < len(self._service['down_servers']):
            down_server = self._service['down_servers'][down_count]['name']
            status = self._haproxy.server_alive(self._service, down_server)

            if status <= 0:
                down_count += 1
                continue
            elif status > 0:
                self._service['curr_servers'].append(
                    self._service['down_servers'].pop(down_count))

    def check_pending(self):
        pending_servers = self._service['pending_servers']
        curr_servers = self._service['curr_servers']
        for server in pending_servers:
            if 'address' not in server:
                addr = self.discover_server(server)
                if addr:
                    server['address'] = addr
                    self._haproxy.server_add_by_dict(self._service, server)
                    self._haproxy.haproxy_restart()
            else:
                status = self._haproxy.server_alive(self._service,
                                                    server['name'])
                if status > 0:
                    curr_servers.append(server)
                    pending_servers.remove(server)

    def hold_conns(self):
        if self._service['shutoff_time'] < time.time():
            new_conns = int(self._haproxy.backend_conn_num(
                self._service + '_proxy'
            ))

            if self._service['shutoff_time'] != 0:
                self._service['min_servers'] -= 1
                self.delete_server()
                self._service['shutoff_time'] = 0

            if new_conns != 0:
                self._service['min_servers'] += 1
                self.add_server()

                new_time = time.time() + self._service['cooldown']
                self._service['shutoff_time'] = new_time

    def monitor_loop(self):
        self.check_health()
        self.adjust_servers()
        self.check_pending()
        if 'hold_conns' in self._service and self._service['hold_conns']:
            self.hold_conns()
