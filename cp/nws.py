import asyncio
from cp.message import Message
from cp.socket_link import SocketLink
from cp.execution_context import Execution_Context
from cp.execution_engine import Execution_Engine
import cp.sizeof as sizeof 
import json
import motor.motor_asyncio
import time

from datetime import datetime, timedelta

from cp.config import mongo_client

class CommandProcessor:
    def __init__(self):
        self.sys_db = mongo_client.nodewire
        self.clients = []
        self.messages = asyncio.Queue()

        self.socket = SocketLink(self.messages)
        self.socket.new = self.client_added
        self.socket.client_done = self.client_closed

        self.pipe = SocketLink(self.messages, port=9001)
        self.pipe.new = self.client_added
        self.pipe.client_done = self.client_closed
        self.pipe.safe = True

        self.execution_contexts = {} # one per gateway
        self.when_dos = [] # universal whendo list
        self.exec_engine = Execution_Engine(self.when_dos, self.execution_contexts)
        self.exec_engine.start()


    def client_added(self, client):
        if client in self.clients:
            self.client_closed(client)
        self.clients.append(client)

    def client_closed(self, client):
        try:
            clients = [c for c in self.clients if c == client]
            if len(clients)!=0:
                client = clients[0]
                self.re_remove_nodes(client)
                if client in self.clients:
                    self.clients.remove(client)

                # update number of connected gateways
                n = len([c for c in self.clients if c['gateway'] == client['gateway']])
                n_g = {'instance': client['gateway'], 'count': n}

                asyncio.get_event_loop().call_soon(self.sys_db.live_gateways.replace_one, {'instance': client['gateway']}, n_g)
        except Exception as ex:
            print('pass 7'),
            print(ex)

    def terminate_connections(self, clients):
        pass

    async def check_id(self, node, gateway, Sender):
        pass

    def is_auth(self, sender):
        pass

    async def handle(self, message:Message, task):
        if message.command == 'ThisIs':
            try:
                clients = [client for client in self.clients if task == client.task]
                client = clients[0]
                node = message.sender
                '''
                nodes     ghosts
                --------------------------
                    in       in       1    shouldn't happen
                    in      not in    2    remove node from clients
                    not in   in       3    replace ghost if new tcp connection
                    not in  not in    4    handle
                '''
                if node not in client.ghosts and node not in client.nodes: # case 4
                    # add to ghosts
                    client.ghosts.append(node)
                    if message.params != []:
                        await self.check_id(node, message.sender_instance, message.sender)
                    else:
                        await client.send(message.sender + ' ack cp\n')
                        await client.send(message.sender + ' get id cp\n')
                elif node in client.nodes: # and len(clients)==1:   # case 2
                    # pass
                    if time.time() - client['last_seen']>20:
                        client.nodes.remove(node) # = [n for n in client['nodes'] if n != node]
                else:                                           # case 3
                    if client['type'] == 'tcp':
                        # terminate previous connections
                        other_ghosts = [client for client in self.clients if node in client.ghosts and client.task!= task]
                        if len(other_ghosts) > 1:
                            self.terminate_connections(other_ghosts)
                        if message.params != []:
                            await self.check_id(node, message.sender_instance, message.sender)
                        else:
                            await client.send(message.sender + ' ack cp\n')
                            await client.send(message.sender + ' get id cp\n')
                    elif client['type'] == 'web':
                        await client.send(message.sender + ' ack cp\n')
            except Exception as ex:
                print(f'pass 2: {ex}, node is {message.sender }')
        elif message.command == 'id':
            node = message.sender
            await self.check_id(node, message.sender_instance, message.sender)
        elif message.command == 'keepalive':
            client = [client for client in self.clients if task == client.task][0]
            if client:
                await client.send(message.sender + ' ack cp\n')
                varname = message.address
                '''if varname not in self.execution_contexts[gateway].pvs and varname not in ['ee', 'nwscript', 'cp', 'db']:
                    self.messages.put_nowait(('{}:cp subscribe {} portvalue {}:re\n'.format(gateway, varname, gateway), None))
                    self.execution_contexts[gateway].pvs.append(varname)
                    self.execution_contexts[gateway].variables['nodes'].append(Node(self.messages, varname, gateway))
                    self.exec_loop.pending_signals.put_nowait(['nodes', gateway])'''
            else:
                print(f'CLIENT NOT CONNECTED => {message}')
        elif self.is_auth(message.sender):
            if message.command == 'get':
                if message.params[0] == 'nodes':
                    # gateway = words[0].split(':')[0] if ':' in words[0] else gateway
                    nodeses = [[n for n in client.nodes] for client in self.clients if
                                client.gateway==message.sender_instance and (client.type=='tcp' or client.type=='mqtt')]
                    nodes_web = [[n for n in client.nodes[1:]] for client in self.clients if
                                client.gateway == message.sender_instance and client.type == 'web']
                    nodes = self.execution_contexts[message.sender_instance].apps
                    for nodegroup in nodeses: nodes = nodes + nodegroup
                    for nodegroup in nodes_web: nodes = nodes + nodegroup
                    response = '{} nodes {} {}:cp\n'.format(message.sender, ' '.join(nodes), message.sender_instance)
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'ghosts':
                    nodeses = [[n for n in client['ghosts']] for client in self.clients if
                                client.gateway == message.sender_instance]
                    nodes = []
                    for nodegroup in nodeses: nodes = nodes + nodegroup
                    response = '{} ghosts {} cp\n'.format(message.sender, ' '.join(nodes))
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'gateways':
                    def fdate(t):
                        d = datetime(1970, 1, 1) + timedelta(seconds=t)
                        return d.strftime('%X %x')
                    gw = [{'gateway': c.gateway, 'lastseen': fdate(c['last_seen']), 'nodes': c.nodes} for c in self.clients]
                    response = f'{message.sender} portvalue gateways {json.dumps(gw)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'users':
                    users = [' '.join(u) for u in [c['nodes'] for c in self.clients if c['type']=='web' and c['gateway']==gateway]]
                    response = f'{message.sender} portvalue users {json.dumps(users)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'connections':
                    response = f'{message.sender} portvalue connections {len(self.clients)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'mem':
                    m = sizeof.deep_getsizeof(self.execution_contexts[message.sender_instance].variables, set())
                    cc = [c for c in self.clients if c['gateway']==message.sender_instance]
                    n = sizeof.deep_getsizeof(cc[0], set())
                    print(m, n)
                    response = f'{message.sender} portvalue mem '+ '{"clients:":' + str(n) + ', "context":' + str(m) + '} cp'
                    self.messages.put_nowait((response, None))
            elif message.command == 'set':
                if message.params[0] == 'id': # cp set id node id_code new_name sender
                    client = [c for c in self.clients if message.params[1] in c['ghosts'] and c['gateway']==message.sender_instance][0]
                    client['ghosts'].remove(message.params[1])
                    if client['type'] == 'tcp':
                        client['writer'].write('{} set id {} cp\n'.format(message.params[1], message.params[2]))
                        await client['writer'].drain()
                        client['writer'].write('{} set name {} cp\n'.format(message.params[1], message.params[3]))
                        await client['writer'].drain()
                    else:
                        await client['websocket'].send('{} set id {} cp\n'.format(message.params[1], message.params[2]))
                        await client['websocket'].send('{} set name {} cp\n'.format(message.params[1], message.params[3]))
                elif message.params[0] == 'reset': # reset all conections from this instance
                    clients = [c for c in self.clients if c['gateway'] == message.sender_instance]
                    self.terminate_connections(clients)
            elif message.command == 'register':
                try:
                    # cp register node id pwd=password user
                    # user = Sender.split(':')[1] if ':' in Sender else Sender
                    # d_user = await self.sys_db.users.find_one({'email': user}, {'layout': 0})
                    d_instance = await self.sys_db.instances.find_one({'instance_id': message.sender_instance})
                    i_user = [u for u in d_instance['users'] if u['user_instance_and_node_name'] == message.sender][0]
                    if i_user['admin']: # d_user['password'] == Params[2].split('=')[1] and i_user['admin']:
                        node = {'name': message.params[0], 'id': message.params[1], 'access_permission': [2,2,1]}
                        if not node in [n['name'] for n in d_instance['registered_nodes']]:
                            d_instance['registered_nodes'].append(node)
                            await self.sys_db.instances.replace_one({'_id': d_instance['_id']}, d_instance)
                except Exception as ex:
                    print('pass 3')
            elif message.command == 'getnode':
                nodes = [n for n in self.execution_contexts[message.sender_instance].variables['nodes'] if n['name'] == message.params[0]]
                if len(nodes)!=0:
                    dnode = nodes[0]
                    nodename = dnode.name
                    nodebody = dnode.json()
                    if nodes[0].type != None:
                        response = '{} node {} {} {} {} cp\n'.format(message.sender, nodebody, nodename, nodes[0].gateway, nodes[0].type)
                    else:
                        response = '{} node {} {} {} cp\n'.format(message.sender, nodebody, nodename, nodes[0].gateway)
                    self.messages.put_nowait((response, None))
                else:
                    # todo handle apps from different instance
                    nodes = [n for n in self.execution_contexts[message.sender_instance].apps if n == message.params[0]]
                    if len(nodes)!=0:
                        ports = [p for p in self.execution_contexts[message.sender_instance].variables[message.params[0]]['inputs']]
                        for p in self.execution_contexts[message.sender_instance].variables[message.params[0]]['outputs']:
                            if p not in ports: ports.append(p)
                        bc = {'app': message.params[0], 'module': self.execution_contexts[message.sender_instance].themodule, 'variables': {}}
                        content =  {}
                        for port in ports:
                            try:
                                content[port] = self.execution_contexts[message.sender_instance].get_val(port, bc)
                            except:
                                content[port] = None
                        response = '{} node {} {} {} {} cp\n'.format(message.sender, json.dumps(content), message.params[0], message.sender_instance, message.params[0])
                        self.messages.put_nowait((response, None))
            elif  message.command == 'erase':
                # cp erase node user
                d_instance = await self.sys_db.instances.find_one({'instance_id': message.sender_instance})
                i_user = [u for u in d_instance['users'] if u['user_instance_and_node_name'] == message.sender][0]
                if i_user['admin']:
                    client = [c for c in self.clients if message.params[0] in c.ghosts and c.gateway == message.sender_instance][0]
                    if client['type'] == 'tcp':
                        client.send('{} set reset cp\n'.format(message.params[0]))
                    else:
                        await client.send('{} set reset cp\n'.format(message.params[0]))

            elif message.command == 'subscribe':
                # cp subscribe node cmd sender
                if message.sender != message.params[0]:
                    clients = [client for client in self.clients if task == client.task]
                    client = clients[0] if len(clients)!=0 else None
                    target = message.params[0] if ':' in message.params[0] else message.sender_instance+':'+message.params[0]
                    if len([s for s in self.subscriptions if s['target']==target and s['command'] == message.params[1]
                    and s['subscriber']==message.sender and s['client']!= None and s['client'].task==client.task]) == 0:
                        self.subscriptions.append({'target': target, 'command': message.params[1],
                                                    'subscriber': message.sender, 'client': client})
        else:
            client = [c for c in self.clients if message.sender in c.ghosts and c.gateway == message.sender_instance][0]
            if client.type == 'tcp':
                client.send(message.sender + ' ack auth_error cp\n')
            elif client['type'] == 'web':
                await client.send(message.sender + ' ack auth_error cp\n')


    async def forward(self, client, message):
        pass

    async def process(self):
        while True:
            raw, sender = await self.messages.get()
            message = Message(raw)
            if message.address == 'cp':
                await self.handle(message, sender)
            elif message.address in ['ee', 'db']:
                pass
            else:
                clients = [c for c in clients if c.address == message.address and c.instance==message.address_instance]
                if clients:
                    self.forward(clients[0], message)

    async def run_async(self):
        await asyncio.gather(
            asyncio.ensure_future(self.socket.start()),
            asyncio.ensure_future(self.pipe.start()),
            asyncio.ensure_future(self.process())
        )

    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(self.run_async())
            loop.run_forever()
        except KeyboardInterrupt:
            loop.run_until_complete(loop.shutdown_asyncgens())




if __name__ == "__main__":
    the_cp = CommandProcessor()
    the_cp.run()