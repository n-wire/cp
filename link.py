import sys
from message import Message
from db import mongo_client
import asyncio
import time
import random

class Link:
    def __init__(self, messages):
        self.new = None
        self.safe = False
        self.client_done = None
        self.sys_db = mongo_client.nodewire
        self.messages = messages

        self.gateway = None
        self.seqn = 0
        self.task = None
        self.reader = None
        self.writer = None
        self.send_queue = None
        self.type = 'tcp'
        self.user = None
        self.last_seen = 0
        self.nodes =  []
        self.ghosts = []

    def start(self, address='0.0.0.0', port = 10001):
        pass

    async def send(self, data):
        pass

    async def receive(self):
        return ''

    def close(self):
        pass

    async def main_loop(self):
        if (await self.authenticated()):
            while True:
                try:
                    data = (await self.receive())
                    self.last_seen = time.time()
                    if not data:  # an empty string means the client disconnected
                        # cp => if the_gw in self.clients: self.clients.remove(the_gw)  # todo renumber the clients
                        break
                    msg = Message(data)
                    if not msg.sender_instance: data = data[:data.rfind(' ')] + ' ' + self.gateway + ':' + msg.sender
                    if not msg.address_instance: data = self.gateway + ':' + data
                    if msg.sender in self.nodes or msg.address == 'cp':
                        self.messages.put_nowait((data + '\n', self))
                except asyncio.CancelledError as ex:
                    break
                except (ConnectionResetError, BrokenPipeError) as ex:
                    break
            self.close()

    async def authenticated(self):
        if self.safe: return True
        try:
            words = (await self.receive()).split()
            return await self.login(words)
        except ConnectionResetError:
            pass
        return False

    async def login(self, words):
        if len(words) >= 3 and words[1] == 'Gateway':
            try:
                d_user = None
                user = words[2].split('=')[1].strip() if 'user' in words[2] and '=' in words[2] else ''
                id = words[2].split('=')[1].strip() if 'id' in words[2] and '=' in words[2] else ''
                key = words[2].split('=')[1].strip() if 'key' in words[2] and '=' in words[2] else ''

                if user:
                    password = words[3].split('=')[1].strip() if 'pwd' in words[3] and '=' in words[3] else ''
                else:
                    password = ''
                '''
                    there are three authentication methods
                    1. usernamen and password:
                       cp Gateway user=username pwd=password instance
                    2. uuid: this is used to register a new gateway. This can only be used once.
                       cp Gateway id=uuid
                    3. uuid and token
                       cp Gateway key=token uuid
                '''
                if user and password:
                    gateway = words[-1]
                    d_user = await self.sys_db.users.find_one({'email': user, 'password': password, 'instance': gateway}, {'layout': 0, 'gateways': 0})
                elif key:
                    d_user = await self.sys_db.users.find_one({'tokens': {'id': words[-1], 'token': key}}, {'layout': 0, 'gateways': 0})
                    if d_user:
                        gateway = words[-1] = d_user['instance']
                elif id:
                    d_user = await self.sys_db.users.find_one({'gateways': id}, {'layout': 0, 'gateways': 0})
                    if d_user:
                        if 'tokens' not in d_user: d_user['tokens'] = []
                        if len([tok for tok in d_user['tokens'] if tok["id"] == id]) == 0:
                            token_gen = ''.join(random.choice(string.ascii_lowercase) for i in range(10))
                            d_user['tokens'].append({'id': id, 'token': token_gen})
                            await self.sys_db.users.replace_one({'email': d_user['email']}, d_user)
                            gateway = words[-1] = d_user['instance']+':'+token_gen
                        else:
                            d_user = None
                    else:
                        gateway = words[-1] = id

                if d_user:
                    n = len([client for client in self.clients if client['gateway']==gateway])
                    self.gateway = gateway
                    self.seqn = n
                    # cp => self.send_queue: self.send_queues[self.sq_index]
                    self.type = 'tcp'
                    self.user = d_user
                    self.last_seen = time.time()
                    self.nodes =  []
                    self.ghosts = []
                    # cp => self.sq_index = (self.sq_index+1) % len(self.send_queues)
                    # update number of connected gateways
                    '''if n == 0 and gateway not in self.execution_contexts:
                        self.execution_contexts[gateway] = context(gateway, self.when_dos, self.exec_loop, self.messages)
                        if gateway not in self.auto_execed:
                            kk = await self.execution_contexts[gateway].engine_process(["exec('auto')"], user)
                            if kk == '':
                                self.auto_execed.append(gateway)
                                await self.execution_contexts[gateway].engine_process(["kill('auto')"], user)
                    '''
                    await self.sys_db.live_gateways.replace_one({'instance': gateway}, {'instance': gateway, 'count': n+1})

                    # check if too many client connections
                    if n >= 20:
                        await self.send((words[-1] + ' too many connections cp\n').encode())
                        await asyncio.sleep(30)
                        self.close()
                        return False

                    # cp => self.clients.append (the_gw)
                    await self.send(('{} gack {} cp\n'.format(gateway, n)).encode())
                    await self.send('any ping cp\n'.encode())

                    return True
                else:
                    await self.send(((words[-1] if len(words) != 0 else 'any') + ' authfail cp\n').encode())
                    self.close()
                    return False
            except Exception as ex:
                print('auth  error')
                print(ex)
                await self.send((words[-1] + ' autherror cp\n').encode())
                self.close()
                return False
        else:
            await self.send(((words[-1] if len(words)!=0 else 'any') + ' authmissing cp\n').encode())
            self.close()
            return False
        