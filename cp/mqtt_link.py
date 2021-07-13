from link import Link
from broker import NodeWireBroker
from message import Message
import asyncio
import time


class MqttLink(Link):
    def __init__(self, messages, address='0.0.0.0', port = 10001) -> None:
        super().__init__(messages)
        # self.safe = True
        self.type = 'mqtt'
        self.queue = asyncio.Queue()
        self.vals = {}

    def start(self):
        config = {
            "listeners": {
                "default": {
                    "max-connections": 50000,
                    "type": "tcp"
                },
                "my-tcp-1":{
                    "bind": "0.0.0.0:1883"
                },
                'ws-mqtt': {
                    'bind': '0.0.0.0:8888',
                    'type': 'ws',
                }
            },
            "topic-check":{
                "enabled": True,
                "plugins": ["topic_taboo"]
            }
        }
        self.the_broker = NodeWireBroker(config=config, handle_msg = self.handle_msg)
        self.the_broker.new_client = self.loop
        self.the_broker.messages = self.messages
        return self.the_broker.start()

    async def loop(self, listener_name, client_reader, client_writer):
        the_link = MqttLink(self.messages)
        the_link.reader = client_reader
        the_link.writer =  client_writer
        the_link.client_done = self.client_done
        the_link.new = self.new
        the_link.the_broker = self.the_broker
        the_link.task = asyncio.current_task()
        the_link.task.add_done_callback(the_link.client_done)
        await the_link.the_broker.loop(listener_name, client_reader, client_writer)

    async def send(self, data):
        msg = Message(data)
        if msg.command == 'set':
            # set port value of mqtt node
            print(msg.address_instance+'/'+msg.address+'/'+msg.port+'/set', msg.params[1].encode())
            if msg.address not in self.vals: self.vals[msg.address] = {}
            self.vals[msg.address][msg.port] = msg.params[1]
            await self.the_broker.send_message(None, msg.address_instance+'/'+msg.address+'/'+msg.port+'/set', msg.params[1].encode())
        elif msg.command == 'val':
            # send value of port belonging to normal node to mqtt node
            print(msg.sender_instance + '/' + msg.sender + '/' + msg.port, msg.params[1].encode())
            await self.the_broker.send_message(None, msg.sender_instance + '/' + msg.sender + '/' + msg.port, msg.params[1].encode())
        elif msg.command == 'get':
            # get value of mqtt node, and send to normal node
            if msg.port!= 'type':
                self.messages.put_nowait((f'{msg.sender_instance}:{msg.sender} val {msg.port} {self.vals[msg.address][msg.port]} {msg.address}', self.task))

    
    async def handle_msg(self, topic, data, session):
        if not isinstance(data, str):
            data = data.decode()
        msg = topic.split('/')
        instanceid = msg[0]
        node = msg[1]
        if session:
            session.instanceid = instanceid
            session.nodename = node
        port = msg[2]
        self.last_seen = time.time()
        if len(msg)==3:
            if node not in self.nodes:
                self.nodes.append(node)
                if len(self.nodes)==1:
                    self.gateway = instanceid
                    self.new(self)
            self.messages.put_nowait((f'ee val {port} {data} {instanceid}:{node}', self.task))
            if node not in self.vals: self.vals[node] = {}
            self.vals[node][port] = data
        elif len(msg)==4 and msg[3] == 'set':
            self.messages.put_nowait((f'{instanceid}:{node} set {port} {data} ee', self.task))


    def close(self):
        self.client_done(self)
        for client_id in self.nodes:
            if client_id in self.the_broker._sessions:
                handler = self.the_broker._sessions[client_id][1]
                asyncio.Task(handler.stop())
                break