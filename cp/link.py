import sys
from message import Message
from config import mongo_client
import asyncio
import time
import random
import string
from websockets.exceptions import ConnectionClosedError
import jwt

class Link:
    def __init__(self, messages):
        self.new = None
        self.safe = False
        self.client_done = None
        self.sys_db = mongo_client.nodewire
        self.messages = messages
        self.session = None

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
                    data = await self.receive()
                    self.last_seen = time.time()
                    if not data:  # an empty string means the client disconnected
                        # cp => if the_gw in self.clients: self.clients.remove(the_gw)  # todo renumber the clients
                        break
                    msg = Message(data)
                    if self.safe:
                        if msg.sender_full not in self.nodes: 
                            # a safe link has nodes from a different process, we should add them here so they are able to receive a response
                            self.nodes.append(msg.sender_full) 
                    else:
                        if not msg.sender_instance: data = data[:data.rfind(' ')] + ' ' + self.gateway + ':' + msg.sender
                        if not msg.address_instance: data = self.gateway + ':' + data
                    if msg.sender in self.nodes or msg.address == 'cp' or self.safe:
                        self.messages.put_nowait((data, self.task))
                except asyncio.CancelledError as ex:
                    break
                except (ConnectionResetError, BrokenPipeError, ConnectionClosedError) as ex:
                    break
                except:
                    break
        self.close()

    async def authenticated(self):
        if self.safe: 
            # safe links connects nodes from a different process. the other process will be responsible for authentication
            return self.new(self)
        try:
            words = (await self.receive()).split()
            return await self.login(words)
        except ConnectionResetError:
            pass
        except ConnectionClosedError:
            pass
        except Exception:
            pass
        return False

    async def login(self, words):
        if len(words) >= 3 and words[1] == 'Gateway':
            try:
                d_user = None
                if len(words) == 3:
                    if words[2].startswith('token'):
                        token = words[2].split('=')[1]
                        decoded = jwt.decode(token, 'this is my secret', algorithms=['HS256'])
                        if 'exp' in decoded and time.time() > decoded['exp']: return False
                        user = decoded['email']
                        gateway = decoded['instance']
                        password = None
                    else:
                        return False
                else:
                    user = words[2].split('=')[1].strip() if 'user' in words[2] and '=' in words[2] else ''
                    id = words[2].split('=')[1].strip() if 'id' in words[2] and '=' in words[2] else ''
                    key = words[2].split('=')[1].strip() if 'key' in words[2] and '=' in words[2] else ''

                    if user:
                        password = words[3].split('=')[1].strip() if 'pwd' in words[3] and '=' in words[3] else ''
                    else:
                        password = ''
                '''
                    there are four authentication methods
                    1. usernamen and password:
                        cp Gateway user=username pwd=password instance
                    2. token: 
                        cp Gateway token=access_token
                    3. uuid and key
                        cp Gateway key=secret uuid
                    4. uuid: this is used to register a new gateway. This can only be used once. subsequent calls must use method 3
                        cp Gateway id=uuid
                    
                '''
                if user and password:
                    gateway = words[-1]
                    d_user = await self.sys_db.users.find_one({'email': user, 'password': password, 'instance': gateway}, {'layout': 0, 'gateways': 0})
                elif token:
                     d_user = await self.sys_db.users.find_one({'email': user}, {'layout': 0})
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
                            gateway = words[-1] = d_user['instance']+':'+d_user['tokens'][0]['token']
                    else:
                        gateway = words[-1] = id

                if d_user:
                    self.gateway = gateway
                    self.user = d_user
                    self.last_seen = time.time()
                    self.nodes =  []
                    self.ghosts = []

                    if self.new and self.new(self):
                        await self.send('{} gack {} cp'.format(gateway, self.seqn))
                        await self.send('any ping cp')
                        return True
                    else:
                        await self.send(words[-1] + ' connection rejected cp')
                        await asyncio.sleep(30)
                        self.close()
                        return False
                else:
                    await self.send((words[-1] if len(words) != 0 else 'any') + ' authfail cp')
                    self.close()
                    return False
            except Exception as ex:
                print('auth  error')
                print(ex)
                await self.send(words[-1] + ' autherror cp')
                self.close()
                return False
        else:
            await self.send((words[-1] if len(words)!=0 else 'any') + ' authmissing cp')
            self.close()
            return False