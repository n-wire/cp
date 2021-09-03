import asyncio
from nodewire import Message
from socket_link import SocketLink
from web_link import WebLink
from mqtt_link import MqttLink
from execution_context import ExecutionContext
from execution_engine import ExecutionEngine
import sizeof as sizeof
import json
from bson.objectid import ObjectId
import time

from datetime import datetime, timedelta
from config import mongo_client


class CommandProcessor:
    def __init__(self):
        self.sys_db = mongo_client.nodewire
        self.clients = []
        self.subscriptions = []
        self.messages = asyncio.Queue()

        self.socket = SocketLink(self.messages)
        self.socket.new = self.client_added
        self.socket.client_done = self.client_closed

        self.pipe = SocketLink(self.messages, port=9001)
        self.pipe.new = self.client_added
        self.pipe.client_done = self.client_closed
        self.pipe.safe = True

        self.web = WebLink(self.messages)
        self.web.new = self.client_added
        self.web.client_done = self.client_closed

        self.mqtt = MqttLink(self.messages)
        self.mqtt.new = self.client_added
        self.mqtt.client_done = self.client_closed

        self.send_queues = []
        for _ in range(4):  # 5 tasks for return message
            q = asyncio.Queue()
            self.send_queues.append(q)
            asyncio.Task(self.msg_sender(q))
        self.sq_index = 0

        self.execution_contexts = {}  # one per gateway
        self.when_dos = []  # universal whendo list
        self.auto_execed = []
        self.exec_engine = ExecutionEngine(self.when_dos, self.execution_contexts)
        self.exec_engine.start()

    async def start_execution(self, client, n):
        if not client.safe and n == 0 and client.gateway not in self.execution_contexts:
            gw = await self.sys_db.instances.find_one({'instance_id': client.gateway})
            users = [u['user_instance_and_node_name'].split(':')[1] for u in gw['users'] if u['admin'] == True]
            if users:
                user = users[0]
                self.execution_contexts[client.gateway] = ExecutionContext(client.gateway, self.when_dos,
                                                                           self.exec_engine, self.messages)
                if client.gateway not in self.auto_execed:
                    kk = await self.execution_contexts[client.gateway].engine_process(["exec('auto')"], user)
                    if kk == '':
                        self.auto_execed.append(client.gateway)
                        await self.execution_contexts[client.gateway].engine_process(["kill('auto')"], user)
        await self.sys_db.live_gateways.replace_one({'instance': client.gateway},
                                                    {'instance': client.gateway, 'count': n + 1})

    def client_added(self, client):
        if client in self.clients:
            self.client_closed(client)
        n = len([c for c in self.clients if c.gateway == client.gateway])
        client.seqn = n
        if n < 20:
            self.sq_index = (self.sq_index + 1) % len(self.send_queues)
            client.send_queue = self.send_queues[self.sq_index]
            asyncio.create_task(self.start_execution(client, n))
            self.clients.append(client)
            if client.type == 'mqtt':
                node = client.nodes[-1]
                if node not in self.execution_contexts[client.gateway].pvs and node != 'ee' and node != 'nwscript':
                        self.execution_contexts[client.gateway].add_node(node, client.gateway)
            return True
        return False

    def client_closed(self, client):
        try:
            clients = [c for c in self.clients if c == client]
            if len(clients) != 0:
                client = clients[0]
                self.terminate_connections(clients)
                # update number of connected gateways
                n = len([c for c in self.clients if c.gateway == client.gateway])
                n_g = {'instance': client.gateway, 'count': n}

                asyncio.get_event_loop().call_soon(self.sys_db.live_gateways.replace_one, {'instance': client.gateway},
                                                   n_g)
        except Exception as ex:
            print('pass 7'),
            print(ex)

    async def scavenger(self):
        while True:
            await asyncio.sleep(300)  # wait 5 minutes
            for client in [c for c in self.clients if not c.safe if c.type!='mqtt']:
                try:
                    if time.time() - client.last_seen > 900:  # older than 15 minutes
                        self.terminate_connections([client])
                except Exception as ex:
                    print('error in scavanger')
                    print(ex)
                await asyncio.sleep(0)

    def terminate_connections(self, clients):
        for client in clients:
            if client.type!= 'mqtt':
                client.task.cancel()
            if client in self.clients:
                self.clients.remove(client)
                for node in client.nodes:
                    if client.gateway is not None and node in self.execution_contexts[client.gateway].pvs:
                        try:
                            self.execution_contexts[client.gateway].pvs.remove(node)
                            thenode = [n for n in self.execution_contexts[client.gateway].variables['nodes'] if
                                       n.name == node]
                            if len(thenode) != 0:
                                self.execution_contexts[client.gateway].variables['nodes'].remove(thenode[0])
                            self.exec_engine.pending_signals.put_nowait(['nodes', client.gateway])
                        except Exception as ex:
                            print("{}. couldn't remove node: {}".format(str(ex), node))
            if client.type == 'web' and len(client.nodes)!=0:
                self.exec_engine.pending_signals.put_nowait(('me.session', client.nodes[0], client.session, client.gateway, client.session))
            client.close()

    async def check_id(self, node, gateway, Sender, id, task):
        try:
            client = None
            clients = [client for client in self.clients if client.gateway == gateway and node in client.ghosts]
            if len(clients) != 1:
                print(f'{len(clients)} other instances present')
                for c in clients:
                    if node in c.nodes and c.task != task:
                        print(f'{node} terminate')
                        self.terminate_connections([c])
                    elif node in c.ghosts and c.task == task:
                        print(f'{node} select')
                        if client is None or client.last_seen < c.last_seen:
                            client = c
            else:
                client = clients[0]

            if not client is None:  # and node in client['nodes']:
                d_instance = await self.sys_db.instances.find_one(
                    {'instance_id': gateway})  # , {'registered_nodes', 1})
                if client.type == 'web' or len(
                        [rn for rn in d_instance['registered_nodes'] if rn['name'] == node and rn['id'] == id]) != 0:
                    if node in client.ghosts: client.ghosts.remove(node)
                    client.nodes.append(node)
                    await client.send((Sender + ' ack cp'))
                    self.messages.put_nowait(('{}:{} get ports {}:ee'.format(gateway, node, gateway), None))
                    if node not in self.execution_contexts[gateway].pvs and node != 'ee' and node != 'nwscript':
                        self.execution_contexts[gateway].add_node(node, gateway)
                        # self.messages.put_nowait(('{}:{} get ports {}:ee'.format(gateway, node, gateway), None))
                    else:
                        pass
                else:
                    await client.send('{}:{} not_registered {}:ee'.format(gateway, node, gateway))

            else:
                print("shouldn't happen")
        except ConnectionResetError:
            clients = [client for client in self.clients if task == client.task]
            self.terminate_connections(clients)
        except Exception as ex:
            print(ex)
            # self.messages.put_nowait((Sender + ' error ' + str(ex).split() + ' cp', None))

    def is_auth(self, gateway, nodename, task):
        clients = [client for client in self.clients if task == client.task]
        if clients and clients[0].safe: return True
        if nodename == 'ee' or nodename == 'cp' or (
            gateway in self.execution_contexts and nodename in self.execution_contexts[gateway].apps): return True
        theyre = [cc for cc in self.clients if cc.gateway == gateway and nodename in cc.nodes]
        return len(theyre) != 0

    async def handle_subscriptions(self, msg):
        subscribers = [s for s in self.subscriptions if s['command'] == msg.command and s['target'] == msg.sender_full]
        for subscriber in subscribers:
            if subscriber['client'] is None or (subscriber['client'].type!='mqtt' and subscriber['client'].task._state  == 'FINISHED'):
                self.subscriptions.remove(subscriber)
            elif msg.address_full != subscriber['subscriber']:
                raw = '{} {} {} {}'.format(subscriber['subscriber'], msg.command, ' '.join(p for p in msg.params), msg.sender_full)
                if not subscriber['client']:
                    self.messages.put_nowait((raw, None))
                else:
                    try:
                        await subscriber['client'].send(raw)
                    except:
                        self.terminate_connections([subscriber['client']])
                        self.subscriptions.remove(subscriber)

    async def handle_val(self, msg, task):
        try:
            varname = msg.sender
            for nn in [p for p in self.execution_contexts[msg.sender_instance].variables['nodes'] if p.name == varname]:
                try:
                    val = json.loads(msg.params[1])
                except ValueError:
                    bc = {'app': msg.address, 'module': self.execution_contexts[msg.sender_instance].themodule, 'variables': {}}
                    val = await self.execution_contexts[msg.sender_instance].evaluate(msg.params[1], bc)
                if val != nn[msg.params[0]]:
                    nn.set(msg.params[0], val)
                    self.exec_engine.pending_signals.put_nowait([varname + '.' + msg.params[0], msg.sender_instance])
                if not nn.discovery_complete:
                    nullports = [pp for pp in nn.ports if nn[pp] is None and pp!=msg.params[0]]
                    if nullports == []:
                        nn.discovery_complete = True
                        self.execution_contexts[msg.sender_instance].anounce(nn.name, nn.gateway)
                        self.messages.put_nowait(('{}:{} get type {}:ee'.format(msg.sender_instance, nn.name, msg.sender_instance), None))
                    for p in nullports:
                        response = '{}:{} get {} ee'.format(msg.sender_instance, nn.name, p)
                        self.messages.put_nowait((response, None))
                        break
            if varname == 'cp':
                self.execution_contexts[msg.sender_instance].variables[msg.params]['cp'].set(msg.params[0],json.loads(msg.params[1]))
                self.exec_engine.pending_signals.put_nowait([varname + '.' + msg.params[0], msg.sender_instance])
            if '@' in varname and '.' in varname:
                try:
                    val = json.loads(msg.params[1])
                except:
                    bc = {'app': msg.address, 'module': self.execution_contexts[msg.sender_instance].themodule, 'variables': {}}
                    val = await self.execution_contexts[msg.sender_instance].evaluate(msg.params[1], bc)
                cs = [c for c in self.clients if c['task'] == task]
                signal = ('me.' + msg.params[0], varname, val, msg.sender, cs[0]['session'])
                self.exec_engine.pending_signals.put_nowait(signal)
            if varname == 'db':
                self.execution_contexts[msg.sender_instance].variables['_id'] = msg.params[1]
        except ValueError:
            print('pass 6')
        except Exception:
            print('pass 7')

    async def handle_ee(self, msg, task):
        gateway = msg.sender_instance
        if msg.command == 'val':
            await self.handle_val(msg, task)
        elif msg.command == 'type':
            nodename = msg.sender
            try:
                thenode = [p for p in self.execution_contexts[gateway].variables['nodes'] if p.name == nodename][0]
                thenode.settype(msg.params[0])
            except:
                pass
        elif msg.command == 'set':
            if msg.params[0] == 'scriptlet':
                # list = json.loads(Params[1])
                line = msg.params[1][1:-1]
                result = []
                try:
                    if line == 'reset':
                        s = 'cleared'
                        self.execution_contexts[gateway].reset('')
                    elif line == 'debug':
                        s = None
                        l_no = 0
                        user =msg.sender
                        for whendo in [wd for wd in self.when_dos if wd.instance==gateway and wd.app==self.execution_contexts[gateway].theapp[user]]:
                            l_no+=1
                            if whendo.errors != []:
                                result.append('Rule {} -> {}'.format(l_no, json.dumps(whendo.errors)))
                                whendo.errors = []
                    else:
                        user =msg.sender
                        s =  await self.execution_contexts[gateway].engine_process(line.splitlines(), user)
                    if s != None: result.append(str(s))
                except Exception as ex:
                    result.append(str(ex))
                self.messages.put_nowait(('{} val script {} {}:ee'.format(msg.sender_full, json.dumps(result), gateway), None))
                # print(result)
            elif msg.params[0] == 'script':
                result = []
                try:
                    #self.execution_contexts[gateway].reset()
                    user = msg.sender
                    if user in  self.execution_contexts[gateway].theapp:
                        # Params[1] = Params[1].replace("'", '"')
                        lines = msg.params[1][1:-1].splitlines()
                        await self.execution_contexts[gateway].engine_process_file(lines, user)
                        result.append('Running {}:{}'.format(self.execution_contexts[gateway].theapp[user], self.execution_contexts[gateway].themodule))
                except Exception as ex:
                    result.append(str(ex))
                self.messages.put_nowait(('{} val script {} {}:ee'.format(msg.sender_full,json.dumps(result),gateway),None))
            elif msg.params[0].split('.')[0] in self.execution_contexts[gateway].variables[msg.address]['inputs'] or msg.params[0].split('[')[0] in self.execution_contexts[gateway].variables[Address]['inputs']:
                bc = {'app': msg.address,'module': self.execution_contexts[gateway].themodule, 'variables': {}}
                await self.execution_contexts[gateway].evaluate(msg.address + '.' + msg.params[0] + '=' + msg.params[1], bc)
                signal = [msg.params[0], gateway, msg.sender]
                if not task is None:
                    cs = [c for c in self.clients if c['task']==task]
                    if 'session' in cs[0]:
                        signal.append(cs[0]['session'])
                self.exec_engine.pending_signals.put_nowait(signal)
                if msg.address != 'ee':
                    self.messages.put_nowait(('{} val {} {} {}:{}'.format(msg.sender_full, msg.params[0], msg.params[1], gateway, msg.address_full), None))
        elif msg.command == 'nodes':
            gw = msg.sender_instance
            self.execution_contexts[gateway].nodes = [n.split(':')[1] for n in msg.params]
            self.execution_contexts[gateway].pvs = []
            self.execution_contexts[gateway].variables['nodes'] = []
            for node in self.execution_contexts[gateway].nodes:
                if node not in self.execution_contexts[gateway].pvs and node != 'ee' and node != 'nwscript':
                    self.messages.put_nowait(('{}:cp subscribe {} val {}:ee'.format(gw,node,gateway),None))
                    # self.messages.put_nowait(('{}:{} get ports {}:ee'.format(gw, node, gateway), None))
                    self.execution_contexts[gateway].add_node(node, gateway)
        elif msg.command == 'ports':
            varname = msg.sender
            gw = msg.sender_instance
            if varname not in self.execution_contexts[gateway].pvs and varname != 'ee' and varname != 'nwscript':
                self.messages.put_nowait(('{}:cp subscribe {} val {}:ee'.format(gw, varname, gateway), None))
                self.execution_contexts[gateway].add_node(varname, gateway)
            nn = [p for p in self.execution_contexts[gateway].variables['nodes'] if p.name == varname][0]
            if len(msg.params) == 0:
                nn.discovery_complete = True
                self.execution_contexts[msg.sender_instance].anounce(nn.name, nn.gateway)
            else:
                nn.discovery_complete = False
                self.messages.put_nowait(('{} get {} {}:ee'.format(msg.sender_full, msg.params[0], gateway), None))
                for port in msg.params:
                    nn.set(port, None)
                    # self.messages.put_nowait(('{} get {} {}:ee'.format(Sender, port, gateway), None))
        elif msg.command == 'get':
            bc = {'app': msg.address,'module': self.execution_contexts[gateway].themodule, 'variables': {}}
            if msg.params[0] == 'ports':
                ports = [p for p in self.execution_contexts[gateway].variables[msg.address]['inputs']] # todo MUMT
                for p in self.execution_contexts[gateway].variables[msg.address]['outputs']:
                    if p not in ports: ports.append(p)
                self.messages.put_nowait(('{} ports {} {}:{}'.format(msg.sender, ' '.join(p for p in ports), gateway, msg.address), None))
            elif self.execution_contexts[gateway].is_defined(msg.params[0], bc) and (
                    msg.params[0] in self.execution_contexts[gateway].variables[msg.address]['inputs'] or
                            msg.params[0] in self.execution_contexts[gateway].variables[msg.address]['outputs']):
                theval = self.execution_contexts[gateway].get_val(msg.params[0], bc) # todo MUMT
                self.messages.put_nowait(('{} val {} {} {}:{}'.format(msg.sender, msg.params[0],
                        '"' + theval + '"' if isinstance(theval,str) else str(theval), gateway, msg.address), None))
            elif msg.params[0] == 'status':
                for whendo in [wd for wd in self.when_dos if wd.instance == gateway and wd.app == msg.address]:
                    self.messages.put_nowait(('{} val status {} {}:ee'.format(msg.sender_full, json.dumps(whendo.errors), gateway), None))
            elif '.' in msg.params[0]:
                var = msg.params[0].split(':')[0]
                if self.execution_contexts[gateway].is_defined(var, bc) and (
                    var in self.execution_contexts[gateway].variables[msg.address]['inputs'] or
                            var in self.execution_contexts[gateway].variables[msg.address]['outputs']):
                    theval = self.execution_contexts[gateway].get_val(msg.params[0], bc)
                    self.messages.put_nowait(('{} val {} {} {}:{}'.format(msg.sender_full, var,'"' + theval + '"' if isinstance(theval,str) else str(theval), gateway, msg.address_full), None))

    async def handle_db(self, msg):
        gateway = msg.address_instance
        db = mongo_client[gateway]
        collection = db[msg.params[0]]
        if msg.command == 'set':
            if msg.params[1] == 'drop':
                await collection.drop()
            elif msg.params[1] == 'remove':
                query = json.loads(msg.params[2])
                if '_id' in query: query['_id'] = ObjectId(query['_id'])
                await collection.delete_many(query)
            elif msg.params[1] == 'index':
                keys = json.loads(msg.params[2])
                options = json.loads(msg.params[3]) if len(msg.params)>=4 else None
                if isinstance(keys, dict):
                    keys = [(k, keys[k]) for k in keys]
                if options:
                    await collection.create_index(keys, background=True, **options)
                else:
                    await collection.create_index(keys, background=True)
                print('index')
            else:
                if len(msg.params) == 3:
                    query = json.loads(msg.params[1])
                    if '_id' in query: query['_id'] = ObjectId(query['_id'])
                    if msg.params[2] == 'remove':
                        await collection.delete_many(query)
                    elif msg.params[2] == 'removeindex':
                        await collection.drop_index(query)
                    elif msg.params[2] == 'index':
                        keys = query
                        if isinstance(keys, dict):
                            keys = [(k, keys[k]) for k in keys]
                        await collection.create_index(keys, background=True)
                    else:
                        doc = json.loads(msg.params[2])
                        if isinstance(doc, list) or '$set' in doc:
                            id = await collection.update_many(query, doc) # update_many
                        else:
                            id = await collection.replace_one(query, doc) # replace one
                        response = msg.sender + ' val ' + msg.params[0] + '_id \"' + str(id.modified_count) + "\" db"
                elif len(msg.params) == 4:
                    if msg.params[3] == 'index':
                        keys = json.loads(msg.params[1])
                        options = json.loads(msg.params[2])
                        if isinstance(keys, dict):
                            keys = [(k, keys[k]) for k in keys]
                        await collection.create_index(keys, background=True, **options)
                else:
                    docs = json.loads(msg.params[1])
                    if type(docs) is dict:
                        docs = [docs]
                    for doc in docs:
                        if '_id' in doc:
                            doc['_id'] = ObjectId(doc['_id'])
                            await collection.replace_one({'_id': doc['_id']}, doc)
                            id = doc['_id']
                        else:
                            result = (await collection.insert_one(doc))
                            id = result.inserted_id
                        response = msg.sender_full + ' val ' + msg.params[0] + '_id \"' + str(id) + "\" db"
        elif msg.command == 'get':
            if msg.params[0] == 'ports':
                collections = await db.collection_names(include_system_collections=False)
                response = msg.sender_full + ' ports ' + ' '.join(c for c in collections) + ' db'
            else:
                query = json.loads(msg.params[1])
                if type(query) is list:
                    pipeline = query if type(query) is list else json.loads(msg.params[2])
                    # if '_id' in query: query['_id'] = ObjectId(query['_id'])
                    results = await collection.aggregate(pipeline).to_list(None)
                    rs = []
                    try:
                        for result in results:
                            if '_id' in result: result['_id'] = str(result['_id'])
                            rs.append(result)
                        response = msg.sender_full + ' val ' + msg.params[0] + ' ' + json.dumps(rs) + ' db'
                    except Exception as ex:
                        print('pass 4')
                else:
                    if '_id' in query: query['_id'] = ObjectId(query['_id'])
                    try:
                        if len(msg.params) >= 4:
                            options = json.loads(msg.params[3])
                            sort = options['$sort'] if '$sort' in options else {}
                            limit = options['$limit'] if '$limit' in options else {}
                            skip = options['$skip'] if '$skip' in options else 0
                            if sort!={} and  type(sort) == dict:
                                sort = list(sort.items())
                            if sort and limit:
                                results = await collection.find(query, json.loads(msg.params[2])).skip(skip).sort(sort).limit(limit).to_list(None)
                            elif sort:
                                results = await collection.find(query, json.loads(msg.params[2])).skip(skip).sort(sort).to_list(None)
                            elif limit:
                                results = await collection.find(query, json.loads(msg.params[2])).skip(skip).limit(limit).to_list(None)
                            else:
                                results = await collection.find(query, json.loads(msg.params[2])).skip(skip).to_list(None)
                        elif len(msg.params)>=3:
                            results = await collection.find(query, json.loads(msg.params[2])).to_list(None)
                        else:
                            results = await collection.find(query).to_list(None)
                        rs = []
                        for result in results:
                            if '_id' in result: result['_id'] = str(result['_id'])
                            rs.append(result)
                        response = msg.sender_full + ' val ' + msg.params[0] + ' ' + json.dumps(rs) + ' db'
                    except Exception as ex:
                        print('pass 5')
        self.messages.put_nowait((response, None))

    def app_permission(self, app, context):
        if 'permission' in context.variables[app]:
            return {'name': app, 'access_permission': context.variables[app]['permission']}
        else:
            return {'name': app, 'access_permission': [2, 2, 0]}

    async def access_allowed(self, user, node, command):
        gu, u = user.split(':')
        g, n = node.split(':')

        if u in ['cp', 'ee', 'remote'] and gu == g: return True

        n_gateway = await self.sys_db.instances.find_one({'instance_id': g})
        d_user = await self.sys_db.users.find_one({'email': u})
        # u_gateway = await self.sys_db.instances.find_one({'instance_id': gu})
        if d_user is None:
            try:
                client = [client for client in self.clients if client.gateway == gu and u in client.nodes]
                if client != []:
                    d_user = client[0].user
                elif u in self.execution_contexts[g].apps:
                    email = self.execution_contexts[g].owners[u]
                    d_user = await self.sys_db.users.find_one({'email': email})
                else:
                    raise Exception('Node or User "{}" does not exist'.format(u))
            except Exception as ex:
                raise Exception('Node or User "{}" does not exist'.format(u))

        if n_gateway['owner'] == d_user['_id']:  # super user
            return True

        i_user = [u1 for u1 in n_gateway['users'] if u1['user_instance_and_node_name'] == user]
        if i_user == []:
            userclass = 2  # 'others, unregistered users
        else:
            i_user = i_user[0]
            if i_user['admin']:
                userclass = 0  # 'admin'
            else:
                userclass = 1  # 'user'

        if n in self.execution_contexts[g].apps:
            i_nodes = [self.app_permission(n, self.execution_contexts[g])]
        else:
            i_nodes = [n1 for n1 in (n_gateway['registered_nodes'] +
                                     [
                                         {'name': 'cp', 'access_permission': [2, 2, 0]},
                                         {'name': 'ee', 'access_permission': [2, 1, 0]},
                                         {'name': 'db', 'access_permission': [2, 0, 0]}
                                     ]) if n1['name'] == n]
        if len(i_nodes) != 0:
            i_node = i_nodes[0]
            node_permission = i_node['access_permission'][userclass]
            if command == 'set' and node_permission == 2:
                return True
            elif command != 'set' and node_permission >= 1:
                return True
        return False
        
    async def handle(self, message: Message, task):
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
                if node not in client.ghosts and node not in client.nodes:  # case 4
                    # add to ghosts
                    client.ghosts.append(node)
                    if client.type == 'web':
                        await self.check_id(node, message.sender_instance, message.sender, message.params[0], task)
                        await client.send(message.sender + ' ack cp')
                    else:
                        if message.params != []:
                            await self.check_id(node, message.sender_instance, message.sender, message.params[0], task)
                        else:
                            await client.send(message.sender + ' ack cp')
                            await client.send(message.sender + ' get id cp')
                elif node in client.nodes:  # and len(clients)==1:   # case 2
                    # pass
                    if time.time() - client.last_seen > 20:
                        client.nodes.remove(node)  # = [n for n in client['nodes'] if n != node]
                else:  # case 3
                    if client.type == 'tcp':
                        # terminate previous connections
                        other_ghosts = [client for client in self.clients if
                                        node in client.ghosts and client.task != task]
                        if len(other_ghosts) > 1:
                            self.terminate_connections(other_ghosts)
                        if message.params != []:
                            await self.check_id(node, message.sender_instance, message.sender, message.params[0], task)
                        else:
                            await client.send(message.sender + ' ack cp')
                            await client.send(message.sender + ' get id cp')
                    elif client.type == 'web':
                        await client.send(message.sender + ' ack cp')
            except ConnectionResetError:
                clients = [client for client in self.clients if task == client.task]
                self.terminate_connections(clients)
            except Exception as ex:
                print(f'pass 2: {ex}, node is {message.sender}')
        elif message.command == 'id':
            node = message.sender
            await self.check_id(node, message.sender_instance, message.sender, message.params[0], task)
        elif message.command == 'keepalive':
            client = [client for client in self.clients if task == client.task][0]
            if client:
                try:
                    await client.send(message.sender + ' ack cp')
                    varname = message.sender
                    if varname not in self.execution_contexts[message.sender_instance].pvs and varname not in ['ee','nwscript','cp','db']:
                        self.terminate_connections([client])
                except ConnectionResetError:
                    self.terminate_connections([client])
            else:
                print(f'CLIENT NOT CONNECTED => {message}')
        elif self.is_auth(message.sender_instance, message.sender, task):
            if message.command == 'get':
                if message.params[0] == 'nodes':
                    nodeses = [[n for n in client.nodes] for client in self.clients if
                               client.gateway == message.sender_instance and (
                                           client.type == 'tcp' or client.type == 'mqtt')]
                    nodes_web = [[n for n in client.nodes[1:]] for client in self.clients if
                                 client.gateway == message.sender_instance and client.type == 'web']
                    nodes = self.execution_contexts[
                        message.sender_instance].apps if message.sender_instance in self.execution_contexts else []
                    for nodegroup in nodeses: nodes = nodes + nodegroup
                    for nodegroup in nodes_web: nodes = nodes + nodegroup
                    response = '{} nodes {} {}:cp'.format(message.sender, ' '.join(nodes), message.sender_instance)
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'ghosts':
                    nodeses = [[n for n in client.ghosts] for client in self.clients if
                               client.gateway == message.sender_instance]
                    nodes = []
                    for nodegroup in nodeses: nodes = nodes + nodegroup
                    response = '{} ghosts {} {}:cp'.format(message.sender, ' '.join(nodes), message.sender_instance)
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'gateways':
                    def fdate(t):
                        d = datetime(1970, 1, 1) + timedelta(seconds=t)
                        return d.strftime('%X %x')

                    gw = [{'gateway': c.gateway, 'lastseen': fdate(c['last_seen']), 'nodes': c.nodes} for c in
                          self.clients]
                    response = f'{message.sender} val gateways {json.dumps(gw)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'users':
                    users = [' '.join(u) for u in [c.nodes for c in self.clients if
                                                   c['type'] == 'web' and c.gateway == message.sender_instance]]
                    response = f'{message.sender} val users {json.dumps(users)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'connections':
                    response = f'{message.sender} val connections {len(self.clients)} cp'
                    self.messages.put_nowait((response, None))
                elif message.params[0] == 'mem':
                    m = sizeof.deep_getsizeof(self.execution_contexts[message.sender_instance].variables, set())
                    cc = [c for c in self.clients if c.gateway == message.sender_instance]
                    n = sizeof.deep_getsizeof(cc[0], set())
                    print(m, n)
                    response = f'{message.sender} val mem ' + '{"clients:":' + str(n) + ', "context":' + str(
                        m) + '} cp'
                    self.messages.put_nowait((response, None))
            elif message.command == 'set':
                if message.params[0] == 'id':  # cp set id node_name id_code new_name sender
                    clients = [c for c in self.clients if message.params[1] in c.ghosts and c.gateway == message.sender_instance]
                    if clients:
                        client = clients[0]
                        client.ghosts.remove(message.params[1])
                        try:
                            await client.send('{} set id {} cp'.format(message.params[1], message.params[2]))
                            await client.send('{} set name {} cp'.format(message.params[1], message.params[3]))
                        except:
                             self.terminate_connections(clients)
                elif message.params[0] == 'reset':  # reset all conections from this instance
                    clients = [c for c in self.clients if c.gateway == message.sender_instance]
                    self.terminate_connections(clients)
            elif message.command == 'register':
                try:
                    # cp register node id pwd=password user
                    d_instance = await self.sys_db.instances.find_one({'instance_id': message.sender_instance})
                    i_user = \
                    [u for u in d_instance['users'] if u['user_instance_and_node_name'] == message.sender_full][0]
                    if i_user['admin']:  # d_user['password'] == Params[2].split('=')[1] and i_user['admin']:
                        node = {'name': message.params[0], 'id': message.params[1], 'access_permission': [2, 2, 1]}
                        if not node in [n['name'] for n in d_instance['registered_nodes']]:
                            d_instance['registered_nodes'].append(node)
                            await self.sys_db.instances.replace_one({'_id': d_instance['_id']}, d_instance)
                except Exception as ex:
                    print('pass 3')
            elif message.command == 'getnode':
                nodename = message.params[0].split(':')[1] if ':' in message.params[0] else message.params[0]
                nodeinstance = message.params[0].split(':')[0] if ':' in message.params[0] else message.sender_instance
                if await self.access_allowed(message.sender_full, nodeinstance+':'+nodename, 'get'):
                    nodes = [n for n in self.execution_contexts[nodeinstance].variables['nodes'] if n['name'] == nodename]
                    if len(nodes) != 0:
                        dnode = nodes[0]
                        nodename = dnode.name
                        nodebody = dnode.json()
                        if nodes[0].type != None:
                            response = '{} node {} {} {} {} cp'.format(message.sender_full, nodebody, nodename, nodes[0].gateway, nodes[0].type)
                        else:
                            response = '{} node {} {} {} cp'.format(message.sender_full, nodebody, nodename, nodes[0].gateway)
                        self.messages.put_nowait((response, None))
                    else:
                        nodes = [n for n in self.execution_contexts[nodeinstance].apps if n == nodename]
                        if len(nodes) != 0:
                            ports = [p for p in
                                    self.execution_contexts[nodeinstance].variables[nodename]['inputs']]
                            for p in self.execution_contexts[nodeinstance].variables[nodename]['outputs']:
                                if p not in ports: ports.append(p)
                            bc = {'app': nodename,'module': self.execution_contexts[nodeinstance].themodule, 'variables': {}}
                            content = {}
                            for port in ports:
                                try:
                                    content[port] = self.execution_contexts[nodeinstance].get_val(port, bc)
                                except:
                                    content[port] = None
                            response = '{} node {} {} {} {} cp'.format(message.sender, json.dumps(content), nodename, nodeinstance, nodename)
                            self.messages.put_nowait((response, None))
                        else:
                            #node not online
                            self.execution_contexts[nodeinstance].nodewaiters.append({'nodename': nodename, 'waiter': message.sender_full})

            elif message.command == 'erase':
                # cp erase node user
                d_instance = await self.sys_db.instances.find_one({'instance_id': message.sender_instance})
                i_user = [u for u in d_instance['users'] if u['user_instance_and_node_name'] == message.sender][0]
                if i_user['admin']:
                    client = \
                    [c for c in self.clients if message.params[0] in c.ghosts and c.gateway == message.sender_instance][
                        0]
                    if client['type'] == 'tcp':
                        client.send('{} set reset cp'.format(message.params[0]))
                    else:
                        await client.send('{} set reset cp'.format(message.params[0]))

            elif message.command == 'subscribe':
                # cp subscribe node cmd sender
                if message.sender != message.params[0]:
                    clients = [client for client in self.clients if task == client.task]
                    client = clients[0] if len(clients) != 0 else None
                    target = message.params[0] if ':' in message.params[0] else message.sender_instance + ':' + message.params[0]
                    if len([s for s in self.subscriptions if s['target'] == target and s['command'] == message.params[1] and s['subscriber'] == message.sender_full and s['client'].task==client.task]) == 0:
                        self.subscriptions.append({'target': target, 'command': message.params[1], 'subscriber': message.sender_full, 'client': client})
        else:
            client = [c for c in self.clients if message.sender in c.ghosts and c.gateway == message.sender_instance]
            if client:
                await client[0].send(message.sender + ' auth_error cp')

    async def msg_sender(self, dqueue):
        while True:
            raw_msg, client = await dqueue.get()
            try:
                await client.send(raw_msg)
            except Exception as ex:
                print(ex)
                self.terminate_connections([client])

    async def process(self):
        while True:
            raw, sender = await self.messages.get()
            # print(f'received:{raw}<<')
            message = Message(raw)
            if message.command == 'error':
                continue
            asyncio.Task(self.handle_subscriptions(message))
            if message.address == 'cp':
                try:
                    await self.handle(message, sender)
                except Exception as ex:
                    print('error while handling message', ex)
            elif (message.command in ['get', 'set'] and (await self.access_allowed(message.sender_full, message.address_full, message.command)))\
                        or (not message.command in ['get', 'set'] and await self.access_allowed(message.address_full, message.sender_full, message.command)):
                if message.address == 'db':
                    await self.handle_db(message)
                elif message.address == 'ee' or message.address in self.execution_contexts[message.address_instance].apps:
                    await self.handle_ee(message, sender)
                else:
                    if 'session' in message.named_params:
                        clients = [c for c in self.clients if
                                   message.address in c.nodes and c.instance == message.address_instance and c.session ==
                                   message.named_params['session']]
                    else:
                        clients = [c for c in self.clients if
                                   message.address in c.nodes and c.gateway == message.address_instance] + \
                                  [c for c in self.clients if message.address_full in c.nodes and c.safe]
                    for client in clients:
                        client.send_queue.put_nowait((raw, client))
                        if message.command == 'val' and message.sender!='ee':
                            await self.handle_val(message, sender)
            self.messages.task_done()

    async def run_async(self):
        await asyncio.gather(
            asyncio.ensure_future(self.socket.start()),
            asyncio.ensure_future(self.pipe.start()),
            asyncio.ensure_future(self.web.start()),
            asyncio.ensure_future(self.mqtt.start()),
            asyncio.ensure_future(self.process()),
            asyncio.ensure_future(self.scavenger())
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
