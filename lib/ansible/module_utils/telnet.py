#
# (c) 2015 Peter Sprygada, <psprygada@ansible.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
#
import re
import socket
import telnetlib

from StringIO import StringIO

ANSI_RE = re.compile(r'(\x1b\[\?1h\x1b=)')

CLI_PROMPTS_RE = [
    re.compile(r'[\r\n]?[a-zA-Z]{1}[a-zA-Z0-9-]*[>|#](?:\s*)$'),
    re.compile(r'[\r\n]?[a-zA-Z]{1}[a-zA-Z0-9-]*\(.+\)#(?:\s*)$')
]

CLI_ERRORS_RE = [
    re.compile(r"% ?Error"),
    re.compile(r"^% \w+", re.M),
    re.compile(r"% ?Bad secret"),
    re.compile(r"invalid input", re.I),
    re.compile(r"(?:incomplete|ambiguous) command", re.I),
    re.compile(r"connection timed out", re.I),
    re.compile(r"[^\r\n]+ not found", re.I),
    re.compile(r"'[^']' +returned error code: ?\d+"),
    re.compile(r"syntax error"),
    re.compile(r"unknown command")
]

def to_list(val):
    if isinstance(val, (list, tuple)):
        return list(val)
    elif val is not None:
        return [val]
    else:
        return list()

class TelnetError(Exception):

    def __init__(self, msg, command=None):
        super(TelnetError, self).__init__(msg)
        self.message = msg
        self.command = command

class Command(object):

    def __init__(self, command, prompt=None, response=None):
        self.command = command
        self.prompt = prompt
        self.response = response

    def __str__(self):
        return self.command

class Telnet(object):

    def __init__(self):
        self.telnet = None

        self._matched_prompt = None

        self.prompts = list()
        self.prompts.extend(CLI_PROMPTS_RE)

        self.errors = list()
        self.errors.extend(CLI_ERRORS_RE)

    def open(self, host, port=23, username=None, password=None,
            timeout=10, key_filename=None, pkey=None, look_for_keys=None,
            allow_agent=False, prompt_user='Username: ', prompt_passwd='Password: '):

        self.telnet = telnetlib.Telnet(host, port, timeout)
        if username:
            self.telnet.read_until(prompt_user, timeout)
            self.telnet.write(username + "\n")
        self.telnet.read_until(prompt_passwd, timeout)
        self.telnet.write(password + "\n")

    def strip(self, data):
        return ANSI_RE.sub('', data)

    def receive(self, cmd=None):
        recv = StringIO()

        while True:
            data = self.telnet.read_very_eager()

            recv.write(data)
            recv.seek(recv.tell() - len(data))

            window = self.strip(recv.read())

            if isinstance(cmd, Command):
                self.handle_input(window, prompt=cmd.prompt,
                                  response=cmd.response)

            try:
                if self.read(window):
                    resp = self.strip(recv.getvalue())
                    return self.sanitize(cmd, resp)
            except TelnetError, exc:
                exc.command = cmd
                raise

    def send(self, commands):
        responses = list()
        try:
            for command in to_list(commands):
                cmd = '%s\n' % str(command)
                self.telnet.write(cmd)
                responses.append(self.receive(command))
        except socket.timeout, exc:
            raise TelnetError("timeout trying to send command", cmd)
        return responses

    def close(self):
        self.telnet.close()

    def handle_input(self, resp, prompt, response):
        if not prompt or not response:
            return

        prompt = to_list(prompt)
        response = to_list(response)

        for pr, ans in zip(prompt, response):
            match = pr.search(resp)
            if match:
                cmd = '%s\r' % ans
                self.telnet.sendall(cmd)

    def sanitize(self, cmd, resp):
        cleaned = []
        for line in resp.splitlines():
            if line.startswith(str(cmd)) or self.read(line):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    def read(self, response):
        for regex in self.errors:
            if regex.search(response):
                raise TelnetError('%s' % response)

        for regex in self.prompts:
            match = regex.search(response)
            if match:
                self._matched_prompt = match.group()
                return True

def get_cli_connection(module):
    host = module.params['host']
    port = module.params['port']
    if not port:
        port = 23

    username = module.params['username']
    password = module.params['password']

    try:
        cli = Cli()
        cli.open(host, port=port, username=username, password=password)
    except socket.error, exc:
        host = '%s:%s' % (host, port)
        module.fail_json(msg=exc.strerror, errno=exc.errno, host=host)
    except socket.timeout:
        module.fail_json(msg='socket timed out')

    return cli

